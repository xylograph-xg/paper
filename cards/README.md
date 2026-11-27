# GPT制卡与卡片发布

精选与不足补充、原文/视觉材料准备、动态卡片合同、严格JSON解析、有限重试、证据匹配和发布。

这是独立源码与接口文件夹，正式包名为 `cards`。跨项目只调用 `cards.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

当前生产仅使用GPT网页版。单ZIP、材料哈希、通用评分与完整回执防止附件混淆和旧答案污染；结构完成不冒充科学通过。专项修复代码仍核对已用次数，保留它们用于阻止重发。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from cards.api import web_card_service__owner_enabled
```

运行依赖：[browser](../infrastructure/browser/README.md)、[codex_desktop_chat](../codex_desktop_chat/README.md)、[core](../infrastructure/core/README.md)、[correction](../correction/README.md)、[read](../workbench/read/README.md)、[reading](../workbench/reading/README.md)、[review](../review/README.md)。

CLI/子进程入口：`python -m cards.web_card_evidence`, `python -m cards.web_card_inputs`, `python -m cards.web_card_retry`, `python -m cards.web_card_service`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project cards
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [web_card_retry.py](web_card_retry.py) | 原所有者核对并归档后重试；根种子明确未发送的技术失败独立计数、持续退避。 | `known_unsent`、`finished_response`、`cooperative_digest`、`frozen_inputs`、`eligible`、`_root_technical_retry`、`reset_unsent_page`、`release_archived_unsent_lease`、`release_verified_unsent_lease`、`relocate_saved_pool_paths`、`_recover_archive`、`run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_rework.py](web_card_rework.py) | Explicit rework authorization bound to the original card fingerprint. | `archived_capacity_deferral`、`authorization`、`archived_receipts`、`submission_history` | 当前公开接口或生产链使用；避免复制实现 |
| [publication_materials.py](publication_materials.py) | Copy verified publication evidence while respecting existing SSD aliases. | `copy` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_evidence.py](web_card_evidence.py) | Offline, case-sensitive quote checks; never infer scientific entailment. | `digest`、`verify` | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_queue.py](web_card_queue.py) | Persistent web-only card queue and reproducible approximate 30% selection. | `install`、`ranking`、`select`、`jobs`、`claim`、`update`、`recover` | 当前公开接口或生产链使用；避免复制实现 |
| [paper_quality.py](paper_quality.py) | Evidence-based literature quality rubric, independent of generated card review. | `dimension_schema`、`weighted_score`、`validate` | `validate` 用于新制卡；`dimension_schema`/`weighted_score` 仅保留 v1 历史兼容与回归，不参与现行网页整体计分。 |
| [web_card_inputs.py](web_card_inputs.py) | Prepare source-only PDFs/visuals and validate web cards without local inference. | `MaterialDeliveryError[]`、`_delivery_failure`、`check_material_delivery`、`inspect_source`、`web_rules`、`item_templates`、`card_format_instructions`、`damaged_latex`、`damaged_text_fields`、`digest`、`valid_source_hash`、`render_visual`、`prepare`、`upgrade_evaluation_packet`、`parse_card` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_service.py](web_card_service.py) | Detached web-only generation keeper, independent of UI and local model lanes. | `external_dependencies`、`code_version`、`paths`、`status`、`start`、`stop`、`enabled`、`owner_enabled`、`_owner_process_confirmed`、`_publication_identity_guard`、`_source_review_publication_guard`、`publish_saved`、`process_job`、`run` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_structure_repair.py](web_card_structure_repair.py) | One explicitly authorized source-only regeneration with a new format packet. | `saved`、`authorized_archives`、`schedule` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_json.py](web_card_json.py) | Repair JSON separators/invalid escapes; never add or change scientific fields. | `normalize_escapes`、`normalize`、`object_span`、`json_body` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_delivery_repair.py](web_card_delivery_repair.py) | Explicit one-off delivery retries; source answers and ordinary limits persist. | `_check_delivery`、`authorized_archive`、`schedule` | 当前公开接口或生产链使用；避免复制实现 |

所有者启动时 `code_version()` 除本仓组件源码外，还用 `external_dependencies()` 把真正运行的仓外内核按登记路径哈希进 `module_sha256`：`dependency:web_gpt.core`、`dependency:web_gpt.package`、`dependency:web_gpt.zip_uploads`、`dependency:codex_desktop_chat.bundles` 与 `dependency:playwright.sdk`（SDK 版本字符串的哈希），并另存 `external_dependencies`（status／import_root／sdk_version／files／errors）供验收绑定。登记来自 `infrastructure/tool-dependencies.json` 的 web_gpt 条目，环境变量 `WEB_GPT_IMPORT_ROOT` 优先；实际已加载的 `web_gpt.core.__file__` 与登记路径不同、文件读不到、SDK 版本取不到或登记缺失，都只把 status 降为 `incomplete` 并记录原因，**不抛错、不杀所有者**（缺哈希会让启动失败并触发 KeepAlive 反复重启）；由验收器据此拒绝自动交接。指纹仍只在启动时采集一次，不用新代码冒称运行中的所有者。

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/test_web_card_evidence.py](tests/test_web_card_evidence.py)：离线/隔离回归，验证当前合同。
- [tests/test_visual_budget.py](tests/test_visual_budget.py)：离线/隔离回归，验证当前合同。
- [tests/test_score_rounding_tolerance.py](tests/test_score_rounding_tolerance.py)：离线/隔离回归，验证当前合同。
- [tests/test_formula_json_prompt.py](tests/test_formula_json_prompt.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_generation_format.py](tests/test_card_generation_format.py)：离线/隔离回归，验证当前合同。
- [tests/test_paper_evaluation.py](tests/test_paper_evaluation.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_image_paths.py](tests/test_card_image_paths.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_card_structure_repair.py](tests/test_web_card_structure_repair.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_quality.py](tests/test_card_quality.py)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_input_audit.py](tests/test_card_input_audit.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_card_resident.py](tests/test_web_card_resident.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_card_rework.py](tests/test_web_card_rework.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_findings.py](tests/test_card_findings.py)：离线/隔离回归，验证当前合同。
- [tests/test_publication_materials.py](tests/test_publication_materials.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_card_stall.py](tests/test_web_card_stall.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_card_publication_protection.py](tests/test_web_card_publication_protection.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_card_retry.py](tests/test_web_card_retry.py)：离线/隔离回归，验证当前合同。
- [tests/test_audit_regressions.py](tests/test_audit_regressions.py)：制卡审计回归，覆盖真实Catalog/PDF与发布保护。
- [tests/test_external_dependency_fingerprint.py](tests/test_external_dependency_fingerprint.py)：仓外依赖指纹与登记一致性回归。
- [tests/test_selection_projection.py](tests/test_selection_projection.py)：精选投影与30%分母保护回归。
- [docs/文献质量评分标准.md](docs/文献质量评分标准.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/制卡库存自动补充.md](docs/制卡库存自动补充.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/制卡失败重试.md](docs/制卡失败重试.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/文献评分.md](docs/文献评分.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

本地材料/队列/候选与卡片发布；实际上传和发送交给browser唯一所有者。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../infrastructure/config/README.md)，共享状态合同见 [data](../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 2026-10-14 审计修复合同

新准备材料携带 `card-contract-v2`：info八项必须为非空字符串，图、公式、表分别检查专属必需字段，公式关联标签为字符串数组，引文至少15字符。缺失资料须明确说明不足，不补造科学值。旧冻结材料不改写，沿用兼容解析；发布元数据明确 `legacy_valid`，不标记当前合同结构完整。详细逐项判断见 [审计复核记录](../reports/workflow-audits/制卡模块代码审计复核与修复_20261014.md)，新增真实Catalog/PDF回归见 [tests/test_audit_regressions.py](tests/test_audit_regressions.py)。

所有入队/准备要求有效小写SHA-256，正式发布再次核对任务、packet、Catalog及实时原文四方指纹，并检查身份/版本/范围和原任务绑定。人工保护、限定重做与未知回执保护保持。解析拒绝公式中可识别的JSON转义损坏，允许合法多行公式，不猜补符号。

发布使用暂存目录、持久意图、SQLite `BEGIN IMMEDIATE`和条件更新，将Catalog路径、任务完成及事件在同一数据库事务登记。重做发布到新的版本目录，旧卡片原字节保留；数据库提交失败不会改掉仍被目录引用的旧卡。文件与数据库并非单一原子事务：未完成意图阻断重发；已提交数据库但末尾意图记录失败时，可凭正式文件/证据/来源指纹核对原提交。无法证明提交的文件保留待检查，不冒称完成。重试归档记录逐目录回执指纹，事务回滚后恢复原回执位置，已用预算不减少；已提交排队后补齐scheduled账本，不重新提交模型请求。

新材料上传硬预算为48 MB（2026-10-16）。本地另限制原文256 MB、1000页、单页4000万像素、逐页图片总量1 GB，以及至少256 MB加本页像素缓冲的剩余磁盘空间；渲染失败清理新图片/visual，保留诊断与原材料。材料文件摘要流式读取并检测读取期间变化。材料准备默认当前解释器；服务复用核对原PID命令、配置、token及占用的所有者锁，陈旧心跳单独显示，不将上传阻塞误报为进程死亡。启动指纹覆盖真实物理源码目录，包含cards、browser、core、review和correction。

## 2026-10-14 近期故障修复

`web_card_json.object_span/json_body` 仅解析明确 JSON 标记、唯一完整对象、无其他正文尾部的回答包装。`web_card_inputs.parse_card` 仍检查原包装中的附件缺失提示及原有科学/结构合同；`normalize` 保留包装字节，只对 JSON 内已有授权语法修复生效。拒绝多个对象、截断及无标记的散文，不补造科学字段。原回答不改写，本地重检仍按回答/材料/解析器指纹只执行一次。

`web_card_retry` 通过 `core.api.archive_paths__move_with_links` 归档和回滚，保持 SSD 原件链接，解决移入 history 后诊断图误报丢失。既有预算、原请求归属和未知回执保护继续生效。

本地解析缓存同时绑定磁盘摘要与已加载的 parser_revision/syntax_revision；解析或辅助逻辑语义变化须更新标记，防止重载前的旧实现污染新版本缓存。已用远程重试次数不因本地解析版本改变而清零。

## 新材料体积软目标（2026-10-15）

`web_card_inputs.visual_budget(material_bytes, dpi)`统一制卡/核验新材料策略（公开API见interface.json）：24,000,000字节软目标，48,000,000字节硬预算；先按220/180/150DPI自适应，软目标无法满足时保留150DPI并记录`material_target_met=false`，只有仍超过硬预算才继续原120/96/72步骤。软目标为本轮工程选择，不是网站限制或实测最优阈值。所有原文页、净化原文、上下文与实际卡片图像保留，冻结/在途材料禁止重写。packet及核验review-visual-policy记录真实目标、DPI与大小；`visual-budget-v3`不追改旧包。回退只将软目标恢复到硬预算，不修改历史材料。59页大包的只读对照结果见[体积测量](../reports/twenty-page-stall-20261015T155655/zip-visual-measurement.json)。

2026-10-16新准备规则增加formula-json-v2逐项JSON往返自检，完整对象统一序列化后与原LaTeX逐字比较；无解析工具不声称执行。旧冻结prompt/回答不改写，损坏公式仍阻断，科学内容不猜补。

2026-10-17：web_card_queue._selection_papers仅投影有可用原文的筛选字段（题名/身份/路径/所需元数据和相关性），不调用Catalog.list装载全库科学卡片/发现/自动精选历史。保持原引用数缺失与显式null区别、原排序与30%分母、人工/已有卡片和原文指纹保护；回归见tests/test_selection_projection.py。

2026-10-20：手选根种子全环节第一顺位，重试/恢复保留同一身份；`core.api.workflow_priority__seed_first`以只读、稳定排序保留原记录对象和组内次序。材料分配、核验准备、混合补充及跨队列上传准入统一种子优先；退避、次数、暂停、固定槽位和未知回执保护保持。见[授权](../../paper/infrastructure/docs/authorizations/20261020-manual-seed-first-all-stages.md)。

2026-10-20：当前5篇手选根种子三版独立优选。`cards.seed_trials`由现有材料线程每60秒推进；逐版原文核验后只选择完整通过、至少85且无重大/缺材料的最高真实核验分，无合格版沿用原修正循环。原卡/回执/报告、固定槽位、暂停、未知与重试计数保留。`independent_request`仅为新准备材料的中性独立请求标识，写入原文上下文/实际提示并记录输入指纹；旧冻结包不改。旧百万优先级不作为质量分展示，优先身份独立标注。见[固定授权](../../paper/infrastructure/docs/authorizations/20261020-manual-seed-three-candidates.md)。

| 文件 | 实现/接口与保留理由 |
| --- | --- |
| [seed_trials.py](seed_trials.py) | `_policy/_source/_completed_receipt/_receipt_proofs/_idle`核对固定授权、根身份和完整原回执；`_schedule/_finish_reset`持久归档并复用原队列；`check_request`在原上传/发送守卫内复查固定范围；`record_review/choose/_finalize`逐版收取、真实择优及原发布守卫；`run_once/status`为现有线程/API的推进和只读进度。`_path/_load/_save/_lock`维护独立证据，不新增常驻、CDP或科学评分实现。 |
| [tests/test_seed_trials.py](tests/test_seed_trials.py) | 19项离线检查覆盖未知不重发、原回执/原卡保留、独立材料标识、不得替代原评分、三版择优、重复收取和发布后中断恢复。 |

旧归档缺少prompt.txt时，仅当已保存实际提示恰为原冻结提示的SHA匹配前缀加固定ZIP包装时，在临时验证视图中交原完整回执守卫复核；原文件不变，证据明确记录该证明。原回答、实际提示、ZIP、材料输入和唯一正式URL仍须全部通过，不借此重发旧请求。

候选核验保存后使用独立终态trial_reviewed，原浏览器收取循环不重复读取已封存候选；迟到的旧轮回调在后续轮次中只核对原候选，不提前发布首版。只有三版结束且明确择优的原报告进入正式核验发布守卫。

2026-10-23：seed_trials.status以真实阻塞追踪覆盖旧generating展示；web_card_retry在合法重试移动原回执前保存根种子证据。历史prompt.txt缺失仅从原实际提示精确包装及冻结SHA核对，原输入不写回。

2026-10-23重试复核：此前无限技术重试只覆盖旧同步入口，常驻共享页仍被两次上限拦截。`web_card_retry.run_once`现按`manual_seed_roots`与任务原文hash双重确认，且所有当前回执均明确`send_click_started=false`时使用独立`technical_retries`；旧`external_retries`不清零、不增加，默认5/15/60分钟退避，后续保持60分钟。归档、CAS、原页、历史请求、材料、暂停与额度守卫保持；完整回答的结构重试和已发送/未知请求不获取额外次数。沿用[2026-10-19授权](../infrastructure/docs/authorizations/20261019-seed-fast-lane.md)。

2026-10-25：公开`web_card_inputs__parse_card(raw,packet)`供独立生产验收直接复用唯一严格解析器；签名、科学字段校验和原生成合同未改。review的web-production-v1通过完整科学核验后再独立判定生产合同，初次生成仍保持两项False。原五篇三版择优、技术重试预算与未知请求不重发规则不变。

`web_card_retry__cooperative_digest(path, checkpoint)`公开复用同一全字节哈希实现：每0.25秒及结束时让出原所有者循环，前后校验inode/体积/mtime/ctime。供共享队列锁外预热使用，不替代原文完整性核对。

Explicit negated delivery classifications are not affirmative missing-input claims. Only the negated failure phrase is excluded; a separate source.pdf/visual.pdf read failure still blocks. Original answers, retry counters and scientific gates remain unchanged.

`web_card_service.run` 在原所有者锁内分流已授权的公式整理模式，随后由 browser 的公开入口执行。此模式先于旧队列恢复和材料线程启动。
