# 2026-10-18 核验漏斗审计复核与修复

审阅本批最新三份 review_Qwen3.8-Flash 报告（01/02/03），原件指纹见同目录 `20261018-review-funnel-evidence.json`。本次以当前源码、只读活动 WAL 库聚合、原生产错误记录与隔离合同测试验证；未另连 Chrome/CDP、未重发原模型请求，也未批量改写历史科学报告。

## 真实性和可行性判断

| 发现 | 复核判断 | 处理 |
| --- | --- | --- |
| review_cycle 使用未定义 config | 确认；当前 card-review-error 与 web-material-producer 均仍报 NameError | completed_failure/failure_count 显式接收可选 config，所有生产调用传同一配置；兼容既有无参数调用 |
| 修正复读漏传 config | 确认；只读查询当前有 241 条“重大问题原核验报告变化”失败，数量不是报告时刻的 239 | 修正执行、发布、旧任务接入、分流恢复、自动补充分流均传配置，保留完整等值校验；不采纳仅比较少数字段的放松建议 |
| minor-only 被额外否决 | 确认，与根 AGENTS 科学通过合同不一致 | 对齐现行完整检查、>=85、无 major/critical、无 missing_inputs、verdict=pass；仍保留修正建议、公式损坏及完整性前置守卫；不批量把旧卡标通过 |
| failed 从循环查询消失 | 确认，但不能把所有 failed 当科学失败 | 仅原 result 标 scientific 且重新通过原回执/当前版本/完整报告核验的任务回到三次循环，保存原行事件；技术、未知、歧义不增加科学失败计数 |
| 技术恢复只匹配三类错误文案 | 确认；原自动分支还缺少现成恢复通道的完整守卫 | 统一复用 review_channel_recovery，兼容 failed；要求 not_sent、明确未点击发送、匹配输入/提示、无回答、无修正、无占用、无旧 PUT 意图且通过暂停/退避守卫 |
| 配置漏传的旧失败无法恢复 | 确认 | 原恢复入口接受精确错误及自动终止前缀的 failed；不再要求另一个旧建议产生的 successor 标记。改用本任务完整冻结证据、当前身份版本、无该修正运输/账本、CAS，并存 config-routing-recovery.json 原行证据 |
| cannot_evaluate 一律重做 | 确认现有 auto_action 会过度授权 | 对 auto_action 增加实质守卫：只有可逐字回查且绑定有效卡片路径的重大问题，或完整检查下实际公式损坏才可重做。纯歧义不获重做权限；不改模型原 verdict |
| 修正结果覆盖科学评估 | 部分成立，报告夸大：472 条引文定位在准备阶段发生，本来没有模型科学评估；原实现也已优先保留 task.assessment | 仍改为保留现存评估，空时用原任务评估，修正结果单独放 correction_result；不凭空补造旧分数 |
| 每 tick DDL 与锁争用 | 源码有重复 install，报告有锁错误，但“所有锁错误均因此产生”未证实 | 暂不在本轮大改 schema 生命周期，需专门验证建表/迁移/并发启动边界；不能只加进程级布尔缓存 |
| 模型 High 控件失败 | 历史错误真实，当前已有 radio 优先修复；不能据历史错误断言新版仍坏 | 本轮处理其遗留的明确未发送恢复，未新增模型/UI实验 |
| 修正容量不足 | 是观测时刻配置/运行态，不足以证明代码缺陷；仓库已有用户后续改动 | 不按旧固定 8/4/3 擅自覆盖当前配置 |
| 引文定位计入科学修正、通过行带失败标签 | 指标语义混用真实 | pass 的 failure_kind 改 null；报告明确分母，不重写历史评分、不增加未经授权的面板展示 |

## 对报告结论的限制

- 报告中的模型身份标签并非底层服务身份的独立实测（03 已主动注明），不能把标签本身作为真实性证明。源码和运行证据可独立验证。
- 三份报告来自同批不同观察窗口，throughput、failed、报告数量持续变化，不能拼成一个同一时刻漏斗。
- 本次只读观察 card_review_jobs：corrected 472、correction_queued 260、failed 758、passed 142、queued 95、ready 16、rework_queued 199、submitted 10。passed 包含发布别名，不能直接视为 142 篇通过。
- card_correction_jobs：applied 574、failed 480、needs_user 2、ready 12、superseded 13。这些是观察时刻状态，并非修复后收益。
- 低通过率不能仅归因科学质量；也不能反过来断言“主要都不是科学质量”。报告没有逐篇复核科学内容，不能保证修复后通过率或恢复 241 条全部成功。
- 472 个准备阶段引文定位任务没有原科学评估，不应描述为 472 份科学报告被覆盖。
- 保留等值/指纹/唯一会话/人工/暂停守卫比为吞吐放宽比较更可靠。历史保护任务必须由原生产线程逐项核对，不做 SQL 批量复活。

## 配套改动与边界

更新 review、correction 接口合同及 README，infrastructure 说明；新增漏斗合同测试，并补技术 failed、科学 failed 和旧修正无后继 marker 恢复测试。全局登记移除已按 20261018 删除清单删除的五份 codex_desktop_chat 历史审计文档；生产源码登记不变，两个使用方已作仅文档删除的适配确认。维护脚本 reset_protected_after_timeout 仅将内部导入改为公开 API，未执行该脚本。

最终验证及交接结果见后续验证记录。本报告的源码修复不等于生产部署或科学验收。

只读真实样本复算：从精确“报告变化”失败中取最新三条，check_task 原冻结证据全部一致，显式传配置后的 feedback 与 assessment 均逐对象等于原任务（3/3）；见 `20261018-review-funnel-readonly-samples.json`。复算使用 SQLite mode=ro/query_only 和仅含 path 的对象，未构造会安装 schema 的生产 Catalog，未改原回执。

## 最终验证与交接

- `NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost make test`：2338 次执行、2127 个唯一用例，0 failure / 0 error / 0 skip。localhost 绕过仅作用于本次测试进程，不改生产代理。初轮全量失败日志与最终通过日志均保存在 `20261018-review-funnel-validation/`。
- `make check`：14 个组件、237 个生产源码文件、344 个公开出口，passed=true。
- 全局 update 与 check_links：8 项目、4 工具、66 登记源码文件、6 模块链接通过；`git diff --check` 通过。
- 全量测试额外发现并处理：无 shared_page_backlog 时自动释放检查仅安全返回，不推断可释放；92 个已删除且与删除清单 SHA 一致的历史报告登记迁至 deleted_entries，原路径/哈希保留，公开读取列表不再宣称文件存在；对应测试同步验证删除语义。
- 验收前后 123 个生产模块指纹及外部内核指纹一致，发布确切版本验收回执；既有监督流程正常退出旧所有者并通过原注册入口接续。新 PID 87304 实查存活，加载源码与验收完全一致，状态 new_owner_confirmed。未强杀、未增加常驻入口/CDP 所有者，未解除暂停、未手工改写任务状态或重发旧请求。
- 存量任务由原线程逐项核对恢复；本轮未把恢复候选量冒称修正完成量，尚无新版卡片科学通过收益的验收。重复 DDL 生命周期、完整指标产品化、上游证据提取质量仍属后续独立事项。
- 三份已分析原件按 audit_reports/README 规则在本聊天交付分析后逐一删除；保留指纹清单与本独立处理报告，无原件副本。
