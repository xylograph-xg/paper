# paper 文献工作区

全部内容归入十一个项目：fetch、cards、review、correction、workbench、infrastructure、codex_desktop_chat、reports、literature、oled_formulas、codex_web_client。每个项目及内部组件拥有README、公开接口和明确的内容归属；[项目地图](WORKFLOWS.md)列出用途和选择理由。

- [OLED 行间公式整理](oled_formulas/README.md)负责页图打包、网页转录和按篇归档。
- 文献拉取：[fetch](fetch/README.md)。
- 制卡、核验、修正：[cards](cards/README.md)、[review](review/README.md)、[correction](correction/README.md)。
- 阅读和任务面板：[workbench](workbench/README.md)，运行 workbench/commands 下现有启动器。
- 共享运行、配置、唯一浏览器所有者及正式数据：[infrastructure](infrastructure/README.md)。
- 全文献标签、证据与主题学习集合：[literature](literature/README.md)，工作台 `/literature`。
- 独立工具包含 [Codex App Chat](codex_desktop_chat/README.md) 和 [Codex Web GPT Python 客户端](codex_web_client/README.md)。
- 各类评审和整理证据：[reports](reports/README.md)。

根目录只保留工作区入口与规则。`make test` / `make check` 使用各组件独立测试。运行任务严格沿用[当前授权](AGENTS.md)；数据备份已禁用，正式原文、卡片、回执和暂停状态持续保护。
