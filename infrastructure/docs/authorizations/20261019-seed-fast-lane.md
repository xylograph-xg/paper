# 文献库种子快车道与无限技术重试（2026-10-19）

用户要求：文献库中放入的新种子在全流程第一优先级，并且不因重试上限被丢掉。

实现：

- `manual_seed_lineage.register_root` 为种子写入 `manual_seed_fast_lane=true`；现有 `manual_seed_roots` 已迁移。
- 发现：快车道种子排在 seed rotation 之前；Crossref 后备候选也优先。
- 拉取：`queue_pending` 排序优先；`fetch_policy.begin/finish` 对快车道目标不设 terminal；失败按退避保留，可无限重试。
- 制卡：沿用 `manual_card_priority` 先于普通精选；快车道制卡技术失败改为 `queued`+退避，不标 `failed`。
- 核验：新 review job 的 priority 设为 1,000,000（现有快车道 job 已迁移）。
- 修正：新 correction job 的 `fifo_at=-1`，现有 queued/preparing 已迁移。
- 安全边界：未知/已发送回执不重发；人工决定、身份/版本/范围、科学失败保护和核验/修正循环继续；无限重试仅指可安全重试的技术失败，不绕过这些门。

统一排序：`core.workflow_priority` 读取 `manual_seed_roots`，在 cards/review/correction 共用的排序键中把 `seed_fast_lane` 放在 passed-correction/manual/fast-score 之前，避免只靠各队列局部 priority 被其他置顶规则压过。
