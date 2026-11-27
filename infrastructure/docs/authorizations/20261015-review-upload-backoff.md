# 核验上传失败技术退避

2026-10-15，用户在本聊天要求执行 S002 工单：`AUDIT_RUNS/20261015-015746-1d5193cc-upload-verification/SOLUTIONS/20261015-021516-efcdd535/TASKS/S002.md`（“核验上传失败退避与统一领取守卫”，对应 G-2/U-08，P1，FIX_REQUIRED）。本条只记录该工单已实现的边界，不构成对其他通道的启动、恢复或外发授权。

根因由方案阶段 CONFIRMED：`review_channel_recovery.recover` 把明确未发送的失败回执直接改回 `ready`，`card_review_jobs` 没有 `retry_at`，也没有技术失败计数；同 ZIP 因此每轮重新烧掉约 200 秒。仅给 `recover` 加 sleep 无效，因为已 `ready` 的材料仍会被立即领取。

授权范围：新增 `browser.upload_retry_policy`（公开出口见 `infrastructure/browser/interface.json`），策略键 lane＋job_id＋inputs_digest＋ZIP SHA，另存唯一 `failure_receipt_id`；只有明确结束、从未点击发送的原生上传技术失败每回执计一次；窗口 5／15／60 分钟（第三次及以后按配置低频自动重试），成功清连续计数而总证据保留；扫描与重启既不更新失败时间也不延长冷却。配置 `card_review.upload_retry.enabled=true`，`backoff_seconds=[300,900,3600]`。

守卫位置：`recover`（归档/原租约核对链全部通过后仍要到期才 `ready`）、`ReviewLane.submit` 的 `BEGIN IMMEDIATE` 领取、提交锁内最终 `before_send`、混合队列 `_head`、非混合 `heads`、`eligible_records` 与 `reconcile` 库存口径。冷却材料保留真实物理分配与不可变 FIFO，显式非到期；not-ready、缺材料、归属变化不得被当成冷却跳过。已 `claimed`、实际上传中、未知归属不移动、不释放、不重发。到期不证明页面可复用。

不变与禁止：用户暂停、额度、访问验证、人工决定、原文/版本/范围保护与真实生成优先于到期；不改 P85、页池页数、固定槽、科学内容、历史回执与科学失败次数；制卡原有额外 2 次与专项次数保持，本轮无新制卡授权；legacy 无详细错误码不批量回填历史次数、不解除 unknown；策略损坏保留材料并停止该材料新领取，不静默当零失败；不新增常驻入口、CDP 所有者或外发通道。

回退：`card_review.upload_retry.enabled=false` 只禁用这一条新调度政策并回代码，两张证据表保留，不恢复旧队列快照，禁用不得成为旧请求重发入口。

证据：实现与验收报告见 `AUDIT_RUNS/20261015-015746-1d5193cc-upload-verification/SOLUTIONS/20261015-021516-efcdd535/RESULTS/`；行为说明见[核验上传失败退避](../../browser/docs/核验上传失败退避.md)。真实生产页自然流量样本与科学验收独立记录，不以离线合同通过代替。
