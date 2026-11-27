# 文献标签与主题学习首版交付（2026-10-20）

完成独立 `literature` 物理项目、公开API/CLI、独立侧库及工作台 `/literature` 页面。基础元信息/来源关键词和既有分数保持主库来源；六维科学标签、独立学习用途、受控别名、三层标签树、人工决定保护、证据及图表/材料/条件定位、多条件检索、集合动态规则、手动加入/排除、主题内角色/顺序/进度/笔记均已有初步实现。

三个用户指定仓库固定提交与源码评估见 [参考评估](../literature/REFERENCES.md)，实际加入可选19项OLED候选词表与扩展证据定位。没有安装/运行上游代理、模型、OCR或训练流程，不复制数值换算及自动重试策略。

两端适配：`core.api.literature_catalog__metadata_rows`提供不构造Catalog、不迁移或刷新分数的只读投影；工作台经 `literature.api.Library` 转发已鉴权JSON调用。workspace、独立接口/依赖、组件README、主项目地图、根规则及infrastructure登记同步维护。接口检查发现两份既有维护脚本绕过core公开接口，本轮仅替换导入，保持同一原函数对象，无维护操作执行。

## 实际验证

| 检查 | 结果 |
| --- | --- |
| literature + workbench相关回归 | 42项全部通过，其中新模块15项 |
| 独立headless浏览器 | 登录、词表创建、标注证据、别名筛选、动态集合、角色/进度、证据查看与移动布局通过，无JS错误 |
| `make check` | 15组件、247份生产源码、350个公开出口，通过 |
| 全局 `sync_tools.py update` / `check_links.py` | 通过；8条模块关系；未改四个已登记通用工具的实现 |
| 独立wheel | 构建成功，使用bundled Python/setuptools；未往既有测试环境安装依赖 |
| 真实主Catalog只读投影 | 31,091篇登记文献，6,483篇已登记原文；缺摘要7,300篇、缺年份5篇；本次约0.296秒 |
| `make test` 全项目 | 执行2,364项，5项失败；此轮发现新模块12项，随后新增3项后相关42项单独全过 |

全项目的5项失败均来自 `correction.tests.test_correction_producer_scan_interval.ScanInterval`：existing_task_recovers、long_failed_routing、run_once_failure、status_write_failure、successful_cycle五种扫描间隔/claim场景。单独运行该11项测试复现同5项失败，`literature_imported=False`；本任务没有修改修正业务或其测试，没有将其冒称全量通过。

原始测试输出、结构化测试汇总、只读盘点及源码指纹见 [验证记录](20261020-literature-validation/validation.json)。界面预览使用合成文献与临时库：[桌面](20261020-literature-validation/desktop.png)、[移动](20261020-literature-validation/mobile.png)，不代表真实文献已标注。

## 运行与剩余范围

源码入口已接入；未重启生产工作台、网页任务所有者或任何常驻。原工作台正常重启后可从顶部“标签与主题学习”进入。开发时可用literature CLI/API明确操作本地侧库。

本轮没有创建生产标签侧库，没有给真实文献打标签，没有模型请求或自动100篇试标。自动标注/原文增强、数值属性observations、图谱/向量检索与自动学习路线属于后续实现，不属于当前已完成功能。已有模型、未知回执、人工、暂停和科学保护不变。
