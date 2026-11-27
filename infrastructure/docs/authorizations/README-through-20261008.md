# 文献阅读工作台

统一入口连接 `crawler` 的检索能力和 `read` 的本地图式阅读器；`article` 原有探索界面与数据仍保留。检索筛选与制卡使用当前 Ollama 的 `gemma4:31b`；人工发起的卡片质量评审通过已有 `web_gpt` 工具调用网页版 ChatGPT，见 [网页版评审接入](docs/网页版评审接入.md)。

## 启动

已接入固定版本 fetchpdf 作为公开 PDF 多来源后备获取器，安装在独立环境；详情见 [PDF获取器接入](docs/PDF获取器接入.md)。有原文后自动重新筛选。Unpaywall 未配置联系邮箱时跳过，不读取学校登录会话。

手动下载后可点击工作台顶部“批量导入 PDF”，一次选择多个文件。首页 DOI 与完整题名能唯一匹配时自动归档，无法确定的文件在结果栏选择对应论文并确认。重复 PDF 跳过；逐篇导入入口仍保留。公开获取先尝试书目直链，再调用 fetchpdf 多来源回退和网页解析；无结果或连接错误不代表需要付费或认证。

双击 [启动文献工作台.command](启动文献工作台.command)。启动器使用 `/Users/xiaoyanhao/venv/bin/python`。允许时段内的本地模型任务按需复用 read 的 Ollama 启动脚本；打开网页本身不会在夜间启动模型。默认工作台地址 `http://127.0.0.1:8767`。

重复启动会打开已经运行的工作台，不再创建第二个服务。若端口被其他应用占用，可运行 `./启动文献工作台.command --port 8768`。

启动脚本也会通过 Tailscale Serve 配置独立的远程 HTTP 端口（默认 8768），并打印 Mac Pro 工作台访问链接。地址为 `http://mac-studio.tail1569a7.ts.net:8768`；登录需使用启动器打印的完整访问链接（包含口令片段）或输入本次口令。口令在网页服务新进程启动时更新；重复打开已有服务复用当前口令，未登录不能读取编目、原文或卡片；登录后也能执行工作台操作。Mac Pro 需接入同一 tailnet，Studio 的网页服务需保持运行。原有 Tailscale 8443 服务保持原配置。可在配置中关闭 `tailscale_enabled` 或调整 `tailscale_port`；远程端口已用于其他服务时不会覆盖它。

列表中的“核心结论”由本地 `gemma4:31b` 生成。已有 PDF 时提取文字层，超过 18000 字符则取前 12000 与后 6000 字符；没有 PDF 时使用 API 摘要。输入同时提供种子的标题与摘要。显示依据范围，保存模型、输入哈希及原始输出；校验引用是否出现在输入文字中。该校验不保证每条中文结论都正确，也不代表完成图片、公式或全文核验。

```bash
cd /Users/xiaoyanhao/project/paper
./启动文献工作台.command
```

首次启动登记种子并排队导入本地 PDF。持续检索覆盖期刊/种子关联、arXiv、ChemRxiv；检索、4 个直链下载进程和 2 个慢速全文回退进程独立调度。成功页与游标持久化，来源限流到期再试，模型阅读积压不会阻塞拉取。获取队列和慢速回退都有容量上限；无可核验 PDF 不作为已获取候选。使用下方 `fetch-start` 可让 Python 服务脱离网页、终端和 Codex 持续工作；机器关机后需重新启动。详情见 [持续拉取通道](docs/持续拉取通道.md)。点击“选为精读”后调用原 read 处理器制作图像、公式卡片。

工作台包括待筛选、精读库、种子与勘误、获取待办、全部文献和任务列表。列表显示核心结论、证据范围与推荐理由。需学生认证的论文先打开出版社页面，完成认证并下载，再在对应论文上“导入已下载 PDF”。手动导入表示你确认此文件对应这篇论文；程序仍验证它是可解析 PDF。

选约 3 篇是建议数量，不是硬性限制。少量自动制卡规则：期刊优先、近期发表加分、相对已有背景的新颖贡献加分；必须有相关性和可核对的全文证据。首轮最多自动选 1 篇，每个跨轮次去重的 100 篇窗口最多 2 篇，允许 0 篇。自动选入会保留评估依据，不覆盖人工决定。初始期刊清单是可修改的项目优先列表，不是实时 JCR/中科院分区。

## 存储和配置

配置：[config/first_round.json](config/first_round.json)。路径可以调整；密钥只通过环境变量传入。

| 内容 | 位置 |
| --- | --- |
| 种子输入 | `/Users/xiaoyanhao/Desktop/文献暂存` |
| 普通 PDF、检索原始响应 | `/Volumes/ssd-1t-1/paper-library` |
| 统一 SQLite 与任务日志 | `data/catalog.sqlite3`、`data/logs` |
| 精读 PDF、解析、图片公式、卡片 | `data/deep_read/<稳定论文 ID>/` |
| 手动上传暂存 | `data/uploads` |
| 旧项目映射与探索历史快照 | `data/legacy` |

归档目录只在配置的外置盘确实挂载时创建；未挂载的任务进入 waiting_storage，连接后点击重试。精读复制原文到 Studio 并校验完整 SHA256，此后原文与卡片可以脱离 SSD 使用。外置盘归档副本继续保留，不自动删除。旧 read 卡片直接只读引用，第一次重跑精读才写入新 Studio 目录；旧来源文件不覆盖。

API 配置可选：`OPENALEX_API_KEY`、`S2_API_KEY`。无 key 访问可能限流；单源异常会记录告警，降级为另一个来源，不将异常当作正常空结果。首轮仅扩一跳，以引文、关键词检索与词项相关性筛选候选，不使用 embedding。

## 命令行

以下命令使用 Python 3.10+，建议使用当前 read 环境。`--config` 必须放在子命令前。

```bash
/Users/xiaoyanhao/venv/bin/python -m pipeline init
/Users/xiaoyanhao/venv/bin/python -m pipeline migrate
/Users/xiaoyanhao/venv/bin/python -m pipeline discover
/Users/xiaoyanhao/venv/bin/python -m pipeline worker
/Users/xiaoyanhao/venv/bin/python -m pipeline serve --no-browser
/Users/xiaoyanhao/venv/bin/python -m pipeline status
/Users/xiaoyanhao/venv/bin/python -m pipeline fetch-start
/Users/xiaoyanhao/venv/bin/python -m pipeline fetch-status
/Users/xiaoyanhao/venv/bin/python -m pipeline fetch-stop
/Users/xiaoyanhao/venv/bin/python -m pipeline repair-reading --dry-run
/Users/xiaoyanhao/venv/bin/python -m pipeline repair-reading
/Users/xiaoyanhao/venv/bin/python -m pipeline reading-contracts
/Users/xiaoyanhao/venv/bin/python -m pipeline reading-start
/Users/xiaoyanhao/venv/bin/python -m pipeline reading-status
/Users/xiaoyanhao/venv/bin/python -m pipeline reading-stop
/Users/xiaoyanhao/venv/bin/python -m pipeline model-schedule
/Users/xiaoyanhao/venv/bin/python -m pipeline model-schedule --start 12:00 --end 23:00
/Users/xiaoyanhao/venv/bin/python -m pipeline model-schedule --allow-minutes 60
/Users/xiaoyanhao/venv/bin/python -m pipeline model-schedule --reset
/Users/xiaoyanhao/venv/bin/python -m pipeline select PAPER_ID deep_read
/Users/xiaoyanhao/venv/bin/python -m pipeline import PAPER_ID /absolute/path/paper.pdf
```

`init` 登记种子并排队本地原文导入。`migrate` 只读旧数据，保留旧 ID 别名、已选记录、反馈与探索完整快照；可重复运行，不自动将历史论文全部加入当前候选或制卡。`discover` 只排队，`worker` 执行到队列为空；`serve` 运行本机界面与后台监督程序。`fetch-start` 启动独立的持续拉取服务，仅获取原文并排队筛选；不启动模型。重复执行复用现有服务，`fetch-stop` 请求正常停止；队列保留。已有持续拉取时，`serve` 复用拉取服务并单独监督阅读通道；关闭网页只停止它管理的阅读监督，持续拉取继续工作。

队列持久化，文件锁覆盖 worker 整个运行期。拉取、初筛（screen/auto_select）、制卡（read/deep_read）三条 lane 可并行，单 worker 兼容模式与三条 lane 互斥；同一 lane 不能重复启动。监督进程与 lane 之间持有管道，监督进程意外退出时 lane 及其活动子进程停止。关停或异常中断后的 running 任务在下一次 worker 启动时恢复，拉取任务按次数限制自动重试；阅读的 failed/partial 按次数及延迟恢复，失败任务保留可见。`repair-reading` 同时持有初筛及制卡通道互斥锁，按新政策一次性恢复旧失败；不会启动模型或网页评审。任务和错误记录保留。已保存初筛输入哈希、PDF 和阅读卡片会复用。精读重试优先沿用已完成的 Figure/Equation，历史 JSON/Markdown 保存副本。部分完成的卡片不会冒充全部成功。元数据、图、公式分别记录状态并重试；合同版本以 `pipeline/reading_contract.py` 为准。已评审卡片保留，来源变动时要求重新核对。网页评审闸门同时核对完成状态、版本、原文/卡片哈希及截图存在性。

本地模型默认每天 **00:00–10:00（Asia/Shanghai）暂停**，10:00自动恢复；时段外任务保留排队，不消耗失败次数。跨入禁止时段会停止推理进程及子进程，把原任务放回队列。手动选入精读、重新评估或重试仍受限制。工作台“本地模型运行时段”可设置 10:00–24:00 内更窄的每日窗口，或明确临时放行若干分钟；放行到期自动恢复限制，保存每日时段会撤销临时放行。`reading-start` 启动脱离网页/终端的 Python 阅读监督，初筛与制卡各有独立 worker；网页会复用它，关闭网页不停止这个独立服务。`reading-stop` 停止两个阅读通道，拉取继续。配置与验收见 [模型时段与并联队列](docs/模型时段与并联队列_20261006.md)。

初筛引文未通过核验时，保留模型结论、相关性和原始响应供人工核对，清空可展示引文，明确标记未核验并禁止自动选入。字段格式错误仍使任务失败；文字匹配不等于科学结论已经验证。

程序退出码：成功 0；错误 1；命令格式错误 2；中断 130。后台单项失败保存在任务中，不导致 worker 停止处理其他任务，需在状态/界面检查实际结果。

## 验证

```bash
python3 -m unittest discover -s tests -v
```

覆盖身份补全、冲突 DOI、跨来源身份冲突、重启恢复、人工决定保护、自动选入限额、年份加分、未挂载盘、资产校验及错误证据。实际网络与模型结果见 [docs/重构验收记录.md](docs/重构验收记录.md)，不把离线测试等同于阅读质量验收。

## 当前限制

- 首轮为可使用的获取/筛选/图式阅读闭环；知识图谱、专题数值提取、训练数据集暂未实现。
- 公开 PDF 自动获取优先 API 提供的直链，复杂出版社网页未做逐站浏览器适配。401/403 标为需检查访问，不一概断言需要学生认证。
- 扫描 PDF 暂需 OCR；首轮校验会明确报错，不生成无证据的阅读卡片。
- 本地初筛超长论文使用头尾节选，并明确标示遗漏中间正文；图式精读沿用 read 的证据定位能力，不能视为无遗漏全文精读。
- Word 种子材料是阅读笔记，只有 DOI/题名用于发现，不被当作论文原文。
- 期刊优先表与新颖性评估需用真实 OLED 样本持续校准，不承诺识别世界首创。
- 现有 article 的独立旧入口仍沿用它原有的网页 GPT 功能；质量评审命令复用其调用适配层。普通后台制卡不发送材料到网页 GPT。当前四类样本按根 AGENTS.md 的明确授权持续送往专用 Chrome 的 ChatGPT 网页版，材料限净化原文 PDF、实际卡片 JSON、图式截图和评审提示。正式落盘的 partial/needs_review 也作诊断送审；每个卡片哈希一次，提交不确定时先核对原会话。历史回执保留供核对。

后台修复与平滑升级见 [后台平滑升级](docs/后台平滑升级.md)，当前升级状态以工作台心跳和 data/handover.json 为准。

精读库可“设为种子”，加入后续关联搜索基准；更多操作可移出。说明见 [种子库管理](docs/种子库管理.md)。

精读中的原图、PDF 组合/整页截图、公式 LaTeX 与宏保留规则见 [图式证据双份保留](docs/图式证据双份保留.md)。

本轮三类真实网页评审、v4 修复和后台复审状态见 [卡片质量迭代记录](docs/卡片质量迭代记录.md)。

2026-10-06 首批独立审计修复、故障回归与剩余风险见 [审计首批修复记录](docs/审计首批修复_20261006.md)。

2026-10-06 拉取端集中修复、真实网络验证和 Python 持续服务运行证据见 [拉取端修复记录](docs/拉取端修复_20261006.md)。

2026-10-06 元数据重试、公式身份、完成合同、历史失败恢复及工作台认证修复见 [审计后续修复记录](docs/审计后续修复_20261006.md)。


03:10 新旧审计合并整改见 [整改清单与验收](docs/新旧审计合并整改_20261006.md)。新生成卡片使用 v9 完成合同，校验非空证据、候选覆盖及截图哈希；真实评审过的卡片按收取记录保护。`python -m pipeline remake PAPER_ID` 排队复用/恢复；明确 `--force` 才覆盖已评审或已完成卡片，先保留完整 history。运行时间限制仍有效。实际配置在 `config/first_round.json`，声明性目标在 `config/policy_specification.json`。旧完成日志/raw 七天后可压缩保留，人工评审及科学证据不自动删除。


## 12:46审计整改运行约束

拉取目标最多6次自动尝试，同一URL最多3次；身份错误、HTML、TLS证书及无效请求为确定性URL失败，访问限制单独记录。新链接/新版本改变指纹后可恢复，人工获取可显式重试。SQL存储约束仅用于让旧存活worker不能覆盖新子进程的终态与退避；权威规则在pipeline/fetch_policy.py，版本部署不重置退避。local_maintenance只执行有界领域再评估及auto_select，不调用模型或网络。初筛与制卡仍各有一个并联worker。

核心状态：done表示实际产物完成；deferred表示获取未成功且等待策略；needs_manual表示达到目标终态；needs_review表示生成合同未通过。warning是诊断说明，不能单独决定成功。卡片结构及哈希完成不等于科学评分通过。评审授权必须显式保存在数据库，未知状态、缺授权、缺账本均阻断。

UNPAYWALL_EMAIL可设置真实研究联系邮箱（或pdf_retrieval.contact_email）。缺失时公开其他来源仍工作，页面报告该来源未启用；程序不猜测或冒用邮箱。流水线现用fetch_pipeline，旧discover分支仅兼容离线旧调用；pdf_attempt_limit、reading_queue_limit及daily_schedule的旧参数不控制当前fetch并发。

网页列表按100条分页，搜索由服务器执行；旧初筛显示为待更新。批量更新通过显式有界迁移，不因提示词版本变更重推全库。原始书目、论文、评审及卡片history须保留，诊断归档每次最多100项。不会删除历史孤儿图式，可通过本地备份归档释放活动目录；科学原文和评审不进入Git。

旧quality_iteration监听已收编为incremental_review兼容入口；本机循环使用macOS kqueue，跨平台可用本地检查而非启动旧监听。测试运行不调用真实模型、真实出版商或外部评审。

12:46 独立审计 F01–F30 的整改、部署与验证证据见 [独立审计整改记录](docs/独立审计1246整改记录_20261006.md)。`pipeline.local_maintenance` 在原拉取服务旁运行，仅负责持久重试策略、范围重检、自动选入与有界诊断归档，不调用模型。

## 桌面任务面板

双击[启动任务面板.command](启动任务面板.command)，原生macOS小窗每3秒显示制卡图式进度、初筛、拉取、网页版评审及question综述任务。图钉切换置顶，关闭窗口后可从菜单栏重开；退出面板不会停止后台任务。说明见[desktop_widget/README.md](desktop_widget/README.md)。


用户明确暂停通过 `pipeline.model_schedule.set_user_pause(config, True, reason)` 持久保存到目录中的 `local-model-control.json`；它优先于时段和临时放行，`reading-start` 返回 `paused`，不启动 worker、不恢复队列。只有用户明确恢复后才可调用 `set_user_pause(config, False)`，恢复仍受10:00–24:00限制。暂停本地模型不影响文献拉取及既有网页版报告收取。原任务保留，精读恢复载荷为 `resume=true`，只复用同源同输入指纹检查点。

用户暂停拉取时，Catalog 目录中的 `fetch-control.json` 持久保存暂停，工作台查看和后台重启不会恢复；状态为 `paused_by_user`。须在用户明确恢复后解除，详见[持续拉取通道](docs/持续拉取通道.md)。
