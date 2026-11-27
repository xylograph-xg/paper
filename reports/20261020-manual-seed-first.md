# 手选根种子全环节第一顺位

用户2026-10-20明确要求所有环节以及重试保持手选种子第一顺位。权威根身份来自 manual_seed_roots，衍生文献不自动获得优先身份。

## 实现

- core.workflow_priority 原排序已以 seed_fast_lane 为首；新增只读 seed_first 用于恢复和重试扫描，保留原记录对象和组内次序，避免附加派生字段破坏原始CAS核对。
- browser.shared_workflow_queue：跨队列领取/上传排序最外层加入种子优先，先于普通最低并行补足和普通高分快车道；原非混合 heads 也采用统一优先排序。
- browser.shared_page_backlog：核验/修正/后继重做中的根种子也触发原未领取材料补充重组，不再仅识别首次手动制卡。
- browser.web_page_queue：材料分配优先种子；现有准备阶段沿用统一排序；旧 next_ready 也保留根种子第一顺位。
- browser.web_card_pool：两个原上传入口共用 _seed_admission；合法种子待字节容量时，普通小包不能继续占用下一份容量，原上传正常结束。
- cards.web_card_queue：原 claim 兼容入口保留种子优先，仍只领取到期 queued 任务。
- cards.web_card_retry：归档恢复和有界重试扫描均先种子；持久游标轮转后再稳定分组，普通游标不越过种子；原退避/次数/归属守卫不变。
- review.card_review_queue：准备阶段优先种子候选，不再仅优先旧已分配页头；准备容量限制、原回答落盘优先仍保留。
- review.review_cycle、review.review_channel_recovery、correction.recover_review_corrections、core.automatic_issue_handler：恢复/后继循环稳定优先根种子，原证据核对和原任务字典不变。
- 全量检查发现 correction 旧扫描间隔测试以 __new__ 构造生产者，却未提供已有并行生产者所需 executor/workers/futures，且将内部0.2秒轮询误计为外层时间点；仅修复隔离夹具，保留原11个断言用例及生产实现。

## 边界

只改变合法可执行候选的顺序；固定8/4/3/5槽位、原活动/上传/已发送/未知页面、暂停、账户、额度、人工决定、原文版本、退避和次数均保留。完整回答的收取/发布仍优先于新的材料准备。不会把生成完成标记为科学验收。

## 验证

详见 [验证目录](20261020-seed-first-validation/)。targeted.log为55项、recovery.log为71项、upload.log为13项、producer-fixture.log为11项针对性检查。完整源码指纹、全库测试、接口检查、全局update/链接检查及正常交接证据分别独立保存；初期失败记录保留，不覆盖历史结果。

read-only-priority.json仅验证当前数据库的排序结果，不领取、不发送、不连接浏览器。部署是否完成以交接回执和运行进程源码指纹为准。
