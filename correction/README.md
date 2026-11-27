# 卡片修正

排版/引文修正、重大问题重新制卡衔接、版本保护、保存回执恢复、发布后重核验。

这是独立源码与接口文件夹，正式包名为 `correction`。跨项目只调用 `correction.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

修正输入必须绑定原文、旧卡片与报告指纹。人工决定、未知提交和暂停优先；修正完成后重新核验，直接通过不替代完整修正链。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from correction.api import card_correction_queue__allows_web_job
```

运行依赖：[browser](../infrastructure/browser/README.md)、[cards](../cards/README.md)、[core](../infrastructure/core/README.md)、[review](../review/README.md)。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project correction
make check
```

逐文件运行修正生产者建议路由间隔测试：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python -m unittest correction.tests.test_correction_producer_scan_interval
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [card_correction_lane.py](card_correction_lane.py) | Correction bookkeeping on the single shared browser owner's event loop. | `CorrectionLane[__init__, stop, sync, pending, ready_requests, latest, allow, state, status]` | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [recover_saved_publication.py](recover_saved_publication.py) | Resume a complete correction answer blocked only by an SSD alias copy error. | `run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [card_correction_queue.py](card_correction_queue.py) | Version-bound corrections, separate from verification and browser ownership. | `CorrectionPaused[]`、`_require_running`、`enabled`、`install`、`rows`、`update`、`_finish_local`、`_recover_local`、`_bound_job`、`_bound_rows`、`_job_ref`、`_collected_review`、`_enqueue`、`partial_rework_allowed`、`_rework_action`、`enqueue_review`、`enqueue_quotes`、`check_task`、`claim`、`_publish_local`、`process`、`web_job_kind`、`allows_web_job`、`mark_web_state`、`_published_rework`、`check_retry_prompt`、`resume_scheduled_retry`、`_resume_prepared_rework`、`sync`、`adopt_legacy`、`ready_requests`、`status`、`CorrectionProducer[__init__, start, stop, work, run, _run_owned]` | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [AUDIT_REVIEW.md](AUDIT_REVIEW.md)：审核真实性、调整方案与验证边界。
- [tests/test_audit_regressions.py](tests/test_audit_regressions.py)：本轮状态、迁移、互斥和发表故障回归。
- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/test_card_correction_queue.py](tests/test_card_correction_queue.py)：离线/隔离回归，验证当前合同。
- [tests/test_correction_producer_scan_interval.py](tests/test_correction_producer_scan_interval.py)：离线/隔离回归，用可控时钟验证路由计算或状态写失败都从结束时刻保持60秒间隔；覆盖活动修正任务不得误判中断、并行任务各自保护、其他遗留任务仍恢复及结束future不永久遮蔽未提交任务。

修正生产者在原独占锁内将自己提交的future绑定任务ID，仅在future仍运行时跳过该任务的中断恢复扫描。真正遗留的preparing/needs_user记录继续走原恢复分支；future结束即撤销活动保护，不建立持久豁免，不改生产状态、原报告、科学结论、暂停或发送权限。

`card_correction_queue._resume_prepared_rework` 由原 `sync` 调用，仅为旧生产者明确误判中断、已经存在的未发送重做意图核对接续：原任务/完整报告、原文/当前卡片、归档旧卡和已结束原请求必须全部一致，当前请求（包括明确未发送草稿）或未知历史均不准入。写入前以原行和文件版本再次核对，保留旧错误到事件；不新建重做、不清重试次数、不重发。`tests/test_audit_regressions.py` 覆盖一次性接续、其他失败、请求/历史未知、材料/人工/暂停及核对期间漂移保护。
- [tests/test_correction_presend_prompt.py](tests/test_correction_presend_prompt.py)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_corrected_library.py](tests/test_corrected_library.py)：离线/隔离回归，验证当前合同。
- [tests/test_card_correction_lane.py](tests/test_card_correction_lane.py)：离线/隔离回归，验证当前合同。

## 数据、并发和权限边界

2026-11-14：历史修正分流恢复在启动时检查，之后在上轮结束后间隔 15 分钟再检查；本地修正队列每轮后等待 3 秒。

修正队列、独立候选、新版卡片及再核验记录。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../infrastructure/config/README.md)，共享状态合同见 [data](../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 2026-10-14 审核整改

发送门禁从宿主 catalog_path 只读核对真实修正/论文/核验/旧卡/原文绑定；仅 ready/submitted 可派发。既有 core 自动故障处理以 recovery=True 核对 needs_user 身份及暂停许可，随后仍检查原错误、归档、原文/卡片和无活动回执；该模式不允许发送。通用运输回调不接受 completed 布尔证明，完成由 sync 的原文、回答、提示、正式卡片检查后登记。状态写入使用事务及旧状态条件，终态不被迟到回调覆盖；已有归档有限重试仍沿用单独证据核对流程。

生产者构造不回收任务；运行期间持有 correction-producer.lock，重复实例退出。唯一持锁生产者只补齐已发布新版的核验登记；未发布的中断保留待核对，不隐式发布或重发。publication.json 在替换正式卡之前记录新版哈希，恢复核对候选、正式卡、原文、人工保护及暂停；事件允许幂等恢复期间重复审计，但不重复卡片替换。

旧任务迁移的 correction 插入与 webjob 绑定共用一个事务；失败可保留不参与调度的任务文件证据，不留下 SQL 孤儿。没有明确 correction_id 的旧回执显示 unknown_legacy，原文件不改写。保存回答恢复入口额外持有 correction-recovery.lock 并重新核对数据库绑定；底层发布原有论文锁继续有效。

诊断追加 correction-diagnostics.jsonl，保留错误类型及堆栈；正式 wheel 不包含 tests。新增 [tests/test_audit_regressions.py](tests/test_audit_regressions.py) 验证迟到回调、伪完成、构造器和发布后故障恢复。详细评估见 [审核评估](AUDIT_REVIEW.md)。这些离线检查不构成真实网页或科学验收。

## 2026-10-14 版本目录发布同步

`card_correction_queue._published_rework` 接受正式库文章目录中的 publications/<publication_id>/card.json；目录 ID、卡片 meta、web-provenance、原 packet 输入、完整原回答与实际提示必须一致，并继续核对当前原文、修正/核验 ID 和旧卡指纹。选择版本目录是为了保留旧卡、避免发布事务回滚改坏旧版本；同步不把结构完成标为科学通过，新版本独立进入核验。

## 已通过核验的修正持续优先（2026-10-14）

`card_correction.priority_passed_first`让同原文的完整通过报告对应修正及其后继待核验新版持续置顶，优先组内继续文章分数/FIFO排序。置顶从不可变原任务判定，不提高评分、不更新原入队时间。

- [recover_review_corrections.py](recover_review_corrections.py)：`run_once`核对原任务、完整原回答、唯一URL、输入/提示/原文/卡片后，在原生产者每60秒分流排版失败；科学改写进入独立原文重做，已由正式新版或完整后续核验替代的旧建议仅标记失效。保留旧任务、旧报告、解析结果及分流证据，不外发、不直接改科学文字、不恢复暂停。
- [tests/test_review_correction_routing.py](tests/test_review_correction_routing.py)：语义修改禁止本地发布、分流幂等、回执变化和暂停保护。

直接通过且没有有效修正链的文章不会为了凑入库数量而制造修正。阻塞由真实原因处理；未知回执、科学歧义、人工决定及额度持续保留。

分流内部`_retire`保存旧行与后继证明后条件写入失效；`_resume_unsent_routing`仅恢复已核对新合同、从未绑定网页运输/账本的新本地任务，保留旧错误事件。新任务继承置顶，旧已发送或未知请求仍不重发。

路由间隔持久回归进一步覆盖长耗时失败、失败下一tick恢复/执行原preparing非空任务、run_once失败不写成功状态、状态写失败保留上次成功字节及每次run重新首扫。仅使用临时诊断文件和假领取/恢复/work，不发布或发送。

2026-10-18 修正报告复核、旧任务接入和分流恢复统一传入配置。config-routing-recovery.json 保存配置漏传导致的原失败行与证据；恢复仍须原任务/回答/输入指纹一致、当前版本及人工/暂停保护通过且无该修正的网页账本或运输绑定。

2026-10-20：手选根种子全环节第一顺位，重试/恢复保留同一身份；`core.api.workflow_priority__seed_first`以只读、稳定排序保留原记录对象和组内次序。材料分配、核验准备、混合补充及跨队列上传准入统一种子优先；退避、次数、暂停、固定槽位和未知回执保护保持。见[授权](/Users/xiaoyanhao/project/paper/infrastructure/docs/authorizations/20261020-manual-seed-first-all-stages.md)。

2026-10-23：allows_web_job增加独立手选根种子准入；普通修正任务、原建议及暂停保留，独占期间不派新工作。
