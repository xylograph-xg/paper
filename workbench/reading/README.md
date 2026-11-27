# 证据与阅读库

原文与图式证据、科学解析合同、普通/精选/精读/已读库、个人备注、手动导入、媒体补充与历史版本完整性检查。

这是独立源码与接口文件夹，正式包名为 `reading`。跨项目只调用 `reading.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

当前阅读界面由workbench提供，解析能力使用read公开接口。保留源证据与当前版本资格判断，使旧卡片不会因目录或排版变化被误判为通过。本地生成兼容合同仅用于已明确守卫的接口，主配置继续禁用。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from reading.api import reading_contract__file_digest
```

运行依赖：[browser](../../infrastructure/browser/README.md)、[cards](../../cards/README.md)、[core](../../infrastructure/core/README.md)、[fetch](../../fetch/README.md)、[read](../read/README.md)、[review](../../review/README.md)。

CLI/子进程入口：`python -m reading.card_display`, `python -m reading.manual_literature`, `python -m reading.reading_bridge`, `python -m reading.science_verifier`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project reading
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [reading_recovery.py](reading_recovery.py) | Bounded recovery bound to actual workflow/model inputs, preserving history. | `activate`、`_activate` | 暂停/禁用、取消、旧合同/回执兼容仍引用；当前主流程不启用本地模型 |
| [batch_import.py](batch_import.py) | Conservative identity matching for unbound PDF uploads. | `match_pdf` | 当前公开接口或生产链使用；避免复制实现 |
| [evidence_repair.py](evidence_repair.py) | Compatibility exports; authoritative evidence preparation lives in read/app. | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [card_display.py](card_display.py) | Source-PDF display crops only; never mutate scientific cards or frozen inputs. | `number`、`unique_region`、`build`、`maintain` | 当前公开接口或生产链使用；避免复制实现 |
| [manual_literature.py](manual_literature.py) | 手动种子库登记优先级，原位模式保留 PDF，并刷新成品及同源结构候选的本地索引。工作台复用同源卡片判定。桌面暂存导入普通候选并移入 SSD 存储，笔记只用于书目关联。 | `install`、`inspect_file`、`_store_item`、`_process_file`、`_seed_card`、`seed_cards`、`_write_seed_index`、`run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [completed_literature_archive.py](completed_literature_archive.py) | Historical completed-loop mover; no longer called by the two-lane intake. | `digest`、`completed_papers`、`move_verified`、`run_once` | 保留历史实现与移动校验；当前入口停用 |
| [quantity_supplement.py](quantity_supplement.py) | Optional, explicitly labelled world-knowledge help for missing equation quantities. | `quantity_rows`、`parse_supplement`、`supplement_quantities` | 当前公开接口或生产链使用；避免复制实现 |
| [reading_bridge.py](reading_bridge.py) | Call the existing read processor in a clean interpreter; never send web messages. | `reviewed_source_matches`、`producer_fingerprint`、`reading_input_hash`、`attach_media`、`reading_config`、`process` | 暂停/禁用、取消、旧合同/回执兼容仍引用；当前主流程不启用本地模型 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [source_media.py](source_media.py) | Version-bound arXiv source evidence. Never execute submitted TeX or macros. | `pdf_version`、`unpack_source`、`uncomment`、`braced`、`command_args`、`environments`、`macro_definitions`、`index_source`、`prepare_source` | 当前公开接口或生产链使用；避免复制实现 |
| [reading_failures.py](reading_failures.py) | Typed local diagnostics; evidence problems never become scientific approval. | `failure_class`、`diagnostics`、`retry_guard` | 当前公开接口或生产链使用；避免复制实现 |
| [science_verifier.py](science_verifier.py) | Bounded offline checks; source truth and semantic entailment remain unverified. | `runtime_identity`、`Unsupported[]`、`_latex`、`parse_math`、`compare_assignment`、`check_dimensions`、`math_spans`、`symbol_scripts`、`_fields`、`_expansions`、`audit_card`、`bounded_audit`、`main` | 当前公开接口或生产链使用；避免复制实现 |
| [reading_library.py](reading_library.py) | Private reading progress/notes and a derived index of existing card summaries/scores. | `ReadingConflict[]`、`install`、`reading`、`update`、`_score`、`refresh_scores` | 当前公开接口或生产链使用；避免复制实现 |
| [prompt_overlays.py](prompt_overlays.py) | Scientific safeguards applied to the reader's own templates, without copies. | `literal_quote_candidates`、`render_review_prompt` | 当前公开接口或生产链使用；避免复制实现 |
| [reading_contract.py](reading_contract.py) | Version and completion gate shared by reading writers and review consumers. | `file_digest`、`verified_completion`、`inventory`、`producer_fingerprint` | 当前公开接口或生产链使用；避免复制实现 |
| [media_evidence.py](media_evidence.py) | Dual evidence for cards: complete PDF references plus versioned source assets. | `normalize_caption`、`match_caption`、`render_dual`、`media_manifest`、`validate_latex`、`parse_latex_response`、`vision_transcriber` | 当前公开接口或生产链使用；避免复制实现 |
| [reading_service.py](reading_service.py) | Manage detached screening/card supervision without touching the fetch owner. | `status`、`start`、`request_stop` | 暂停/禁用、取消、旧合同/回执兼容仍引用；当前主流程不启用本地模型 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/browser_reading_library.cjs](tests/browser_reading_library.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_science_verifier.py](tests/test_science_verifier.py)：离线/隔离回归，验证当前合同。
- [tests/test_manual_backlog.py](tests/test_manual_backlog.py)：离线/隔离回归，验证当前合同。
- [tests/browser_card_findings.cjs](tests/browser_card_findings.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_reader_regression.py](tests/test_reader_regression.py)：离线/隔离回归，验证当前合同。
- [tests/test_quantity_supplement.py](tests/test_quantity_supplement.py)：离线/隔离回归，验证当前合同。
- [tests/browser_card_zoom.cjs](tests/browser_card_zoom.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_worker_and_evidence_safety.py](tests/test_worker_and_evidence_safety.py)：离线/隔离回归，验证当前合同。
- [tests/test_evidence_and_execution_integrity.py](tests/test_evidence_and_execution_integrity.py)：离线/隔离回归，验证当前合同。
- [tests/reading_library_browser_fixture.py](tests/reading_library_browser_fixture.py)：离线/隔离回归，验证当前合同。
- [tests/browser_media_evidence.cjs](tests/browser_media_evidence.cjs)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_source_media.py](tests/test_source_media.py)：离线/隔离回归，验证当前合同。
- [tests/test_reading_library.py](tests/test_reading_library.py)：离线/隔离回归，验证当前合同。
- [tests/test_evidence_quotes.py](tests/test_evidence_quotes.py)：离线/隔离回归，验证当前合同。
- [tests/test_pdf_geometry.py](tests/test_pdf_geometry.py)：离线/隔离回归，验证当前合同。
- [tests/test_completed_literature_archive.py](tests/test_completed_literature_archive.py)：离线/隔离回归，验证当前合同。
- [tests/test_evidence_repair.py](tests/test_evidence_repair.py)：离线/隔离回归，验证当前合同。
- [tests/browser_reader_layout.cjs](tests/browser_reader_layout.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_card_display.py](tests/test_card_display.py)：离线/隔离回归，验证当前合同。
- [tests/test_batch_import.py](tests/test_batch_import.py)：离线/隔离回归，验证当前合同。
- [tests/browser_paper_evaluation.cjs](tests/browser_paper_evaluation.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_manual_literature.py](tests/test_manual_literature.py)：离线/隔离回归，验证当前合同。
- [tests/browser_combined_scores.cjs](tests/browser_combined_scores.cjs)：离线/隔离回归，验证当前合同。
- [tests/manual_library_browser_fixture.py](tests/manual_library_browser_fixture.py)：离线/隔离回归，验证当前合同。
- [tests/browser_manual_library.cjs](tests/browser_manual_library.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_reading_safety.py](tests/test_reading_safety.py)：离线/隔离回归，验证当前合同。
- [docs/手动文献库与来源分区.md](docs/手动文献库与来源分区.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/图式证据双份保留.md](docs/图式证据双份保留.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/精读与已读库.md](docs/精读与已读库.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

原文解析与本地证据/阅读状态；本地模型功能与持久暂停仍双重阻断。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../../infrastructure/config/README.md)，共享状态合同见 [data](../../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 2026-10-14 审核修复与保留理由

- `completed_literature_archive.py`：验收后独立副本、随机同目录custody原子移交、inode/hash复核、不可覆盖发布；不再删除可被替换的原路径。失败恢复原路径，原路径被新材料占用时保留随机custody并显式报位置。不把副本当数据备份；成功移交仅保留正式归档。进程崩溃留下`.archive-custody-*`应先核对原身份与库中哈希再恢复，禁止扫除；独立副本避免旧fd改写库中证据。文件及目录fsync不等于已完成真实断电验收。
- `reading_contract.py`：通过公开API包安装位置绑定实际源码及依赖清单，宿主配置经公开load_config读取；不追认或改写历史完成标记，新指纹使旧本地合同待重新核对。主GPT网页资格链独立，不因此恢复本地模型。
- `reading_recovery.py`：复用Catalog幂等enqueue，成功及事件记录后才记processed。若两次提交之间崩溃，后续enqueue复用活动任务；门槛跳过不消耗台账，全局activation事件不再阻止重评估。这是兼容离线恢复接口的维护，不运行旧恢复队列，不自动修订生产历史台账。
- `manual_literature.py`：输入100MiB，DOCX最多2000条/展开100MiB，正文8MiB与压缩比200，XML深度128/节点100000；拒绝DTD/entity和带NUL的UTF-16/32正文，保留不支持的原文件，不执行文档宏。预算是确定性拒绝门槛，不依赖子进程超时后才终止。
- `source_media.py`：available要求archive、index及完整文件树哈希一致。损坏缓存标记needs_rebuild并保留材料，本次不自动覆盖取证缓存或联网重建。
- [log_output.py](log_output.py)：公开`spawn_logged(args,path,**kwargs)`，子进程自身将stdout/stderr按8192字符分段写入，5MiB轮转、3历史段，不等进程重启；内部`run_logged`在原子进程初始化日志，`LogStream.write/flush/isatty`提供输出流，`OperationalHandler.handleError`避免磁盘满时递归stderr；仅包装Python -m/-c，在原子进程内运行，不增加后台进程；启动器退出后仍能轮转，常见口令字段遮盖。不把导入当成启动授权。
- [tests/test_audit_regressions.py](tests/test_audit_regressions.py)：归档替换/异常/旧fd，DOCX炸弹/实体，入队失败及源码指纹/缓存损坏回归。

新增日志接口沿用既有reading依赖，无跨项目内部导入或新后台入口。详见 [审核复核](../AUDIT_REVIEW.md)。

### worker退出诊断

[tests/test_worker_and_evidence_safety.py](tests/test_worker_and_evidence_safety.py) 同时记录临时worker的alive、kill(0)、锁路径/inode/持锁状态；保留原10秒等待和最终worker_locks断言，不延长等待或吞异常。探针只读临时锁，负例确认不释放所有者锁。历史锁失败本轮定向25次未复现，真实历史根因仍未确认；生产runtime/cli未修改。
