# 原生任务面板

Swift面板、四任务快照、20×5真实格位、控制请求、启动入口发现与卡片模板展示。

这是独立源码与接口文件夹，正式包名为 `desktop_widget`。跨项目只调用 `desktop_widget.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

保留原生面板及固定构建位置，当前运行实例依赖这些接口。状态读取只显示真实任务与观测，控制交给core；不把预留页或缓存busy当作实际生成。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from desktop_widget.api import snapshot
```

运行依赖：[browser](../../infrastructure/browser/README.md)、[core](../../infrastructure/core/README.md)、[correction](../../correction/README.md)、[review](../../review/README.md)。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project desktop_widget
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [TaskPanel.swift](TaskPanel.swift) | 原生任务面板与按钮 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |
| [control.py](control.py) | Pause an existing isolated model group using the pipeline control contract. | `pause` | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [snapshot.py](snapshot.py) | Read-only shared project status; fetch and web cards are permanent categories. | `read`、`alive`、`projects`、`command_files`、`upload_issue`、`row`、`db_rows`、`paper_rows`、`question_rows`、`snapshot` | 当前公开接口或生产链使用；避免复制实现 |
| [page_grid.py](page_grid.py) | Read-only 20-page display; the four queue rows are stored assignments. | `_read`、`_fresh`、`_recent_health`、`_dict`、`_canonical_queue`、`_catalog`、`_selection`、`page_grid` | 当前公开接口或生产链使用；避免复制实现 |
| [render_card_template.mjs](render_card_template.mjs) | 卡片模板发布工具 | 静态资源 / 声明 / 执行入口 | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [tests/test_panel_boundaries.py](tests/test_panel_boundaries.py)：独立20×5格只读、陈旧busy不冒称生成、模型组暂停边界与缺失数据库读取测试。
- [tests/test_page_grid_upload_cooldown.py](tests/test_page_grid_upload_cooldown.py)：退避保留原格位；新鲜登录证据显示原固定槽位及等待登录，陈旧观测不冒称实时登录状态。
- [tests/__init__.py](tests/__init__.py)：独立测试发现入口。

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

原观察器的同所有者/同窗口新鲜`login_required`证据优先显示“等待手动登录”和原固定槽位，即使页池健康检查因人工门暂停而陈旧；格位仍保留保护颜色，不关闭或跳转页面。通道警告展示原后台登记的具体登录原因及槽位。旧证据仍显示待观测，面板不会据此登录、清除暂停或开始发送。

读取状态及用户明确按按钮后的控制/启动；读取本身不恢复暂停。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../../infrastructure/config/README.md)，共享状态合同见 [data](../../infrastructure/data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 当前物理布局与刷新（2026-10-14）

TaskPanel启动/并行设置使用infrastructure/environments/web/bin/python，模板使用infrastructure/docs/文献卡片模板.html，模板按钮绑定workbench/commands/启动文献工作台.command。快照启动入口扫描排除environments、dependencies、cache和面板自身，避免遍历运行环境；业务数量仍读取原事务与真实网页观测。

2026-10-14：快照沿用core统一排序，为已通过原核验的修正及待核验后继添加“置顶”标识；保持四任务分类和原顺序，原记录、评分及真实状态不改写。

2026-10-15：20×5 格新增核验上传失败退避展示。冷却中的未领取核验材料仍占原格位并保留标题/原入队顺序，仅 `runnable=false` 与明细“上传失败退避中，稍后自动恢复原排名”；材料清单读不到或策略记录损坏时标为待核对并拒绝新领取。面板只读 `browser.upload_retry_policy` 的公开出口，不建表、不分配、不移动、不释放任何页面或回执。

2026-10-20：当前5篇手选根种子三版独立优选。`cards.seed_trials`由现有材料线程每60秒推进；逐版原文核验后只选择完整通过、至少85且无重大/缺材料的最高真实核验分，无合格版沿用原修正循环。原卡/回执/报告、固定槽位、暂停、未知与重试计数保留。`independent_request`仅为新准备材料的中性独立请求标识，写入原文上下文/实际提示并记录输入指纹；旧冻结包不改。旧百万优先级不作为质量分展示，优先身份独立标注。见[固定授权](../../../paper/infrastructure/docs/authorizations/20261020-manual-seed-three-candidates.md)。

2026-10-22：[snapshot.py](snapshot.py)通过literature.api.level1_status只读新增“paper · 一级标签”，显示全库进度、无法判断、失败、并行上限8和实际在途数。[TaskPanel.swift](TaskPanel.swift)的该组按钮独立调用literature.background的--start/--pause，保留其他四队启停路径；不调用模型/浏览器，也不把一级在途数计入20页池。不存在状态文件时不显示虚构任务。依赖paper-literature==0.6.0。验证见[任务面板测试](../tests/test_desktop_widget.py)及[literature后台测试](../../literature/tests/test_level1_background.py)。


2026-10-23全库二级标签：通过literature.api的level2_status/control提供独立“二级标签”任务与暂停/开始，8进程、原文合格检查/有核心/无法判断/待处理/失败/等待原文/来源阻断分别显示。快照仅只读状态文件，页面读取不建侧库、不启动后台。原生TaskPanel调用专用literature.background_level2 CLI，不通过原四任务启动器，不恢复其他暂停；HTTP工作台无需为此自动启动。详见[全库二级授权](../../infrastructure/docs/authorizations/20261023-level2-background.md)。

2026-10-23：2026-10-23：渐进重启旁增加“仅手选种子”开关，调用core.seed_focus CLI，默认关闭；Snapshot.seedOnly兼容可选字段。新增手选追踪分类、3小时停滞行与顶部警示数量，20秒刷新只读。trace完整科学及生产合同完成后才结束活动追踪，证据仍保留。

面板左栏「paper · 公式整理」读取[OLED 行间公式项目](../../../tools/oled-formulas/oled_formulas/README.md)的队列进度，也支持已登记的两篇临时聊天测试。开关表示是否允许该测试运行，旁边显示实际阶段。上传前受阻可重试；已有发送意图的同批回执只收取原临时聊天。结果详情读取本批次的 status.json 和 formulas.jsonl。

公式自动队列使用同一面板开关，显示待排、已收取、待核对批数及实际阶段，结果指向自动队列输出目录。

[formula_window.py](formula_window.py) 将公式唯一所有者的 window-observation.json 与原槽位登记、同一会话回执和当前操作对应。公式整理详情显示 01–20 号页、生成/空闲/图片异常/待观测数量及可展开的状态说明，悬停可查看批次、上海时间。只使用 60 秒内同一窗口和存活所有者的完整网页观测；图片告警可叠加于生成、待收、空回答或已保存等状态。

公式整理详情的“并行处理”统计当前分配给独立标签页的批次数。上传、收取与模型核对可同时进行，各格按目标页显示操作与批号。

通道暂停时，公式面板从最近的专窗实查列出需登录或需验证的槽位。发送前已有上传记录且受阻的批次显示“发送前受阻”，已保存回答且已回到空白首页的原槽位显示“已离开原会话”。

公式页在有新鲜证据时单独显示网页加载、浏览器加载失败或未检测到输入框。Chrome 明确报告标签页曾被回收后重载时也可显示该信息。

每个公式槽位显示输入框按钮的当前强度。控件缺失或网页观测过期时显示未确认或待观测。

公式路由选择 Codex Web GPT 时，公式整理详情显示系统观测到的 App 窗口编号、App 全局网页任务数和本队列批次。查看 App 按钮定位运行中的桌面应用。App 模式的账户与等待原因来自 App 回执。

[app_windows.py](app_windows.py) 按 App 启动器登记及原生日志中的 tabId、traceId 核对各任务页，读取轮转日志最近 1 MiB。面板每 20 秒显示任务页 ID、操作阶段和上海时间的最近事件或心跳。心跳超过 60 秒显示待观测，材料批号仍按队列回执独立展示。缺少可核实身份时显示待观测页数。
