# 维护与审计

外围HTTP watcher、失败DOI同步、SSD检查、保留策略、不可变审计、历史导入、备份/隔离恢复、结构检查和测试入口。

这是独立源码与接口文件夹，正式包名为 `maintenance`。跨项目只调用 `maintenance.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

维护沿用原三个LaunchAgent之一，不增加入口、不另连CDP。备份与恢复工具作为当前数据的按需管理接口保留，恢复只产出独立候选；本次新增结构检查替代旧符号链接迁移脚本。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from maintenance.api import history__preserve
```

运行依赖：[browser](../browser/README.md)、[cards](../../cards/README.md)、[core](../core/README.md)、[fetch](../../fetch/README.md)、[reading](../../workbench/reading/README.md)。

CLI/子进程入口：`python -m maintenance.audit_archive`, `python -m maintenance.local_maintenance`, `python -m maintenance.maintenance_audit`, `python -m maintenance.organize_ssd`, `python -m maintenance.recovery_backup`, `python -m maintenance.web_artifact_retention`, `python -m maintenance.web_tab_watch`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project maintenance
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [audit_archive.py](audit_archive.py) | Explicit content-addressed archive of selected immutable JSON evidence. | `digest`、`capture`、`verify` | 当前编排、控制或按需恢复接口的依赖 |
| [recovery_backup.py](recovery_backup.py) | Local verified recovery snapshots. Restoration only creates isolated candidates. | `sha`、`copy_stable`、`create`、`verify`、`restore_candidate` | 当前编排、控制或按需恢复接口的依赖 |
| [web_tab_watch.py](web_tab_watch.py) | Periodic dedicated-browser counts and cleanup of archived owned tabs. | `_local_targets`、`counts`、`cleanup_candidate`、`check_shared`、`check`、`run` | 当前编排、控制或按需恢复接口的依赖 |
| [owner_supervision.py](owner_supervision.py) | 原HTTP watcher监督已注册网页所有者；验收源码更新和双心跳停滞后正常交接 | `tick`、`publish_validated`；内部`_code`、`_release_evidence`、`_external_ready`、`_owner`、`_permitted`、`_managed`、`_submission_idle`、`_kickstart` | 补全自动技术恢复；公开cards/core接口核对身份，等待旧PID退出，不增加常驻或CDP连接 |
| [local_maintenance.py](local_maintenance.py) | Local policy maintenance for live legacy owners; never calls models or discovery. | `step`、`refresh_stale_assessments`、`main` | 当前编排、控制或按需恢复接口的依赖 |
| [sync_failed_dois.py](sync_failed_dois.py) | Read-only Catalog snapshot -> managed, journal-grouped desktop DOI lists, plus a level-weighted journal ranking. | `tick`、`atomic`、`normalize_doi`、`publication_key`、`collect`、`normalize_journal`、`load_levels`、`journal_level`、`rank_journals`、`write_ranking`、`sync` | 当前编排、控制或按需恢复接口的依赖；期刊水平表可编辑 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前编排、控制或按需恢复接口的依赖 |
| [artifact_retention.py](artifact_retention.py) | Bounded diagnostic archival; active and scientific artifacts are always preserved. | `maintain`、`read_raw` | 当前编排、控制或按需恢复接口的依赖 |
| [test_runner.py](test_runner.py) | 按独立包发现各项目测试 | `main` | 当前编排、控制或按需恢复接口的依赖 |
| [check_subprojects.py](check_subprojects.py) | 无跨目录源码链接、公开导入边界与声明校验 | `sources`、`check`、`main` | 当前编排、控制或按需恢复接口的依赖 |
| [maintenance_audit.py](maintenance_audit.py) | Read-only maintenance inventories. Missing references never authorize deletion. | `inventory` | 当前编排、控制或按需恢复接口的依赖 |
| [organize_ssd.py](organize_ssd.py) | Verified one-time main-library SSD migration; does not send or generate anything. | `migrate` | 当前编排、控制或按需恢复接口的依赖 |
| [migration.py](migration.py) | Read-only legacy intake. Preserve complete exploration snapshots and ID aliases. | `migrate` | 当前编排、控制或按需恢复接口的依赖 |
| [web_artifact_retention.py](web_artifact_retention.py) | Deduplicate completed web inputs; preserve exact uploaded artifacts and receipts. | `compact_completed` | 当前编排、控制或按需恢复接口的依赖 |
| [history.py](history.py) | Immutable historical card snapshots become visible only after a verified complete copy. | `preserve` | 当前编排、控制或按需恢复接口的依赖 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/test_audit_archive.py](tests/test_audit_archive.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_artifact_retention.py](tests/test_web_artifact_retention.py)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_audit_contract_repairs.py](tests/test_audit_contract_repairs.py)：离线/隔离回归，验证当前合同。
- [tests/test_audit_dispatch_and_retry.py](tests/test_audit_dispatch_and_retry.py)：离线/隔离回归，验证当前合同。
- [tests/test_technical_audit_1746.py](tests/test_technical_audit_1746.py)：离线/隔离回归，验证当前合同。
- [docs/网页制卡文件保留策略.md](docs/网页制卡文件保留策略.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/SSD存储布局.md](docs/SSD存储布局.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

- [tests/test_subproject_interfaces.py](tests/test_subproject_interfaces.py)：冷启动对象身份、旧所有者交接、导入无启动副作用及旧CLI安全检查。

## 数据、并发和权限边界

"`owner_supervision__publish_validated(config, hashes, verification)`只登记实际已验收的源码，要求测试、接口及链接成功、真实测试数量，并且 `verification.external_dependencies` 必须逐字等于当下 `code_version()` 的外部内核证据且 status=ok；验收记录升到 schema_version 2。`tick` 的 approved 同时比较 module_sha256（已含 dependency:web_gpt.* 等哈希）与该外部证据，所以仓外 core 单文件漂移就会让已验收标记失效并停在 `waiting_validated_release`，不会只新增展示字段而监督器照旧放行；登记本身不重启。`owner_supervision__tick(config, at=None)`由原watcher每轮执行，双心跳均过期至少300秒且两次实查相隔60秒，或源码与已验收版本不同才请求交接。源码更新优先等待提交锁空闲；同一确切新版验收满五分钟后仅请求原所有者正常退出，原操作仍由原守卫结束；原PID退出后才kickstart原注册入口；每小时最多两次、间隔五分钟。持久`owner-supervision.json`保存意图与令牌哈希；启动回执不明只核对，控制文件不改写。选择正常交接而保留浏览器，是为继续收取原网页请求。运行验收marker保存在`validated-owner-release.json`；未验收源码不自动执行。新[test_owner_supervision.py](tests/test_owner_supervision.py)覆盖身份变更、暂停、占锁、旧进程未退出、验收缺失、次数限制及入口匹配。

本地维护、归档或明确管理命令；浏览器维护只发给原所有者。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../config/README.md)，共享状态合同见 [data](../data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 本轮归并与备份禁用

检查器按workspace.json中每个组件的真实path扫描，排除嵌套子组件以避免重复归属；test_runner按各自真实测试包发现。requirements-test.txt归此组件，科学解析依赖引用workbench/reading。recovery_backup.create保留显式禁用守卫，不创建数据备份；旧备份验证/恢复读取接口仅作为历史合同，不能启动运行恢复。当前备份副本已按用户要求删除。

## 运行数据软链接迁移修复（2026-10-14）

[ runtime_link_migration.py ](runtime_link_migration.py)提供plan、apply_plan与CLI：从原data位置和现data位置重建相对链接的几何关系，只修失效且真实目标位于配置SSD的链接；计划记录目标SHA及文件版本，应用时核对链接原文和目标版本后原子替换链接。_version、_digest核对目标身份和内容，main持久保存计划与执行证据；目标文件原字节不写入、不备份，plan/apply不改变任务状态或外发。独立resume_link_blocked_materials/--resume-materials仅将本次链接修复对应的本地文件缺失故障，在核对原文、冻结输入、旧回执、人工/暂停/修正绑定、无当前请求和事务CAS后恢复原队列；不改回执、不重置重试计数和FIFO，不操作浏览器。tests/test_runtime_link_migration.py验证原字节保持、正常链接保留和并发变更拒绝。保留此工具用于物理归并后的真实运行路径验收，避免仅由Python路径适配掩盖OS链接失效。

## 2026-10-14 历史诊断链接

`runtime_link_migration.plan` 另识别 web_cards/<paper>/history/automatic-retry-*/chatgpt/error-page.png 的旧 SSD 地址：相对链接中的绝对尾部必须精确指向 archive_root/web-inputs/<同一paper>/chatgpt/error-page.png，且原件存在。原 target SHA/版本和链接文本 CAS 通过后才原子改链接；不改 attempt，不声称旧图就是该次请求的截图，不用其解除未知请求。选择此受限恢复是因为旧归档多加两层路径，原迁移几何无法解析。

[review_preparation_recovery.py](review_preparation_recovery.py) 为显式维护 CLI：`python -m maintenance.review_preparation_recovery --review-id <原任务ID> --report <报告>`，每次最多4项。仅处理已知 ZIP 超限/本地媒体登记准备错误且 result 为空、没有任何当前/历史请求或页面分配的原任务；原文、卡片、暂停及人工保护保持。完整冻结包原字节复用；未冻结失败材料保留，单独 ID/目录生成符合60MB预算的新候选，重新核对后 CAS 更新原行并保存事件。它不成为常驻自动重试，不发送网页请求，不增加核验科学失败次数。保留此入口用于修复已明确限定的旧技术准备失败；[tests/test_review_preparation_recovery.py](tests/test_review_preparation_recovery.py) 验证候选隔离、完整包复用、未知回执/暂停/领取阻断。

## 测试发现与隔离合同

[test_runner.py](test_runner.py) 保留原组件顺序、重复用例和 --project/--pattern，crawler 使用独立子 Python，避免裸 config/models 污染。缺测试目录、空套件、导入或来源错误均明确报告并退出1。PAPER_TEST_SUMMARY JSON 分别记录槽位、唯一id、重复id、实际执行、skip与缺席；普通组件标为 EXECUTED，tests_run=null，整体结果为 unittest 的实际计数，避免 setUpClass 错误被拆成虚假组件PASS。

快照执行须将快照 infrastructure、workbench、fetch 放到 PYTHONPATH，排在虚拟环境 .pth 的原工作区路径之前。PAPER_WORKSPACE_ROOT 仅控制数据路径，来源检查会阻断混用，不清缓存后静默继续。crawler 子模式仅是内部测试协议。[tests/test_test_runner_discovery.py](tests/test_test_runner_discovery.py) 覆盖缺席、空套件、导入/来源错误、继承/重复口径、参数及子回执。read/desktop_widget 缺独立tests时，全库仍返回非零，不伪报完整通过。


## 节点波动时的本机浏览器盘点（2026-10-15）

`web_tab_watch._local_targets`仅允许localhost/127.0.0.1/::1的显式HTTP(S)端口，拒绝认证、路径、查询及片段，以空ProxyHandler读取/json/list。只绕过本机元数据的系统代理，实际网站及材料上传继续沿用用户线路；不新增CDP连接或改变代理设置。测试[本机元数据](tests/test_local_browser_metadata.py)覆盖系统代理失效时仍直读本机及非本机目标拒绝；原共享入口测试继续验证只发维护请求、不关闭或重建页面。

## 文献组织组件接入（2026-10-20）

`test_runner.py` 增加独立literature测试发现。`abnormal_protection_cleanup.py` 和 `auto_recover_work.py` 的旧core内部导入替换为已声明公开API；原函数对象和恢复逻辑保持，本轮不调用这两个维护入口。

2026-10-22: auto_recover_work, abnormal_protection_cleanup and reset_protected_after_timeout no longer move receipts, clear claims or requeue submitted work by TTL. Compatibility entries only request original-owner maintenance. Shared web_tab_watch returns through HTTP inventory before material refill/cleanup and never invokes the retired writers. Original sources and SHA256 are in reports/20261022-page-throughput-validation/unsafe-watch-originals. tests/test_owner_only_recovery.py covers the read-only boundary and owner delegation.

2026-10-23：web_artifact_retention跳过尚未完成追踪的根种子材料，不以生成完成替代最终科学与生产合同完成。种子证据保全由core.seed_focus实现；本维护接口不重发原请求。
