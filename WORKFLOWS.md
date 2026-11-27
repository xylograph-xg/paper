# paper 项目地图

根目录包含十一个物理项目。源码组件按业务归属嵌套，组件接口和Python包名保持；没有源码软链接。

| 顶层项目 | 内容 |
| --- | --- |
| [fetch](fetch/README.md) | 文献发现与原文拉取；fetch, crawler |
| [cards](cards/README.md) | GPT文献制卡；cards |
| [review](review/README.md) | 独立科学核验；review |
| [correction](correction/README.md) | 卡片修正与循环；correction |
| [workbench](workbench/README.md) | 阅读工作台与证据解析；workbench, reading, read, desktop_widget |
| [infrastructure](infrastructure/README.md) | 共享运行、浏览器调度与维护；core, browser, maintenance, article, pipeline |
| [codex_desktop_chat](../tools/codex_desktop_chat/codex_desktop_chat/README.md) | 独立桌面Chat与通用ZIP工具；codex_desktop_chat |
| [codex_web_client](../tools/codex_web_client/codex_web_client/README.md) | Codex Web GPT 的 Python 客户端、持久任务队列与结果核对 |
| [oled_formulas](../tools/oled-formulas/oled_formulas/README.md) | OLED 行间公式提取、临时聊天批处理和按篇归档 |
| [literature](literature/README.md) | 文献标签、证据与主题学习集合；literature |
| [reports](reports/README.md) | 评审与审计报告； |

共享配置、运行数据、授权文档、维护规则和旧入口全部属于 infrastructure；第三方拉取依赖属于 fetch；PDF/科学/测试依赖清单归各自组件。根目录 AGENTS/README/WORKFLOWS/workspace.json/Makefile 是工作区入口，不承载业务实现。

旧回执和冻结JSON仍保存原字节。读取旧路径时使用 core.api.paths__WorkspacePath，具体物理路径见 workspace.json 的 physical_roots。迁移不解除暂停，也不重发未知请求。

```sh
make test
make check
python -m maintenance.test_runner --project fetch
```

用户已要求删除数据备份；不创建新的数据备份。原文、卡片、数据库和回执仍是正式数据。

启动导入适配位于 infrastructure/bootstrap/sitecustomize.py；根目录只保留工作区规则、说明、项目地图、Makefile和workspace.json。
