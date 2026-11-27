# 文献发现与原文拉取

发现种子、主题、参考文献与被引文献，管理游标、来源限速、元数据缓存、直链/回退下载与身份核对。

这是独立源码与接口文件夹，正式包名为 `fetch`。跨项目只调用 `fetch.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

保留有界的原生HTTP适配与fetchpdf回退，而不是多进程绕过站点限速；已验证的ChemRxiv最小适配保留许可证。成功下载仍须真实PDF、DOI/题名、版本与SSD校验。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from fetch.api import fetch_timing__install
```

运行依赖：[core](../infrastructure/core/README.md)、[crawler](crawler/README.md)。

CLI/子进程入口：`python -m fetch.acquire_bridge`, `python -m fetch.discovery_bridge`, `python -m fetch.fetch_diagnostics`, `python -m fetch.fetch_service`, `python -m fetch.fetchpdf_bridge`, `python -m fetch.requeue_oa`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:. infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project fetch
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [fetch_diagnostics.py](fetch_diagnostics.py) | Read-only acquisition results and reasons for idle capacity; no HTTP probes. | `report` | 当前公开接口或生产链使用；避免复制实现 |
| [manual_seed_lineage.py](manual_seed_lineage.py) | Evidence-backed manual seed ancestry, independent of cards and reading notes. | `install`、`register_root`、`record_origin`、`reconcile`、`library_condition` | 当前公开接口或生产链使用；避免复制实现 |
| [discovery_bridge.py](discovery_bridge.py) | Isolated crawler adapter; stdout JSON, diagnostics kept inside result. | `oa_record`、`s2_record`、`page_state`、`distinct_seeds`、`discover` | 当前公开接口或生产链使用；避免复制实现 |
| [osti_retrieval.py](osti_retrieval.py) | Bounded OSTI public manuscript route, preserving DOI and version evidence. | `BindingConflict[]`、`lookup`、`fetch`、`bind` | 当前公开接口或生产链使用；避免复制实现 |
| [public_http.py](public_http.py) | Validate the addresses that are actually connected; preserve TLS host/SNI. | `dial_public`、`HTTPConnection[connect]`、`HTTPSConnection[connect]`、`HTTPHandler[http_open]`、`HTTPSHandler[https_open]`、`opener`、`requests_adapter` | 当前公开接口或生产链使用；避免复制实现 |
| [fetch_timing.py](fetch_timing.py) | Actual fetch attempt timestamps, including transitions made by old workers. | `install`、`status` | 当前公开接口或生产链使用；避免复制实现 |
| [preprints.py](preprints.py) | Bounded arXiv Atom and ChemRxiv/Crossref discovery channels. | `crossref_pdf_urls`、`crossref_record`、`relevant`、`parse_arxiv`、`safe_xml`、`parse_chemrxiv`、`discover` | 当前公开接口或生产链使用；避免复制实现 |
| [seed_crossref_fallback.py](seed_crossref_fallback.py) | Bounded DOI-exact Crossref references when the primary seed source fails. | `discover_seed` | 当前公开接口或生产链使用；避免复制实现 |
| [fetch_wait_recovery.py](fetch_wait_recovery.py) | Repair only evidenced pre-request host waits misrouted into fallback. | `reconcile` | 当前公开接口或生产链使用；避免复制实现 |
| [metadata_cache.py](metadata_cache.py) | Bounded public JSON metadata cache; no PDFs, cookies, failures or credentials. | `identity`、`location`、`read`、`write`、`prune` | 当前公开接口或生产链使用；避免复制实现 |
| [acquire_bridge.py](acquire_bridge.py) | Each acquisition uses its own Python process; MuPDF is never shared by threads. | `main` | 当前公开接口或生产链使用；避免复制实现 |
| [fetching.py](fetching.py) | Durable metadata discovery plus bounded fast/slow acquisition dispatch. | `seed_observation`、`discovery_schedule_path`、`discovery_schedule`、`record_discovery_schedule`、`schedule_discovery`、`persist_page`、`queue_pending`、`discover_and_queue`、`restore_checkpoints`、`run_acquisition`、`complete_acquisition`、`recover_fetch`、`fetch_loop`、`_locked_retry` | 当前公开接口或生产链使用；避免复制实现 |
| [oa_policy.py](oa_policy.py) | OA eligibility and acquisition priority; closed publisher links are not treated as downloadable PDFs. | `eligible`、`priority` | OA-only 入队与高收益来源优先 |
| [requeue_oa.py](requeue_oa.py) | Bounded, auditable requeue of OA records that were terminal before the OA gate. | `classify`、`requeue`、`main` | 受控恢复存量 OA；不发送请求 |
| [fetchpdf_bridge.py](fetchpdf_bridge.py) | Isolated public-only fetchpdf runner; stdout is a single JSON result. | `install_http_guards`、`main` | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [seed_expansion.py](seed_expansion.py) | Grow the main discovery graph from GPT-scored selected cards, without inference. | `expand_when_idle` | 当前公开接口或生产链使用；避免复制实现 |
| [chemrxiv_enrichment.py](chemrxiv_enrichment.py) | Paperscraper's Open Engage source under existing acquisition protections. | `resolve`、`enrich` | 当前公开接口或生产链使用；避免复制实现 |
| [network.py](network.py) | Small public-provider HTTP policy with persistent cooldowns, never long retries. | `DeferredRequest[__init__]`、`canonical_provider`、`provider_keys`、`provider_for_url`、`state_folder`、`state_file`、`ready`、`retry_seconds`、`failed`、`succeeded`、`pace`、`arxiv_connection`、`ProviderClient[__init__, get]` | 当前公开接口或生产链使用；避免复制实现 |
| [fetch_policy.py](fetch_policy.py) | Durable per-target and per-URL retry policy, including old live worker compatibility. | `install`、`fingerprint`、`begin`、`classify`、`record_url`、`select_urls`、`finish` | 当前公开接口或生产链使用；避免复制实现 |
| [acquisition_budget.py](acquisition_budget.py) | One deadline for all URLs, fallback lookup, validation and catalog writes. | `remaining` | 当前公开接口或生产链使用；避免复制实现 |
| [net_limits.py](net_limits.py) | Persisted host pacing shared by direct downloads and their redirects. | `pace_arxiv`、`pdf_connection` | 当前公开接口或生产链使用；避免复制实现 |
| [fetch_service.py](fetch_service.py) | Detached Python keeper for the fetch supervisor, independent of the web UI. | `paused`、`status`、`start`、`request_stop`、`run` | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/test_discovery_fallback.py](tests/test_discovery_fallback.py)：离线/隔离回归，验证当前合同。
- [tests/test_seed_parallel_discovery.py](tests/test_seed_parallel_discovery.py)：离线/隔离回归，验证当前合同。
- [tests/test_seed_expansion.py](tests/test_seed_expansion.py)：离线/隔离回归，验证当前合同。
- [tests/test_seeds.py](tests/test_seeds.py)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_pause.py](tests/test_fetch_pause.py)：离线/隔离回归，验证当前合同。
- [tests/test_manual_seed_lineage.py](tests/test_manual_seed_lineage.py)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_audit_safety.py](tests/test_fetch_audit_safety.py)：离线/隔离回归，验证当前合同。
- [tests/test_manual_discovery_origin.py](tests/test_manual_discovery_origin.py)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_pipeline.py](tests/test_fetch_pipeline.py)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_timing.py](tests/test_fetch_timing.py)：离线/隔离回归，验证当前合同。
- [tests/test_diagnostic_extraction.py](tests/test_diagnostic_extraction.py)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_source_efficiency.py](tests/test_fetch_source_efficiency.py)：离线/隔离回归，验证当前合同。
- [tests/test_owner_runtime_diagnostics.py](tests/test_owner_runtime_diagnostics.py)：离线/隔离回归，验证当前合同。
- [tests/test_retrieval_integration.py](tests/test_retrieval_integration.py)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_asset_integrity.py](tests/test_fetch_asset_integrity.py)：离线/隔离回归，验证当前合同。
- [tests/browser_seed_membership.cjs](tests/browser_seed_membership.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_improvement.py](tests/test_fetch_improvement.py)：离线/隔离回归，验证当前合同。
- [tests/test_osti_retrieval.py](tests/test_osti_retrieval.py)：离线/隔离回归，验证当前合同。
- [tests/test_fetch_efficiency_repairs.py](tests/test_fetch_efficiency_repairs.py)：拉取效率修复回归，覆盖来源冷却、缓存与入队。
- [tests/test_oa_gate.py](tests/test_oa_gate.py)：OA 门禁回归，覆盖 `oa_policy` 与 `requeue_oa`。
- [docs/按文献质量自动扩展种子.md](docs/按文献质量自动扩展种子.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/持续拉取问题审查.md](docs/持续拉取问题审查.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/新文献发现与来源回退.md](docs/新文献发现与来源回退.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/持续拉取通道.md](docs/持续拉取通道.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/文献拉取并发与当前瓶颈.md](docs/文献拉取并发与当前瓶颈.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/种子库管理.md](docs/种子库管理.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/PDF获取器接入.md](docs/PDF获取器接入.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

网络调用、临时文件和Catalog下载状态；不解除暂停或来源冷却。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../infrastructure/config/README.md)，共享状态合同见 [data](../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 归并后的完整项目范围

本目录同时拥有以下组件，各组件保留真实包名、公开接口、独立测试和逐文件说明。它们属于同一业务项目，不再占用根目录。

- `crawler`：来源元数据组件，保留已登记公开检索接口；说明见 crawler/README.md。
- `dependencies`：原 fetchpdf 第三方实现和许可证，供受保护回退拉取；没有新增上游。
- `environments/fetchpdf`：原回退解释器，仅随现有配置使用。

## 2026-10-14 审核修复

[审核核对与方案调整](AUDIT_REVIEW.md)逐项记录外部报告 F-01–F-09 的当前源码证据、生产影响和修复边界。新增 [tests/test_audit_regressions.py](tests/test_audit_regressions.py) 覆盖响应大小/重定向/压缩、慢文件读取下的并发写入与晋升CAS、谱系撤销及并发启动。原HTTP测试使用流式响应桩并隔离网络状态，不接触真实库。

`fetch_service.start` 的启动级锁覆盖状态读取、创建和确认；保持原 `runtime.lock` 与 keeper 锁的职责。`seed_expansion.expand_when_idle` 在写事务外验证文件，在短写事务内复核候选、人工事件、下载队列、重试、完成记录与暂停；文件变动则本轮延后。`manual_seed_lineage.reconcile` 同步现存证据图的关系差集，保留未变化关系的时间，不把衍生索引当作原始证据。

`fetchpdf_bridge` 增加 `RESPONSE_LIMIT`（60MiB）和 `METADATA_LIMIT`（8MiB）响应预算；响应钩子在Requests准备重定向之前限制解码后的实际字节数，后续每跳继续地址/限流/预算检查。非流式和显式stream调用均返回已完成有界读取的响应；仅在隔离fetchpdf子进程安装此守卫。外网、大规模RSS压测及真实长时服务未在本轮执行。

2026-10-23：seed_focus独占时，原拉取keeper保持空闲而不启动新的拉取子任务；现有worker由原pause_decision停止新领取、完成本轮后退出。关闭独占自动恢复原未暂停的准入，用户暂停与失败控制仍优先，不新增常驻入口。
