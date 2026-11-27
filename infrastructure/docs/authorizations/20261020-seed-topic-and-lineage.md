# 新种子切题与手动种子来源隔离（2026-10-20）

用户要求：文献库中手动放入的种子可以是跨领域“思维方式”文献；但由这些种子拉取到的参考文献/被引文献/衍生内容**不得自动成为新种子**；其他自动新晋种子必须切题。

实现：

- 手动种子继续走 `manual_seed_fast_lane`，不因离场被过滤或撤销。
- `fetch.seed_expansion` 自动晋升前检查：
  - 候选不得存在于 `manual_seed_lineage`；
  - 不得直接来自 `manual_seed_roots` 的 `seed_discovery_origins`；
  - `seed_on_topic(title, abstract)` 必须为真；通用 ML/数据挖掘/风险最小化论文即使有高分卡片也不晋升。
- 历史清理：对 `auto_seed_quality` 自动种子中“来自手动种子 lineage”或“不切题”的 373 篇撤销 `seed=1/selected_as_seed`，保留原文、卡片和事件；清单见 `data/auto-seed-demotions-20261020.json`。
- 人工通过界面显式 set_seed 的种子不在此自动规则内；手动文献库种子不受领域过滤。
