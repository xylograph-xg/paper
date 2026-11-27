# 控制与公共存储接口

Catalog、原子claim、控制/暂停、并行、任务优先级、CLI、监督进程租约、服务入口、恢复编排与版本备份。

这是独立源码与接口文件夹，正式包名为 `core`。跨项目只调用 `core.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

2026-10-14：`catalog.load_config`校验自动所有者监督的布尔开关及至少300秒的双心跳门槛。沿用唯一主配置与公开接口，避免监控和后台所有者采用不同的恢复边界；不更改持久暂停。

一个Catalog和原子控制写入支持身份去重与三队统一领取，因此通过API共享事务，不复制数据库实现。保留model_schedule/model_identity/model_job：当前CLI、旧卡片合同及禁用/取消测试仍调用它们；它们不是可恢复实验的授权。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from core.api import catalog__Catalog
```

运行依赖：[browser](../browser/README.md)、[cards](../../cards/README.md)、[correction](../../correction/README.md)、[fetch](../../fetch/README.md)、[maintenance](../maintenance/README.md)、[read](../../workbench/read/README.md)、[reading](../../workbench/reading/README.md)、[review](../../review/README.md)、[workbench](../../workbench/README.md)。

CLI/子进程入口：`python -m core.action_inbox`, `python -m core.concurrency_control`, `python -m core.continuous_start`, `python -m core.model_job`, `python -m core.resident`, `python -m core.runtime`, `python -m core.workflow_versions`, `python -m core.cli`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project core
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [catalog.py](catalog.py) | Stable identities, human decisions and durable jobs. No network or model calls. | `now`、`doi`、`title_key`、`load_config`、`validate_fetch_capacity`、`validate_local_model`、`Catalog[__init__, connect, upsert, find_doi, get, list, page, recheck_scope, update, event, selection_check, decide, set_seed, enqueue, enqueue_daily, jobs_page, jobs, claim, finish, defer, recover, cursors, retain_discovery, pending_discovery, pending_result, retry, reserve_auto]` | 当前编排、控制或按需恢复接口的依赖 |
| [continuous_start.py](continuous_start.py) | Explicit main-project controls for fetch, cards, verification and correction. | `scope`、`_main_data`、`start`、`stop` | 当前编排、控制或按需恢复接口的依赖 |
| [services.py](services.py) | Acquisition, evidence-grounded screening, and legacy reader orchestration. | `StorageUnavailable[]`、`archive_root`、`maybe_daily`、`atomic_json`、`validate_pdf`、`pdf_dois`、`verify_identity`、`store_asset`、`PROXY_FAKE_IP_NET`、`is_public_address`、`public_url`、`CheckedRedirect[redirect_request]`、`download`、`_download`、`acquisition`、`bridge`、`init_seeds`、`discover`、`acquisition_due`、`maintain_jobs`、`EvidenceText[__new__]`、`evidence_input`、`validate_assessment`、`screen_workflow_fingerprint`、`screen`、`auto_select`、`deep_read` | 当前编排、控制或按需恢复接口的依赖 |
| [concurrency_control.py](concurrency_control.py) | Persisted desired concurrency; running tasks drain rather than being killed. | `_values`、`settings`、`apply`、`set_limits`、`set_limit`、`set_minimum` | 当前编排、控制或按需恢复接口的依赖 |
| [storage_health.py](storage_health.py) | Read-only storage status works even with a worker from an older revision. | `status` | 当前编排、控制或按需恢复接口的依赖 |
| [paths.py](paths.py) | 主机工作区定位，安装后通过PAPER_WORKSPACE_ROOT配置 | `workspace_root` | 当前编排、控制或按需恢复接口的依赖 |
| [workflow_recovery.py](workflow_recovery.py) | Durable active recovery queue for every review/correction retained task. | `install`、`scan`、`run_once`、`decorate` | 当前编排、控制或按需恢复接口的依赖 |
| [automatic_issue_handler.py](automatic_issue_handler.py) | Bounded local issue reconciliation under the existing material worker. | `recover_archived_dispatch`、`enabled`、`recover_review_preparation_lock`、`disposition`、`diagnosis`、`recover_preparation`、`run_once` | 当前编排、控制或按需恢复接口的依赖 |
| [model_identity.py](model_identity.py) | Resolve the weights behind an Ollama tag before using generated caches. | `resolve_identity` | 暂停/禁用、取消、旧合同/回执兼容仍引用；当前主流程不启用本地模型 |
| [control.py](control.py) | Shared, fail-closed decisions over existing scoped control files. | `InvalidControl[]`、`Decision[allowed, as_dict]`、`read_record`、`evaluate`、`pause_decision`、`provider_decisions`、`submission_decision`、`transition_decision`、`explicit_reset`、`mutate_record` | 当前编排、控制或按需恢复接口的依赖 |
| [model_job.py](model_job.py) | A cancellable inference process; closing its lease kills bridge descendants. | `terminate`、`run`、`bootstrap`、`main` | 暂停/禁用、取消、旧合同/回执兼容仍引用；当前主流程不启用本地模型 |
| [workflow_priority.py](workflow_priority.py) | Version-matched article scores; queue timestamps remain immutable evidence. | `seed_first`、`enabled`、`_number`、`_passed_corrections`、`annotate`、`key`、`sort` | 当前编排、控制或按需恢复接口的依赖 |
| [continuous_status.py](continuous_status.py) | Read-only catalog counts and current fetch/card progress for both panels. | `clock`、`status` | 当前编排、控制或按需恢复接口的依赖 |
| [model_schedule.py](model_schedule.py) | Daily inference windows, explicit all-day operation, and expiring overrides. | `ModelWindowClosed[]`、`schedule_path`、`pause_path`、`set_user_pause`、`minute`、`validate`、`status`、`require_allowed`、`configure` | 暂停/禁用、取消、旧合同/回执兼容仍引用；当前主流程不启用本地模型 |
| [process_runner.py](process_runner.py) | Bounded child sessions with kernel-backed parent leases for nested bridges. | `watch_parent`、`run` | 当前编排、控制或按需恢复接口的依赖 |
| [resident.py](resident.py) | Install the two explicitly authorized user-session resident services. | `definitions`、`install` | 当前编排、控制或按需恢复接口的依赖 |
| [runtime.py](runtime.py) | Python-only supervision and a queue-boundary handover for legacy workers. | `alive`、`queue_drained`、`watch_supervisor`、`stop_requested`、`worker_identity`、`publish`、`runtime_status`、`attached_read_status`、`supervise`、`handover` | 当前编排、控制或按需恢复接口的依赖 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前编排、控制或按需恢复接口的依赖 |
| [cli.py](cli.py) | worker/状态/控制的正式CLI | `worker_locks`、`work`、`_work`、`main` | 当前编排、控制或按需恢复接口的依赖 |
| [action_inbox.py](action_inbox.py) | One read-only inbox for user actions, separate from automatic cooldowns. | `snapshot`、`publish` | 当前编排、控制或按需恢复接口的依赖 |
| [workflow_versions.py](workflow_versions.py) | Recoverable local source/config versions and SQLite/history backups; no Git or uploads. | `capture`、`backup_state` | 当前编排、控制或按需恢复接口的依赖 |
| [record_contract.py](record_contract.py) | Normalize provider records once; malformed items retain an explicit error. | `text`、`normalize` | 当前编排、控制或按需恢复接口的依赖 |
| [commands/一键启动拉取和GPT制卡.command](commands/一键启动拉取和GPT制卡.command) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前编排、控制或按需恢复接口的依赖 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/test_stall_timeout_distribution.py](tests/test_stall_timeout_distribution.py)：离线/隔离回归，验证当前合同。
- [tests/test_short_cycle_prompts.py](tests/test_short_cycle_prompts.py)：离线/隔离回归，验证当前合同。
- [tests/test_four_workflow_snapshot.py](tests/test_four_workflow_snapshot.py)：离线/隔离回归，验证当前合同。
- [tests/test_automatic_issue_handler.py](tests/test_automatic_issue_handler.py)：离线/隔离回归，验证当前合同。
- [tests/test_health_recovery_timing.py](tests/test_health_recovery_timing.py)：离线/隔离回归，验证当前合同。
- [tests/test_preparation_claim_recovery.py](tests/test_preparation_claim_recovery.py)：离线/隔离回归，验证当前合同。
- [tests/test_control_precedence.py](tests/test_control_precedence.py)：离线/隔离回归，验证当前合同。
- [tests/test_concurrency_control.py](tests/test_concurrency_control.py)：离线/隔离回归，验证当前合同。
- [tests/test_config_boundaries.py](tests/test_config_boundaries.py)：离线/隔离回归，验证当前合同。
- [tests/browser_continuous_control.cjs](tests/browser_continuous_control.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_continuous_control.py](tests/test_continuous_control.py)：离线/隔离回归，验证当前合同。
- [tests/test_retired_receipt_relocation.py](tests/test_retired_receipt_relocation.py)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_action_inbox.py](tests/test_action_inbox.py)：离线/隔离回归，验证当前合同。
- [tests/test_continuous_access.py](tests/test_continuous_access.py)：离线/隔离回归，验证当前合同。
- [tests/test_bridge_progress.py](tests/test_bridge_progress.py)：离线/隔离回归，验证当前合同。
- [tests/test_workflow.py](tests/test_workflow.py)：离线/隔离回归，验证当前合同。
- [tests/test_channels.py](tests/test_channels.py)：离线/隔离回归，验证当前合同。
- [tests/test_state_and_contract_integrity.py](tests/test_state_and_contract_integrity.py)：离线/隔离回归，验证当前合同。
- [tests/test_abandoned_unsent_claims.py](tests/test_abandoned_unsent_claims.py)：离线/隔离回归，验证当前合同。
- [tests/test_four_workflow_http.py](tests/test_four_workflow_http.py)：离线/隔离回归，验证当前合同。
- [tests/test_workflow_recovery.py](tests/test_workflow_recovery.py)：离线/隔离回归，验证当前合同。
- [tests/test_page_grid_snapshot.py](tests/test_page_grid_snapshot.py)：离线/隔离回归，验证当前合同。
- [tests/test_model_schedule.py](tests/test_model_schedule.py)：离线/隔离回归，验证当前合同。
- [tests/test_generation_budget_and_recovery.py](tests/test_generation_budget_and_recovery.py)：离线/隔离回归，验证当前合同。
- [tests/test_four_workflow_controls.py](tests/test_four_workflow_controls.py)：离线/隔离回归，验证当前合同。
- [tests/test_runtime_revision.py](tests/test_runtime_revision.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_pool_lifecycle.py](tests/test_web_pool_lifecycle.py)：离线/隔离回归，验证当前合同。
- [tests/test_workflow_priority.py](tests/test_workflow_priority.py)：离线/隔离回归，验证当前合同。
- [docs/一键启动与实时统计.md](docs/一键启动与实时统计.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/异常自动处理.md](docs/异常自动处理.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/工作流架构.md](docs/工作流架构.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/动态并行控制.md](docs/动态并行控制.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

数据库、控制事件和显式启动/停止接口；本次迁移不调用这些启动接口。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../config/README.md)，共享状态合同见 [data](../data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 本轮路径与备份政策

`paths.py` 的公开 `WorkspacePath` / `resolve_runtime_path` 在文件读取边界将旧绝对路径解析到 workspace.json 的 physical_roots，冻结JSON/账本/授权原字节不重写。支持 pathlib 在Python 3.11与3.12+的构造差异；workspace_root仍返回工作区根。旧调用可继续读取原回执，实际文件只有一份。

`resident.py` 更新原常驻配置时不再写resident-backups。`workflow_versions.backup_state` 明确拒绝创建数据备份；源码指纹/历史科学证据仍保留。`tests/test_workspace_paths.py` 验证旧路径读取字节、嵌套包路径、外部路径保持和ZIP存储归属。

路径实现全功能：`_host`定位工作区/读取PAPER_WORKSPACE_ROOT，`_relocate`只解析属于本工作区的旧绝对路径，`WorkspacePath.__new__/__init__`适配Python路径构造，`__truediv__/joinpath`解析嵌套资源，`workspace_root`返回工作区根，`resolve_runtime_path`提供显式读取入口。相对归档路径和其他项目路径不修改。

## 路径解析性能（2026-10-14）

paths._relocate使用路径parts的精确前缀匹配，不调用relative_to或枚举父目录；避免在WorkspacePath派生父目录时反复触发适配。相邻项目名（如paper-other）、相对归档路径和已经归并的路径保持原语义。原回执无需改写，仍经同一公开Path类解析。

修正故障恢复显式使用 correction 的 recovery=True 身份/暂停核对；原错误、归档、无活动回执和版本保护仍在原恢复事务中检查。派发门禁默认不允许 needs_user。

## 2026-10-14 归档路径修复

[archive_paths.py](archive_paths.py) 的公开接口 `archive_paths__move_with_links(source, destination)` 以持久日志和目录 inode 绑定原目录，在重试归档及回滚时重新计算相对链接；内部链接随目录移动，外部链接仍指向同一原件，绝对链接不变。调用方持有原队列写锁；路径冲突、链接变化或日志归属不符时抛出 ValueError 并保留证据。中断后用同一参数继续，既不复制原文数据，也不创建数据备份。选择此接口是因为 Python 旧路径解析无法修复操作系统对软链接的原生遍历；[tests/test_archive_paths.py](tests/test_archive_paths.py) 验证原件字节、中断恢复和冲突保护。

`automatic_issue_handler.review_preparation_fingerprint` 将公开核验准备/修复实现及旧路径解析的源码指纹加入本地检查缓存键；代码修复后重新核对一次，旧 ledger 与科学失败次数保留。同版本、同材料的保留检查不无限重做，原 repair 证据和暂停守卫仍是入队前提。

本地检查键同时记录源码摘要与已加载的 recovery_revision，区分“磁盘代码已更新、常驻尚未重载”和真正的新实现。修复/准备逻辑的语义变化须更新此标记，避免旧进程把新源码版本标为已检查。

## 已完成初始化的快速复用

[schema_cache.py](schema_cache.py) 的 signature/ready/record 绑定实际已加载的 Catalog、fetch timing 和 reading 初始化字节码、常量及DDL对象清单；校验表/索引/触发器、读取列、旧触发器移除及版本标记后，重复 Catalog 构造仅查询，跳过反复建表和历史回填。缺失结构或实现变化仍执行原初始化，全部完成才写派生标记。不清空业务表、次数、暂停或原回执。选择此机制用于减少每个拉取子进程和服务重载争抢SQLite写锁；[tests/test_schema_cache.py](tests/test_schema_cache.py) 验证另一写事务存在时仍可快速构造、缺失触发器修复和新实现重新初始化。

2026-10-14：`workflow_priority`统一派生`passed_correction_priority`。不可变完整通过报告和同原文作为来源，修正后待核验版本继承置顶；优先组内保持原分数/FIFO。源版本变化、材料缺失或未完整检查不产生置顶；标记不构成运行/发送授权。

2026-10-17：workflow_priority.annotate空候选直接返回；修正来源/后继及文章/当前版核验分仅按本次records相关paper_id查询。采用json_each参数集合避免占位符数限制；同文献原文/版本、优先组、缺分及FIFO语义不变，不缓存旧分数。回归同时阻断无关报告/修正payload被读取。

[cooperative_sql.py](cooperative_sql.py) 提供显式同线程set_checkpoint（返回原回调供恢复）。仅WAL纯SELECT且无事务时按至少50ms/1000步调用；默认无回调零行为变化，写入/显式事务/DDL/PRAGMA/非WAL不让出。错误中断读取并保留原异常。Catalog.connect在原连接上下文挂载/卸载，只供原浏览器所有者驱动原循环；无额外线程/服务。回归见[tests/test_cooperative_sql.py](tests/test_cooperative_sql.py)，含真实原驱动观察继续和WAL另一写入恰一次。

## 普通文献元信息只读投影（2026-10-20）

[literature_catalog.py](literature_catalog.py) 提供 `literature_catalog__metadata_rows(catalog_path)`：SQLite只读一致快照，返回全部文献元信息、原关键词、个人阅读状态与原文/卡片版本绑定的已存评分，不构造Catalog、不刷新评分、不读取报告正文或启动任务；供独立literature组件使用。分数缺失保持空。`automatic_issue_handler__normalize_needs_user`仅公开原函数对象，供维护脚本遵循公开导入边界，不新增恢复行为；两份维护脚本仅更换导入写法。

`literature_catalog__source_records(catalog_path, paper_ids)`新增每次1–100篇只读原文身份/原任务材料指针投影，供literature核对已有中间文本；不读取旧科学卡片/回执正文，不执行队列或控制写入。

2026-10-20：手选根种子全环节第一顺位，重试/恢复保留同一身份；`core.api.workflow_priority__seed_first`以只读、稳定排序保留原记录对象和组内次序。材料分配、核验准备、混合补充及跨队列上传准入统一种子优先；退避、次数、暂停、固定槽位和未知回执保护保持。见[授权](/Users/xiaoyanhao/project/paper/infrastructure/docs/authorizations/20261020-manual-seed-first-all-stages.md)。

2026-10-22：automatic_issue_handler.release_proven_presend_claims先通过browser公开active_lease_targets核对原后台回调仍持有的页面；活跃领取或证据读取异常不释放。与原未发送/暂停/原文和科学保护共同生效，旧not_sent不授权回收新回调。

2026-10-23：`seed_focus.py`：独立仅手选开关；公开active/allowed/filter_records/set_enabled/capture/monitor/status，CLI `python -m core.seed_focus [--enable|--disable]`。默认只采集追踪；开启过滤普通文献，关闭保留用户暂停。seed-tracking侧录持久证据、真实阶段和3小时停滞；不发请求或修改科学卡。

`seed_focus`接口：active(config)->bool（损坏开关拒绝普通准入），allowed(config,paper_id)->bool（根种子表只读核对，失败拒绝），filter_records(db,records,config=None)->原记录子集（不改状态），set_enabled(config,bool)->控制回执（原子控制锁，不解除别处暂停）。capture(config,paper_id,reason)->不可变证据清单路径（hash对象去重，文件读取变化时报错、不动原文件），monitor(config,at=None)->{enabled,checked_at,items}（单独文件锁；生产库mode=ro，仅侧录写入），status(config)->快照（只读，按当前时间计算10800秒停滞）。缺失/损坏材料显式阻断保全，不伪造科学字段。元数据发布只有与原候选或同轮修正版本的通过核验及原科学内容指纹一致才认可；旧报告或技术回退不刷新进展时钟。默认保留成品后的证据，不提供提前删除接口。

2026-10-25：`seed_focus.monitor`让不在固定五篇三版实验中的新手选根种子按当前同源、通过原报告和独立生产合同结束追踪；已登记实验仍须按原run.selected/repairing绑定获选版本。完成时不保留旧技术错误为当前阻塞；原进展时钟、证据保留及手选第一顺位不变。回归增加在[tests/test_seed_focus.py](tests/test_seed_focus.py)。

原材料线程停止信号经 automatic_issue_handler.run_once(..., stopping=None) 与 workflow_recovery.run_once(..., stopping=None) 传至既有 review_cycle.run_once；历史 failure_count(..., stopping=None) 在每份历史报告前检查，当前完整科学检查结束后再次核对再决定是否推进。停止时保留原报告/计数/任务，不继续后续恢复、收取请求或科学重做，不将中断算作科学失败。

常驻材料线程调用 `automatic_issue_handler.run_once(..., maintain_review_cycle=False)`，将历史科学复查交给核验生产者的 15 分钟调度。通用维护仍每分钟检查其他恢复事项；按需调用默认包含历史科学复查。

## 2026-10-26 失败原因幂等

`automatic_issue_handler.normalize_needs_user`在两队的既有no_user_state处置中只添加一次“自动终止：”；已带前缀的原因原样保留，不在再次归一化时截断。原事件和科学报告不清洗、不回填原因，不新增重试权限。与review的终态直接准备合同配合，未成功的科学恢复轮询不反复修改原失败状态或更新时间。回归见tests/test_automatic_issue_handler.py，实测见../../reports/20261026-recovery-terminal-idempotency.md。

2026-10-30：`seed_focus.monitor`采用`qualified-material-v2`实质进展合同。`_qualified_events`完整读取制卡/核验原回答及实际提示、核对各自SHA256、原正式会话、冻结输入清单和当前原文版本，以原`observed_complete_at/finished`有效时间记完整收取；队列状态、仅发送、终态空回答不推进时钟。卡片按去除meta后的内容指纹去重，当前版本科学通过与生产完成另列事件；`_event_time/_event_id`规范原证据时间及稳定身份。`_qualified_clock`保留首次事件时间，移动/重复归档/后写finished不刷新；迁移保留旧trace原字节和SHA对象，使用首条历史基线与可核对的原收取时间校正，不用巡检时刻补造进展。旧progress兼容展示不再驱动停滞时钟；metadata-only发布不算新卡。新增回归覆盖只发送、空正文、漏记核验、迁移校正、重复归档、损坏/变源、内容与元数据以及科学/生产分离。生产库仍只读，保护/发送/完成准入不变，无新增依赖或浏览器通道。
