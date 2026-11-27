# 种子文献库与手动原文分流（2026-10-18）

用户要求：

- 文献库放在 SSD，不在桌面；放入文献库的 PDF 直接作为种子，并优先制卡。
- 桌面“文献暂存”放用户手动拉取 DOI 的 PDF；识别后移到 SSD 的真实文献库，与自动拉取文献同等地位，不再自动成为种子或优先任务。
- 系统读取文献库/文献暂存后自动移动文件，不应删除目录本身。

实现边界：

- `manual_literature.seed_directory` = `/Volumes/ssd-1t-1/paper-library/文献库`，是种子入口。
- 种子入口的 PDF 经身份核对、原文入库、字节指纹校验后，移入 `seed_storage_directory` = `/Volumes/ssd-1t-1/paper-library/library/seeds`；登记 `manual_seed_roots` 与 `manual_card_priority`。
- `manual_literature.directory` = `/Users/xiaoyanhao/Desktop/文献暂存`，是普通手动 DOI 入口；导入为普通候选，不设种子、不写 `manual_card_priority`；核对后移入 `storage_directory` = `/Volumes/ssd-1t-1/paper-library/library/manual`。
- 旧“完成修正+核验后移入桌面文献库”的完成后归库流程停用（`archive_completed_enabled=false`）；已完成文献仍在工作台/卡片与原文资产中，不因本次调整删除。
- 补充材料仍不能单独作为原文；识别为补充材料的文件保留在入口并标 `seed_needs_inspection`/`needs_inspection`。
- Word 笔记只提取 DOI 关联已登记原文，不进入科学输入，不单独作为原文移动。
- 不增加常驻入口，不恢复暂停，不重发未知请求；原文、卡片、回执和人工决定不改写。

迁移证据：

- 三篇种子文件从桌面文献库迁至 SSD 文献库，字节 SHA-256 见 `infrastructure/data/seed-library-restore-20261018.json`。
- 2026-10-18 手工扫描后：`反向能量传递.pdf` 已入库并移入 `library/seeds`，登记种子 root 与 priority；两篇 ACS 文件被识别为补充材料，保留在 `文献库` 待核对；15 篇原 `文献暂存` PDF 移入 `library/manual`，撤销旧手动种子优先级；`triplet_coherence_PRL2024.docx` 仅作为阅读笔记关联，不移动。
