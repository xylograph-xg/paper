# 零页重建、启动页可替换与预留自锁修复

本轮目标是让“20 个固定页全部丢失 / 启动页全部为代理错误页”不再形成永久卡死，并解除旧上传预留对重试的自锁。

## 代码修改

- `shared_window_start.run_once`：识别 `initializing_window` 指向的窗口已无任何登记页，且全部旧槽 `opening/never_submitted`、无 attempt 账本时，归档旧 request/registry，清理旧 `window_creation_intent`，标记旧槽 `retired_window_lost`，再走原有新窗口/20 槽创建路径。
- `shared_page_health.classify`：`opening + never_submitted + 无账本 + 完整历史` 的稳定错误页允许归档替换；有账本、未知提交或不完整历史仍保护。
- `startup_page_restart.run_once`：20 条启动页替换逐条独立处理，单条 target 消失/内容变化只标记 `blocked`，不再头阻塞其余条目；终态区分 `complete/partial`。
- `original_upload_http1.material_intent`：只把真实 `intent.json` 当作可能已发送回执；`reservation.json`（含 156 个 `not_observed`、31 个 `armed`）不再阻断同材料重试。31 个 `armed` 均有对应 intent，仍由 intent 保护。
- `first_round.json`：关闭普通路径的 HTTP/1.1 原 PUT 探测；上传并行 5→3；附件结算 180→300 秒。原 epoch、intent、reservation 字节保留。

## 验证

- 定向回归：shared_page_health / shared_window_start / startup_page_restart / original_upload_http1 / shared_page_repair / shared_window_owner / web_page_observer / owner_upload_jobs，220 项通过。
- review upload backoff：78 项通过（旧“reservation 阻断”测试改为新语义，并断言真实 intent 仍由浏览器测试保护）。
- `make test`：2276 项执行，0 失败、0 错误；2093 唯一 ID、183 重复导入。
- `make check`：14 组件、234 生产源码、343 公开出口，0 错误。
- 全局 `sync_tools.py update`：0 变更；`check`：0 待同步。

## 线上恢复边界

当前 Chrome 仍在，但专用窗口 0 页；当前 20 个固定 target 的 pool 均为 `opening/never_submitted`，attempt 历史命中 0，故允许整窗重建。重建只创建空白启动页，不重发任何已发送/未知请求。当前系统网络到 `chatgpt.com` 超时，重建后页面可能先显示网络错误；新逻辑不会再因此永久卡死，网络恢复后可替换/重新加载。

## 最终线上恢复结果（20:31–20:39）

- 原 owner 45602 正常退出，82206/83484 为过渡 owner；最终 85200 通过原 LaunchAgent 入口启动，旧进程已退出，没有新增 CDP 所有者。
- 20 个固定槽位全部重建成功：`shared-gpt-window-status` 为 `ready`，`live_fixed_slots=20`，`missing_slot_ids=[]`。
- `web-card-service` 从 `waiting_browser` 进入 `running`：`live_total_pages=20`，`workers=1`、`uploading_pages=2`，观察器为 `idle 16 / generating 4`。
- 共享 backlog：`current_tasks=3`、`queued_tasks=68`、`ready_queued_tasks=27`，额度/暂停/未知回执保护未解除。
- 20:29:41 记录到一次 3.90MB 原生上传成功（30.1 秒），说明上传路径已恢复。
- 启动页健康分类新增网络保护：代理断开时保留启动页等待重新加载，不反复关闭重建；`network_unavailable` 计数可见。
- 当前仍有一个空的“启动页维护：”错误显示；不影响页面派发与上传，后续可按真实异常栈继续收窄。

## 2026-10-17 22:30 现场修复结果

- owner 已重启到 97312；`owner-supervision=healthy`，20/20 页在位。
- 当前观察：7 页生成、5 页完成、8 页空闲；completed 982，needs_inspection 494，failed 419，queued 105。
- 新上传代码已被现场使用：新卡片 attempt 出现 `local_file_write_node=objectId`；22:22 一次 14.6MB 核验上传成功（84.3 秒）。重启后未再看到 `write_failed`。
- 两篇被“补充材料未提供”误判的已保存回答已手工发布为 completed（adc174a0…、a8a66586…），未重发。
- 1520 个旧窗口（437812756）的 `shared-page-repairs` journal 已移入 `shared-page-repairs-archive/20261017T221235`，带 SHA-256 索引；当前窗口 journal 未改动。`shared-page-health` 与 `shared-page-repair-status` 均为 `checked`、errors 为空、pending 为空。
- `shared_page_repair` 成功周期现在也刷新 `shared-page-repair-status`，不再只在失败时写旧状态。
- 全量测试仍有 reading 的 5 个环境错误（本地模型 502/HTTP 测试服务空 JSON）；上传、投递、page-grid、repair 的定向测试通过，`make check` 通过。

## 2026-10-17 23:50 快车道与状态色

- `workflow_priority` 增加 `fast_lane`：卡质量≥80、核验分≥85 或总分≥170 的记录排在普通 lane-minimum FIFO 之前；已通过修正/人工优先仍高于快车道。
- `shared_workflow_queue` 的 `minimum_priority` 对 `fast_lane` 返回最高优先级，但仍受 lane 硬上限、保护页和未知回执约束。
- 页面网格新增 `severity`：正常运行/排队保持 lane 色，普通保护与陈旧观测为弱灰，不可用为深灰，登录/验证/额度/移出专窗/未知/错误等硬问题为红色。Swift `TaskPanel` 已重编译并重启。
- 64MB 总上传预算已上线；当前 3 个上传占 28.5MB，但 HTTP/2 `ERR_HTTP2_PROTOCOL_ERROR` 再次触发通道冷却，新 claim 暂停。
