# 共享运行与调度项目

本项目拥有四任务共用的控制/数据库、唯一浏览器所有者、页面调度、维护和旧入口适配。集中这些内容是为了保持一个状态来源和一个 CDP 所有者，业务项目仍通过公开接口调用，不复制代码或数据。

| 内容 | 功能与保留理由 |
| --- | --- |
| [core](core/README.md) | Catalog 原子事务、暂停/授权、任务生命周期、模型禁用守卫和运行路径解析。 |
| [browser](browser/README.md) | 原20槽专窗、共享调度、提交锁、观测和有证据的故障恢复。 |
| [maintenance](maintenance/README.md) | 离线测试、边界检查、审计、失败 DOI 清单及原 watcher。 |
| [article](article/README.md) | 仍使用的网页工具适配；启动只能请求原唯一所有者。 |
| [pipeline](pipeline/README.md) | 旧导入/CLI合同转发及旧静态发布资源，没有业务实现。 |
| [config](config/README.md) | 主配置、合同和依赖锁文件；配置开启不解除用户暂停。 |
| [data](data/README.md) | 唯一运行存储，原文/卡片索引、冻结输入、回执、人工决定和控制记录。 |
| [docs](docs/README.md) | 授权原文、模板和回执所依赖的静态证据，原字节保留。 |
| [工具目录](../../tools/README.md) | 各工具的调用说明。本目录是 paper 的工具依赖登记根。 |
| environments | 原网页和测试解释器，迁移原环境而非新建服务。 |
| api.py / interface.json | 只返回四个组件公开API，导入不会启动任务。 |
| pyproject.toml | 共享项目的独立构建及组件依赖。 |
| tool-dependencies.json / AGENTS.md | 本项目维护的全局工具登记和规则。 |

组件内部全部实现及功能说明见各自README。新增公开路径接口 `core.api.paths__WorkspacePath` 在读取时解析旧绝对路径；不改写旧回执/冻结材料、不造历史、不重发未知请求。根目录没有源码软链接或运行数据别名目录。

用户本轮禁用数据备份，已有数据备份副本已删除；数据备份接口明确阻断，不创建替代备份。原有控制、人工决定、暂停和唯一所有者保护继续有效。

验证：在工作区根执行 `make test` 和 `make check`。启动与暂停使用现有CLI和持久控制合同，迁移仅维护原有三个常驻入口。

启动导入适配位于 infrastructure/bootstrap/sitecustomize.py；根目录只保留工作区规则、说明、项目地图、Makefile和workspace.json。

2026-10-18 automatic_issue_handler 对完整核验报告的补充分流显式传入当前配置，与修正入队复核一致。
