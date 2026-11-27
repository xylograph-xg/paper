# 网页版制卡唯一所有者 CPU 空转分析与处置报告

- 时间：2026-11-01 00:32–00:47（本地，UTC+8）
- 对象：PID 54670，`local.paper.web-cards`（`cards.web_card_service run --config infrastructure/config/first_round.json`）
- 现场数字见 [证据文件](20261101-web-card-owner-idle-spin-evidence.json)
- 标注约定：**实测**=当场取到的数；**推断**=由实测推出的解释，未单独验证

## 一、结论

CPU 不在做卡片，在做"重复盘点"。所有者进程已 11.7 小时没有任何外发产出，却仍以约 **2.3 个核满载**运行；累计 76.2 CPU-小时里，约 **27 CPU-小时是零产出的空转**。

三件事叠在一起才成为故障：

1. **空转成本**：每个调度周期都对回执仓库作全量递归重扫（实测 33,796 目录 / 129,614 文件 / 19,228 个 `attempt.json`，单次 rglob 实测 2.32 秒、其中 1.08 秒是系统时间），同时 24 个线程在 SQLite 读与 GIL 上互相踩踏。
2. **无产出原因**：专窗 20 个槽位里 10 页被 `submitted` 账本按"生成或活动页面必须保留"锁死，`workers=0`、状态 `waiting_browser`；核验队又因 `packet_version != 1` 把任务"领取→回滚→重新入队"原地打转。派发不前进，盘点照旧跑。
3. **停不下来的原因**：官方 `stop` 只置了制卡队的用户暂停，`owner_enabled()` 仍返回 True（实测：cards=False、shared window=True、review=True、correction=True → owner_enabled=True），循环的退出条件永不成立。这与 AGENTS.md"用户暂停优先于功能开启"直接冲突，属实现 bug。

大白话因果映射：**耗 CPU 的旋钮不是"并行 20 页"，而是"每轮重新清点整个回执仓库"**。清点结果 11.7 小时没变过一次（因为没有页可派），所以这份消耗没有换回任何卡片、核验或修正进展。

## 二、处置时间线

| 时刻(本地) | 动作 | 实测结果 |
|---|---|---|
| 00:32 | `top`/`ps` 取证 | 54670 CPU 208–227%；10 秒墙钟内 CPU 时间涨 23.5 秒；24 线程 |
| 00:34 | `sample 54670 2` | 栈顶全是 `take_gil` 等待 + `pysqlite_cursor_iternext`；`sqlite3_step → progress_callback → os_stat` 15 帧 |
| 00:36 | 服务 `status` CLI | `state=waiting_browser`、`workers=0`、`queued=6160`、`submitted=10`、`pool_ready=9` |
| 00:37:57 | `python -m cards.web_card_service stop` | 返回 `stop_requested`；写入 `paused_by_user=true`；**未**写 `web-card-stop.json`（`owner_enabled()` 当时仍为 True） |
| 00:38–00:43 | 连续观察 5 分 | CPU 190→265%，仍满载；`web-card-service.json` 仍刷新到 00:43:22 |
| ~00:44:30 | `kill -STOP 54670` | 状态 `T`、CPU 0.0%、CPU 时间冻结在 4572:24.75 |
| 00:46–00:47 | 复核 | 整机 86.88% idle（原 61.68%）、sys 7.21%（原 23.58%）、load1 5.59（原 7.05）；状态文件 `updated` 20 秒内两次取值不变，确认无第二个写入者 |

当前遗留状态（需要你知情）：

- 进程处于**冻结**，未退出。它仍持有 `web-card-service.lock`、`correction-producer.lock` 的 flock 和 20 页专窗归属 → 任何其他入口无法接管，也不能重复启动。
- `paused_by_user=true` 已生效，watcher 依规则也不能拉起（`start()` 会抛"已被用户暂停"）。所以这是**持久暂停**，不会被自动恢复。
- 1.9 GB RSS 未释放（冻结不解内存）。`queued=6160` 停在队列中；`submitted=10` 未收口。

## 三、根因链（分三层）

### 3.1 空转成本来自哪里（实测）

- 调用点：[web_card_pool.py:813](../infrastructure/browser/web_card_pool.py#L813) 每周期 `index_attempts(root)`。
- 扫描体：[attempt_history.py:68](../infrastructure/browser/attempt_history.py#L68) 对 `web_cards`+`card_reviews` 两支作 `rglob('attempt.json')`；每个命中在 [attempt_history.py:37](../infrastructure/browser/attempt_history.py#L37) 与 [:43](../infrastructure/browser/attempt_history.py#L43) 各 `stat()` 一次；末尾还要遍历进程缓存 `_CACHE` 逐条判断是否被归档。
- 实测代价：单次全量 rglob 2.32 秒（sys 1.08 秒）。这一项约等于**持续一个核**。
- 24 线程 × GIL：采样中 289/266/236/215 帧停在 `take_gil`，即线程把时间花在"排队拿锁"而不是计算；`owner-thread-dump.log` 37 次转储中 **18 次**停在同一 `_index_attempts` 帧。
- 另有一路纯 SELECT 检查点：[cooperative_sql.py:44](../infrastructure/core/cooperative_sql.py#L44) 每 1000 条 VM 指令回调一次 Python，回调里出现 `os_stat`（实测 15 帧）——这正是 2026-10-17 为"主线程数据库游标遍历"加的机制（AGENTS.md 有记录），**它能 yield、不能 break**。

**推断**：全量扫描约 1 核，其余约 1.3 核来自 SQLite 轮询 + GIL 往返；未逐调用计数验证。

### 3.2 为什么 11.7 小时没有产出（实测）

- 队列：`queued=6160`、`workers=0`、`review_workers=0`、`submitted=10`、`needs_inspection=528`、`failed=841`。
- 页面：`live_total_pages=20`、`pool_ready=9`、`pool_busy=3`；健康快照 `counts={busy:10, completed_saved:9, saved_response_protected:1}`，`available=9`、`protected=11`；10 个 busy 页原因均为"生成或活动页面必须保留"、`ledger_state=submitted`、`replace_allowed=false`。
- 配置 `background_no_create=true` → 不允许新开页，只能用这 20 个槽；槽位被保护态占满 → `phase='waiting_browser'`（[web_card_pool.py:1092](../infrastructure/browser/web_card_pool.py#L1092)、[:1118](../infrastructure/browser/web_card_pool.py#L1118)）。
- 历史窗口登记 2,942 条：`retired_replaced 2404 / missing 307 / needs_inspection 107 / opening 87 / busy 25 / ready 10 / repair_pending 2`。其中 `opening`/`repair_pending` 在归档核对循环里被直接跳过（[web_card_pool.py:806](../infrastructure/browser/web_card_pool.py#L806)），不会转成 `missing`。
- 核验队独立拒派：`review-dispatch-rejection.json` reason=`image_upgrade_preparation`，条件为 `packet_version != 1` → 任务回 `queued` 并 `rollback_claim`（[card_review_lane.py:245](../review/card_review_lane.py#L245)）。6,160 条待办按此路径反复领取-回滚。

**推断**：真正的死结是那 10 个 `submitted` 未收口账本（数量与 10 个被保护页精确相等）；它们既不允许换页，又没有走完"完整收取→释放"，于是 20 槽永久不足，派发与核验双双停摆。

### 3.3 为什么官方 `stop` 无效（实测）

```
cards enabled=False, shared window=True, review=True, correction=True → owner_enabled()=True
```
- 退出条件只在 `not owner_enabled(config)` 时触发（[web_card_pool.py:552](../infrastructure/browser/web_card_pool.py#L552)、[:641](../infrastructure/browser/web_card_pool.py#L641)）。
- `stop()` 仅写制卡队的用户暂停；因为 `owner_enabled` 经"共享窗口 + 核验或修正任一开启"分支仍为 True，它连 `web-card-stop.json` 都没写（现存文件是旧 owner pid 86532 的陈旧请求）。
- 结果：**已验收的三队共享所有者语义，压过了单队用户暂停**。AGENTS.md 明确"用户暂停优先于功能开启、时段、额度恢复及常驻重启"，此处实现与规则不一致。

## 四、建议（按优先级，含授权边界）

P0（需你选一条，我不擅自动另外两队或强杀）：
- A 保持现状：冻结即已止血（整机空闲 86.9%），代价是专窗归属与两个 flock 一直被占，恢复前无法并行推进任何网页队。
- B 走正常退出：先把核验、修正两队也置用户暂停，使 `owner_enabled()` 变 False，所有者在下一周期 `break` 并落 `state=stopped`、释放锁。**这会暂停另外两队**，需要你明确授权。
- C 立即终止（`kill -TERM`）：pool 模式未注册 SIGTERM 处理（[web_card_service.py:557](../cards/web_card_service.py#L557) 在 `run_pool` 分支之后），默认处置=直接死。锁由内核回收，WAL 崩溃安全，但 `web-card-service.json` 会停在 `waiting_browser`、可能残留半写的临时 JSON。**不建议**，除非 B 也走不通。

P1（代码修复，属"修改代码不构成外发授权"，可离线做）：
1. `index_attempts` 加节流与增量：按 lane 缓存 rglob 结果、以目录 mtime/登记数变化触发，或至少限制"每 N 秒最多一次全量"，避免每周期重扫 19,228 条回执。
2. 让检查点能中断：`scan_checkpoint` 与 `read_checkpoints` 回调除 yield 外，必须能在暂停/停止时抛断，使 `stop` 在 50ms 内生效。
3. 修 `owner_enabled` 优先级：单队 `paused_by_user` 不应被"共享窗口 + 他队开启"覆盖成继续满载运行；至少要能停派发、保留低耗看护。
4. 核验队 `packet_version != 1` 路径加退避：同一 job 不得立即重领，避免 6,160 条队列的 claim/rollback 空转。
5. 给 `workers=0 且 state=waiting_browser 持续 >15 分钟`加显式告警（写入 `action-inbox.json`），这类停摆 11.7 小时无人知。

P2（需先查证据再动手，涉及真实会话，不能靠重启糊过去）：
- 逐条核对那 10 个 `submitted` 账本与页面：按 AGENTS.md 只核对原 target/唯一会话与材料标识，**不重发**；完整收取并核对 hash 后才释放槽位。
- 查 `needs_inspection=528`、`failed=841`、`opening=87` 是否同源；`missing=307`/`retired_replaced=2404` 是否应退出活跃盘点。
- 查核验队"图像升级准备"是否自己卡住（若卡在准备环节，P2 的第一条无从谈起）。

## 五、恢复步骤（备忘）

- 解冻继续跑（注意：`paused_by_user` 仍为 true，恢复派发需先经官方 `start` 清暂停，否则仍不派新任务）：`kill -CONT 54670`
- 查看归属状态：`cd /Users/xiaoyanhao/project/paper && infrastructure/environments/web/bin/python -m cards.web_card_service status --config infrastructure/config/first_round.json`
- 复核暂停标志：`cat infrastructure/data/web-card-control.json`

## 六、我没有做也不打算擅自做的事

未杀进程、未清理任何 `data/` 回执或队列、未改代码、未暂停核验/修正队、未触碰 Chrome 页面、未重发任何未知回执。本次只写了两个用户暂停标志位（可回滚）与一次 SIGSTOP 冻结。
