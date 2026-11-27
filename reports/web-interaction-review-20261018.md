# 网页交互改动审查（2026-10-18）

审查基线：`581ef939f8fd25acc92a8bad9e08b98efd599232`。重点检查 10 月 17 日晚至 18 日早晨的浏览器、上传、调度提交，并交叉读取原所有者已落盘的状态和上传事件。Git 作者字段无法证明具体由哪个模型完成，本文称“相关改动”。

并发编辑说明：全量测试启动后，09:32–09:33 观察到 `review/card_review_queue.py`、`infrastructure/config/first_round.json`、`infrastructure/config/card_review_standard.json` 出现新的未提交补充材料策略修改。这些改动并非本轮写入；全部原样保留。下列复现针对审查基线，全量测试结果不能用于验收这批随后写入的代码。

本轮仅审查、离线复现及运行检查，没有修改生产实现、控制文件或任务，没有连接 CDP、点击真实网页、上传、重发或重启服务。本报告及配套检查结果是本轮新增文件。

## 结论

存在需要修复的问题，尤其是新增熔断没有接上真实失败结果，以及设备限制后的自动 Retry 缺少严格绑定。不能据此断言这些改动就是服务端设备限制的唯一原因，也不能把附件入口失败次数当成实际上传次数或模型请求数。

原落盘证据在上海时间 **09:16:12** 记录了用户所述提示。以该时刻为截止点，直接统计 `infrastructure/data/upload-attempt-events.jsonl` 的 `upload_finished`，按 `finished_at` 计数：

| 窗口 | 入口未就绪 | 上传成功 | 涉及 target |
| --- | ---: | ---: | ---: |
| 前 1 小时 | 238 | 6 | 13 |
| 前 3 小时 | 644 | 64 | 14 |

三小时的 644 次入口失败中：制卡 241、核验 402、修正 1；成功分别 15、43、6。入口失败涉及 519 个不同 job，全部没有进入附件写入阶段。因此这主要证明长期入口故障下仍不断派发不同材料，不能解读为同一模型请求被重发 644 次。`quota-restart-test-state.json` 的既有汇总采用不同观测截止，本文没有照抄其 243/66 数值。

## 需要修复的问题

### 1. P1：新熔断读不到生产路径的失败

- 引入提交：`a21284c`。
- 位置：`infrastructure/browser/web_card_pool.py:705–721`；调用方对照 `review/card_review_lane.py:350–365`、`web_card_pool.py:496–507`、`owner_upload_jobs.py:153–166`。
- 熔断只检查 `reap()` 结果中的 `error` 字符串。核验提交已经捕获真实上传异常并返回 `False`；制卡错误处理保存错误后返回 `None`。上传任务包装器将它们作为正常返回，输出 `result=False/None`，没有 `error`。
- 新逻辑把这些失败当成“没有错误”并清零计数。离线直接执行实际 AST 中的熔断循环，输入三次这样的失败结果，计数仍为 0，也没有写熔断记录。审查时正式目录也没有 `upload-entry-block.json`。
- 此外，计数和截止时间只在进程内，重载会归零；落盘的熔断记录没有恢复读取。当前独立上传通道覆盖了主要运行路径；旧派发路径也没有统一读取这项熔断。
- 修复方向：让回调返回持久回执绑定的结构化失败类型，按真实附件入口失败统计；所有新上传准入共用持久化门。`False/None` 不能当作上传成功。保留每材料退避，同时限制账户入口持续失败时的新派发。

### 2. P1：设备异常后的 Retry 没有按钮归属和持久防重

- 引入提交：`581ef93`。
- 位置：`infrastructure/browser/web_card_transport.py:235–250,261–264`。
- `_retry_unusual_activity` 在整个页面寻找名称含 `Try again / Retry / 重试` 的任意可见按钮，既不限定设备异常提示容器，也不核对按钮作用、原账本或未发送证据，然后直接点击。
- 所谓“仅一次”是 Python Page 对象的临时属性；重连后新 Page 对象没有这个属性。离线两个新包装对象指向同一个模拟按钮，实际累计点击两次。没有持久 nonce、点击意图或未知点击回执保护。
- 这是确定的按钮绑定/恢复边界问题；本轮没有证据证明它已经点击了真实会话的重发按钮。
- 修复方向：设备限制只记录真实 UI 并阻止新派发。任何获准的页面级恢复都必须先绑定原 target、提示容器、未发送账本和持久一次性意图，不复用任意 Retry 控件。

### 3. P1：设备异常被降级为附件额度，可能缩短已有保护

- 引入提交：`581ef93` 新返回 `kind=unusual_activity`，但未适配调用链。
- 位置：`infrastructure/browser/web_card_pool.py:58–65`；`infrastructure/browser/web_card_transport.py:88–115`。
- `record_channel_failure` 将所有 notice 一律归入 `quota`，忽略新增 kind；`Router.block` 又只支持 verification/quota/network。设备限制于是落入普通 900 秒额度冷却，没有专门的持久恢复核对。
- 离线临时目录中，原本还有 3600 秒的 `unusual_activity` 记录被此路径覆盖为 `quota`，剩余时间缩至 900 秒，没有建立访问保护记录。
- 审查时正式状态另有 09:16:12 至 10:16:12 的设备限制记录，当前确实禁止新派发；10:16:12 仅是本地设定的截止，不能声称是网站恢复时间。对相同正式记录作只读未来时刻求值，截止后结果直接变为 `ready`。既有 UI 就绪检测也没有显式识别 `unusual activity`，不能据登录控件及输入框存在证明设备限制消失。
- 修复方向：为设备限制保留独立类型、真实提示证据和恢复条件；不被普通额度/网络错误覆盖或缩短。无服务端恢复时间时，只允许有界只读探测，不能把到时等同于可以上传。

### 4. P2：整页搜索把普通正文也当成当前设备限制

- 引入提交：`581ef93`。
- 位置：`infrastructure/browser/upload_quota.py:10,130–135`。
- 原有 `LIVE_NOTICE_SCRIPT` 排除聊天消息、输入框、代码和历史内容；新增分支绕过这些过滤，读取整个 body，并且单独匹配泛化的 `Try again later`。
- 离线模拟 `notices=[]`，仅聊天正文写“网络失败时显示 Try again later”，仍返回 `unusual_activity`。普通错误和历史引用都可能触发；而且设备分支先于真实额度处理，可能遮盖有明确时间的上传额度提示。
- `notice` 保存的是 body 前 600 字，提示在正文后部时甚至无法保留实际命中的提示文本。`first_observed_at` 每次重置，身份固定为 `unusual-activity`，无法区分同一提示的首次观测。
- 修复方向：从真实可见原生提示节点读取精确错误，排除消息/草稿/历史，绑定节点和首次时间，保存实际命中的提示。裸 `Try again later` 不足以识别设备异常。

### 5. P1：旧上传预留前置保护被整个移除

- 引入提交：`8ddd36a`。
- 位置：`infrastructure/browser/original_upload_http1.py:52–68`。
- `material_intent()` 原来同时读取 intent 和 reservation，新实现完全不读 reservation，未按状态和证据分别处理。这与仍生效的 `infrastructure/docs/authorizations/20261017-prior-upload-reservation-preflight.md` 要求相反。
- 离线只有 `state=unknown` 的同材料 reservation 时，函数直接返回 `None`。这明确移除了预留前置门；尚不能据此推断后续其他账本守卫也失效或已有模型请求被重发。
- 正式目录存在 156 份没有 intent 的 reservation，当前状态均为 `not_observed`。这些本地状态本身不等于逐材料、跨 epoch 的安全恢复证据。
- 修复方向：恢复真实 PUT 优先、reservation 仍阻断的原合同；若要释放确证未开始的预留，另走逐材料证据核对及持久归档流程，不能全局忽略。

### 6. P1：新自动重做策略与原回答一致性守卫冲突，实际无法入队

- 引入提交：`e504b87`；正式配置 `review_standard.no_user_state=true` 已开启。
- 位置：`review/card_review_queue.py:449–472`；`correction/card_correction_queue.py:185–195`。
- `apply_result` 把解析出的 `needs_user` 结果改成 `rework`，保存改后的 assessment，再传给 `enqueue_review`。后者重新从完整原回答解析出原始结果并严格比较；原始结果没有被改成 rework，必然触发“修正建议与原核验回答不一致”。
- 复用现有测试的独立临时 Catalog、合成原文和完整回执，制造缺少 `visual.pdf` 的报告，并开启正式使用的策略：原解析为 `needs_user`，真实 `apply_result` 抛上述 ValueError；assessment 已写 `rework`，修正任务数为 0，直接调用结束时核验 job 留在 `applying`。生产上层异常处理还可将其改记 `failed`，但并没有完成所宣称的自动修正入队。
- 修复方向：原报告及其解析评估保持不可变，自动流程决策另存；补材料、纯歧义、证据不足和真实重大问题分别沿已授权合同处理，不通过改写原评估绕过一致性守卫。

## 不应混同为错误的改动

- `cf04ad8` 允许不同 ZIP 路径但要求完整体积及 SHA-256 一致，方向合理；相关本机上传回归通过。
- `63cd87f` 使用 shadow-root 元素的 objectId 定位本机文件输入，仍在写入意图后保留未知保护，未发现它直接解释设备限制的证据。
- 五页上传本身在现行规则已有授权，不能仅凭“5”就归因；应修复长期入口失败的账户级准入和恢复门。
- 300/480 秒结算、64MB 总预算、5/4/3 固定组和队列优先级也有变化。当前 AGENTS 仍记有 180 秒、32MB、8/4/3/5 规则；需另核对修改来源和授权登记，不能从提交说明直接推定新授权。本文不据此擅自回滚配置。

## 验证

- 定向回归 81 项：80 项通过，1 项错误。`test_incomplete_quota_read_fails_closed` 的原测试使用没有 body 文本的 Mock；新增整页读取触发 `TypeError`，使原本预期的损坏额度 `ValueError` 检查无法完成。这是回归/测试合同未同步，不把 Mock 类型错误冒称真实网页故障。
- 六项离线复现均使用模拟页面或临时目录，没有网络调用或生产状态写入；另对正式控制记录做了只读未来求值。
- `make check`：14 项目、236 生产源码文件、344 公开出口，0 错误。
- 全局 `sync_tools.py check/update`：待同步 0，更新 0 文件；`check_links.py` 通过。接口指纹检查不保证网页行为正确。
- 全量 `make test` 未通过：执行 2303 个测试槽位（2120 个唯一 ID、183 个重复执行），0 个 assertion failure、5 个 error。其中 1 个是上述额度测试 TypeError，另 4 个来自 reading 的本地 HTTP 异常返回 JSON 检查，暂未归因于网页交互改动。另有 `PageObserver.run` 协程未等待警告。不要将这次结果表述为全量验收通过。
- 原始机器摘要和错误栈保存在 [配套检查记录](web-interaction-review-20261018-checks.json)。

优先顺序：先修复真实熔断与设备保护，去掉无绑定自动 Retry，再修提示识别和旧预留门；之后通过离线回归及原所有者的既有正常交接机制落地，保留所有原请求和暂停边界。
