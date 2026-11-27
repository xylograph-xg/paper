# 科学核验

当前版本原文核验、五维核验分、完整报告、材料修复、三次失败循环和修正衔接。

这是独立源码与接口文件夹，正式包名为 `review`。跨项目只调用 `review.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

核验与制卡独立记录，原报告保留；通过需要完整检查、至少85分且没有重大问题或材料缺失。保留旧材料的完整性判断，删除旧无限/独立监听循环。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from review.api import card_review_queue__enabled
```

运行依赖：[article](../infrastructure/article/README.md)、[browser](../infrastructure/browser/README.md)、[cards](../cards/README.md)、[codex_desktop_chat](../codex_desktop_chat/README.md)、[core](../infrastructure/core/README.md)、[correction](../correction/README.md)、[read](../workbench/read/README.md)、[reading](../workbench/reading/README.md)。

CLI/子进程入口：`python -m review.card_evaluation`, `python -m review.card_review_queue`, `python -m review.card_review_repair`, `python -m review.review_tabs`, `python -m review.web_feedback`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project review
make check
```

逐文件运行核验生产者扫描间隔测试：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python -m unittest review.tests.test_review_producer_scan_interval
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [review_cycle.py](review_cycle.py) | Keep failed reviews/corrections cycling; three completed failures recard. | `policy`、`failure_limit`、`completed_failure`、`failure_count`、`run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [card_review_lane.py](card_review_lane.py) | Parallel reviewer conversations on the card keeper's existing CDP connection. | `ReviewLane[__init__, stop, ledgers, latest, owns, collect, submit, reconcile_submissions]` | 当前公开接口或生产链使用；避免复制实现 |
| [card_evaluation.py](card_evaluation.py) | Reproducible card review packets; external feedback is data, never executable code. | `sample_config`、`LazySamples[__iter__, __len__, items, values, __getitem__]`、`digest`、`published_evidence_available`、`structural_metrics`、`safe_card`、`review_prompt`、`contact_sheets`、`prepare`、`assess_feedback` | 当前公开接口或生产链使用；避免复制实现 |
| [review_ledger.py](review_ledger.py) | Fail-closed external authorization and durable per-card submission claims. | `catalog_for`、`install`、`authorized`、`reserve`、`update`、`reconcile` | 当前公开接口或生产链使用；避免复制实现 |
| [web_feedback.py](web_feedback.py) | Serial, explicit web_gpt review jobs; never retry an uncertain submission. | `save_json`、`parse_feedback`、`packet_files`、`parse_or_reformat`、`session_factory`、`require_unique_review_conversation`、`require_current_legacy_control`、`run_reviews`、`main` | 当前公开接口或生产链使用；避免复制实现 |
| [card_review_queue.py](card_review_queue.py) | Version-bound scientific review queue, independent of historical review loops. | `enabled`、`install`、`rows`、`update`、`enqueue`、`current`、`protected`、`prompt_for`、`prepare`、`source_inputs`、`locate_quotes`、`replacement`、`check_packet`、`parse_review`、`formatting_candidate`、`apply_result`、`finish_publication`、`queue_rework`、`finish_rework_reset`、`ReviewProducer[__init__, start, stop, work, run]`、`status`、`for_card`、`public_result`、`visual`、`render_review_visual`、`fit_review_visual_budget` | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [review_tabs.py](review_tabs.py) | Close only saved, completed review tabs whose live answer still matches. | `close_page`、`close_saved_review` | 当前公开接口或生产链使用；避免复制实现 |
| [review_protection.py](review_protection.py) | Protect the exact independently reviewed snapshot without rewriting card text. | `protection` | 当前公开接口或生产链使用；避免复制实现 |
| [review_channel_recovery.py](review_channel_recovery.py) | Recover proven unsent reviews without discarding receipts or changing science. | `recover` | 当前公开接口或生产链使用；避免复制实现 |
| [card_review_repair.py](card_review_repair.py) | Explicit, bounded material repairs after a fully collected source review. | `supplement_packet`、`collected`、`repair`、`supplement_visual` | 当前公开接口或生产链使用；避免复制实现 |
| [eligibility.py](eligibility.py) | 完整落盘合同判断，不包含旧自动监听循环 | `eligible` | 当前仅被 `workbench/reading/tests` 直接引用；未登记为公开出口，待正式纳入 `review.api` 或标注 legacy。 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/browser_card_review.cjs](tests/browser_card_review.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_card_review_repair.py](tests/test_card_review_repair.py)：离线/隔离回归，验证当前合同。
- [tests/test_review_preparation_lock.py](tests/test_review_preparation_lock.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_review_pause.py](tests/test_card_review_pause.py)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_review_channel_recovery.py](tests/test_review_channel_recovery.py)：离线/隔离回归，验证当前合同。
- [tests/test_review_upload_backoff.py](tests/test_review_upload_backoff.py)：真实临时Catalog/回执验证上传退避计数、领取与发送守卫及恢复门。
- [tests/test_card_review_queue.py](tests/test_card_review_queue.py)：离线/隔离回归，验证当前合同。
- [tests/test_review_producer_scan_interval.py](tests/test_review_producer_scan_interval.py)：离线/隔离回归，用可控时钟验证扫描成功或失败都从结束时刻保持60秒间隔。
- [tests/test_review_audit_safety.py](tests/test_review_audit_safety.py)：离线/隔离回归，验证当前合同。
- [tests/test_review_visual_budget.py](tests/test_review_visual_budget.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_review_lane.py](tests/test_card_review_lane.py)：离线/隔离回归，验证当前合同。
- [tests/test_review_cycle.py](tests/test_review_cycle.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_feedback.py](tests/test_web_feedback.py)：离线/隔离回归，验证当前合同。
- [tests/test_review_tabs.py](tests/test_review_tabs.py)：离线/隔离回归，验证当前合同。
- [docs/网页版评审接入.md](docs/网页版评审接入.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/核验材料修复.md](docs/核验材料修复.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/核验准备数据库锁恢复.md](docs/核验准备数据库锁恢复.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/卡片并行核对.md](docs/卡片并行核对.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/核心结论与卡片核验.md](docs/核心结论与卡片核验.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

2026-11-14：常驻核验生产者在启动时发现候选并复查历史核验回执，之后在上轮完成后间隔 15 分钟再执行。常驻材料线程的每分钟通用维护跳过重复的历史核验复查。现有就绪任务和已收取回答仍每秒检查。

核验包、核验队列和报告；网页发送交由browser，不自行建立CDP。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../infrastructure/config/README.md)，共享状态合同见 [data](../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 2026-10-14 审核修复

- [AUDIT_REVIEW.md](AUDIT_REVIEW.md)：审核真实性、方案调整、修复范围和验证边界。
- [tests/test_audit_regressions.py](tests/test_audit_regressions.py)：附件与提示篡改、越界、工厂授权、竞争领取、发布与清理中断恢复。

旧评审仍默认禁用。新准备的旧合同材料冻结全部附件及提示 SHA-256；历史材料缺少冻结摘要时拒绝发送，不自动补签。正式外发入口无论会话工厂均检查控制与授权，并在统一 Catalog 原子领取卡片版本；跨目录回执冲突保留并阻断发送。

核验解析新增 `failure_kind`，只有完整、有依据的科学失败推进科学失败次数；材料不足、不完整、歧义及无依据问题保留独立处置。引文新增可选 `source_document=main|supplement`，省略仅代表主文，分别匹配对应文字层。新提示采用该合同，旧冻结提示不改写。

发布保存 `publication-intent.json` 与候选指纹，持锁重放文件与数据库步骤；暂停、人工保护、原文身份及冲突版本阻断恢复。重做在锁外完整归档材料，提交 `review_reset_pending` 后才清理旧工作目录，成功后转 queued；中断保留不可领取状态，原生产器初始化时恢复，不增加常驻入口。归档是既有流程的版本历史与原回执保存，不新增数据备份服务。

## 核验附件回执合同（2026-10-14）

新ReviewLane提交账本记录同一packet的upload_bundle，供原所有者恢复附件归属；旧账本不回填。公开card_review_queue__check_packet(folder)只读核对冻结输入、原图、ZIP及实际提示指纹，失败抛错，无浏览器或模型副作用。保留此接口是为了让跨项目恢复使用同一核验实现，避免复制材料合同。

## 2026-10-14 中断材料候选恢复

`card_review_repair.repair` 可继续已登记 repair-intent、但没有真实材料/冻结包/请求的准备候选；核对原任务身份、当前原文与卡片、原 packet/完整回答指纹、次数及暂停，并确认新 ID 尚未入库。已冻结 packet 由 `card_review_queue.prepare` 原样复用；未冻结 PDF 需再次核对原文/卡片绑定；原目录整份移动归档并保持 SSD 原件，新准备使用独立媒体目录。未知请求或归属变化继续保留候选。完成材料后再次检查新 packet 的 job_id、卡片与原文指纹，才条件入队。这样恢复准备失败的候选，同时避免“目录存在”造成永久技术阻塞；旧报告、评分及限额不清零。同版本的确定性本地准备失败只执行一次，源码变化后才重新核对。

`card_review_queue.source_inputs` 只读解析已归档的原文材料：活动 packet 已移走时，完整原核验回执的卡片/原文/文字层指纹，或唯一正式发布回答/提示/input 回执，必须绑定 source-review 原归档；候选包字节指纹必须唯一，正式发布页图与原包逐页一致。净化原文读取正式卡片绑定文件，文字层读取原归档，活动目录不写回旧 packet。选择此路径避免重做清理活动材料后，独立核验仍错误依赖活动目录。

半途目录的移动在外侧 partial-recovery 持久意图中预先登记；即使在移动后、建立新候选前中断，也先校验原目录/回执/文件指纹，再恢复独立媒体地址。原活动 packet 不恢复，未知请求不解除。

活动材料仍存在但净化PDF指纹已改变时，也不能替代正式卡片原文。若没有唯一匹配的网页归档，但完整原核验已绑定同一原文、卡片和文字层，可使用正式PDF与原冻结上下文建立“新渲染描述”，逐页从核对的PDF生成视觉证据；不是重建历史网页 packet，原活动包和原核验文件均不改写。新 packet 记录 source_binding。

未冻结候选已复制了较新净化版本时，只有当前正式网页 packet 的同一 paper/原始原文 SHA，以及候选 PDF/文字层双指纹同时证明其来源，才允许整份移入原候选归档；新核验仍只使用正式卡片绑定的原PDF，较新净化副本不成为替代原文。来源不能证明的候选继续保护。

2026-10-14：`card_review_queue.parse_review`在派生动作前核对修正字段、完整原字符串和科学词元。无法作为纯排版应用的有原文依据建议转独立原文重做；原回答与旧评审保留，不本地改科学文字。待核验新版通过统一优先级继承原修正置顶；科学验收与置顶独立。

核验入口同时接受Catalog已登记的`publications/<publication_id>/card.json`，须原生成事件、publication_id、完整正式回执和输入哈希一致；仍逐字核对任务卡片哈希、原文哈希、净化原文、身份与范围，不按路径猜测新版。

2026-10-14：card_review_lane发送前调用browser公开reusable_home.prepare复用干净首页、等待模型控件；原复用守卫、固定target、材料/卡片指纹、GPT/High及发送回执保护保持。减少无必要的同首页重载，防止只看到输入框就进入尚未加载的模型菜单。

扫描间隔持久回归进一步覆盖长耗时失败从结束时刻计时、失败下一tick提交原response_saved非空任务、每次run重新首扫以及真实异常日志。仅使用可控时钟、假数据库/executor，不发网页请求。

`card_review_lane.submit` 只把明确结束、从未点击发送的原生上传失败（`upload_failure_stage`）在回执落盘后经 `browser.upload_retry_policy.record_failure` 计一次，成功发送清连续计数、总证据保留；领取（`BEGIN IMMEDIATE`）与提交锁内最终 `before_send` 各自再核对策略、暂停、材料与原回执，冷却到期不证明页面可复用。`review_channel_recovery.recover` 保留原归档与原租约核对链，只在链条全部通过且不在冷却中才把作业改回 `ready`，未到期时回执原样保留、下一轮再看。科学失败次数、原文/卡片、历史回执、`max_reworks` 与页池均不变；详见[核验上传失败退避](../infrastructure/browser/docs/核验上传失败退避.md)与[授权记录](../infrastructure/docs/authorizations/20261015-review-upload-backoff.md)。

2026-10-15：S002 返工（`EXEC_RUN_ID=20261015-141532-291e14cd`）把退避的两处异常越界收口到本道内部。`card_review_lane.submit` 现在对领取层的 `first_eligible` 与发送后的 `settle_success` 各自局部捕获 `(ValueError, OSError, sqlite3.Error)`（`PolicyIntegrityError` 是 `ValueError` 子类，`OperationalError` 不是）：损坏策略行或写锁占用只写 `review-dispatch-rejection.json` 的 `upload_policy_error: …` 与 attempt 的 `upload_settle_policy_error` 诊断键，**不改写已落盘的 `submitted` 回执、不改 `card_review_jobs.state`、不触页面、不让异常到达所有者派发大周期**；异常外泄会让内联路径跳过同周期其后的制卡与修正派发（并行上传＝1 时），并行路径则由上传协程吞掉。`upload_retry_receipts.reason` 落盘前先经 `browser.upload_trace.desensitize`，签名URL、query与正文不再进入持久表；计数段标签改用内核自己的 `attachment_write`／`attachment_visible` 拆分（旧 `attach` 仍可读），是否计一次由 `detail['retryable_upload']` 决定。核验暂停、额度、访问验证、人工决定与未知回执保护均优先于以上变化；`card_review.upload_retry.enabled` 的默认生效仍未登记进 AGENTS.md，属用户决定项，本批未改配置。

## 上传失败收尾（2026-10-15）

`ReviewLane.submit`在退避记账SQLite错误或诊断写失败后仍完成明确未发送回执和页面needs_inspection收尾；已提交回执不因队列确认失败而降级。`reconcile_submissions(entries, excluded_targets=())`只将submitting与原结束回执对齐为needs_user/submitted，核对job/target、冻结输入，排除活跃回调；不变ready、不释放原生上传、不重发。策略损坏材料保留原FIFO，非混合领取可选下一健康材料。原退避5/15/60分钟启用，技术失败不计科学失败。新核验材料通过cards公开`visual_budget`共享24MB软目标/150DPI软下限/48MB硬预算，原文、实际卡片图像和冻结材料保持原字节。测试见[test_review_upload_backoff.py](tests/test_review_upload_backoff.py)。

`browser.api.original_upload_http1__material_intent`在恢复及领取处阻断已有原PUT意图的材料（含跨epoch unknown）；原页面可按明确未发送的归档链释放，原材料不重传，其他健康材料继续排队。

核验提交通过公开`browser.api.web_card_transport__commit_submitted`确认原请求，避免晚到发送确认降级已经由独立原观察器保存的同指纹回答。共享模式原始正文只由观察器提取，队列确认仍核对原target/唯一会话/完整提示及实时正文；新回执与180秒结算阈值、科学评分无关。实现及证据见[独立执行授权](../infrastructure/docs/authorizations/20261016-independent-upload-and-collection.md)。

2026-10-16核验提交按on_stage保存发送前真实阶段和异常类型/堆栈；同指纹已收取回答不因晚到确认失败降级。新准备ZIP不得超过远程浏览器50MiB，视觉硬预算48MB，旧材料不改写。

冻结ZIP通过公开browser.api.web_upload_bundle__check_zip_size在页面检查前核对本地容量；UploadSizeError不作账户额度或网络门。

核验上传上下文沿用web_cards.parallel_uploads.local_file_paths，由browser公开submit_gpt_background入口使用原所有者本机路径赋值；不另连浏览器，不改变原生附件完成判定或未知请求保护。

2026-10-17：ReviewLane.ledgers先只查id/folder，latest不读取全库报告正文；collect只取当前pages的完整job，提交回执恢复只扫描submitting。原read_attempt inode/大小/mtime/ctime指纹变化重读；job.folder变动拒绝旧绑定，缓存诊断键不写入原回执。构造时一次安装模式，避免每轮rows重复全报告及安装。回归见[tests/test_review_ledger_reads.py](tests/test_review_ledger_reads.py)。

ReviewLane.submit兼容新增on_unstarted回调，原bool返回不变。真正预检结束或本机writer未进入且无发送意图的失败才通知；policy_error等诊断侧写显式final=False，不提前释放仍将继续执行的任务。原owner绑定当前target/准入job/材料，容量证明不改变页面、队列、原回执或重试权限。

2026-10-18 核验漏斗修复：review_cycle 的报告解析及历史科学失败计数显式传入同一配置；完整回执核对后的 scientific failed 可回原三次循环，技术/未知/歧义不计科学失败。minor 建议不额外否决满足现行标准的报告，通过项 failure_kind=null。tests/test_funnel_contract.py 覆盖这些合同。

2026-10-20：手选根种子全环节第一顺位，重试/恢复保留同一身份；`core.api.workflow_priority__seed_first`以只读、稳定排序保留原记录对象和组内次序。材料分配、核验准备、混合补充及跨队列上传准入统一种子优先；退避、次数、暂停、固定槽位和未知回执保护保持。见[授权](/Users/xiaoyanhao/project/paper/infrastructure/docs/authorizations/20261020-manual-seed-first-all-stages.md)。

2026-10-20：当前5篇手选根种子三版独立优选。`cards.seed_trials`由现有材料线程每60秒推进；逐版原文核验后只选择完整通过、至少85且无重大/缺材料的最高真实核验分，无合格版沿用原修正循环。原卡/回执/报告、固定槽位、暂停、未知与重试计数保留。`independent_request`仅为新准备材料的中性独立请求标识，写入原文上下文/实际提示并记录输入指纹；旧冻结包不改。旧百万优先级不作为质量分展示，优先身份独立标注。见[固定授权](/Users/xiaoyanhao/project/paper/infrastructure/docs/authorizations/20261020-manual-seed-three-candidates.md)。

2026-10-22吞吐修复：`ReviewProducer.run`将全库enqueue发现放在原executor的单个future中，不阻塞当前队首材料准备及response_saved处理；60秒间隔按发现结束计，失败同样计时，不堆叠扫描。`enqueue(...,stopping=None)`与`review_cycle.run_once(...,stopping=None)`在文献之间检查停止，保留既有调用默认行为；不绕过手选优先、FIFO或暂停。`ReviewLane.submit(...,on_submitted=None)`向原owner提交同请求合并回调；SQL确认仅从submitting进入submitted，原完整回答不降级。收取异常若发现原回执已保存，仅追加collection-followup-error，不覆盖正文和原状态。测试包含发现慢/失败仍能处理队首材料及原完整回答、原时间节流、暂停/停止。

2026-10-23：核验媒体目录新增物理准备文件夹指纹，防止同一核验ID的重排候选覆盖原冻结PDF。已发送旧材料仅可从原ZIP按每文件及整体指纹恢复到独立verified-inputs视图；旧损坏字节、原packet、实际提示和回执均保留，不生成新输入或重发。

2026-10-23：仅手选模式在原核验领取前经core.api.seed_focus__allowed检查，跨队列排序及最终发送均保留同一门；已发送普通核验仍按原回执收取。

## 2026-10-25 自动生产验收接续

| 文件 | 全部入口与保留理由 |
| --- | --- |
| [production_contract.py](production_contract.py) | `evaluate`：复用cards公开严格解析器、原核验材料与实际图像清单进行独立web-production-v1验收；`reconcile`：原材料线程每60秒接续现存同版本通过卡，独立元数据意图保留旧科学报告。历史诊断字段只按明确的兼容规则比较，旧评估、当前复核、原回执及独立生产合同均须通过；暂停、人工保护、版本与独占门继续生效。 |
| [tests/test_production_contract.py](tests/test_production_contract.py) | 严格结构、科学major/缺材料/非pass阻断、实际图像与发送副本变化、元数据发布不改科学字段、旧通过接续、发布中断重入及暂停保护。 |

公开API为`production_contract__evaluate(card,path,job,folder,assessment,*,published_path=None)`与`production_contract__reconcile(catalog,config,*,limit=5)`。前者只读并返回complete/blockers及版本绑定；后者可能写卡片元数据和独立production-acceptance意图/新hash别名，绝不生成科学文字。新卡初次发布仍保持科学/生产未验收；科学通过也不直接等于生产合同通过。原`finish_publication`额外核对独立验收、原完整报告和科学内容不变；独立接续保留原通过修正链，旧回执/报告/候选/发布意图不覆盖。全局工具`web_gpt`实现/合同未更改。

原材料线程停止信号经 automatic_issue_handler.run_once(..., stopping=None) 与 workflow_recovery.run_once(..., stopping=None) 传至既有 review_cycle.run_once；历史 failure_count(..., stopping=None) 在每份历史报告前检查，当前完整科学检查结束后再次核对再决定是否推进。停止时保留原报告/计数/任务，不继续后续恢复、收取请求或科学重做，不将中断算作科学失败。

## 2026-10-26 科学失败直接准备

`review_cycle.run_once`不在准备或原文重做成功前将failed写回needs_user，也不为未推进的轮询新增review_cycle_terminal_recovered事件。`card_review_repair.repair(...,cycle=True)`允许failure_kind=scientific的failed入口，仍重新完整核对原回答、原文和卡片版本、科学失败、次数、暂停/人工及最终CAS；cycle=False或非科学failed不扩大准入。新材料事务完成才变为ready，候选意图保留原failed任务，旧报告/回执/卡片和计数不变。recovery_revision更新为terminal-scientific-preparation-v7，原同版本本地准备失败守卫保留。相关三份现有测试覆盖状态不抖动、原因保全、真实成功及拒绝路径；实测见../reports/20261026-recovery-terminal-idempotency.md。

2026-11-09 核验未发送恢复沿用原50 MiB本地传输上限。冻结ZIP的申报和实际体积都须通过已有检查，超限时保留原未发送回执、材料和队列状态，不再按同一输入反复归档与领取。
