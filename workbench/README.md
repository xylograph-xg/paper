# 网页工作台

文献库HTTP接口、阅读器、搜索/备注/已读、访问凭据、远程访问、后台网页服务及启动器。

这是独立源码与接口文件夹，正式包名为 `workbench`。跨项目只调用 `workbench.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

选独立后台HTTP服务和读取有限重试，关闭终端不影响远程查阅；写请求回执不明不重试。保留KaTeX/Marked及许可证供科学文字与公式显示，页面不改科学正文。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from workbench.api import web__serve
```

运行依赖：[browser](../infrastructure/browser/README.md)、[cards](../cards/README.md)、[core](../infrastructure/core/README.md)、[correction](../correction/README.md)、[fetch](../fetch/README.md)、[reading](reading/README.md)、[review](../review/README.md)。

CLI/子进程入口：`python -m workbench.workbench_service`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project workbench
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [web.py](web.py) | Authenticated workbench on loopback or through the configured tailnet proxy. | `card_image_asset`、`WorkbenchHTTPServer[__init__, process_request, process_request_thread]`、`serve`、`create_http_server` | 当前公开接口或生产链使用；避免复制实现 |
| [upload_storage.py](upload_storage.py) | Bound temporary uploads; never collect files referenced by unfinished jobs. | `upload_lock`、`collect`、`write_upload`、`prepare` | 当前公开接口或生产链使用；避免复制实现 |
| [workbench_service.py](workbench_service.py) | Launch the reading UI in its own session; never starts workflow workers. | `access`、`probe`、`announce`、`start`、`run`、`main` | 当前公开接口或生产链使用；避免复制实现 |
| [test_api.cjs](test_api.cjs) | 隔离浏览器测试或其公开辅助入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [tailscale_access.py](tailscale_access.py) | Expose the loopback workbench through a dedicated tailnet-only Serve port. | `setup` | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [workbench.html](workbench.html) | 工作台或模板静态页面 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [commands/启动文献工作台.command](commands/启动文献工作台.command) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [commands/启动任务面板.command](commands/启动任务面板.command) | 接口、配置或启动入口 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/browser_lan_card.cjs](tests/browser_lan_card.cjs)：离线/隔离回归，验证当前合同。
- [tests/workbench_browser_access.cjs](tests/workbench_browser_access.cjs)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：测试包标记（46字节），不是回归用例。
- [tests/browser_workbench_refresh.cjs](tests/browser_workbench_refresh.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_workbench_service.py](tests/test_workbench_service.py)：离线/隔离回归，验证当前合同。
- [tests/browser_authenticated_workbench.cjs](tests/browser_authenticated_workbench.cjs)：离线/隔离回归，验证当前合同。
- [tests/workbench_browser_fixture.py](tests/workbench_browser_fixture.py)：离线/隔离回归，验证当前合同。
- [tests/test_desktop_widget.py](tests/test_desktop_widget.py)：离线/隔离回归，验证当前合同。
- [tests/browser_runtime.cjs](tests/browser_runtime.cjs)：离线/隔离回归，验证当前合同。
- [tests/test_workbench_access.py](tests/test_workbench_access.py)：离线/隔离回归，验证当前合同。
- [docs/局域网查看卡片兼容修复.md](docs/局域网查看卡片兼容修复.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/网页卡片高清图像展示.md](docs/网页卡片高清图像展示.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/工作台后台运行与接口容错.md](docs/工作台后台运行与接口容错.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

本机HTTP服务、访问凭据和用户明确执行的操作；读取和写入语义独立。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../infrastructure/config/README.md)，共享状态合同见 [data](../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 归并后的完整项目范围

本目录同时拥有以下组件，各组件保留真实包名、公开接口、独立测试和逐文件说明。它们属于同一业务项目，不再占用根目录。

- `reading`：证据关联、阅读库资格与状态，说明见 reading/README.md。
- `read`：PDF解析和证据引擎，含几何依赖清单，说明见 read/README.md。
- `desktop_widget`：原生任务面板、实际并行格位与控制，说明见 desktop_widget/README.md。
- `environments`：原离线科学解析环境，不能启动本地模型。

## 2026-10-14 审核修复

完整复核、调整依据和验证限制见 [AUDIT_REVIEW.md](AUDIT_REVIEW.md)。

- [upload_storage.py](upload_storage.py)：上传暂存检查、跨进程锁、独占写入与失败清理；默认总额度1GiB、未绑定文件7天。`python -m workbench.upload_storage`默认dry-run，`--apply`才回收；上传时在同一锁内检查并回收。不新增常驻入口。任何未完成/失败导入引用均保护；成功导入只有归档原文哈希一致才回收临时文件。`upload_storage.max_bytes/ttl_seconds`可由宿主配置覆盖。当前共用访问口令，不虚构每用户配额。
- [tests/test_audit_regressions.py](tests/test_audit_regressions.py)：CSV前缀、暂存保护/额度、慢连接隔离、连续日志轮转回归。
- [tests/reader_latest_selection.cjs](tests/reader_latest_selection.cjs)：延迟A/B响应及关闭后请求失效，直接执行正式`showCard`实现。

HTTP头部握手使用独立64槽、2秒总期限和16KiB预算；完整头部才占16个业务槽。仍是本机/Tailscale有限入口，并非无限连接攻击下的可用性保证。CSV按文本展示中和危险前缀，不改变数据库值。新启动的工作台/worker通过reading公开日志接口持续轮转，单文件5MiB、保留3个历史段；既有进程需正常重载后生效。

2026-10-14：修正及其后继核验任务沿用core统一置顶标记和排序；界面仅显示真实优先级，不改变精读库完整循环准入条件。

### HTTP容量回归

[tests/test_workbench_access.py](tests/test_workbench_access.py) 的本地 fixture 禁用代理，每个空客户端确认进入真实握手后才创建下一个，避免将listen backlog当成活动握手。正常GET不重试；16个完整请求占满时验证503/Retry-After=2，释放后恢复200；永久槽位丢失负例不能通过容量恢复断言。生产服务器阈值、超时和身份合同不变。

2026-10-15：文献列表在“寻找相关文献”右侧提供“访达查看”，悬停显示路径。点击经认证的 `POST /api/reveal-local`（JSON仅含文献`id`），从目录记录选择原文，无原文时选择卡片，通过macOS `open -R`定位；拒绝客户端路径及多余字段，缺失文件返回404，非Mac返回400，系统命令超时10秒。不重试操作；远程访问时打开运行工作台的Mac上的访达。

## 文献标签与主题学习入口（2026-10-20）

顶部“标签与主题学习”进入 `/literature`，复用原工作台鉴权。`web.py` 仅将 `/api/literature/<operation>` 转交独立 [literature](../literature/README.md) 公开API；不增加服务、浏览器所有者或任务队列。该普通检索覆盖全部文献，精选/精读准入不变。前端资源由独立组件包提供，工作台新增 `paper-literature` 依赖。旧工作台进程正常重启后加载新路由，本轮不重载网页任务所有者。

2026-10-20：literature更新至0.2.0，页面改为运行一二级自动标注及批量自动处理。逐篇人工标注/确认已停用；集合角色/顺序/笔记继续独立。新依赖paper-literature==0.2.0，Python规则执行，无模型或网页附件。旧工作台需正常重启加载，未由本轮重启原网页任务所有者。

文献标签0.3.0：列表仅显示核心标签，详情保留辅助证据及上位分类；标签/集合筛选采用核心和继承分类。一级1～3、二级2～5为参考，不凑数或硬截；旧自动记录需显式重新运行，旧服务需正常重启加载新源码。本轮没有恢复网页任务或本地模型。见[literature](../literature/README.md)。

文献标签0.3.1：依赖方向规则1.2.0，新增同句证据归属与罗马数字章节；当前聊天每30分钟离线优化，规则状态和评测独立于工作台生产运行。不启动工作台或网页所有者来执行该评测。

2026-10-20：当前5篇手选根种子三版独立优选。`cards.seed_trials`由现有材料线程每60秒推进；逐版原文核验后只选择完整通过、至少85且无重大/缺材料的最高真实核验分，无合格版沿用原修正循环。原卡/回执/报告、固定槽位、暂停、未知与重试计数保留。`independent_request`仅为新准备材料的中性独立请求标识，写入原文上下文/实际提示并记录输入指纹；旧冻结包不改。旧百万优先级不作为质量分展示，优先身份独立标注。见[固定授权](/Users/xiaoyanhao/project/paper/infrastructure/docs/authorizations/20261020-manual-seed-three-candidates.md)。

文献标签0.4.0：受控词表41项，新增取向、溶液制备、电荷陷阱；HTTP及核心/辅助/继承筛选合同不变。方向规则1.3.0完成标签专项验证，但未通过全项目验收，不由本任务重载生产服务；首组新留出已使用，后续见literature/ITERATION.md。

第二轮标签0.4.0依赖当轮为候选声明：42项标签回归通过，但全项目独立制卡重试测试失败，未作为已验收版本发布，也未重启工作台。

第三轮候选依赖0.4.1 / 规则1.3.1：41项ID不变，显式自旋振动耦合与普通振电耦合分开；全项目检查完成前仍属候选。本任务不重启工作台。

第四轮依赖0.4.2 / 规则1.3.2：DFT名词单复数及optimization/optimisation匹配，原41项ID、核心/辅助/继承合同不变。当前验收状态见literature/ITERATION.md；本任务不重启服务。

第四轮离线验证结果：PASS，literature 0.4.2当前状态validated；全项目2422次执行。当前已验收规则directions-rules-1.3.2，没有新独立评测或工作台重启。

第五轮依赖0.4.3 / 规则1.3.3：当前方法操作引用既往步骤的有界判别，保留原核心/辅助/继承合同。证据可选procedure_reference保存判别依据；验收读literature/ITERATION.md，不由本任务重启服务。

第五轮离线验证结果：PASS，literature 0.4.3当前状态validated；全项目2427次执行。当前已验收规则directions-rules-1.3.3，没有新独立评测或工作台重启。

第六轮依赖0.5.0 / 规则1.4.0：42项词表，色谱与质谱降解产物分析需实际联合方法及正文产物关联证据。核心/辅助/继承合同不变，复合流程可用其科学目的判断核心性，但不能补造正文。当前验收状态见literature/ITERATION.md，不由本任务重启服务。

第六轮离线验证结果：PASS，literature 0.5.0当前状态validated；全项目2432次执行。当前已验收规则directions-rules-1.4.0，没有新独立评测或工作台重启。

标签1.4.0第二组10篇独立评测细标P45.16%/R28.00%：未改运行代码或依赖，不作可靠性提升声明；此前软件验收与科学泛化评测分开。未发布全库或重载服务，报告见literature/ITERATION.md。

第8轮离线候选literature0.5.1 / 规则1.4.1：摘要相邻结果指代与精确前句证据；接口依赖同步，三组已曝光开发回归，无新的独立评测，不重启工作台。

第8轮软件检查PASS，全项目2437次；最近已验收离线规则directions-rules-1.4.1，无新独立评测，不重启工作台。

第9轮候选1.5.0只作离线MR科学概念区分与简称评测，固定开发精确率退化，未替换当前依赖paper-literature0.5.1 / 规则1.4.1；候选证据隔离保留，未重启工作台、未发布全库。

第10轮候选literature0.5.3 / 规则1.4.3：有界摘要因果结果归属，42项词表不变；接口依赖同步。三组已曝光开发，无新独立评测，未重载工作台。第9轮MR1.5.0仍隔离。

第10轮最终1.4.3 / literature0.5.3，68项标签与全项目2444次检查PASS，已验收规则directions-rules-1.4.3；初版否定探针及回执保留，未重启工作台。

第11轮不改literature0.5.3 / 1.4.3，第三组首次独立评测一级P90.91/R64.52、二级P61.11/R40.74；参考先于预测，无事后调参。第四组封存，依赖与运行代码未改，未重启工作台。

第12轮离线候选literature0.5.4 / 1.4.4：旁支推测机制保留辅助而不进核心，显式研究目标及直接证据仍可核心。四组曝光开发，第三组二级精确率66.67/召回40.74，无新独立成绩；接口依赖同步，未重启工作台。

第12轮软件检查PASS，全项目2451次；最近已验收离线规则directions-rules-1.4.4。无新独立评测，未重启工作台或发布标签。

第13轮标签研发保留1.4.5词形候选：开发核心指标不变、增加2篇辅助方法证据，否定测量反例失败，未提升；当前依赖及源码仍literature0.5.4 / 1.4.4，无服务重载。见[报告](../reports/20261020-tagging-iteration-013.md)。

第13轮恢复的活动1.4.4工作区全项目2451次PASS；该结果不适用于失败的隔离1.4.5候选。依赖仍0.5.4，未重启或发布标签。

第14轮离线候选literature0.5.5 / 1.4.7：仅方法否定子句归属，未使用不记used，否定原句保留；四组曝光开发指标不变，无新独立结果。依赖同步，词形1.4.5未合入，未重载工作台。见[报告](../reports/20261020-tagging-iteration-014.md)。

第14轮最终离线1.4.7全项目2459次PASS；依赖literature0.5.5，初版1.4.6未提升。无新独立成绩，未重载工作台。

第15轮离线候选literature0.5.6 / 1.4.8：时间分辨词形采用现有否定守卫，91项测试通过；四组开发核心指标不变，2篇新增辅助证据，无新独立成绩。依赖同步，未重载工作台。见[报告](../reports/20261020-tagging-iteration-015.md)。

第15轮离线1.4.8全项目2467次PASS，依赖literature0.5.6；无新独立成绩，未重载工作台或发布全库标签。

第16轮离线候选literature0.5.7 / 1.4.9：明确方法主语的科学结果归因可核心，原证据不变；第三曝光开发补回1个正确细标，误标11不增，P67.65/R42.59，无新独立成绩。依赖同步，未重载工作台。见[报告](../reports/20261020-tagging-iteration-016.md)。

第16轮离线1.4.9全项目2475次PASS，依赖literature0.5.7；无新独立成绩，未重载工作台或发布全库标签。

第17轮离线候选literature0.5.8 / 1.4.10：方法使用完整词形及已有明确实验结果依据，阻断performance等误词干；106项回归通过，四组开发核心标签/指标不变，1条误准入证据原样归档，无新独立成绩。依赖同步，未重载工作台。见[报告](../reports/20261020-tagging-iteration-017.md)。

第17轮离线1.4.10全项目2482次PASS，依赖literature0.5.8；无新独立成绩，未重载工作台或发布全库标签。

第18轮literature0.5.8 / 1.4.10代码与依赖不改，第四组首次独立参考25/56先冻后预测；一级P88.24/R60.00、二级P60.00/R26.79，细标覆盖不足，无事后调参。第五组与50篇无重复并封存，未重载工作台。见[报告](../reports/20261020-tagging-iteration-018.md)。

第19轮离线候选literature0.5.9 / 1.4.11：引用作者的紧邻被动表征不作本文主题/方法，证据留mentions并校验原前句。115项标签通过，五组曝光开发中第四组两级各少1个误标，正确及漏标不变；无当前独立成绩，第五组封存。依赖同步，未重载工作台。见[报告](../reports/20261020-tagging-iteration-019.md)。

第19轮1.4.11已通过离线全项目2493次检查，依赖literature0.5.9；五组开发，无当前独立成绩，未重载工作台或发布全库。

第20轮离线候选literature0.5.10 / 1.4.12：一级标题beyond局部比较命中只作提及，独立标题/摘要依据保留，弱证据即使同标签已准入也保留原句。125项标签通过，五组曝光开发核心指标全部不变；一条标题依据转提及，摘要泛化动作词干问题未解决。无当前独立成绩，第五组封存。依赖同步，未重载工作台。见[报告](../reports/20261020-tagging-iteration-020.md)。

第20轮1.4.12已通过离线全项目2503次检查，依赖literature0.5.10；五组开发核心指标未改善，无当前独立成绩，未重载工作台或发布全库。

第21轮离线候选literature0.5.11 / 最终1.4.14：只收紧元信息摘要及其前句develop词形，原fulltext规则保留；初版1.4.13二级退化留档未提升。136项标签通过，第四曝光开发一级FP1→0、正确/漏标不变，所有二级输出原样。无当前独立成绩，第五组封存。依赖同步，未重载工作台。见[报告](../reports/20261020-tagging-iteration-021.md)。

第21轮最终1.4.14通过离线全项目2514次检查，依赖literature0.5.11；初版1.4.13退化留档，最终一级去1误标、二级基线保留，无当前独立成绩，未重载工作台或全库发布。

第22轮保持literature0.5.11 / 1.4.14代码与依赖不改，第五组26/58参考及85条原句先冻后预测：一级P83.33/R57.69，二级P59.09/R22.41，细标覆盖仍不足，无事后调参。第六组与60篇无重复且封存；未重载工作台。见[报告](../reports/20261021-tagging-iteration-022.md)。

第23轮离线候选依赖literature0.5.12 / 1.4.15：书目结构覆盖错误章节归属，保留精确条目为提及，真实独立方法保留；六组开发去掉1个二级误标，TP/FN不变，无新独立成绩，第六留出封存。依赖同步，未重载工作台。见[报告](../reports/20261021-tagging-iteration-023.md)。

第23轮1.4.15已通过离线全项目2521次检查，依赖literature0.5.12；六组开发去1二级误标、TP/FN不变，无新独立成绩，未重载工作台或全库发布。

第24轮初版离线候选依赖literature0.5.13 / 1.4.16（该候选及依赖未提升）：同块书目残段组合结构与精确追踪，152项标签通过，六组开发核心指标不变，仅清除辅助污染，无新独立成绩，第六留出封存。未重载工作台。见[报告](../reports/20261021-tagging-iteration-024.md)。

第24轮最终候选1.4.17虽154项局部测试通过，但固定开发丢1个正确二级标签，已隔离保留，工作台依赖恢复paper-literature==0.5.12，活动规则1.4.15。无新独立成绩，第六留出封存，未重载工作台。

第24轮恢复活动literature0.5.12 / 1.4.15通过全项目2521次及静态/全局联动检查；候选1.4.17科学退化隔离保留，未重载工作台，无新独立成绩，第六留出封存。

第25轮离线候选依赖literature0.5.13 / 最终1.4.19：仅效率滚降复合词写法/单复数，初版1.4.18词间空白退化留档；155项局部通过，六组开发补回2个二级正确核心、误标不增。多空白及旧书目问题仍保留，无新独立成绩，第六留出封存，未重载工作台。见[报告](../reports/20261021-tagging-iteration-025.md)。

第25轮最终1.4.19 / literature0.5.13通过离线全项目2533次及静态/全局联动；六组开发补2正确二级核心、误标不增，初版1.4.18退化留档，无新独立成绩，第六留出封存，未重载工作台或全库发布。

第26轮离线候选依赖literature0.5.14 / 1.4.20：问题泛指背景不累计核心投票，证据仍保留；167项局部通过，六组开发对象/指标不变，旧1.4.18组件误标回放降辅助不计新成绩。无新独立评测，第六留出封存，未重载工作台。见[报告](../reports/20261021-tagging-iteration-026.md)。

第26轮1.4.20 / literature0.5.14通过离线全项目2545次及静态/全局联动；六组当前指标/对象不变，已用旧组件误标回放降辅助不计独立成绩。第六留出封存，未重载工作台或全库发布。

第27轮离线候选依赖literature0.5.15 / 1.4.21：仅限定词多空白，42ID不变；177项局部通过，六组核心指标不变，新增辅助证据及历史提及各1条。无新独立结果，第六留出封存。见[报告](../reports/20261021-tagging-iteration-027.md)。

第27轮1.4.21 / literature0.5.15通过离线全项目2555次及静态/全局联动；六组核心指标不变，辅助证据与历史提及各新增1条，第六留出封存，无新独立结果，未重载工作台或全库发布。

第28轮评测已通过离线检查：固定literature0.5.15 / 1.4.21，第六组单次一级P80/R30.77/F144.44、二级P62.5/R40.98/F149.5；源码/精确依赖不改，未重载。第六组已用、第七组封存。见[报告](../reports/20261021-tagging-iteration-028.md)。

第29轮依赖候选literature0.5.16 / 1.4.22：仅摘要首次被动结果主语，189项局部通过；七组开发补1个正确一级、误标不增，二级不变。1.4.21独立结果转历史，1.4.22无独立成绩，第七组封存，未重载。见[报告](../reports/20261021-tagging-iteration-029.md)。

第29轮1.4.22 / literature0.5.16通过离线全项目2567次及静态/全局联动；七组开发增加1个正确一级、误标不增，二级不变。独立成绩当前为空、1.4.21仅历史，第七组封存；工作台未重载、未全库发布。

第30轮依赖候选literature0.5.17 / 1.4.23：仅增一级圆偏振发光受控全称，词表43ID、旧42项不改。202项局部通过，七组开发补1个正确一级、误标不增、二级不变；同义评价对应预先公开冻结，原gold不改。无当前独立成绩，第七组封存，未重载。见[报告](../reports/20261021-tagging-iteration-030.md)。

第30轮1.4.23 / literature0.5.17通过离线全项目2580次及静态/全局联动；七组开发补1个正确一级、误标不增、二级不变。对应公开预先冻结、gold不改，无新独立成绩，第七组封存；未重载工作台或全库发布。

第31轮依赖候选literature0.5.18 / 1.4.24：仅增一级机器学习分子逆向设计受控方向，词表44ID、旧43项不改。216项局部通过，七组开发补1个正确一级、误标不增、二级不变；同义评价对应预先冻结，原gold不改。无当前独立成绩，第七组封存，未重载。见[报告](../reports/20261021-tagging-iteration-031.md)。

第31轮1.4.24 / literature0.5.18通过离线全项目2594次及静态/全局联动；七组开发补1个正确一级、误标不增、二级不变。评价对应先冻结、gold及旧对应保留，无新独立成绩，第七组封存，未重载或全库发布。

第32轮评测已通过离线检查：固定literature0.5.18 / 1.4.24第七组单次独立一级P78.95/R55.56/F165.22、二级P42.31/R21.15/F128.21；科学源码/测试/精确依赖不改，二级分类不足，未重载。第七组已用、第八组封存。见[报告](../reports/20261021-tagging-iteration-032.md)。

第33轮依赖候选literature0.5.19 / 1.4.25：仅补联合LC/GC-MS降解产物结果句实际使用，核心/词表/来源规则不扩张。227项局部通过，八组80篇开发补1个正确二级、误标不增、一级不变。无新独立成绩，1.4.24仅历史，第八组封存。未重载，见[报告](../reports/20261021-tagging-iteration-033.md)。

第33轮literature0.5.19 / 1.4.25通过离线全项目2605次与静态/全局联动；八组开发补1个正确二级、误标不增、一级不变，无新独立成绩，第八组封存；精确依赖同步，未重载。

第34轮依赖候选literature0.5.20 / 1.4.26：只处理带期刊/年份上下文的Soc.误作SOC，保留原句消歧回执。239项局部通过，八组80篇开发减少1个二级误标、TP/FN/一级不变；另去除3个辅助同类误识，无新独立成绩，第八组封存。未重载，见[报告](../reports/20261021-tagging-iteration-034.md)。

第34轮literature0.5.20 / 1.4.26通过离线全项目2617次及静态/全局联动；八组开发减少1个二级核心误标、TP/FN及一级不变，无新独立成绩，第八组封存；精确依赖同步，未重载。

第35轮离线评测检查完成：固定literature0.5.20 / 1.4.26第八组单次独立一级P87.50/R46.67/F160.87、二级P81.25/R22.81/F135.62；科学源码/239项测试/精确依赖不改，漏标仍明显，未重载。第八组已用、第九组封存。见[报告](../reports/20261021-tagging-iteration-035.md)。

第36轮依赖候选literature0.5.21 / 1.4.27：受控host-for-OLED材料角色别名与精确回执，旧别名/全部二级/核心排序不改。251项局部通过，九组90篇开发补回2个一级正确核心，误标不增；无当前独立成绩，第九组封存。精确依赖同步，未重载，见[报告](../reports/20261021-tagging-iteration-036.md)。

第36轮literature0.5.21 / 1.4.27通过离线全项目2629次及静态/全局联动；九组开发补回2个一级正确核心、误标不增、全部二级不变，无当前独立成绩，009封存；精确依赖同步，未重载。

第37轮依赖候选literature0.5.22 / 1.4.28：现有发射偶极取向明确短语别名，核心/来源/旧别名/方法策略不改。263项局部通过，九组90篇开发补回1个二级正确核心、误标不增；无当前独立成绩，009封存。精确依赖同步，未重载，见[报告](../reports/20261021-tagging-iteration-037.md)。

第37轮literature0.5.22 / 1.4.28通过离线全项目2641次与静态/全局联动；九组开发补回1个二级正确核心、误标不增、一级不变，无当前独立成绩；009封存，精确依赖同步，未重载。

五轮试验1/5，第38轮候选directions-rules-1.4.29 / 0.5.23：激子增殖与高能激子利用主题覆盖。90篇已曝光开发，局部270项通过；旧gold/输入/原对应保留，新同义对应先冻结，未开009，无新独立成绩。见[报告](../reports/20261022-tagging-iteration-038.md)。 精确依赖已同步，未重载。

五轮试验2/5，第39轮候选directions-rules-1.4.30 / 0.5.24：溶液多层成膜的溶剂正交与膜层耐溶剂覆盖。90篇已曝光开发，局部276项通过；旧gold/输入/原对应保留，新同义对应先冻结，未开009，无新独立成绩。见[报告](../reports/20261022-tagging-iteration-039.md)。 精确依赖已同步，未重载。

五轮试验4/5，第41轮候选directions-rules-1.4.32 / 0.5.26：光学出耦的主题、问题、模型和角分辨测量覆盖。90篇已曝光开发，局部288项通过；旧gold/输入/原对应保留，新同义对应先冻结，未开009，无新独立成绩。见[报告](../reports/20261022-tagging-iteration-041.md)。 精确依赖已同步，未重载。

五轮试验5/5，第42轮候选directions-rules-1.4.33 / 0.6.0：跨页重复页眉与正文科学证据分离，复核保留的主体细标。90篇已曝光开发，局部310项通过；旧gold/输入/原对应保留，新同义对应先冻结，未开009，无新独立成绩。见[报告](../reports/20261022-tagging-iteration-042.md)。 精确依赖已同步，未重载。

2026-10-22本次5轮完成（历史第38～42轮）：1、2、4、5采用，第3轮候选因重复页眉误标保留未采用。当前1.4.33/v19/0.6.0；90篇开发一级P/R/F1=89.70/62.98/74.00%，二级=62.81/32.48/42.82%，二级空白仍14/89。新10篇009先冻结24/49个参考再比较前后规则，一级F1=57.14%、二级=41.67%，前后完全相同；已标已用，不再调参。本轮310局部、2693次项目执行及静态/全局/报告门通过。010另取10篇，与已用100篇无身份重叠，正文未读、无gold/预测。详见[五轮实测汇总](../reports/20261022-core-directions-five-rounds.md)。 工作台精确依赖仍paper-literature==0.6.0，未重载或全库发布。

2026-10-22：一级标签独立后台（paper-literature==0.6.0）。[web.py](web.py)在`/api/state`返回只读`literature_level1`，新增认证的`POST /api/literature-level1/control`严格接收`{paused:bool}`；[workbench.html](workbench.html)单列一级进度、无法判断/失败、并行8及实际在途数、独立暂停/启动。[desktop_widget/snapshot.py](desktop_widget/snapshot.py)同样只读此API；启动不调用四队控制，不触及网页/模型。二级保持不启动。授权见[一级后台](../infrastructure/docs/authorizations/20261022-level1-background.md)。


2026-10-23全库二级标签：通过literature.api的level2_status/control提供独立“二级标签”任务与暂停/开始，8进程、原文合格检查/有核心/无法判断/待处理/失败/等待原文/来源阻断分别显示。快照仅只读状态文件，页面读取不建侧库、不启动后台。原生TaskPanel调用专用literature.background_level2 CLI，不通过原四任务启动器，不恢复其他暂停；HTTP工作台无需为此自动启动。详见[全库二级授权](../infrastructure/docs/authorizations/20261023-level2-background.md)。

文献工作台顶部“手选卡片”可打开已登记手选根种子的同源成品和结构候选。候选卡在列表和正文标明核验状态。主配置启用 `workbench_passwordless`。本机与经 Tailscale Serve 提供用户身份的设备直接打开启动器显示的普通地址。操作请求检查同源 Origin。
