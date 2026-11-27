# 来源元数据组件

OpenAlex/Semantic Scholar解析、跨来源去重、主题扩展、相关性排序、人工反馈及原登记发现CLI。

这是独立源码与接口文件夹，正式包名为 `crawler`。跨项目只调用 `crawler.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

保留登记工具的唯一源码位置与纯标准库接口。api.load_metadata_parsers隔离该工具的顶层config/models命名空间，避免污染其他子项目；实际生产来源配额由fetch控制。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from crawler.api import load_metadata_parsers
```

运行依赖：无需其他业务子项目；外部依赖见原接口及环境清单。。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project crawler
make check
```

登记工具原独立测试：`cd literature_explorer && python3 -m unittest discover -s tests`。生产解析通过api隔离顶层模块，保留原工具调用约定。

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [01_core_repository_analysis.md](01_core_repository_analysis.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [00_Literature_Explorer_初步大纲.md](00_Literature_Explorer_初步大纲.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [tool-dependencies.json](tool-dependencies.json) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `load_metadata_parsers` | 当前公开接口或生产链使用；避免复制实现 |
| [AGENTS.md](AGENTS.md) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/config.py](literature_explorer/config.py) | Literature Explorer 配置：全部通过环境变量覆盖，无硬编码密钥。 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/connectors/semantic_scholar.py](literature_explorer/connectors/semantic_scholar.py) | Semantic Scholar connector：搜索 / 单篇 / references / citations。 | `_get_client`、`_headers`、`parse_paper`、`search_semantic_scholar`、`get_semantic_scholar_paper`、`_fetch_edges`、`get_semantic_scholar_citations`、`get_semantic_scholar_references` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/connectors/openalex.py](literature_explorer/connectors/openalex.py) | OpenAlex connector：搜索 / 单篇 / references / citations。 | `short_id`、`restore_abstract`、`_params`、`parse_work`、`_fetch_works`、`search_openalex`、`get_openalex_work`、`get_openalex_references`、`get_openalex_citations` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/connectors/base.py](literature_explorer/connectors/base.py) | HTTP 基础设施：per-instance 限流锁 + 双预算重试（简化自 findpapers ConnectorBase）。 | `ConnectorError[]`、`HttpClient[__init__, _rate_limit, get_json, _backoff]` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/ranking/embedding.py](literature_explorer/ranking/embedding.py) | Embedding provider：OpenAI 兼容 /embeddings 接口 + (paper_id, model, text_hash) 缓存。 | `paper_text`、`text_hash`、`is_configured`、`model_name`、`_embed_batch`、`embed_texts`、`embed_topic`、`embed_papers` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/ranking/relevance.py](literature_explorer/ranking/relevance.py) | 相关性打分：embedding cosine 优先，未配置 embedding 时降级为词袋重叠打分。 | `cosine`、`_tokens`、`lexical_score`、`score_papers`、`rank` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/discovery/citation_expand.py](literature_explorer/discovery/citation_expand.py) | Citation expansion：只对 interesting 论文执行，每轮只扩一层。 | `_ingest`、`expand_from_paper` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/discovery/query_expand.py](literature_explorer/discovery/query_expand.py) | Query expansion：确定性实现，不动用 LLM。 | `initial_queries`、`expanded_queries` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/discovery/loop.py](literature_explorer/discovery/loop.py) | Discovery loop：topic → 搜索 → 术语反哺第二波 → 打分排序 → Top N。 | `run_discovery_cycle` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/discovery/search.py](literature_explorer/discovery/search.py) | 双源搜索：OpenAlex + Semantic Scholar → 标准化 → 去重合并 → 入库 → 记 provenance。 | `search_papers` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/models/paper.py](literature_explorer/models/paper.py) | 统一 Paper 数据模型：去重键、合并规则、序列化。 | `normalize_doi`、`normalize_title`、`Paper[dedup_key, ensure_id, merge, to_dict, from_dict]` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/storage/sqlite.py](literature_explorer/storage/sqlite.py) | SQLite 持久化：所有搜索结果与状态可恢复，中断后可继续。 | `_now`、`Store[__init__, close, __enter__, __exit__, create_run, finish_run, latest_run, _find_existing, upsert_paper, _row_to_paper, get_paper, set_score, commit, count_papers, add_discovery, provenance_for, record_feedback, get_feedback, review_queue, interesting_papers, score_for, top_scored_papers, get_embedding, save_embedding, citation_fetch_done, mark_citation_fetch]` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/scripts/expand_interesting.py](literature_explorer/scripts/expand_interesting.py) | 对所有 interesting 论文做引文扩展（references + citations），生成下一批候选。 | `main` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/scripts/review_candidates.py](literature_explorer/scripts/review_candidates.py) | 逐篇审核候选论文：interesting / reject / later。 | `_show`、`main` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/scripts/search_topic.py](literature_explorer/scripts/search_topic.py) | 搜索一个研究主题，产出 Top N 候选论文。 | `main` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/screening/queue.py](literature_explorer/screening/queue.py) | 待审队列：已打分、未被判定 interesting/reject 的论文，按相关性降序。 | `get_review_queue` | 当前公开接口或生产链使用；避免复制实现 |
| [literature_explorer/screening/feedback.py](literature_explorer/screening/feedback.py) | 人工反馈：interesting / reject / later（later 会回到待审队列）。 | `record_feedback`、`interesting_papers` | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [literature_explorer/tests/test_core.py](literature_explorer/tests/test_core.py)：离线/隔离回归，验证当前合同。

## 数据、并发和权限边界

显式工具调用可能访问公开来源或写独立SQLite；纯解析API不联网。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../../infrastructure/config/README.md)，共享状态合同见 [data](../../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 审核回归（2026-10-14）

登记工具的修复位于唯一源码 [literature_explorer](literature_explorer/README.md)：来源失败持久延后、矛盾身份隔离、embedding严格对齐、当前波次关键词和HTTP冷却。新增 [test_audit_regressions.py](literature_explorer/tests/test_audit_regressions.py)，独立运行标准库测试，不初始化主生产库或调用外网。纯解析 `api.load_metadata_parsers` 的出口与签名保持。
