# 评审报告与整理证据

- [20261022-l2-architecture-comparison.md](20261022-l2-architecture-comparison.md)：11个GitHub仓库、3条独立二级路线及20篇已用开发材料实测；均退化保留，不上线，010仍封存。

技术/科学审计、来源调研、环境记录、旧验证、物理隔离清理清单和逐文件位置索引。

- [20261109-workflow-stability.md](20261109-workflow-stability.md) 记录网页编辑与附件提示、旧占用及核验恢复循环的修复和实机验收，并保留[运行证据](20261109-workflow-stability-evidence.json)。
- [20261023-seed-retry-diagnosis.md](20261023-seed-retry-diagnosis.md)：五篇停滞原回执、页面替换与技术重试上限脱节；验证回执保存在[20261023-seed-retry-validation](20261023-seed-retry-validation/)。

## 为什么保留、为什么这样选择

保留完整报告正文和hash，以便判断某项结论对应哪个版本和原请求。报告是历史证据，不作为当前启动说明；执行规则看AGENTS、接口JSON和各项目README。

## 接口与内容

接口声明见 [interface.json](interface.json)。正式调用入口是 `reports.api`；文件型接口保持原JSON/哈希合同。

| 报告文件 | 保留理由 |
| --- | --- |
| [__init__.py](__init__.py) | 原版本审查或实测证据，正文hash可核对 |
| [audits/全自动科学数据候选提取拓展报告_20261011_1121.md](audits/全自动科学数据候选提取拓展报告_20261011_1121.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/制卡材料与Prompt审核报告_20261009_1727.md](audits/制卡材料与Prompt审核报告_20261009_1727.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/工具化与专业化维护审核报告_20261012_0435.md](audits/工具化与专业化维护审核报告_20261012_0435.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/并行空转与调度抱死审核报告_20261012_0305.md](audits/并行空转与调度抱死审核报告_20261012_0305.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/拉取流程审核报告_20261012_0310.md](audits/拉取流程审核报告_20261012_0310.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/文献修正流程最终审核报告_20261012_0252.md](audits/文献修正流程最终审核报告_20261012_0252.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/文献拉取通道状态审核报告_20261012_0227.md](audits/文献拉取通道状态审核报告_20261012_0227.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/文献核验流程审核报告_20261012_0242.md](audits/文献核验流程审核报告_20261012_0242.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/最终审核报告_20261012_0252.md](audits/最终审核报告_20261012_0252.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/最终审计评估_20261006.md](audits/最终审计评估_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/独立技术审计报告_20261006_0310.md](audits/独立技术审计报告_20261006_0310.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/独立技术审计报告_20261006_1246.md](audits/独立技术审计报告_20261006_1246.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/独立技术审计报告_20261009_1746.md](audits/独立技术审计报告_20261009_1746.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/磁盘占用与备份策略审核报告_20261009_1937.md](audits/磁盘占用与备份策略审核报告_20261009_1937.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/网页三队任务状态审核报告_20261012_0236.md](audits/网页三队任务状态审核报告_20261012_0236.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/重要科学数据提取拓展方案报告_20261011_0919.md](audits/重要科学数据提取拓展方案报告_20261011_0919.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/项目分析与整合方案.md](audits/项目分析与整合方案.md) | 原版本审查或实测证据，正文hash可核对 |
| [audits/项目问题分析_20261008_0055.md](audits/项目问题分析_20261008_0055.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/333f30c8.md](card-audits/333f30c8.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/不可恢复网页通用兜底替换_20261009.md](card-audits/不可恢复网页通用兜底替换_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/健康回收时序与未知回执有界复核_20261009.md](card-audits/健康回收时序与未知回执有界复核_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/公式JSON转义提示规范_20261010.md](card-audits/公式JSON转义提示规范_20261010.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/卡片质量根因审计_20261006_1208.md](card-audits/卡片质量根因审计_20261006_1208.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/后台维护反复中断隔离修复_20261012-003234.md](card-audits/后台维护反复中断隔离修复_20261012-003234.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/核验修正分流与分数排序复核_20261009.md](card-audits/核验修正分流与分数排序复核_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/橙色占位收尾修复_20261010.md](card-audits/橙色占位收尾修复_20261010.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/橙色窗口后台维护中断修复_20261012-002427.md](card-audits/橙色窗口后台维护中断修复_20261012-002427.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/橙色阻塞自动处理复核与修复_20261009.md](card-audits/橙色阻塞自动处理复核与修复_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/网页池橙色槽位分类诊断与处理方案_20261009_1922.md](card-audits/网页池橙色槽位分类诊断与处理方案_20261009_1922.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/网页池橙色槽位复核与修复结果_20261009.md](card-audits/网页池橙色槽位复核与修复结果_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/网页池灰色与橙色状态深度审计_20261011_0014.md](card-audits/网页池灰色与橙色状态深度审计_20261011_0014.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/网页派发与收发正确性与稳定性审核_20261009_1418.md](card-audits/网页派发与收发正确性与稳定性审核_20261009_1418.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/网页端任务派发与收发审计_20261009_1356.md](card-audits/网页端任务派发与收发审计_20261009_1356.md) | 原版本审查或实测证据，正文hash可核对 |
| [card-audits/训练数据拓展方案_20261011_0919.md](card-audits/训练数据拓展方案_20261011_0919.md) | 原版本审查或实测证据，正文hash可核对 |
| [environment/Mac-Studio-模型验证.json](environment/Mac-Studio-模型验证.json) | 原版本审查或实测证据，正文hash可核对 |
| [environment/Mac-Studio-环境配置记录.md](environment/Mac-Studio-环境配置记录.md) | 原版本审查或实测证据，正文hash可核对 |
| [legacy-validation/article-VALIDATION.md](legacy-validation/article-VALIDATION.md) | 原版本审查或实测证据，正文hash可核对 |
| [retrieval-research/20261012-GitHub原文来源对照.md](retrieval-research/20261012-GitHub原文来源对照.md) | 原版本审查或实测证据，正文hash可核对 |
| [retrieval-research/20261013-拉取效率深度分析与项目调研.md](retrieval-research/20261013-拉取效率深度分析与项目调研.md) | 原版本审查或实测证据，正文hash可核对 |
| [retrieval-research/20261013-拉取链路改进与实测.md](retrieval-research/20261013-拉取链路改进与实测.md) | 原版本审查或实测证据，正文hash可核对 |
| [retrieval-research/20261013-来源调度与缓存改进.md](retrieval-research/20261013-来源调度与缓存改进.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/3页文献三组评审共性与差异_20261007.md](workflow-audits/3页文献三组评审共性与差异_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/5页Gemma与Qwen同流程对照_20261007.md](workflow-audits/5页Gemma与Qwen同流程对照_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/5页xhigh对照启动_20261007.md](workflow-audits/5页xhigh对照启动_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/5页网页版直接制卡对照_20261007.md](workflow-audits/5页网页版直接制卡对照_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/Chrome故障恢复与多会话测试.md](workflow-audits/Chrome故障恢复与多会话测试.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/GGUF模型下载与用时评分对照_20261006.md](workflow-audits/GGUF模型下载与用时评分对照_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/Qwen38两篇制卡测试_20261006.md](workflow-audits/Qwen38两篇制卡测试_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/Qwen38推理档位对照_20261007.md](workflow-audits/Qwen38推理档位对照_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/三份新增流程报告复核与修复_20261012.md](workflow-audits/三份新增流程报告复核与修复_20261012.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/上传期间页面格位颜色复核与修复_20261011.md](workflow-audits/上传期间页面格位颜色复核与修复_20261011.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/两份状态审核报告复核与修复_20261012.md](workflow-audits/两份状态审核报告复核与修复_20261012.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/两篇短文三轮优化汇总_20261006.md](workflow-audits/两篇短文三轮优化汇总_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/全天候模型运行设置_20261007.md](workflow-audits/全天候模型运行设置_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/全灰与网页不派发溯源修复_20261012.md](workflow-audits/全灰与网页不派发溯源修复_20261012.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/制卡20篇问题修复_20261010.md](workflow-audits/制卡20篇问题修复_20261010.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/制卡定时检查_20261010_0157.md](workflow-audits/制卡定时检查_20261010_0157.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/制卡暂停与送审版本整改_20261006_1648.md](workflow-audits/制卡暂停与送审版本整改_20261006_1648.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/制卡材料Prompt审核复核与修复_20261009.md](workflow-audits/制卡材料Prompt审核复核与修复_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/制卡根因审计整改_20261006_1208.md](workflow-audits/制卡根因审计整改_20261006_1208.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/制卡编辑器输入修复_20261013.md](workflow-audits/制卡编辑器输入修复_20261013.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/卡片质量迭代记录.md](workflow-audits/卡片质量迭代记录.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/同提示模型对照准备_20261006.md](workflow-audits/同提示模型对照准备_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/后台集体故障批次恢复修复-20261012.md](workflow-audits/后台集体故障批次恢复修复-20261012.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/启动后空页不提交修复_20261010.md](workflow-audits/启动后空页不提交修复_20261010.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/审计修复基线_20261006.json](workflow-audits/审计修复基线_20261006.json) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/审计后续修复_20261006.md](workflow-audits/审计后续修复_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/审计首批修复_20261006.md](workflow-audits/审计首批修复_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/工具化维护审核真实性与可行性复核_20261013.md](workflow-audits/工具化维护审核真实性与可行性复核_20261013.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/当前项目工作流_20261007.md](workflow-audits/当前项目工作流_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/拉取流程审核复核与修复_20261012.md](workflow-audits/拉取流程审核复核与修复_20261012.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/拉取端修复_20261006.md](workflow-audits/拉取端修复_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/文献核验流程审核复核与修复_20261012.md](workflow-audits/文献核验流程审核复核与修复_20261012.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/新增审核报告检查收尾_20261012_0400.md](workflow-audits/新增审核报告检查收尾_20261012_0400.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/新审计首批整改_20261008.md](workflow-audits/新审计首批整改_20261008.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/新旧审计合并整改_20261006.md](workflow-audits/新旧审计合并整改_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/最新网页审计复核与整改_20261009.md](workflow-audits/最新网页审计复核与整改_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/核验与修正卡死恢复修复_20261013.md](workflow-audits/核验与修正卡死恢复修复_20261013.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/核验修正通过率分析_20261010.md](workflow-audits/核验修正通过率分析_20261010.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/核验修正阻塞全部入循环_20261013.md](workflow-audits/核验修正阻塞全部入循环_20261013.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/模型制卡对照汇总_20261007.md](workflow-audits/模型制卡对照汇总_20261007.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/模型时段与并联队列_20261006.md](workflow-audits/模型时段与并联队列_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/治理整改_20261008.md](workflow-audits/治理整改_20261008.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/灰色页面与材料队首准备修复_20261010.md](workflow-audits/灰色页面与材料队首准备修复_20261010.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/独立审计1246复核汇总_20261006.md](workflow-audits/独立审计1246复核汇总_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/独立审计1246整改记录_20261006.md](workflow-audits/独立审计1246整改记录_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/独立技术审计1746复核与修复_20261009.md](workflow-audits/独立技术审计1746复核与修复_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/科学核验组件接入与评估_20261006.md](workflow-audits/科学核验组件接入与评估_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/第二组件基准与保留决策_20261006.md](workflow-audits/第二组件基准与保留决策_20261006.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/粘贴审计核对与修复_20261010.md](workflow-audits/粘贴审计核对与修复_20261010.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/网页池深度审计复核与整改_20261011.md](workflow-audits/网页池深度审计复核与整改_20261011.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/网页派发审计复核与整改_20261009.md](workflow-audits/网页派发审计复核与整改_20261009.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/网页流程半小时诊断_20261011_0258.md](workflow-audits/网页流程半小时诊断_20261011_0258.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/网页流程半小时诊断_20261011_0458.md](workflow-audits/网页流程半小时诊断_20261011_0458.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/网页流程半小时诊断_20261011_0528.md](workflow-audits/网页流程半小时诊断_20261011_0528.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/网页观测超时复核与修复_20261011.md](workflow-audits/网页观测超时复核与修复_20261011.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/重构验收记录.md](workflow-audits/重构验收记录.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/页面可用但未派发复核与修复_20261011.md](workflow-audits/页面可用但未派发复核与修复_20261011.md) | 原版本审查或实测证据，正文hash可核对 |
| [workflow-audits/高分文献卡片抽查_20261009.md](workflow-audits/高分文献卡片抽查_20261009.md) | 原版本审查或实测证据，正文hash可核对 |

- [physical-isolation-cleanup.json](physical-isolation-cleanup.json)：逐文件删除/移动依据、保留理由和回滚证据。
- [physical-isolation-verification.json](physical-isolation-verification.json)：真实测试、独立构建、控制与接口验收。

## 边界

报告原文字节不改写；新位置由索引解释旧路径，历史路径不视作现存接口。

源码当前接口与删除理由见 [项目地图](../WORKFLOWS.md)。

## 八项目完整归并与备份删除

- [迁移核对](20261014-eight-projects-migration.json)：八项目归属、暂停控制与数据库同一文件核对。
- [删除数据备份](20261013-backup-removal.json)：备份副本及未启用恢复演练副本的删除原因和体积。
- [旧部署副本清理](20261014-retired-deployment-cleanup.json)：已退休静态副本的完整删除指纹。
- [独立构建](20261014-grouped-wheel-builds.json)：18个组件与项目的实际构建结果。

## 发布与接口维护（1.0.1）

`make test`运行独立合同测试；`make check`临时构建Wheel、隔离安装并逐项调用公开API、校验hash，再以Python默认方式解压UTF-8 ZIP。`make release`通过相同门禁后输出dist中的Wheel、ZIP和verification.json。构建工具需要Python 3.11+、pip、setuptools>=68、wheel；离线构建不下载依赖。

`api.py`只读并即时校验清单，异常均兼容ValueError；不缓存可变清单。`resolve_report_link`优先精确相对路径，仅对../文件名形式且包内唯一的迁移报告做回退，歧义和外部项目路径返回None。调用方保留原锚点，原报告正文不改写。`release.py`维护交付门禁；`Makefile`提供独立入口；`tests/test_reports.py`验证清单、路径保护、损坏和链接解析。系统.DS_Store已移出正式清单并删除，其旧指纹保留于本轮整改说明；__init__.py仍保留以兼容旧登记。

SHA-256只证明内容与当前清单一致，不证明独立来源真实性；签名需要独立可信签发与分发流程，本版本不伪造该保证。

本轮逐项复核、方案调整及验证限制见[AUDIT_REVIEW.md](AUDIT_REVIEW.md)。

## 任务面板停滞诊断与修复（2026-10-14）

[修复与实测](20261014-task-panel-stall-repair.json)记录迁移路径、回执索引和健康观测瓶颈、1818项离线回归及原所有者重载结果；未知回执、补页CAS冲突与草稿保护仍独立记录，不冒称全部恢复。

## 剩余运行阻塞恢复（2026-10-14）

- [恢复与原因](20261014-remaining-page-recovery.json)：1850项回归、真实20页与三队派发，以及仍保护的历史回执。
- [SSD链接证据](20261014-runtime-ssd-link-repair.json)：8032个链接的旧/新目标、内容与文件版本指纹、16个本地准备任务恢复；不修改目标字节。
- [第05槽方案](20261014-missing-slot05-recovery-proposal.json)：单次用户批准的绑定参数，旧未知创建保留。

## 2026-10-14 近期故障深入恢复

- [溯源与修复报告](20261014-deep-recovery.md)：版本发布绑定、准备候选/缓存、JSON包装、空白草稿、SSD归档、六项旧准备失败和退役材料只读解析。
- [运行验收](20261014-deep-recovery-live.json) 与 [验证指纹](20261014-deep-recovery-verification.json)：真实队列、固定窗口、暂停及源码/测试证据。
- [诊断链接修复](20261014-deep-diagnostic-links-applied.json)、[四项旧准备恢复](20261014-local-review-preparation-recovery.json)、[两项旧准备恢复](20261014-local-review-preparation-recovery-extra.json)、[退役材料核对](20261014-retired-source-input-verification.json)。

- [20261014-passed-correction-priority.md](20261014-passed-correction-priority.md)：核验通过修正持续置顶、13项历史排版阻塞来源与分流、正式版本保护及1885项回归；运行证据见同名runtime/routing JSON。

- [20261014-current-stall-recovery.md](20261014-current-stall-recovery.md)：主页UI错误误判、已结束移窗争锁及输入区诊断修复；原20页专窗恢复真实生成，1887项回归通过。

- [20261014-automatic-owner-supervision.md](20261014-automatic-owner-supervision.md)：补全原HTTP watcher对网页所有者的自动监督、验收源码交接及双心跳故障恢复；1897项回归及实机交接证据。

- [20261014-throughput-stall-recovery.md](20261014-throughput-stall-recovery.md)：重复首页加载、模型控件就绪、跨槽CAS、唯一原历史回执及真实上传保护的溯源修复，附原所有者自动接续与实机验收。

2026-10-18：92 个已按删除指纹清单移除的旧审计文件从 interface.json 的可读 entries 迁至 deleted_entries（保留原路径与 SHA）；已删除链接解析为不存在，不恢复原件。

## 2026-10-20 文献标签与主题学习首版

[交付与验证](20261020-literature-initial.md)记录新子项目实现、三仓库参考取舍、相关42项测试通过及全项目修正模块5项独立复现失败。[验证目录](20261020-literature-validation/)保留日志、只读元信息盘点、源码指纹及临时合成库桌面/移动截图，不代表真实文献已标注。全部新增文件按字节登记在interface.json。

[2026-10-20中间结果复用盘点](20261020-literature-intermediate-reuse.md)：当前任务指针下1,838篇冻结逐页文本、6篇更细解析及GitHub四项目只读评估；原始计数与范围限制独立保存，不是批量标注或模型运行回执。

[2026-10-20一二级自动标签10篇评测](20261020-directions-evaluation.md)：先冻结规则/预测，再同输入助手参考标准；保留开放词表错漏、10篇清单和逐篇标准，以及SI-only安全修复单独复测。[验证目录](20261020-directions-validation/)保存指标、协议、汇总、原始日志和合成浏览器截图；原文证据窗口和gold保留在infrastructure运行数据中，不作生产标签。

- [2026-10-20 手选种子全环节第一顺位](20261020-manual-seed-first.md)：调度、上传容量、重试/恢复顺位及全量检查、原owner交接证据；[验证目录](20261020-seed-first-validation/)。

## 2026-10-20 核心标签试验

[20261020-core-directions-evaluation.md](20261020-core-directions-evaluation.md)：同10篇核心标准开发重评，说明数量减少、核心P/R变化及尚未覆盖的方向。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-core-directions-validation/baseline-leaves-metrics.json | 旧宽标签去重复父类后同口径比较 |
| 20261020-core-directions-validation/baseline-raw-metrics.json | 旧宽标签原样对同核心标准计分 |
| 20261020-core-directions-validation/browser.log | 独立页面端到端验证 |
| 20261020-core-directions-validation/desktop.png | 合成临时库桌面展示 |
| 20261020-core-directions-validation/frozen-output-hashes.json | 冻结输入、输出、协议指纹 |
| 20261020-core-directions-validation/full-tests.log | 本次make test真实日志 |
| 20261020-core-directions-validation/gold-frozen.json | 评测专用核心参考冻结指纹 |
| 20261020-core-directions-validation/metrics.json | 新策略核心指标与逐篇错漏 |
| 20261020-core-directions-validation/mobile.png | 合成临时库移动端展示 |
| 20261020-core-directions-validation/policy.json | 核心参考定义、开发集及SI排除边界 |
| 20261020-core-directions-validation/protocol.json | 预测前冻结的源码指纹与输入预算 |
| 20261020-core-directions-validation/samples.json | 原10篇身份及分层 |
| 20261020-core-directions-validation/source-guard-retest.json | 已知SI-only原文当前守卫复核 |
| 20261020-core-directions-validation/targeted-tests.log | literature/reports针对性验证 |
| 20261020-core-directions-validation/validation.json | 测试及新旧证据完整性汇总 |
| 20261020-core-directions-validation/workbench-tests.log | 工作台27项回归 |

## 标签持续优化第1轮（2026-10-20）

[20261020-tagging-iteration-001.md](20261020-tagging-iteration-001.md)：持续优化授权、每30分钟heartbeat回执、开发集同口径改进与未见留出保护。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-001-validation/automation-receipt.json | 当前聊天每30分钟ACTIVE设置核对 |
| 20261020-tagging-iteration-001-validation/browser.log | 独立headless页面操作验证 |
| 20261020-tagging-iteration-001-validation/check.log | 接口与组件静态检查 |
| 20261020-tagging-iteration-001-validation/frozen-output-hashes.json | 不可变输入、预测、协议指纹 |
| 20261020-tagging-iteration-001-validation/full-tests.log | 本轮全项目执行日志 |
| 20261020-tagging-iteration-001-validation/holdout-disjoint-audit.json | 原文SHA/标题无开发重叠或组内重复 |
| 20261020-tagging-iteration-001-validation/holdout-frozen-output-hashes.json | 留出初始输入冻结证据 |
| 20261020-tagging-iteration-001-validation/holdout-holdout-status.json | 冻结时未读、未预测状态快照 |
| 20261020-tagging-iteration-001-validation/holdout-protocol.json | 未见留出抽样与预算 |
| 20261020-tagging-iteration-001-validation/holdout-samples.json | 新10篇身份与分层 |
| 20261020-tagging-iteration-001-validation/links.log | 全局联动检查 |
| 20261020-tagging-iteration-001-validation/literature-tests.log | 38项标签回归 |
| 20261020-tagging-iteration-001-validation/metrics.json | 固定开发标准成绩及逐篇错漏 |
| 20261020-tagging-iteration-001-validation/protocol.json | 当前候选和开发协议指纹 |
| 20261020-tagging-iteration-001-validation/validation.json | 源码、冻结证据与实际验证汇总 |

## 标签持续优化第2轮（2026-10-20）

[20261020-tagging-iteration-002.md](20261020-tagging-iteration-002.md)：41项词表候选、固定开发标准与首次新10篇评测，独立制卡测试阻断全量验收，未发布为可用版。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-002-validation/browser.log | 独立页面验证 |
| 20261020-tagging-iteration-002-validation/check.log | 接口及组件检查 |
| 20261020-tagging-iteration-002-validation/development-baseline-metrics.json | 旧预测同一标准复算 |
| 20261020-tagging-iteration-002-validation/evaluation-context.json | 41项评价器与38项旧执行词表区别 |
| 20261020-tagging-iteration-002-validation/frozen-output-hashes.json | 开发输入、预测、对应及协议指纹 |
| 20261020-tagging-iteration-002-validation/full-tests.log | 2415次执行及1项失败完整记录 |
| 20261020-tagging-iteration-002-validation/gate-repro.log | 未加载literature的独立失败复现 |
| 20261020-tagging-iteration-002-validation/global-gate-failure.json | 制卡断言及原源码指纹 |
| 20261020-tagging-iteration-002-validation/links.log | 全局联动检查 |
| 20261020-tagging-iteration-002-validation/literature-tests.log | 42项标签回归通过 |
| 20261020-tagging-iteration-002-validation/metrics.json | 候选开发集指标及错漏 |
| 20261020-tagging-iteration-002-validation/next-disjoint-audit.json | 新10篇与此前20篇无重复 |
| 20261020-tagging-iteration-002-validation/next-frozen-output-hashes.json | 第二组输入冻结清单 |
| 20261020-tagging-iteration-002-validation/next-holdout-status.json | 第二组未见状态 |
| 20261020-tagging-iteration-002-validation/next-protocol.json | 第二组未见输入协议 |
| 20261020-tagging-iteration-002-validation/protocol.json | 候选源码和开发协议冻结 |
| 20261020-tagging-iteration-002-validation/semantic-map.json | 先冻结的一对一同层同维度评价ID对应 |
| 20261020-tagging-iteration-002-validation/test-baseline-metrics.json | 冻结旧版在同新样本标准下成绩 |
| 20261020-tagging-iteration-002-validation/test-exposure-001.json | 候选冻结后的首次曝光 |
| 20261020-tagging-iteration-002-validation/test-frozen-output-hashes.json | 新样本初始输入清单未改 |
| 20261020-tagging-iteration-002-validation/test-gold-frozen.json | 新样本预测之前的参考冻结 |
| 20261020-tagging-iteration-002-validation/test-holdout-status.json | 首次测试已使用状态 |
| 20261020-tagging-iteration-002-validation/test-metrics.json | 首次新样本候选成绩 |
| 20261020-tagging-iteration-002-validation/test-predictions-frozen.json | gold之后的预测冻结 |
| 20261020-tagging-iteration-002-validation/test-samples.json | 首次新10篇身份 |
| 20261020-tagging-iteration-002-validation/validation.json | 候选状态、冻结完整性及验证总览 |

## 标签持续优化第3轮（2026-10-20）

[20261020-tagging-iteration-003.md](20261020-tagging-iteration-003.md)：显式自旋振动与普通振电耦合区分；已曝光10篇仅作开发回归，无新独立评测；同一制卡测试继续阻断候选验收。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-003-validation/browser.log | 隔离页面回归，无生产CDP |
| 20261020-tagging-iteration-003-validation/check.log | 15组件静态接口检查 |
| 20261020-tagging-iteration-003-validation/development-audit.json | 每篇数量、证据来源及实际改变 |
| 20261020-tagging-iteration-003-validation/development-baseline-metrics.json | 冻结1.3.0预测同标准复核 |
| 20261020-tagging-iteration-003-validation/development-frozen-output-hashes.json | 同输入及预测冻结回执 |
| 20261020-tagging-iteration-003-validation/development-gold-frozen.json | 原标准不变的冻结指纹 |
| 20261020-tagging-iteration-003-validation/development-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-003-validation/full-tests.log | 2418次执行及独立制卡失败 |
| 20261020-tagging-iteration-003-validation/global-gate-failure.json | 同一制卡断言、原源码指纹与历史独立复现 |
| 20261020-tagging-iteration-003-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-003-validation/literature-tests.log | 45项标签回归 |
| 20261020-tagging-iteration-003-validation/protected-after.json | 保护核对及新留出未曝光状态 |
| 20261020-tagging-iteration-003-validation/protected-before.json | 历史135文件保护指纹 |
| 20261020-tagging-iteration-003-validation/protocol.json | 候选源码指纹与固定预算 |
| 20261020-tagging-iteration-003-validation/semantic-map.json | 原三条一对一对应不变，仅作评测 |
| 20261020-tagging-iteration-003-validation/update.log | 全局接口联动更新 |
| 20261020-tagging-iteration-003-validation/used-development-audit.json | 每篇数量、证据来源及实际改变 |
| 20261020-tagging-iteration-003-validation/used-development-baseline-metrics.json | 冻结1.3.0预测同标准复核 |
| 20261020-tagging-iteration-003-validation/used-development-frozen-output-hashes.json | 同输入及预测冻结回执 |
| 20261020-tagging-iteration-003-validation/used-development-gold-frozen.json | 原标准不变的冻结指纹 |
| 20261020-tagging-iteration-003-validation/used-development-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-003-validation/validation.json | 候选未验收、当前检查及无独立评测的总览 |

- [2026-10-20 手选种子三版独立优选](20261020-manual-seed-three-candidates.md)：固定5篇、真实核验择优、百万优先级显示修复；[验证](20261020-seed-three-validation/)。

## 标签持续优化第4轮（2026-10-20）

[20261020-tagging-iteration-004.md](20261020-tagging-iteration-004.md)：DFT名词词形与二级正文边界、已曝光开发组补回1个正确核心；本轮没有新独立评测。验证状态：validated。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-004-validation/browser.log | 临时库独立页面回归 |
| 20261020-tagging-iteration-004-validation/check.log | 组件静态接口检查 |
| 20261020-tagging-iteration-004-validation/development-audit.json | 每篇数量、证据来源和实际改变 |
| 20261020-tagging-iteration-004-validation/development-baseline-metrics.json | 冻结1.3.1预测在同一标准下复核 |
| 20261020-tagging-iteration-004-validation/development-frozen-output-hashes.json | 原输入与新预测冻结回执 |
| 20261020-tagging-iteration-004-validation/development-gold-frozen.json | 原参考不变的指纹 |
| 20261020-tagging-iteration-004-validation/development-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-004-validation/full-summary.json | 全项目执行数、去重数及组件结果 |
| 20261020-tagging-iteration-004-validation/full-tests.log | 本轮全项目真实执行日志 |
| 20261020-tagging-iteration-004-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-004-validation/literature-tests.log | 48项标签回归 |
| 20261020-tagging-iteration-004-validation/prior-gate-context.json | 既有制卡失败的源码变化，仅作只读背景 |
| 20261020-tagging-iteration-004-validation/protected-after.json | 保护核对及未见留出状态 |
| 20261020-tagging-iteration-004-validation/protected-before.json | 历史193文件保护指纹 |
| 20261020-tagging-iteration-004-validation/protocol.json | 候选源码指纹与固定预算 |
| 20261020-tagging-iteration-004-validation/semantic-map.json | 原三条一对一评价对应保持原字节 |
| 20261020-tagging-iteration-004-validation/update.log | 全局联动更新 |
| 20261020-tagging-iteration-004-validation/used-development-audit.json | 每篇数量、证据来源和实际改变 |
| 20261020-tagging-iteration-004-validation/used-development-baseline-metrics.json | 冻结1.3.1预测在同一标准下复核 |
| 20261020-tagging-iteration-004-validation/used-development-frozen-output-hashes.json | 原输入与新预测冻结回执 |
| 20261020-tagging-iteration-004-validation/used-development-gold-frozen.json | 原参考不变的指纹 |
| 20261020-tagging-iteration-004-validation/used-development-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-004-validation/validation.json | 当前验收状态、冻结保护与本轮无独立评测 |

## 标签持续优化第5轮（2026-10-20）

[20261020-tagging-iteration-005.md](20261020-tagging-iteration-005.md)：当前方法引用既往步骤的语境边界；开发核心及指标不变；本轮没有新独立评测。验证状态：validated。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-005-validation/browser.log | 临时库独立页面回归 |
| 20261020-tagging-iteration-005-validation/check.log | 组件静态接口检查 |
| 20261020-tagging-iteration-005-validation/context-audit.json | 已曝光真实原文的当前步骤与历史语境诊断，无新标签 |
| 20261020-tagging-iteration-005-validation/development-audit.json | 每篇数量、证据来源和实际改变 |
| 20261020-tagging-iteration-005-validation/development-baseline-metrics.json | 冻结1.3.2预测在同一标准下复核 |
| 20261020-tagging-iteration-005-validation/development-frozen-output-hashes.json | 原输入与新预测冻结回执 |
| 20261020-tagging-iteration-005-validation/development-gold-frozen.json | 原参考不变的指纹 |
| 20261020-tagging-iteration-005-validation/development-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-005-validation/full-summary.json | 全项目执行数、去重数及组件结果 |
| 20261020-tagging-iteration-005-validation/full-tests.log | 本轮全项目真实执行日志 |
| 20261020-tagging-iteration-005-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-005-validation/literature-tests.log | 51项标签回归 |
| 20261020-tagging-iteration-005-validation/protected-after.json | 保护核对及未见留出状态 |
| 20261020-tagging-iteration-005-validation/protected-before.json | 历史252文件保护指纹 |
| 20261020-tagging-iteration-005-validation/protocol.json | 候选源码指纹与固定预算 |
| 20261020-tagging-iteration-005-validation/semantic-map.json | 原三条一对一评价对应保持原字节 |
| 20261020-tagging-iteration-005-validation/update.log | 全局联动更新 |
| 20261020-tagging-iteration-005-validation/used-development-audit.json | 每篇数量、证据来源和实际改变 |
| 20261020-tagging-iteration-005-validation/used-development-baseline-metrics.json | 冻结1.3.2预测在同一标准下复核 |
| 20261020-tagging-iteration-005-validation/used-development-frozen-output-hashes.json | 原输入与新预测冻结回执 |
| 20261020-tagging-iteration-005-validation/used-development-gold-frozen.json | 原参考不变的指纹 |
| 20261020-tagging-iteration-005-validation/used-development-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-005-validation/validation.json | 当前验收状态、冻结保护与本轮无独立评测 |

## 标签持续优化第6轮（2026-10-20）

[20261020-tagging-iteration-006.md](20261020-tagging-iteration-006.md)：联合色谱/质谱降解产物分析、预测前语义对应与双证据；开发补回1个正确核心；本轮没有新独立评测。验证状态：validated。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-006-validation/browser.log | 临时库独立页面回归 |
| 20261020-tagging-iteration-006-validation/check.log | 组件静态接口检查 |
| 20261020-tagging-iteration-006-validation/development-audit.json | 每篇数量、证据来源和实际改变 |
| 20261020-tagging-iteration-006-validation/development-baseline-metrics.json | 冻结1.3.3预测在同一标准下复核 |
| 20261020-tagging-iteration-006-validation/development-frozen-output-hashes.json | 原输入与新预测冻结回执 |
| 20261020-tagging-iteration-006-validation/development-gold-frozen.json | 原参考不变的指纹 |
| 20261020-tagging-iteration-006-validation/development-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-006-validation/full-summary.json | 全项目执行数、去重数及组件结果 |
| 20261020-tagging-iteration-006-validation/full-tests.log | 本轮全项目真实执行日志 |
| 20261020-tagging-iteration-006-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-006-validation/literature-tests.log | 56项标签回归 |
| 20261020-tagging-iteration-006-validation/protected-after.json | 保护核对及未见留出状态 |
| 20261020-tagging-iteration-006-validation/protected-before.json | 历史311文件保护指纹 |
| 20261020-tagging-iteration-006-validation/protocol.json | 候选源码指纹与固定预算 |
| 20261020-tagging-iteration-006-validation/semantic-map-degradation.json | 预测前冻结的联合分析流程一对一评价定义及边界 |
| 20261020-tagging-iteration-006-validation/semantic-map.json | 原三条一对一评价对应保持原字节 |
| 20261020-tagging-iteration-006-validation/update.log | 全局联动更新 |
| 20261020-tagging-iteration-006-validation/used-development-audit.json | 每篇数量、证据来源和实际改变 |
| 20261020-tagging-iteration-006-validation/used-development-baseline-metrics.json | 冻结1.3.3预测在同一标准下复核 |
| 20261020-tagging-iteration-006-validation/used-development-frozen-output-hashes.json | 原输入与新预测冻结回执 |
| 20261020-tagging-iteration-006-validation/used-development-gold-frozen.json | 原参考不变的指纹 |
| 20261020-tagging-iteration-006-validation/used-development-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-006-validation/validation.json | 当前验收状态、冻结保护与本轮无独立评测 |

## 标签持续优化第7轮：独立评测（2026-10-20）

[20261020-tagging-iteration-007.md](20261020-tagging-iteration-007.md)：1.4.0不改，第二组10篇独立gold先于预测；一级P78.95/R62.50，二级P45.16/R28.00，泛化仍不足。第三组新留出封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-007-validation/check.log | 15组件静态接口检查 |
| 20261020-tagging-iteration-007-validation/development-original-metrics.json | 沿用第6轮同版本开发指标，未冒称本轮新测 |
| 20261020-tagging-iteration-007-validation/development-used-metrics.json | 沿用第6轮同版本开发指标，未冒称本轮新测 |
| 20261020-tagging-iteration-007-validation/full-summary.json | 全量执行、唯一ID及组件结果 |
| 20261020-tagging-iteration-007-validation/full-tests.log | 2432次全项目执行真实日志 |
| 20261020-tagging-iteration-007-validation/holdout-status-before.json | 初始未打开状态原字节 |
| 20261020-tagging-iteration-007-validation/holdout-status-gold-frozen.json | 参考冻结但尚未预测的状态 |
| 20261020-tagging-iteration-007-validation/holdout-status-opened.json | 首次打开且参考未冻的状态 |
| 20261020-tagging-iteration-007-validation/independent-audit.json | 每篇核心数量及机械来源检查 |
| 20261020-tagging-iteration-007-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-007-validation/next-disjoint-audit.json | 第三组与此前30篇无身份/原文/标题重复 |
| 20261020-tagging-iteration-007-validation/next-frozen-output-hashes.json | 第三组初始输入指纹 |
| 20261020-tagging-iteration-007-validation/next-holdout-status.json | 第三组未读、无gold/预测 |
| 20261020-tagging-iteration-007-validation/next-protocol.json | 第三组新输入抽样协议 |
| 20261020-tagging-iteration-007-validation/protected-after.json | 原字节与可变曝光状态区分 |
| 20261020-tagging-iteration-007-validation/protected-before.json | 371个不可变文件保护清单 |
| 20261020-tagging-iteration-007-validation/protocol.json | 1.4.0未改与既有开发冻结指标关联 |
| 20261020-tagging-iteration-007-validation/test-exposure-001.json | 候选及开发已冻后的首次曝光 |
| 20261020-tagging-iteration-007-validation/test-frozen-output-hashes.json | 初始输入和抽样回执不变 |
| 20261020-tagging-iteration-007-validation/test-gold-authoring-record.json | 助手同输入独立理由与覆盖边界 |
| 20261020-tagging-iteration-007-validation/test-gold-frozen.json | 预测前24/50核心参考冻结 |
| 20261020-tagging-iteration-007-validation/test-holdout-status.json | 已使用测试、无事后调参 |
| 20261020-tagging-iteration-007-validation/test-metrics.json | 首次独立指标与逐篇错漏 |
| 20261020-tagging-iteration-007-validation/test-predictions-frozen.json | gold后预测与有效规则版本 |
| 20261020-tagging-iteration-007-validation/test-protocol.json | 最初抽样与固定输入预算，不冒称本轮分类版本 |
| 20261020-tagging-iteration-007-validation/update.log | 全局联动更新 |
| 20261020-tagging-iteration-007-validation/validation.json | 软件通过与独立科学效果不足分开记录 |

## 标签持续优化第8轮（2026-10-20）

[20261020-tagging-iteration-008.md](20261020-tagging-iteration-008.md)：一级摘要相邻结果指代；第二已用组开发P84.21/R66.67，其余不变，无新独立评测。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-008-validation/browser.log | 隔离页面回归 |
| 20261020-tagging-iteration-008-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-008-validation/development-notes.json | 预测前边界修复与冻结时序 |
| 20261020-tagging-iteration-008-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-008-validation/full-summary.json | 全量执行、唯一ID及组件结果 |
| 20261020-tagging-iteration-008-validation/full-tests.log | 全项目真实执行日志 |
| 20261020-tagging-iteration-008-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-008-validation/literature-tests.log | 61项标签测试 |
| 20261020-tagging-iteration-008-validation/original-audit.json | 逐篇数量、实际变更和机械来源校验 |
| 20261020-tagging-iteration-008-validation/original-baseline-metrics.json | 旧1.4.0冻结预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-008-validation/original-frozen-output-hashes.json | 输入与新预测指纹 |
| 20261020-tagging-iteration-008-validation/original-gold-frozen.json | 旧参考指纹保持 |
| 20261020-tagging-iteration-008-validation/original-metrics.json | 已曝光开发指标与逐篇错漏 |
| 20261020-tagging-iteration-008-validation/original-protocol.json | 开发角色与旧参考来源 |
| 20261020-tagging-iteration-008-validation/protected-after.json | 历史字节不变与第三留出封存 |
| 20261020-tagging-iteration-008-validation/protected-before.json | 422个历史文件保护清单 |
| 20261020-tagging-iteration-008-validation/protocol.json | 本轮候选源码指纹与单项变更 |
| 20261020-tagging-iteration-008-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-008-validation/used001-audit.json | 逐篇数量、实际变更和机械来源校验 |
| 20261020-tagging-iteration-008-validation/used001-baseline-metrics.json | 旧1.4.0冻结预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-008-validation/used001-frozen-output-hashes.json | 输入与新预测指纹 |
| 20261020-tagging-iteration-008-validation/used001-gold-frozen.json | 旧参考指纹保持 |
| 20261020-tagging-iteration-008-validation/used001-metrics.json | 已曝光开发指标与逐篇错漏 |
| 20261020-tagging-iteration-008-validation/used001-protocol.json | 开发角色与旧参考来源 |
| 20261020-tagging-iteration-008-validation/used002-audit.json | 逐篇数量、实际变更和机械来源校验 |
| 20261020-tagging-iteration-008-validation/used002-baseline-metrics.json | 旧1.4.0冻结预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-008-validation/used002-frozen-output-hashes.json | 输入与新预测指纹 |
| 20261020-tagging-iteration-008-validation/used002-gold-frozen.json | 旧参考指纹保持 |
| 20261020-tagging-iteration-008-validation/used002-metrics.json | 已曝光开发指标与逐篇错漏 |
| 20261020-tagging-iteration-008-validation/used002-protocol.json | 开发角色与旧参考来源 |
| 20261020-tagging-iteration-008-validation/validation.json | 软件验收、开发角色及独立指标为空 |

## 标签持续优化第9轮（2026-10-20）

[20261020-tagging-iteration-009.md](20261020-tagging-iteration-009.md)：MR与MR-TADF独立定义、摘要局部简称；固定开发分数退化，候选隔离保留，当前1.4.1不替换。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-009-validation/browser.log | 候选隔离页面回归 |
| 20261020-tagging-iteration-009-validation/check.log | 候选静态检查 |
| 20261020-tagging-iteration-009-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-009-validation/full-summary.json | 候选全量执行数、唯一ID及组件结果 |
| 20261020-tagging-iteration-009-validation/full-tests.log | 候选全项目真实日志 |
| 20261020-tagging-iteration-009-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-009-validation/literature-tests.log | 候选67项标签回归 |
| 20261020-tagging-iteration-009-validation/original-audit.json | 每篇数量、实际变更及机械来源检查 |
| 20261020-tagging-iteration-009-validation/original-baseline-metrics.json | 1.4.1冻结预测同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-009-validation/original-frozen-output-hashes.json | 本轮输入与新预测冻结 |
| 20261020-tagging-iteration-009-validation/original-gold-frozen.json | 原参考SHA未改 |
| 20261020-tagging-iteration-009-validation/original-metrics.json | 三组曝光开发指标与逐篇错漏 |
| 20261020-tagging-iteration-009-validation/original-protocol.json | 曝光开发角色和旧参考来源 |
| 20261020-tagging-iteration-009-validation/protected-after.json | 历史文件原字节与第三留出保护 |
| 20261020-tagging-iteration-009-validation/protected-before.json | 503个历史文件指纹 |
| 20261020-tagging-iteration-009-validation/protocol.json | 候选源码指纹及固定输入预算 |
| 20261020-tagging-iteration-009-validation/semantic-review.json | MR与MR-TADF的定义、拒绝映射和参考粒度疑点 |
| 20261020-tagging-iteration-009-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-009-validation/used001-audit.json | 每篇数量、实际变更及机械来源检查 |
| 20261020-tagging-iteration-009-validation/used001-baseline-metrics.json | 1.4.1冻结预测同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-009-validation/used001-frozen-output-hashes.json | 本轮输入与新预测冻结 |
| 20261020-tagging-iteration-009-validation/used001-gold-frozen.json | 原参考SHA未改 |
| 20261020-tagging-iteration-009-validation/used001-metrics.json | 三组曝光开发指标与逐篇错漏 |
| 20261020-tagging-iteration-009-validation/used001-protocol.json | 曝光开发角色和旧参考来源 |
| 20261020-tagging-iteration-009-validation/used002-audit.json | 每篇数量、实际变更及机械来源检查 |
| 20261020-tagging-iteration-009-validation/used002-baseline-metrics.json | 1.4.1冻结预测同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-009-validation/used002-frozen-output-hashes.json | 本轮输入与新预测冻结 |
| 20261020-tagging-iteration-009-validation/used002-gold-frozen.json | 原参考SHA未改 |
| 20261020-tagging-iteration-009-validation/used002-metrics.json | 三组曝光开发指标与逐篇错漏 |
| 20261020-tagging-iteration-009-validation/used002-protocol.json | 曝光开发角色和旧参考来源 |
| 20261020-tagging-iteration-009-validation/validation.json | 候选软件验证与科学回归门分开记录 |

## 标签持续优化第10轮（2026-10-20）

[20261020-tagging-iteration-010.md](20261020-tagging-iteration-010.md)：有界摘要因果归属，初版复合否定失败保全与独立版本修订；最终开发补回1个超荧光，无新独立评测。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-010-validation/browser.log | 最终隔离页面回归 |
| 20261020-tagging-iteration-010-validation/check.log | 最终静态检查 |
| 20261020-tagging-iteration-010-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-010-validation/full-summary.json | 最终执行、唯一ID及组件结果 |
| 20261020-tagging-iteration-010-validation/full-tests.log | 最终候选完整项目真实日志 |
| 20261020-tagging-iteration-010-validation/initial-candidate-hashes.json | 初版1.4.2源码/预测/日志保全 |
| 20261020-tagging-iteration-010-validation/initial-full-summary.json | 初版2443软件测试通过，与语义探针失败区分 |
| 20261020-tagging-iteration-010-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-010-validation/literature-tests.log | 最终68项标签回归 |
| 20261020-tagging-iteration-010-validation/negation-probe-1.4.2.json | 初版3个复合否定错误原结果 |
| 20261020-tagging-iteration-010-validation/negation-probe-1.4.3.json | 修订后同一合成探针全部拒绝 |
| 20261020-tagging-iteration-010-validation/original-audit.json | 数量、实际改动和机械来源检查 |
| 20261020-tagging-iteration-010-validation/original-baseline-metrics.json | 冻结1.4.1预测同标准重算开发基线 |
| 20261020-tagging-iteration-010-validation/original-frozen-output-hashes.json | 固定输入与新预测冻结 |
| 20261020-tagging-iteration-010-validation/original-gold-frozen.json | 原gold SHA不变 |
| 20261020-tagging-iteration-010-validation/original-metrics.json | 三组曝光开发指标及逐篇错漏 |
| 20261020-tagging-iteration-010-validation/original-protocol.json | 开发角色及旧参考来源 |
| 20261020-tagging-iteration-010-validation/protected-after.json | 旧字节与第三留出封存 |
| 20261020-tagging-iteration-010-validation/protected-before.json | 590个旧文件保护 |
| 20261020-tagging-iteration-010-validation/protocol.json | 最终1.4.3候选源码指纹与固定预算 |
| 20261020-tagging-iteration-010-validation/revision-reason.json | 通用否定反例触发新版本，旧预测不覆盖 |
| 20261020-tagging-iteration-010-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-010-validation/used001-audit.json | 数量、实际改动和机械来源检查 |
| 20261020-tagging-iteration-010-validation/used001-baseline-metrics.json | 冻结1.4.1预测同标准重算开发基线 |
| 20261020-tagging-iteration-010-validation/used001-frozen-output-hashes.json | 固定输入与新预测冻结 |
| 20261020-tagging-iteration-010-validation/used001-gold-frozen.json | 原gold SHA不变 |
| 20261020-tagging-iteration-010-validation/used001-metrics.json | 三组曝光开发指标及逐篇错漏 |
| 20261020-tagging-iteration-010-validation/used001-protocol.json | 开发角色及旧参考来源 |
| 20261020-tagging-iteration-010-validation/used002-audit.json | 数量、实际改动和机械来源检查 |
| 20261020-tagging-iteration-010-validation/used002-baseline-metrics.json | 冻结1.4.1预测同标准重算开发基线 |
| 20261020-tagging-iteration-010-validation/used002-frozen-output-hashes.json | 固定输入与新预测冻结 |
| 20261020-tagging-iteration-010-validation/used002-gold-frozen.json | 原gold SHA不变 |
| 20261020-tagging-iteration-010-validation/used002-metrics.json | 三组曝光开发指标及逐篇错漏 |
| 20261020-tagging-iteration-010-validation/used002-protocol.json | 开发角色及旧参考来源 |
| 20261020-tagging-iteration-010-validation/validation.json | 软件检查、否定修订与无独立科学成绩 |

## 标签持续优化第11轮独立评测（2026-10-20）

[20261020-tagging-iteration-011.md](20261020-tagging-iteration-011.md)：1.4.3不改，第三组参考先冻后预测；一级P90.91/R64.52，二级P61.11/R40.74，无事后调参。第四组与40篇无重复并封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-011-validation/check.log | 15组件静态检查 |
| 20261020-tagging-iteration-011-validation/development-original-metrics.json | 沿用第10轮1.4.3开发，不冒称本轮重测 |
| 20261020-tagging-iteration-011-validation/development-used001-metrics.json | 沿用第10轮1.4.3开发，不冒称本轮重测 |
| 20261020-tagging-iteration-011-validation/development-used002-metrics.json | 沿用第10轮1.4.3开发，不冒称本轮重测 |
| 20261020-tagging-iteration-011-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-011-validation/full-summary.json | 全量执行、唯一ID、重复和组件结果 |
| 20261020-tagging-iteration-011-validation/full-tests.log | 本轮完整项目真实日志 |
| 20261020-tagging-iteration-011-validation/holdout-status-before.json | 第三组未打开原状态 |
| 20261020-tagging-iteration-011-validation/holdout-status-gold-frozen.json | gold冻结但尚无预测 |
| 20261020-tagging-iteration-011-validation/holdout-status-opened.json | 首次曝光且gold尚未冻结 |
| 20261020-tagging-iteration-011-validation/independent-audit.json | 每篇核心数、输入来源和机械证据检查 |
| 20261020-tagging-iteration-011-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-011-validation/next-disjoint-audit.json | 与40篇及组内无身份/原文/标题重叠 |
| 20261020-tagging-iteration-011-validation/next-frozen-output-hashes.json | 第四组固定输入指纹 |
| 20261020-tagging-iteration-011-validation/next-holdout-status.json | 第四组未读无gold/预测 |
| 20261020-tagging-iteration-011-validation/next-protocol.json | 第四组只按元信息冻结 |
| 20261020-tagging-iteration-011-validation/next-selection-exclusions.json | 第四组只按40篇身份/元信息排重 |
| 20261020-tagging-iteration-011-validation/protected-after.json | 不可变原字节与允许的曝光状态变化 |
| 20261020-tagging-iteration-011-validation/protected-before.json | 756个旧文件保护 |
| 20261020-tagging-iteration-011-validation/protocol.json | 曝光前1.4.3源码/开发指标指纹关联 |
| 20261020-tagging-iteration-011-validation/test-exposure-001.json | 冻结候选及开发之后首次打开 |
| 20261020-tagging-iteration-011-validation/test-frozen-output-hashes.json | 最初抽样与输入回执字节不变 |
| 20261020-tagging-iteration-011-validation/test-gold-authoring-record.json | 助手同输入参考理由、精确区间与边界 |
| 20261020-tagging-iteration-011-validation/test-gold-frozen.json | 预测之前31/54参考冻结回执 |
| 20261020-tagging-iteration-011-validation/test-holdout-status.json | 第三组已使用且无事后调参 |
| 20261020-tagging-iteration-011-validation/test-metrics.json | 首次独立指标和逐篇错漏 |
| 20261020-tagging-iteration-011-validation/test-predictions-frozen.json | gold之后实际1.4.3预测回执 |
| 20261020-tagging-iteration-011-validation/test-protocol.json | 原抽样版本1.4.0不改，非当前分类版本 |
| 20261020-tagging-iteration-011-validation/update.log | 全局联动更新 |
| 20261020-tagging-iteration-011-validation/validation.json | 软件通过与科学细标签不足分开 |

## 标签持续优化第12轮（2026-10-20）

[20261020-tagging-iteration-012.md](20261020-tagging-iteration-012.md)：旁支/一般机制不借邻近贡献词，原证据保留；四组已曝光开发，第三组FP14→11、TP22/FN32不变，无新独立成绩。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-012-validation/browser.log | 隔离页面回归 |
| 20261020-tagging-iteration-012-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-012-validation/development-roles.json | 四组当前开发角色与历史独立回执区分 |
| 20261020-tagging-iteration-012-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-012-validation/full-summary.json | 执行、唯一ID、重复及组件结果 |
| 20261020-tagging-iteration-012-validation/full-tests.log | 全项目真实执行日志 |
| 20261020-tagging-iteration-012-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-012-validation/literature-tests.log | 75项标签回归 |
| 20261020-tagging-iteration-012-validation/original-audit.json | 每篇数量、实际变更和机械来源 |
| 20261020-tagging-iteration-012-validation/original-baseline-metrics.json | 冻结1.4.3预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-012-validation/original-frozen-output-hashes.json | 原输入与本轮新预测冻结 |
| 20261020-tagging-iteration-012-validation/original-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-012-validation/original-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-012-validation/original-protocol.json | 曝光开发角色和原参考来源 |
| 20261020-tagging-iteration-012-validation/protected-after.json | 旧字节与第四留出封存 |
| 20261020-tagging-iteration-012-validation/protected-before.json | 813个旧文件指纹 |
| 20261020-tagging-iteration-012-validation/protocol.json | 候选源码及单项核心筛选改进 |
| 20261020-tagging-iteration-012-validation/retention-audit.json | 3个降级标签原证据完全保留 |
| 20261020-tagging-iteration-012-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-012-validation/used001-audit.json | 每篇数量、实际变更和机械来源 |
| 20261020-tagging-iteration-012-validation/used001-baseline-metrics.json | 冻结1.4.3预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-012-validation/used001-frozen-output-hashes.json | 原输入与本轮新预测冻结 |
| 20261020-tagging-iteration-012-validation/used001-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-012-validation/used001-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-012-validation/used001-protocol.json | 曝光开发角色和原参考来源 |
| 20261020-tagging-iteration-012-validation/used002-audit.json | 每篇数量、实际变更和机械来源 |
| 20261020-tagging-iteration-012-validation/used002-baseline-metrics.json | 冻结1.4.3预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-012-validation/used002-frozen-output-hashes.json | 原输入与本轮新预测冻结 |
| 20261020-tagging-iteration-012-validation/used002-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-012-validation/used002-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-012-validation/used002-protocol.json | 曝光开发角色和原参考来源 |
| 20261020-tagging-iteration-012-validation/used003-audit.json | 每篇数量、实际变更和机械来源 |
| 20261020-tagging-iteration-012-validation/used003-baseline-metrics.json | 冻结1.4.3预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-012-validation/used003-frozen-output-hashes.json | 原输入与本轮新预测冻结 |
| 20261020-tagging-iteration-012-validation/used003-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-012-validation/used003-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-012-validation/used003-protocol.json | 曝光开发角色和原参考来源 |
| 20261020-tagging-iteration-012-validation/validation.json | 软件验收与无当前独立成绩分开 |

## 标签持续优化第13轮（2026-10-20）

[20261020-tagging-iteration-013.md](20261020-tagging-iteration-013.md)：时间分辨词形候选开发核心指标不变，新增2篇辅助证据；否定反例失败，候选隔离未提升，当前仍1.4.4，无新独立成绩。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-013-validation/baseline-negation-probes.json | 活动旧别名否定缺陷复现 |
| 20261020-tagging-iteration-013-validation/browser.log | 隔离页面回归 |
| 20261020-tagging-iteration-013-validation/candidate-decision.json | 反例失败候选保留及活动源码恢复 |
| 20261020-tagging-iteration-013-validation/candidate-literature-tests.log | 候选82项1失败原始日志 |
| 20261020-tagging-iteration-013-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-013-validation/development-roles.json | 四组当前开发角色与历史独立记录区分 |
| 20261020-tagging-iteration-013-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-013-validation/full-summary.json | 活动工作区执行/唯一ID/重复及组件结果 |
| 20261020-tagging-iteration-013-validation/full-tests.log | 活动工作区全项目真实执行日志，不含隔离候选 |
| 20261020-tagging-iteration-013-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-013-validation/negation-probes.json | 合成否定候选失败探针 |
| 20261020-tagging-iteration-013-validation/original-audit.json | 每篇数量及机械来源检查 |
| 20261020-tagging-iteration-013-validation/original-baseline-metrics.json | 活动1.4.4冻结预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-013-validation/original-frozen-output-hashes.json | 同输入候选预测冻结 |
| 20261020-tagging-iteration-013-validation/original-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-013-validation/original-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-013-validation/original-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-013-validation/protected-after.json | 原历史字节不变及第四留出封存 |
| 20261020-tagging-iteration-013-validation/protected-before.json | 914个旧文件指纹 |
| 20261020-tagging-iteration-013-validation/protocol.json | 隔离候选词形改动及源码指纹 |
| 20261020-tagging-iteration-013-validation/retention-audit.json | 621条旧标签证据保留 |
| 20261020-tagging-iteration-013-validation/stable-literature-tests.log | 恢复活动源码75项通过 |
| 20261020-tagging-iteration-013-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-013-validation/used001-audit.json | 每篇数量及机械来源检查 |
| 20261020-tagging-iteration-013-validation/used001-baseline-metrics.json | 活动1.4.4冻结预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-013-validation/used001-frozen-output-hashes.json | 同输入候选预测冻结 |
| 20261020-tagging-iteration-013-validation/used001-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-013-validation/used001-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-013-validation/used001-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-013-validation/used002-audit.json | 每篇数量及机械来源检查 |
| 20261020-tagging-iteration-013-validation/used002-baseline-metrics.json | 活动1.4.4冻结预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-013-validation/used002-frozen-output-hashes.json | 同输入候选预测冻结 |
| 20261020-tagging-iteration-013-validation/used002-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-013-validation/used002-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-013-validation/used002-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-013-validation/used003-audit.json | 每篇数量及机械来源检查 |
| 20261020-tagging-iteration-013-validation/used003-baseline-metrics.json | 活动1.4.4冻结预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-013-validation/used003-frozen-output-hashes.json | 同输入候选预测冻结 |
| 20261020-tagging-iteration-013-validation/used003-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-013-validation/used003-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-013-validation/used003-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-013-validation/validation.json | 候选失败与活动工作区软件通过分开 |

## 标签持续优化第14轮（2026-10-20）

[20261020-tagging-iteration-014.md](20261020-tagging-iteration-014.md)：方法否定子句归属。初版1.4.6共享助动词探针失败保留，最终1.4.7通过；四组曝光开发指标及原证据不变，无新独立成绩。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-014-validation/browser.log | 隔离页面回归 |
| 20261020-tagging-iteration-014-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-014-validation/development-roles.json | 四组当前开发角色及历史独立回执 |
| 20261020-tagging-iteration-014-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-014-validation/full-summary.json | 执行/唯一ID/重复及组件结果 |
| 20261020-tagging-iteration-014-validation/full-tests.log | 最终确切源码全项目日志 |
| 20261020-tagging-iteration-014-validation/initial-extra-probes.log | 初版额外8项探针1失败，保留失败断言 |
| 20261020-tagging-iteration-014-validation/initial-protocol.json | 初版1.4.6冻结不提升 |
| 20261020-tagging-iteration-014-validation/initial-shared-auxiliary-probe.json | 共享否定助动词失败证据 |
| 20261020-tagging-iteration-014-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-014-validation/literature-tests.log | 最终83项标签测试通过 |
| 20261020-tagging-iteration-014-validation/original-audit.json | 每篇数量及机械来源 |
| 20261020-tagging-iteration-014-validation/original-baseline-metrics.json | 活动1.4.4预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-014-validation/original-frozen-output-hashes.json | 相同输入与最终预测冻结 |
| 20261020-tagging-iteration-014-validation/original-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-014-validation/original-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-014-validation/original-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-014-validation/polarity-probes.json | 合成否定/肯定前后探针，不计文献指标 |
| 20261020-tagging-iteration-014-validation/protected-after.json | 原历史字节与第四留出封存 |
| 20261020-tagging-iteration-014-validation/protected-before.json | 全部旧文件指纹 |
| 20261020-tagging-iteration-014-validation/protocol.json | 最终1.4.7源码冻结及单项否定改进 |
| 20261020-tagging-iteration-014-validation/retention-audit.json | 621条原证据及核心/辅助/继承不变 |
| 20261020-tagging-iteration-014-validation/tests-frozen.json | 最终回归文件指纹 |
| 20261020-tagging-iteration-014-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-014-validation/used001-audit.json | 每篇数量及机械来源 |
| 20261020-tagging-iteration-014-validation/used001-baseline-metrics.json | 活动1.4.4预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-014-validation/used001-frozen-output-hashes.json | 相同输入与最终预测冻结 |
| 20261020-tagging-iteration-014-validation/used001-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-014-validation/used001-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-014-validation/used001-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-014-validation/used002-audit.json | 每篇数量及机械来源 |
| 20261020-tagging-iteration-014-validation/used002-baseline-metrics.json | 活动1.4.4预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-014-validation/used002-frozen-output-hashes.json | 相同输入与最终预测冻结 |
| 20261020-tagging-iteration-014-validation/used002-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-014-validation/used002-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-014-validation/used002-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-014-validation/used003-audit.json | 每篇数量及机械来源 |
| 20261020-tagging-iteration-014-validation/used003-baseline-metrics.json | 活动1.4.4预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-014-validation/used003-frozen-output-hashes.json | 相同输入与最终预测冻结 |
| 20261020-tagging-iteration-014-validation/used003-gold-frozen.json | 原参考指纹不变 |
| 20261020-tagging-iteration-014-validation/used003-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-014-validation/used003-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-014-validation/validation.json | 软件验收与科学开发指标不变分开 |

## 标签持续优化第15轮（2026-10-20）

[20261020-tagging-iteration-015.md](20261020-tagging-iteration-015.md)：时间分辨词形在现有否定守卫下通过原失败断言；四组开发核心指标不变，2篇新增辅助，旧证据保留，无新独立成绩。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-015-validation/browser.log | 隔离页面回归 |
| 20261020-tagging-iteration-015-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-015-validation/development-roles.json | 四组开发角色与历史独立成绩区分 |
| 20261020-tagging-iteration-015-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-015-validation/full-summary.json | 执行/唯一ID/重复及组件结果 |
| 20261020-tagging-iteration-015-validation/full-tests.log | 最终确切源码全项目日志 |
| 20261020-tagging-iteration-015-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-015-validation/literature-tests.log | 91项标签回归，原失败断言现通过 |
| 20261020-tagging-iteration-015-validation/original-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-015-validation/original-baseline-metrics.json | 冻结1.4.7预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-015-validation/original-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-015-validation/original-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-015-validation/original-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-015-validation/original-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-015-validation/protected-after.json | 历史字节与第四留出封存 |
| 20261020-tagging-iteration-015-validation/protected-before.json | 全部旧文件指纹 |
| 20261020-tagging-iteration-015-validation/protocol.json | 最终源码冻结及单项词形改进 |
| 20261020-tagging-iteration-015-validation/retention-audit.json | 621条原证据保留、2篇新增辅助 |
| 20261020-tagging-iteration-015-validation/source-scope-audit.json | 仅一标签词形变化、否定/核心/输入守卫不变 |
| 20261020-tagging-iteration-015-validation/tests-frozen.json | 原失败断言及新词形否定组合测试指纹 |
| 20261020-tagging-iteration-015-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-015-validation/used001-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-015-validation/used001-baseline-metrics.json | 冻结1.4.7预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-015-validation/used001-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-015-validation/used001-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-015-validation/used001-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-015-validation/used001-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-015-validation/used002-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-015-validation/used002-baseline-metrics.json | 冻结1.4.7预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-015-validation/used002-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-015-validation/used002-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-015-validation/used002-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-015-validation/used002-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-015-validation/used003-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-015-validation/used003-baseline-metrics.json | 冻结1.4.7预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-015-validation/used003-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-015-validation/used003-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-015-validation/used003-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-015-validation/used003-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-015-validation/validation.json | 软件验收与无当前独立成绩分开 |

## 标签持续优化第16轮（2026-10-20）

[20261020-tagging-iteration-016.md](20261020-tagging-iteration-016.md)：明确方法主语的科学结果归因可核心，原证据不变；第三曝光开发补1个正确细标、FP11不增，无新独立成绩。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-016-validation/browser.log | 隔离页面回归 |
| 20261020-tagging-iteration-016-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-016-validation/development-roles.json | 四组开发角色与历史独立成绩区分 |
| 20261020-tagging-iteration-016-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-016-validation/full-summary.json | 执行/唯一ID/重复及组件结果 |
| 20261020-tagging-iteration-016-validation/full-tests.log | 最终确切源码全项目日志 |
| 20261020-tagging-iteration-016-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-016-validation/literature-tests.log | 99项标签回归，方法主语/科学双论元及来源边界 |
| 20261020-tagging-iteration-016-validation/original-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-016-validation/original-baseline-metrics.json | 冻结1.4.8预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-016-validation/original-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-016-validation/original-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-016-validation/original-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-016-validation/original-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-016-validation/pre-freeze-source-admission-test.log | 初测来源准入边界错误原日志；非最终失败 |
| 20261020-tagging-iteration-016-validation/protected-after.json | 历史字节与第四留出封存 |
| 20261020-tagging-iteration-016-validation/protected-before.json | 全部旧文件指纹 |
| 20261020-tagging-iteration-016-validation/protocol.json | 最终源码冻结及单项方法核心归因改进 |
| 20261020-tagging-iteration-016-validation/retention-audit.json | 624条原证据不变、1个方法辅助升核心 |
| 20261020-tagging-iteration-016-validation/source-scope-audit.json | 仅方法核心归因实现变化、词表/来源/输入不变 |
| 20261020-tagging-iteration-016-validation/tests-frozen.json | 方法归因正反例与来源门隔离测试指纹 |
| 20261020-tagging-iteration-016-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-016-validation/used001-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-016-validation/used001-baseline-metrics.json | 冻结1.4.8预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-016-validation/used001-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-016-validation/used001-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-016-validation/used001-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-016-validation/used001-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-016-validation/used002-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-016-validation/used002-baseline-metrics.json | 冻结1.4.8预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-016-validation/used002-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-016-validation/used002-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-016-validation/used002-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-016-validation/used002-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-016-validation/used003-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-016-validation/used003-baseline-metrics.json | 冻结1.4.8预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-016-validation/used003-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-016-validation/used003-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-016-validation/used003-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-016-validation/used003-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-016-validation/validation.json | 软件验收与无当前独立成绩分开 |

## 标签持续优化第17轮（2026-10-20）

[20261020-tagging-iteration-017.md](20261020-tagging-iteration-017.md)：方法使用完整词形及既有明确实验结果依据。四组曝光开发核心指标不变，1条误准入原证据归档，同标签真实依据保留；无新独立成绩。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-017-validation/admission-delta-summary.json | 撤下误准入证据的页码/区间/hash，无原文 |
| 20261020-tagging-iteration-017-validation/admission-probes.json | 合成前后准入探针，不计文献指标 |
| 20261020-tagging-iteration-017-validation/browser.log | 隔离页面回归 |
| 20261020-tagging-iteration-017-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-017-validation/development-roles.json | 四组开发角色与历史独立成绩区分 |
| 20261020-tagging-iteration-017-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-017-validation/full-summary.json | 执行/唯一ID/重复及组件结果 |
| 20261020-tagging-iteration-017-validation/full-tests.log | 最终确切源码全项目日志 |
| 20261020-tagging-iteration-017-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-017-validation/literature-tests.log | 106项标签回归，完整词形/误词干/明确实验结果 |
| 20261020-tagging-iteration-017-validation/original-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-017-validation/original-baseline-metrics.json | 冻结1.4.9预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-017-validation/original-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-017-validation/original-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-017-validation/original-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-017-validation/original-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-017-validation/pre-freeze-deposit-form-test.log | 初测deposit基本形遗漏，冻结前修复的原日志 |
| 20261020-tagging-iteration-017-validation/protected-after.json | 历史字节与第四留出封存 |
| 20261020-tagging-iteration-017-validation/protected-before.json | 全部旧文件指纹 |
| 20261020-tagging-iteration-017-validation/protocol.json | 最终源码冻结及完整方法使用词形 |
| 20261020-tagging-iteration-017-validation/retention-audit.json | 623条仍准入、1条旧误准入原样归档 |
| 20261020-tagging-iteration-017-validation/source-scope-audit.json | 仅方法准入实现变化、核心/词表/输入原字节不变 |
| 20261020-tagging-iteration-017-validation/tests-frozen.json | 完整词形及名词化实验结果测试指纹 |
| 20261020-tagging-iteration-017-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-017-validation/used001-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-017-validation/used001-baseline-metrics.json | 冻结1.4.9预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-017-validation/used001-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-017-validation/used001-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-017-validation/used001-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-017-validation/used001-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-017-validation/used002-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-017-validation/used002-baseline-metrics.json | 冻结1.4.9预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-017-validation/used002-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-017-validation/used002-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-017-validation/used002-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-017-validation/used002-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-017-validation/used003-audit.json | 每篇核心数及机械来源 |
| 20261020-tagging-iteration-017-validation/used003-baseline-metrics.json | 冻结1.4.9预测同标准重算，仅开发基线 |
| 20261020-tagging-iteration-017-validation/used003-frozen-output-hashes.json | 相同输入与候选预测冻结 |
| 20261020-tagging-iteration-017-validation/used003-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-017-validation/used003-metrics.json | 固定标准开发指标与逐篇错漏 |
| 20261020-tagging-iteration-017-validation/used003-protocol.json | 曝光开发角色和参考来源 |
| 20261020-tagging-iteration-017-validation/validation.json | 软件验收与无当前独立成绩分开 |

## 标签持续优化第18轮独立评测（2026-10-20）

[20261020-tagging-iteration-018.md](20261020-tagging-iteration-018.md)：1.4.10不改，第四组25/56参考先冻再预测，一级P88.24/R60.00、二级P60.00/R26.79，细标覆盖不足；无调参，第五组与50篇无重复并封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-018-validation/check.log | 静态接口检查 |
| 20261020-tagging-iteration-018-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-018-validation/full-summary.json | 执行/唯一ID/重复及组件结果 |
| 20261020-tagging-iteration-018-validation/full-tests.log | 本轮完整项目真实日志，含106项literature |
| 20261020-tagging-iteration-018-validation/holdout-opened.json | 开发/候选冻结后首次打开且无预测 |
| 20261020-tagging-iteration-018-validation/holdout-status-after.json | 第四组已用且无事后调参 |
| 20261020-tagging-iteration-018-validation/holdout-status-before.json | 第四组原未打开状态 |
| 20261020-tagging-iteration-018-validation/independent-audit.json | 逐篇数量、机械引文/来源及输入问题 |
| 20261020-tagging-iteration-018-validation/links.log | 全局链接检查 |
| 20261020-tagging-iteration-018-validation/next-disjoint-audit.json | 与50篇及组内无身份/源hash/标题重复 |
| 20261020-tagging-iteration-018-validation/next-frozen-output-hashes.json | 第五组未见输入指纹 |
| 20261020-tagging-iteration-018-validation/next-holdout-status.json | 第五组未读无gold/预测 |
| 20261020-tagging-iteration-018-validation/next-protocol.json | 第五组只按元信息冻结 |
| 20261020-tagging-iteration-018-validation/next-selection-exclusions.json | 下一组只按50篇元信息排除 |
| 20261020-tagging-iteration-018-validation/original-audit.json | 逐篇开发数量及机械引文/来源 |
| 20261020-tagging-iteration-018-validation/original-frozen-output-hashes.json | 原输入与本轮同规则开发预测冻结 |
| 20261020-tagging-iteration-018-validation/original-gold-frozen.json | 旧参考指纹不变 |
| 20261020-tagging-iteration-018-validation/original-metrics.json | 本轮固定曝光开发成绩，非新独立结果 |
| 20261020-tagging-iteration-018-validation/protected-after-independent.json | 旧字节不变与允许的曝光状态前后hash |
| 20261020-tagging-iteration-018-validation/protected-before.json | 旧不可变文件指纹；仅排除第四组可变曝光状态 |
| 20261020-tagging-iteration-018-validation/protocol.json | 独立曝光前源码及四组开发冻结时点 |
| 20261020-tagging-iteration-018-validation/test-frozen-output-hashes.json | 原抽样输入/协议/清单hash不变 |
| 20261020-tagging-iteration-018-validation/test-gold-frozen.json | 预测前25/56参考及81证据冻结回执 |
| 20261020-tagging-iteration-018-validation/test-metrics.json | 第四组首次独立指标和逐篇错漏 |
| 20261020-tagging-iteration-018-validation/test-predictions-frozen.json | gold后实际1.4.10预测及源码指纹 |
| 20261020-tagging-iteration-018-validation/test-protocol.json | 最初1.4.3抽样协议保留，不冒称本轮分类版本 |
| 20261020-tagging-iteration-018-validation/update.log | 全局更新 |
| 20261020-tagging-iteration-018-validation/used001-audit.json | 逐篇开发数量及机械引文/来源 |
| 20261020-tagging-iteration-018-validation/used001-frozen-output-hashes.json | 原输入与本轮同规则开发预测冻结 |
| 20261020-tagging-iteration-018-validation/used001-gold-frozen.json | 旧参考指纹不变 |
| 20261020-tagging-iteration-018-validation/used001-metrics.json | 本轮固定曝光开发成绩，非新独立结果 |
| 20261020-tagging-iteration-018-validation/used002-audit.json | 逐篇开发数量及机械引文/来源 |
| 20261020-tagging-iteration-018-validation/used002-frozen-output-hashes.json | 原输入与本轮同规则开发预测冻结 |
| 20261020-tagging-iteration-018-validation/used002-gold-frozen.json | 旧参考指纹不变 |
| 20261020-tagging-iteration-018-validation/used002-metrics.json | 本轮固定曝光开发成绩，非新独立结果 |
| 20261020-tagging-iteration-018-validation/used003-audit.json | 逐篇开发数量及机械引文/来源 |
| 20261020-tagging-iteration-018-validation/used003-frozen-output-hashes.json | 原输入与本轮同规则开发预测冻结 |
| 20261020-tagging-iteration-018-validation/used003-gold-frozen.json | 旧参考指纹不变 |
| 20261020-tagging-iteration-018-validation/used003-metrics.json | 本轮固定曝光开发成绩，非新独立结果 |
| 20261020-tagging-iteration-018-validation/validation.json | 软件通过与独立细标不足分开 |

## 标签持续优化第19轮（2026-10-20）

[20261020-tagging-iteration-019.md](20261020-tagging-iteration-019.md)：引用作者后紧邻被动句归属，五组曝光开发中第四组两级各减少1个误标；3条原证据留mentions。无当前独立成绩，第五组封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-019-validation/admission-delta-summary.json | 误准入转提及的来源/位置/hash，无原文 |
| 20261020-tagging-iteration-019-validation/admission-probes.json | 合成正反例前后结果，不计文献指标 |
| 20261020-tagging-iteration-019-validation/before-tests.log | 旧1.4.10在新增反例上5项失败，非最终测试 |
| 20261020-tagging-iteration-019-validation/check.log | 静态接口与依赖检查 |
| 20261020-tagging-iteration-019-validation/development-roles.json | 五组曝光开发与历史独立成绩区分 |
| 20261020-tagging-iteration-019-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-019-validation/full-summary.json | 执行/唯一ID/重复及组件实测结果 |
| 20261020-tagging-iteration-019-validation/full-tests.log | 确切候选源码全项目软件日志 |
| 20261020-tagging-iteration-019-validation/links.log | 全局链接与引用检查 |
| 20261020-tagging-iteration-019-validation/literature-tests.log | 115项标签最终回归 |
| 20261020-tagging-iteration-019-validation/mention-evidence-audit.json | 提及证据与引用前句机械校验 |
| 20261020-tagging-iteration-019-validation/original-audit.json | 每篇核心数/变化与机械来源 |
| 20261020-tagging-iteration-019-validation/original-baseline-metrics.json | 冻结1.4.10预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-019-validation/original-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-019-validation/original-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-019-validation/original-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-019-validation/original-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-019-validation/protected-after.json | 旧输入/标准/回执及第五留出原字节核对 |
| 20261020-tagging-iteration-019-validation/protected-before.json | 1609个历史文件指纹 |
| 20261020-tagging-iteration-019-validation/protocol.json | 五文件规则冻结与唯一改动范围 |
| 20261020-tagging-iteration-019-validation/retention-audit.json | 764条仍准入及3条mentions原依据保护 |
| 20261020-tagging-iteration-019-validation/source-scope-audit.json | 核心/词表/输入/评价代码原字节不变 |
| 20261020-tagging-iteration-019-validation/tests-frozen.json | 9项新归属测试源码指纹 |
| 20261020-tagging-iteration-019-validation/update.log | tools全局更新 |
| 20261020-tagging-iteration-019-validation/used001-audit.json | 每篇核心数/变化与机械来源 |
| 20261020-tagging-iteration-019-validation/used001-baseline-metrics.json | 冻结1.4.10预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-019-validation/used001-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-019-validation/used001-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-019-validation/used001-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-019-validation/used001-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-019-validation/used002-audit.json | 每篇核心数/变化与机械来源 |
| 20261020-tagging-iteration-019-validation/used002-baseline-metrics.json | 冻结1.4.10预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-019-validation/used002-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-019-validation/used002-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-019-validation/used002-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-019-validation/used002-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-019-validation/used003-audit.json | 每篇核心数/变化与机械来源 |
| 20261020-tagging-iteration-019-validation/used003-baseline-metrics.json | 冻结1.4.10预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-019-validation/used003-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-019-validation/used003-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-019-validation/used003-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-019-validation/used003-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-019-validation/used004-audit.json | 每篇核心数/变化与机械来源 |
| 20261020-tagging-iteration-019-validation/used004-baseline-metrics.json | 冻结1.4.10预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-019-validation/used004-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-019-validation/used004-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-019-validation/used004-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-019-validation/used004-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-019-validation/validation.json | 离线软件验收与科学覆盖边界 |

## 标签持续优化第20轮（2026-10-20）

[20261020-tagging-iteration-020.md](20261020-tagging-iteration-020.md)：一级标题beyond局部比较命中保留提及，不作整体标签否决。五组开发核心指标不变，1条标题依据转提及；摘要背景development词干问题未解决，无当前独立成绩，第五组封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-020-validation/admission-delta-summary.json | 比较标题转提及的来源/位置/hash，无原文 |
| 20261020-tagging-iteration-020-validation/admission-probes.json | 合成前后结果，不计真实文献指标 |
| 20261020-tagging-iteration-020-validation/before-tests.log | 旧1.4.11在新增测试上11个子例失败及1错误，非最终回归 |
| 20261020-tagging-iteration-020-validation/check.log | 静态接口与依赖检查 |
| 20261020-tagging-iteration-020-validation/development-roles.json | 五组曝光开发与历史独立成绩区分 |
| 20261020-tagging-iteration-020-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-020-validation/full-summary.json | 执行/唯一ID/重复及组件实测结果 |
| 20261020-tagging-iteration-020-validation/full-tests.log | 确切候选源码全项目软件日志 |
| 20261020-tagging-iteration-020-validation/links.log | 全局链接与引用检查 |
| 20261020-tagging-iteration-020-validation/literature-tests.log | 125项标签最终回归 |
| 20261020-tagging-iteration-020-validation/mention-evidence-audit.json | 所有提及及新标题/旧引用归属逐字校验 |
| 20261020-tagging-iteration-020-validation/mention-source-audit.json | 所有提及证据的层级来源检查 |
| 20261020-tagging-iteration-020-validation/original-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-020-validation/original-baseline-metrics.json | 冻结1.4.11预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-020-validation/original-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-020-validation/original-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-020-validation/original-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-020-validation/original-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-020-validation/protected-after.json | 旧输入/标准/回执及第五留出原字节核对 |
| 20261020-tagging-iteration-020-validation/protected-before.json | 1725个历史文件指纹 |
| 20261020-tagging-iteration-020-validation/protocol.json | 五文件规则冻结与标题比较唯一改动 |
| 20261020-tagging-iteration-020-validation/retention-audit.json | 763条仍准入、1条转提及及114条原mentions保护 |
| 20261020-tagging-iteration-020-validation/source-scope-audit.json | 核心/词表/输入/评价原字节不变 |
| 20261020-tagging-iteration-020-validation/tests-frozen.json | 10项标题比较测试源码指纹 |
| 20261020-tagging-iteration-020-validation/update.log | tools全局更新 |
| 20261020-tagging-iteration-020-validation/used001-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-020-validation/used001-baseline-metrics.json | 冻结1.4.11预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-020-validation/used001-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-020-validation/used001-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-020-validation/used001-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-020-validation/used001-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-020-validation/used002-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-020-validation/used002-baseline-metrics.json | 冻结1.4.11预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-020-validation/used002-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-020-validation/used002-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-020-validation/used002-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-020-validation/used002-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-020-validation/used003-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-020-validation/used003-baseline-metrics.json | 冻结1.4.11预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-020-validation/used003-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-020-validation/used003-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-020-validation/used003-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-020-validation/used003-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-020-validation/used004-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-020-validation/used004-baseline-metrics.json | 冻结1.4.11预测对同一标准重算，仅开发基线 |
| 20261020-tagging-iteration-020-validation/used004-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-020-validation/used004-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-020-validation/used004-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-020-validation/used004-protocol.json | 曝光开发角色与参考来源 |
| 20261020-tagging-iteration-020-validation/validation.json | 离线软件验收与未改善核心指标的边界 |

## 标签持续优化第21轮（2026-10-20启动）

[20261020-tagging-iteration-021.md](20261020-tagging-iteration-021.md)：最终1.4.14仅收紧元信息摘要及指代前句develop完整词，原文层保持基线。第四曝光开发一级FP1→0，二级不变；初版1.4.13真实二级退化留档未提升。无当前独立成绩，第五组封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261020-tagging-iteration-021-validation/admission-delta-summary.json | 退出准入的摘要位置/hash及真实可见状态，无原文 |
| 20261020-tagging-iteration-021-validation/admission-probes.json | 合成词形/归属探针，不计文献指标 |
| 20261020-tagging-iteration-021-validation/before-tests.log | 旧1.4.12在新增9项测试中的14个子例失败 |
| 20261020-tagging-iteration-021-validation/check.log | 静态接口与依赖检查 |
| 20261020-tagging-iteration-021-validation/development-roles.json | 五组曝光开发及初版失败/历史独立区分 |
| 20261020-tagging-iteration-021-validation/diff.log | 空白差异检查 |
| 20261020-tagging-iteration-021-validation/full-summary.json | 执行/唯一ID/重复及组件实测结果 |
| 20261020-tagging-iteration-021-validation/full-tests.log | 确切最终1.4.14全项目软件日志 |
| 20261020-tagging-iteration-021-validation/initial-candidate-failure.json | 初版真实二级开发退化及修订计划 |
| 20261020-tagging-iteration-021-validation/initial-literature-tests.log | 初版134项本地通过，不能替代开发集科学检查 |
| 20261020-tagging-iteration-021-validation/initial-protocol.json | 初版1.4.13全局FOCUS源码冻结，未提升 |
| 20261020-tagging-iteration-021-validation/links.log | 全局链接与引用检查 |
| 20261020-tagging-iteration-021-validation/literature-tests.log | 136项标签最终回归 |
| 20261020-tagging-iteration-021-validation/mention-evidence-audit.json | 所有提及证据精确位置及来源 |
| 20261020-tagging-iteration-021-validation/original-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-021-validation/original-baseline-metrics.json | 冻结1.4.12同标准重算，仅开发基线 |
| 20261020-tagging-iteration-021-validation/original-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-021-validation/original-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-021-validation/original-initial-metrics.json | 初版1.4.13同标准开发结果，保留真实退化 |
| 20261020-tagging-iteration-021-validation/original-metrics.json | 最终固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-021-validation/original-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-021-validation/pre-freeze-fixture-failure.json | 新合成夹具L1对象假设不成立的原因与修复边界 |
| 20261020-tagging-iteration-021-validation/pre-freeze-fixture-failure.log | 最终代码初测136项中的单个夹具失败原日志 |
| 20261020-tagging-iteration-021-validation/protected-after.json | 旧输入/标准/回执及初版原字节核对 |
| 20261020-tagging-iteration-021-validation/protected-before.json | 1951个历史及初版文件指纹 |
| 20261020-tagging-iteration-021-validation/protocol.json | 最终1.4.14五文件冻结与摘要范围 |
| 20261020-tagging-iteration-021-validation/retention-audit.json | 741条不变/22条归档/10条原输入可见及115条原mentions保护 |
| 20261020-tagging-iteration-021-validation/source-scope-audit.json | 原文FOCUS、核心/词表/输入/评价代码原字节保持 |
| 20261020-tagging-iteration-021-validation/tests-frozen.json | 最终11项词形与来源隔离测试指纹 |
| 20261020-tagging-iteration-021-validation/update.log | tools全局更新 |
| 20261020-tagging-iteration-021-validation/used001-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-021-validation/used001-baseline-metrics.json | 冻结1.4.12同标准重算，仅开发基线 |
| 20261020-tagging-iteration-021-validation/used001-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-021-validation/used001-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-021-validation/used001-initial-metrics.json | 初版1.4.13同标准开发结果，保留真实退化 |
| 20261020-tagging-iteration-021-validation/used001-metrics.json | 最终固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-021-validation/used001-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-021-validation/used002-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-021-validation/used002-baseline-metrics.json | 冻结1.4.12同标准重算，仅开发基线 |
| 20261020-tagging-iteration-021-validation/used002-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-021-validation/used002-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-021-validation/used002-initial-metrics.json | 初版1.4.13同标准开发结果，保留真实退化 |
| 20261020-tagging-iteration-021-validation/used002-metrics.json | 最终固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-021-validation/used002-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-021-validation/used003-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-021-validation/used003-baseline-metrics.json | 冻结1.4.12同标准重算，仅开发基线 |
| 20261020-tagging-iteration-021-validation/used003-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-021-validation/used003-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-021-validation/used003-initial-metrics.json | 初版1.4.13同标准开发结果，保留真实退化 |
| 20261020-tagging-iteration-021-validation/used003-metrics.json | 最终固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-021-validation/used003-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-021-validation/used004-audit.json | 每篇核心数量及机械来源 |
| 20261020-tagging-iteration-021-validation/used004-baseline-metrics.json | 冻结1.4.12同标准重算，仅开发基线 |
| 20261020-tagging-iteration-021-validation/used004-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261020-tagging-iteration-021-validation/used004-gold-frozen.json | 原参考指纹 |
| 20261020-tagging-iteration-021-validation/used004-initial-metrics.json | 初版1.4.13同标准开发结果，保留真实退化 |
| 20261020-tagging-iteration-021-validation/used004-metrics.json | 最终固定参考开发指标与逐篇错漏 |
| 20261020-tagging-iteration-021-validation/used004-protocol.json | 曝光开发角色与原参考来源 |
| 20261020-tagging-iteration-021-validation/validation.json | 最终离线软件验收、初版退化及科学覆盖边界 |

## 标签持续优化第22轮独立评测（2026-10-21）

[20261021-tagging-iteration-022.md](20261021-tagging-iteration-022.md)：1.4.14未改，第五组26/58参考与85条精确证据先冻后预测，一级P83.33/R57.69、二级P59.09/R22.41，细标覆盖不足；无调参，第六组与60篇无重复并封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-022-validation/check.log | 静态接口检查 |
| 20261021-tagging-iteration-022-validation/diff.log | 空白差异检查 |
| 20261021-tagging-iteration-022-validation/full-summary.json | 执行/唯一ID/重复与组件实测结果 |
| 20261021-tagging-iteration-022-validation/full-tests.log | 本轮完整项目日志，含136项literature |
| 20261021-tagging-iteration-022-validation/holdout-opened.json | 候选及五组开发冻结后首次打开，无预测 |
| 20261021-tagging-iteration-022-validation/holdout-status-after.json | 第五组单次已用、无事后调参 |
| 20261021-tagging-iteration-022-validation/holdout-status-before.json | 第五组原未见状态 |
| 20261021-tagging-iteration-022-validation/independent-audit.json | 逐篇核心数和机械引文/来源 |
| 20261021-tagging-iteration-022-validation/independent-identity-audit.json | 10篇当前原文与冻结context hash复核 |
| 20261021-tagging-iteration-022-validation/independent-mention-audit.json | 提及证据及层级来源 |
| 20261021-tagging-iteration-022-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-022-validation/next-disjoint-audit.json | 与60篇及组内身份/原文/标题无重复 |
| 20261021-tagging-iteration-022-validation/next-frozen-output-hashes.json | 第六组未见输入指纹 |
| 20261021-tagging-iteration-022-validation/next-holdout-status.json | 第六组未读无gold/预测 |
| 20261021-tagging-iteration-022-validation/next-protocol.json | 第六组只按元信息冻结 |
| 20261021-tagging-iteration-022-validation/next-selection-exclusions.json | 第六组只按60篇元信息排重 |
| 20261021-tagging-iteration-022-validation/original-audit.json | 每篇开发数量及机械来源 |
| 20261021-tagging-iteration-022-validation/original-frozen-output-hashes.json | 相同输入及开发预测冻结 |
| 20261021-tagging-iteration-022-validation/original-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-022-validation/original-metrics.json | 本轮相同规则曝光开发成绩，非独立结果 |
| 20261021-tagging-iteration-022-validation/pre-freeze-evidence-audit.json | 预测前纠正过细Xray参考，数量不变 |
| 20261021-tagging-iteration-022-validation/protected-after-independent.json | 历史字节保持与原状态前后hash |
| 20261021-tagging-iteration-022-validation/protected-before.json | 2067个旧不可变文件指纹，排除第五组可变曝光状态 |
| 20261021-tagging-iteration-022-validation/protocol.json | 独立曝光前源码及五组开发冻结时点 |
| 20261021-tagging-iteration-022-validation/test-frozen-output-hashes.json | 原抽样输入/清单/协议指纹 |
| 20261021-tagging-iteration-022-validation/test-gold-frozen.json | 预测前26/58参考及85证据冻结回执 |
| 20261021-tagging-iteration-022-validation/test-metrics.json | 第五组首次独立成绩及逐篇错漏 |
| 20261021-tagging-iteration-022-validation/test-predictions-frozen.json | gold后实际1.4.14预测/源码hash |
| 20261021-tagging-iteration-022-validation/test-protocol.json | 最初1.4.10抽样协议原字节保留 |
| 20261021-tagging-iteration-022-validation/update.log | 全局更新 |
| 20261021-tagging-iteration-022-validation/used001-audit.json | 每篇开发数量及机械来源 |
| 20261021-tagging-iteration-022-validation/used001-frozen-output-hashes.json | 相同输入及开发预测冻结 |
| 20261021-tagging-iteration-022-validation/used001-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-022-validation/used001-metrics.json | 本轮相同规则曝光开发成绩，非独立结果 |
| 20261021-tagging-iteration-022-validation/used002-audit.json | 每篇开发数量及机械来源 |
| 20261021-tagging-iteration-022-validation/used002-frozen-output-hashes.json | 相同输入及开发预测冻结 |
| 20261021-tagging-iteration-022-validation/used002-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-022-validation/used002-metrics.json | 本轮相同规则曝光开发成绩，非独立结果 |
| 20261021-tagging-iteration-022-validation/used003-audit.json | 每篇开发数量及机械来源 |
| 20261021-tagging-iteration-022-validation/used003-frozen-output-hashes.json | 相同输入及开发预测冻结 |
| 20261021-tagging-iteration-022-validation/used003-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-022-validation/used003-metrics.json | 本轮相同规则曝光开发成绩，非独立结果 |
| 20261021-tagging-iteration-022-validation/used004-audit.json | 每篇开发数量及机械来源 |
| 20261021-tagging-iteration-022-validation/used004-frozen-output-hashes.json | 相同输入及开发预测冻结 |
| 20261021-tagging-iteration-022-validation/used004-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-022-validation/used004-metrics.json | 本轮相同规则曝光开发成绩，非独立结果 |
| 20261021-tagging-iteration-022-validation/validation.json | 软件通过与独立科学覆盖不足分开 |

## 标签持续优化第23轮（2026-10-21）

[20261021-tagging-iteration-023.md](20261021-tagging-iteration-023.md)：编号多作者书目结构覆盖错误章节归属，保留逐字追踪；六组开发二级去1误标、TP/FN不变，无新独立成绩，第六留出封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-023-validation/admission-delta-summary.json | 退出准入的来源/位置/hash，不含原句 |
| 20261021-tagging-iteration-023-validation/before-tests.log | 旧规则在新增合成回归上9个子例失败及1错误，非候选最终回归 |
| 20261021-tagging-iteration-023-validation/check.log | 静态接口/依赖检查 |
| 20261021-tagging-iteration-023-validation/development-roles.json | 六组60篇曝光开发与历史独立成绩区分 |
| 20261021-tagging-iteration-023-validation/diff.log | 空白差异检查 |
| 20261021-tagging-iteration-023-validation/full-summary.json | 执行/唯一ID/重复与组件实测结果 |
| 20261021-tagging-iteration-023-validation/full-tests.log | 确切候选源码全项目软件日志 |
| 20261021-tagging-iteration-023-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-023-validation/literature-tests.log | 143项标签局部回归 |
| 20261021-tagging-iteration-023-validation/mention-source-audit.json | 162条提及逐字/来源及21条书目追踪校验 |
| 20261021-tagging-iteration-023-validation/original-audit.json | 每篇核心数量、证据与来源 |
| 20261021-tagging-iteration-023-validation/original-baseline-metrics.json | 冻结1.4.14预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-023-validation/original-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-023-validation/original-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-023-validation/original-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261021-tagging-iteration-023-validation/original-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-023-validation/protected-after.json | 旧输入/标准/回执及第六留出原字节核对 |
| 20261021-tagging-iteration-023-validation/protected-before.json | 2210个历史文件指纹 |
| 20261021-tagging-iteration-023-validation/protocol.json | 五文件候选冻结及唯一改动 |
| 20261021-tagging-iteration-023-validation/retention-audit.json | 894条原准入、4条转提及、140条原提及与8条原因细化 |
| 20261021-tagging-iteration-023-validation/source-scope-audit.json | 词表/核心/输入/评价不变及截断书目边界 |
| 20261021-tagging-iteration-023-validation/tests-frozen.json | 当前所有标签测试源码指纹，新增7项 |
| 20261021-tagging-iteration-023-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-023-validation/used001-audit.json | 每篇核心数量、证据与来源 |
| 20261021-tagging-iteration-023-validation/used001-baseline-metrics.json | 冻结1.4.14预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-023-validation/used001-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-023-validation/used001-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-023-validation/used001-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261021-tagging-iteration-023-validation/used001-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-023-validation/used002-audit.json | 每篇核心数量、证据与来源 |
| 20261021-tagging-iteration-023-validation/used002-baseline-metrics.json | 冻结1.4.14预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-023-validation/used002-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-023-validation/used002-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-023-validation/used002-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261021-tagging-iteration-023-validation/used002-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-023-validation/used003-audit.json | 每篇核心数量、证据与来源 |
| 20261021-tagging-iteration-023-validation/used003-baseline-metrics.json | 冻结1.4.14预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-023-validation/used003-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-023-validation/used003-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-023-validation/used003-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261021-tagging-iteration-023-validation/used003-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-023-validation/used004-audit.json | 每篇核心数量、证据与来源 |
| 20261021-tagging-iteration-023-validation/used004-baseline-metrics.json | 冻结1.4.14预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-023-validation/used004-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-023-validation/used004-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-023-validation/used004-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261021-tagging-iteration-023-validation/used004-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-023-validation/used005-audit.json | 每篇核心数量、证据与来源 |
| 20261021-tagging-iteration-023-validation/used005-baseline-metrics.json | 冻结1.4.14预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-023-validation/used005-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-023-validation/used005-gold-frozen.json | 旧参考指纹 |
| 20261021-tagging-iteration-023-validation/used005-metrics.json | 固定参考开发指标与逐篇错漏 |
| 20261021-tagging-iteration-023-validation/used005-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-023-validation/validation.json | 离线软件验收及未解决科学边界 |

## 标签持续优化第24轮（2026-10-21）

[20261021-tagging-iteration-024.md](20261021-tagging-iteration-024.md)：截断书目候选1.4.17局部154项通过，但固定开发丢1正确二级标签，候选/初版隔离保留；活动1.4.15 / 0.5.12恢复并验收，无新独立成绩，第六留出封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-024-validation/active-check.log | 恢复接口/依赖静态检查 |
| 20261021-tagging-iteration-024-validation/active-diff.log | 空白差异检查 |
| 20261021-tagging-iteration-024-validation/active-full-summary.json | 恢复活动版真实执行/唯一/重复及组件结果 |
| 20261021-tagging-iteration-024-validation/active-full-tests.log | 恢复活动1.4.15全项目日志，不属于候选1.4.17 |
| 20261021-tagging-iteration-024-validation/active-links.log | 恢复全局链接检查 |
| 20261021-tagging-iteration-024-validation/active-restoration.json | 五源码/包/依赖恢复及60篇实际预测对象一致 |
| 20261021-tagging-iteration-024-validation/active-tests-frozen.json | 恢复143项活动测试源码指纹 |
| 20261021-tagging-iteration-024-validation/active-tests.log | 恢复1.4.15活动143项局部回归 |
| 20261021-tagging-iteration-024-validation/active-update.log | 恢复全局update |
| 20261021-tagging-iteration-024-validation/admission-delta-summary.json | 退出准入的来源/位置/hash，不含原句 |
| 20261021-tagging-iteration-024-validation/candidate-decision.json | 最终候选固定开发退化及不提升决定 |
| 20261021-tagging-iteration-024-validation/candidate-tests.log | 最终1.4.17候选154项局部回归，不代表全量验收 |
| 20261021-tagging-iteration-024-validation/development-roles.json | 六组已曝光开发与历史独立成绩边界 |
| 20261021-tagging-iteration-024-validation/initial-before-tests.log | 旧1.4.15对新增9项回归的12失败子例及1错误 |
| 20261021-tagging-iteration-024-validation/initial-initial-full-summary.json | 仅属于1.4.16的2530次软件结果 |
| 20261021-tagging-iteration-024-validation/initial-initial-retention.json | 初版未提升及原软件结果边界 |
| 20261021-tagging-iteration-024-validation/initial-pre-freeze-debug.json | 冻结前期刊缩写吞标题末词失败与修正 |
| 20261021-tagging-iteration-024-validation/initial-pre-freeze-tests.log | 冻结前初始实现10失败子例及1错误 |
| 20261021-tagging-iteration-024-validation/initial-protocol.json | 初冻1.4.16来源hash |
| 20261021-tagging-iteration-024-validation/initial-retention-audit.json | 初版只清除辅助污染、未修目标残段 |
| 20261021-tagging-iteration-024-validation/mention-source-audit.json | 168条提及逐字/层级来源及7条残段追踪 |
| 20261021-tagging-iteration-024-validation/original-audit.json | 逐篇核心数量和证据/来源 |
| 20261021-tagging-iteration-024-validation/original-baseline-metrics.json | 活动1.4.15冻结预测对同一标准重算；恢复后60篇新预测与其完全一致 |
| 20261021-tagging-iteration-024-validation/original-frozen-output-hashes.json | 原输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-024-validation/original-gold-frozen.json | 原参考指纹 |
| 20261021-tagging-iteration-024-validation/original-metrics.json | 最终候选固定开发指标/错漏 |
| 20261021-tagging-iteration-024-validation/original-protocol.json | 最终候选曝光开发角色 |
| 20261021-tagging-iteration-024-validation/protected-after.json | 旧字节保持及第六留出封存 |
| 20261021-tagging-iteration-024-validation/protected-before.json | 2344个旧输入/标准/回执/留出指纹 |
| 20261021-tagging-iteration-024-validation/protocol.json | 最终候选五文件冻结及唯一归属规则 |
| 20261021-tagging-iteration-024-validation/retained-initial-hashes.json | 初冻1.4.16全部文件原字节保护 |
| 20261021-tagging-iteration-024-validation/retention-audit.json | 892条仍准入、3条转提及及168条提及保护 |
| 20261021-tagging-iteration-024-validation/revision-before-tests.log | 复合词边界在初冻1.4.16新增11项回归失败1项 |
| 20261021-tagging-iteration-024-validation/source-scope-audit.json | 未改科学词表/核心/输入及组合结构局限 |
| 20261021-tagging-iteration-024-validation/tests-frozen.json | 最终候选154项局部测试源码指纹 |
| 20261021-tagging-iteration-024-validation/used001-audit.json | 逐篇核心数量和证据/来源 |
| 20261021-tagging-iteration-024-validation/used001-baseline-metrics.json | 活动1.4.15冻结预测对同一标准重算；恢复后60篇新预测与其完全一致 |
| 20261021-tagging-iteration-024-validation/used001-frozen-output-hashes.json | 原输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-024-validation/used001-gold-frozen.json | 原参考指纹 |
| 20261021-tagging-iteration-024-validation/used001-metrics.json | 最终候选固定开发指标/错漏 |
| 20261021-tagging-iteration-024-validation/used001-protocol.json | 最终候选曝光开发角色 |
| 20261021-tagging-iteration-024-validation/used002-audit.json | 逐篇核心数量和证据/来源 |
| 20261021-tagging-iteration-024-validation/used002-baseline-metrics.json | 活动1.4.15冻结预测对同一标准重算；恢复后60篇新预测与其完全一致 |
| 20261021-tagging-iteration-024-validation/used002-frozen-output-hashes.json | 原输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-024-validation/used002-gold-frozen.json | 原参考指纹 |
| 20261021-tagging-iteration-024-validation/used002-metrics.json | 最终候选固定开发指标/错漏 |
| 20261021-tagging-iteration-024-validation/used002-protocol.json | 最终候选曝光开发角色 |
| 20261021-tagging-iteration-024-validation/used003-audit.json | 逐篇核心数量和证据/来源 |
| 20261021-tagging-iteration-024-validation/used003-baseline-metrics.json | 活动1.4.15冻结预测对同一标准重算；恢复后60篇新预测与其完全一致 |
| 20261021-tagging-iteration-024-validation/used003-frozen-output-hashes.json | 原输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-024-validation/used003-gold-frozen.json | 原参考指纹 |
| 20261021-tagging-iteration-024-validation/used003-metrics.json | 最终候选固定开发指标/错漏 |
| 20261021-tagging-iteration-024-validation/used003-protocol.json | 最终候选曝光开发角色 |
| 20261021-tagging-iteration-024-validation/used004-audit.json | 逐篇核心数量和证据/来源 |
| 20261021-tagging-iteration-024-validation/used004-baseline-metrics.json | 活动1.4.15冻结预测对同一标准重算；恢复后60篇新预测与其完全一致 |
| 20261021-tagging-iteration-024-validation/used004-frozen-output-hashes.json | 原输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-024-validation/used004-gold-frozen.json | 原参考指纹 |
| 20261021-tagging-iteration-024-validation/used004-metrics.json | 最终候选固定开发指标/错漏 |
| 20261021-tagging-iteration-024-validation/used004-protocol.json | 最终候选曝光开发角色 |
| 20261021-tagging-iteration-024-validation/used005-audit.json | 逐篇核心数量和证据/来源 |
| 20261021-tagging-iteration-024-validation/used005-baseline-metrics.json | 活动1.4.15冻结预测对同一标准重算；恢复后60篇新预测与其完全一致 |
| 20261021-tagging-iteration-024-validation/used005-frozen-output-hashes.json | 原输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-024-validation/used005-gold-frozen.json | 原参考指纹 |
| 20261021-tagging-iteration-024-validation/used005-metrics.json | 最终候选固定开发指标/错漏 |
| 20261021-tagging-iteration-024-validation/used005-protocol.json | 最终候选曝光开发角色 |
| 20261021-tagging-iteration-024-validation/validation.json | 候选科学退化与已验收活动版恢复分开 |

## 标签持续优化第25轮（2026-10-21）

[20261021-tagging-iteration-025.md](20261021-tagging-iteration-025.md)：最终1.4.19仅效率/EQE滚降复合词写法/单复数；六组开发补2正确二级核心、误标不增，初版1.4.18词间空白误标留档。无新独立成绩，第六留出封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-025-validation/admission-delta-summary.json | 新增依据位置/hash，不含原句 |
| 20261021-tagging-iteration-025-validation/before-tests.log | 旧1.4.15在新增11项回归中12个失败子例及1错误 |
| 20261021-tagging-iteration-025-validation/check.log | 最终接口/依赖静态检查 |
| 20261021-tagging-iteration-025-validation/development-roles.json | 六组曝光开发，独立历史及第六留出隔离 |
| 20261021-tagging-iteration-025-validation/diff.log | 空白差异检查 |
| 20261021-tagging-iteration-025-validation/final-tests.log | 最终1.4.19的155项局部回归 |
| 20261021-tagging-iteration-025-validation/full-summary.json | 执行/唯一ID/重复及组件真实结果 |
| 20261021-tagging-iteration-025-validation/full-tests.log | 确切最终源码的全项目软件日志 |
| 20261021-tagging-iteration-025-validation/initial-initial-decision.json | 词间空白引入背景核心FP及初版不提升决定 |
| 20261021-tagging-iteration-025-validation/initial-initial-local-tests.log | 初版154项局部通过，不冒称最终验收 |
| 20261021-tagging-iteration-025-validation/initial-protocol.json | 初版1.4.18/v8科学源码冻结 |
| 20261021-tagging-iteration-025-validation/initial-summary.json | 初版六组开发指标/逐篇数量及变化 |
| 20261021-tagging-iteration-025-validation/initial-tests-frozen.json | 初版154项测试源码指纹 |
| 20261021-tagging-iteration-025-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-025-validation/mention-source-audit.json | 全部提及的逐字和分层来源检查 |
| 20261021-tagging-iteration-025-validation/original-audit.json | 每篇核心数及机械来源 |
| 20261021-tagging-iteration-025-validation/original-baseline-metrics.json | 冻结1.4.15预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-025-validation/original-frozen-output-hashes.json | 相同输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-025-validation/original-gold-frozen.json | 原参考标准hash |
| 20261021-tagging-iteration-025-validation/original-metrics.json | 最终候选固定开发P/R/F1及错漏 |
| 20261021-tagging-iteration-025-validation/original-protocol.json | 曝光开发角色及实际规则 |
| 20261021-tagging-iteration-025-validation/protected-after.json | 历史输入/gold/回执/留出原字节核对 |
| 20261021-tagging-iteration-025-validation/protected-before.json | 2626个历史文件指纹 |
| 20261021-tagging-iteration-025-validation/protocol.json | 最终1.4.19源码/词表冻结与复合词限定范围 |
| 20261021-tagging-iteration-025-validation/retained-initial-hashes.json | 初冻1.4.18预测/测试/协议指纹 |
| 20261021-tagging-iteration-025-validation/retention-audit.json | 895条旧准入及162条提及原样保留，4条新增 |
| 20261021-tagging-iteration-025-validation/revision-before-tests.log | 最终限制多空白边界前，2个合法但未解决布局子例暴露初版范围 |
| 20261021-tagging-iteration-025-validation/source-scope-audit.json | 42ID未变、两条别名变化及未解决词间空白 |
| 20261021-tagging-iteration-025-validation/tests-frozen.json | 155项最终局部测试源码指纹，12项新增 |
| 20261021-tagging-iteration-025-validation/update.log | 全局更新 |
| 20261021-tagging-iteration-025-validation/used001-audit.json | 每篇核心数及机械来源 |
| 20261021-tagging-iteration-025-validation/used001-baseline-metrics.json | 冻结1.4.15预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-025-validation/used001-frozen-output-hashes.json | 相同输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-025-validation/used001-gold-frozen.json | 原参考标准hash |
| 20261021-tagging-iteration-025-validation/used001-metrics.json | 最终候选固定开发P/R/F1及错漏 |
| 20261021-tagging-iteration-025-validation/used001-protocol.json | 曝光开发角色及实际规则 |
| 20261021-tagging-iteration-025-validation/used002-audit.json | 每篇核心数及机械来源 |
| 20261021-tagging-iteration-025-validation/used002-baseline-metrics.json | 冻结1.4.15预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-025-validation/used002-frozen-output-hashes.json | 相同输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-025-validation/used002-gold-frozen.json | 原参考标准hash |
| 20261021-tagging-iteration-025-validation/used002-metrics.json | 最终候选固定开发P/R/F1及错漏 |
| 20261021-tagging-iteration-025-validation/used002-protocol.json | 曝光开发角色及实际规则 |
| 20261021-tagging-iteration-025-validation/used003-audit.json | 每篇核心数及机械来源 |
| 20261021-tagging-iteration-025-validation/used003-baseline-metrics.json | 冻结1.4.15预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-025-validation/used003-frozen-output-hashes.json | 相同输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-025-validation/used003-gold-frozen.json | 原参考标准hash |
| 20261021-tagging-iteration-025-validation/used003-metrics.json | 最终候选固定开发P/R/F1及错漏 |
| 20261021-tagging-iteration-025-validation/used003-protocol.json | 曝光开发角色及实际规则 |
| 20261021-tagging-iteration-025-validation/used004-audit.json | 每篇核心数及机械来源 |
| 20261021-tagging-iteration-025-validation/used004-baseline-metrics.json | 冻结1.4.15预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-025-validation/used004-frozen-output-hashes.json | 相同输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-025-validation/used004-gold-frozen.json | 原参考标准hash |
| 20261021-tagging-iteration-025-validation/used004-metrics.json | 最终候选固定开发P/R/F1及错漏 |
| 20261021-tagging-iteration-025-validation/used004-protocol.json | 曝光开发角色及实际规则 |
| 20261021-tagging-iteration-025-validation/used005-audit.json | 每篇核心数及机械来源 |
| 20261021-tagging-iteration-025-validation/used005-baseline-metrics.json | 冻结1.4.15预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-025-validation/used005-frozen-output-hashes.json | 相同输入/最终预测/协议/映射冻结 |
| 20261021-tagging-iteration-025-validation/used005-gold-frozen.json | 原参考标准hash |
| 20261021-tagging-iteration-025-validation/used005-metrics.json | 最终候选固定开发P/R/F1及错漏 |
| 20261021-tagging-iteration-025-validation/used005-protocol.json | 曝光开发角色及实际规则 |
| 20261021-tagging-iteration-025-validation/validation.json | 离线软件验收、开发收益及未解决边界分开 |

## 标签持续优化第26轮（2026-10-21）

[20261021-tagging-iteration-026.md](20261021-tagging-iteration-026.md)：仅问题泛指背景核心投票，167项局部通过；六组开发科学对象/指标不变，旧1.4.18已用误标组件回放降辅助不计新成绩，第六留出封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-026-validation/before-tests.log | 旧1.4.19在新增12项回归中5项失败 |
| 20261021-tagging-iteration-026-validation/check.log | 静态接口与依赖检查 |
| 20261021-tagging-iteration-026-validation/component-replay-audit.json | 旧1.4.18已曝光FP严格组件替换及完整基线重现，非当前指标 |
| 20261021-tagging-iteration-026-validation/development-roles.json | 六组开发与组件挑战/独立历史分开 |
| 20261021-tagging-iteration-026-validation/diff.log | 空白差异检查 |
| 20261021-tagging-iteration-026-validation/full-summary.json | 执行/唯一ID/重复和组件真实结果 |
| 20261021-tagging-iteration-026-validation/full-tests.log | 确切1.4.20源码全项目日志 |
| 20261021-tagging-iteration-026-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-026-validation/literature-tests.log | 167项局部回归 |
| 20261021-tagging-iteration-026-validation/mention-source-audit.json | 提及逐字/层级来源检查 |
| 20261021-tagging-iteration-026-validation/original-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-026-validation/original-baseline-metrics.json | 冻结1.4.19预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-026-validation/original-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-026-validation/original-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-026-validation/original-metrics.json | 固定开发P/R/F1及逐篇错漏，当前无变化 |
| 20261021-tagging-iteration-026-validation/original-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-026-validation/protected-after.json | 旧字节保持和第六留出封存 |
| 20261021-tagging-iteration-026-validation/protected-before.json | 2884个旧输入/gold/回执/留出指纹 |
| 20261021-tagging-iteration-026-validation/protocol.json | 五科学文件冻结及唯一问题背景核心投票改动 |
| 20261021-tagging-iteration-026-validation/retention-audit.json | 899条旧接受与162条提及及科学对象不变 |
| 20261021-tagging-iteration-026-validation/source-scope-audit.json | 词表/输入/准入不变及受控语境边界 |
| 20261021-tagging-iteration-026-validation/tests-frozen.json | 167项局部测试源码指纹，12项新增 |
| 20261021-tagging-iteration-026-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-026-validation/used001-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-026-validation/used001-baseline-metrics.json | 冻结1.4.19预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-026-validation/used001-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-026-validation/used001-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-026-validation/used001-metrics.json | 固定开发P/R/F1及逐篇错漏，当前无变化 |
| 20261021-tagging-iteration-026-validation/used001-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-026-validation/used002-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-026-validation/used002-baseline-metrics.json | 冻结1.4.19预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-026-validation/used002-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-026-validation/used002-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-026-validation/used002-metrics.json | 固定开发P/R/F1及逐篇错漏，当前无变化 |
| 20261021-tagging-iteration-026-validation/used002-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-026-validation/used003-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-026-validation/used003-baseline-metrics.json | 冻结1.4.19预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-026-validation/used003-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-026-validation/used003-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-026-validation/used003-metrics.json | 固定开发P/R/F1及逐篇错漏，当前无变化 |
| 20261021-tagging-iteration-026-validation/used003-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-026-validation/used004-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-026-validation/used004-baseline-metrics.json | 冻结1.4.19预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-026-validation/used004-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-026-validation/used004-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-026-validation/used004-metrics.json | 固定开发P/R/F1及逐篇错漏，当前无变化 |
| 20261021-tagging-iteration-026-validation/used004-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-026-validation/used005-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-026-validation/used005-baseline-metrics.json | 冻结1.4.19预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-026-validation/used005-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-026-validation/used005-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-026-validation/used005-metrics.json | 固定开发P/R/F1及逐篇错漏，当前无变化 |
| 20261021-tagging-iteration-026-validation/used005-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-026-validation/validation.json | 软件通过、开发指标不变与组件挑战边界 |

## 标签持续优化第27轮（2026-10-21）

[20261021-tagging-iteration-027.md](20261021-tagging-iteration-027.md)：限定词多空白识别，177项局部通过；六组开发核心指标不变，新增辅助/历史提及各1条，未新增核心误标，第六留出封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-027-validation/admission-delta-summary.json | 新增1条背景辅助证据的页/块/区间与hash |
| 20261021-tagging-iteration-027-validation/before-tests.log | 旧版在新布局要求中10失败及1证据未找到错误 |
| 20261021-tagging-iteration-027-validation/check.log | 静态接口与依赖检查 |
| 20261021-tagging-iteration-027-validation/development-roles.json | 六组曝光开发与独立历史分开 |
| 20261021-tagging-iteration-027-validation/diff.log | 空白差异检查 |
| 20261021-tagging-iteration-027-validation/full-summary.json | 执行/唯一ID/重复与组件真实结果 |
| 20261021-tagging-iteration-027-validation/full-tests.log | 确切1.4.21源码全项目日志 |
| 20261021-tagging-iteration-027-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-027-validation/literature-tests.log | 177项局部回归 |
| 20261021-tagging-iteration-027-validation/mention-delta-summary.json | 新增1条历史提及的来源及hash，不含原文 |
| 20261021-tagging-iteration-027-validation/mention-source-audit.json | 当前163条提及逐字与层级来源 |
| 20261021-tagging-iteration-027-validation/original-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-027-validation/original-baseline-metrics.json | 冻结1.4.20预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-027-validation/original-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-027-validation/original-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-027-validation/original-metrics.json | 固定开发P/R/F1及逐篇错漏，前后无变 |
| 20261021-tagging-iteration-027-validation/original-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-027-validation/protected-after.json | 旧字节保持和第六留出封存 |
| 20261021-tagging-iteration-027-validation/protected-before.json | 3018个旧输入/gold/回执/留出指纹 |
| 20261021-tagging-iteration-027-validation/protocol.json | 五科学文件冻结及唯一限定词多空白改动 |
| 20261021-tagging-iteration-027-validation/retention-audit.json | 899条旧接受和162条提及保留，核心指标无变 |
| 20261021-tagging-iteration-027-validation/source-scope-audit.json | 两个别名改动，focus/输入/准入/语义ID不变 |
| 20261021-tagging-iteration-027-validation/tests-frozen.json | 177项局部测试指纹及原测试有意更新说明 |
| 20261021-tagging-iteration-027-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-027-validation/used001-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-027-validation/used001-baseline-metrics.json | 冻结1.4.20预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-027-validation/used001-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-027-validation/used001-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-027-validation/used001-metrics.json | 固定开发P/R/F1及逐篇错漏，前后无变 |
| 20261021-tagging-iteration-027-validation/used001-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-027-validation/used002-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-027-validation/used002-baseline-metrics.json | 冻结1.4.20预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-027-validation/used002-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-027-validation/used002-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-027-validation/used002-metrics.json | 固定开发P/R/F1及逐篇错漏，前后无变 |
| 20261021-tagging-iteration-027-validation/used002-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-027-validation/used003-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-027-validation/used003-baseline-metrics.json | 冻结1.4.20预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-027-validation/used003-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-027-validation/used003-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-027-validation/used003-metrics.json | 固定开发P/R/F1及逐篇错漏，前后无变 |
| 20261021-tagging-iteration-027-validation/used003-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-027-validation/used004-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-027-validation/used004-baseline-metrics.json | 冻结1.4.20预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-027-validation/used004-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-027-validation/used004-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-027-validation/used004-metrics.json | 固定开发P/R/F1及逐篇错漏，前后无变 |
| 20261021-tagging-iteration-027-validation/used004-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-027-validation/used005-audit.json | 逐篇核心数、证据及来源 |
| 20261021-tagging-iteration-027-validation/used005-baseline-metrics.json | 冻结1.4.20预测对同一标准重算，仅开发基线 |
| 20261021-tagging-iteration-027-validation/used005-frozen-output-hashes.json | 输入/预测/协议/映射冻结 |
| 20261021-tagging-iteration-027-validation/used005-gold-frozen.json | 旧参考标准hash |
| 20261021-tagging-iteration-027-validation/used005-metrics.json | 固定开发P/R/F1及逐篇错漏，前后无变 |
| 20261021-tagging-iteration-027-validation/used005-protocol.json | 曝光开发角色及来源 |
| 20261021-tagging-iteration-027-validation/validation.json | 离线软件验收、当前开发无指标变化及独立边界 |

## 标签持续优化第28轮（2026-10-21）

[20261021-tagging-iteration-028.md](20261021-tagging-iteration-028.md)：固定1.4.21第六组单次独立评测，参考先冻后预测；一级P80/R30.77/F144.44、二级P62.5/R40.98/F149.5。保留疑似SI难例，源码不改、第七组封存，未达到可靠分类。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-028-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-028-validation/development-reuse.json | 六组开发同源码不重跑的原始逐文件hash |
| 20261021-tagging-iteration-028-validation/development-summary.json | 六组60篇固定开发指标/数量/来源 |
| 20261021-tagging-iteration-028-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-028-validation/full-summary.json | 真实全量执行/唯一/重复/失败统计 |
| 20261021-tagging-iteration-028-validation/full-tests.log | 未改1.4.21科学源码全项目日志 |
| 20261021-tagging-iteration-028-validation/identity-audit.json | 10份PDF/冻结上下文字节核对及语义身份边界 |
| 20261021-tagging-iteration-028-validation/independent006-audit.json | 逐篇参考/预测数和证据/来源/身份hash |
| 20261021-tagging-iteration-028-validation/independent006-disjoint-audit.json | 原006与先前60篇身份不重叠 |
| 20261021-tagging-iteration-028-validation/independent006-exposure.json | 首次打开、先参考后预测与已使用时间 |
| 20261021-tagging-iteration-028-validation/independent006-frozen-output-hashes.json | 原输入/抽样/本轮协议冻结 |
| 20261021-tagging-iteration-028-validation/independent006-gold-frozen.json | 26/61参考及87引文先于预测的冻结回执 |
| 20261021-tagging-iteration-028-validation/independent006-metrics.json | 本轮单次独立P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-028-validation/independent006-original-sampling-protocol.json | 原006元信息分层协议原字节 |
| 20261021-tagging-iteration-028-validation/independent006-predictions-frozen.json | 单次预测及科学文件指纹 |
| 20261021-tagging-iteration-028-validation/independent006-protocol.json | 本轮评测与旧抽样版本环境分开 |
| 20261021-tagging-iteration-028-validation/independent006-reference-selection-notes.json | 预测前助手主线选择理由与SI疑点，不含完整原文 |
| 20261021-tagging-iteration-028-validation/independent006-reference-validation-before-predictions.json | 生成预测前逐字参考校验 |
| 20261021-tagging-iteration-028-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-028-validation/next-holdout-receipt.json | 第七组未读/无预测和与70篇无重叠 |
| 20261021-tagging-iteration-028-validation/next-improvement.json | 下一项只诊断摘要被动结果插入修饰语 |
| 20261021-tagging-iteration-028-validation/next-selection-exclusions.json | 下轮分层样本按已用身份去重，不按错误选例 |
| 20261021-tagging-iteration-028-validation/protected-after.json | 旧字节不变，原封存快照与实际曝光分开 |
| 20261021-tagging-iteration-028-validation/protected-before.json | 历史冻结输入/参考/回执的只读指纹 |
| 20261021-tagging-iteration-028-validation/protocol.json | 同1.4.21源码及候选/开发先于独立输入打开 |
| 20261021-tagging-iteration-028-validation/reference-concepts.json | 32个评测专用词表外概念，无生产映射 |
| 20261021-tagging-iteration-028-validation/tests-frozen.json | 177项标签测试源码不变，无新增测试 |
| 20261021-tagging-iteration-028-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-028-validation/validation.json | 软件验收与独立结果/主文来源限制分别记录 |

## 标签持续优化第29轮（2026-10-21）

[20261021-tagging-iteration-029.md](20261021-tagging-iteration-029.md)：仅摘要首次被动结果主语；189项局部通过，七组开发补1个正确一级、误标不增、全部二级不变。1.4.21独立结果仅历史，第七留出封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-029-validation/before-tests.log | 旧1.4.21新被动要求17失败和1缺证据错误 |
| 20261021-tagging-iteration-029-validation/check.log | 静态接口依赖 |
| 20261021-tagging-iteration-029-validation/development-roles.json | 七组70篇已曝光开发及来源疑点保留 |
| 20261021-tagging-iteration-029-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-029-validation/evidence-delta-summary.json | 新接受及旧提及转移hash与区间摘要 |
| 20261021-tagging-iteration-029-validation/full-summary.json | 实际全量执行/唯一/重复/失败数 |
| 20261021-tagging-iteration-029-validation/full-tests.log | 确切1.4.22源码全量日志 |
| 20261021-tagging-iteration-029-validation/links.log | 全局链接 |
| 20261021-tagging-iteration-029-validation/literature-tests.log | 189项局部回归 |
| 20261021-tagging-iteration-029-validation/mention-source-audit.json | 191条当前提及逐字/来源 |
| 20261021-tagging-iteration-029-validation/original-audit.json | 逐篇核心数量、证据和来源 |
| 20261021-tagging-iteration-029-validation/original-baseline-metrics.json | 冻结1.4.21预测对同一gold重算，仅开发基线 |
| 20261021-tagging-iteration-029-validation/original-frozen-output-hashes.json | 新预测/旧输入/协议/映射冻结 |
| 20261021-tagging-iteration-029-validation/original-gold-frozen.json | 历史参考标准hash |
| 20261021-tagging-iteration-029-validation/original-metrics.json | 固定开发P/R/F1及逐篇错漏，非独立结果 |
| 20261021-tagging-iteration-029-validation/original-protocol.json | 已用开发角色与原参考来源 |
| 20261021-tagging-iteration-029-validation/protected-after.json | 历史字节保持及007无预测 |
| 20261021-tagging-iteration-029-validation/protected-before.json | 旧输入/gold/回执与第七留出指纹 |
| 20261021-tagging-iteration-029-validation/protocol.json | 五科学文件冻结及唯一级一摘要被动归属改动 |
| 20261021-tagging-iteration-029-validation/retention-audit.json | 1087旧接受保留和4提及转接受/继承归档 |
| 20261021-tagging-iteration-029-validation/source-scope-audit.json | AST与字节审计：原文/词表/旧模式不变 |
| 20261021-tagging-iteration-029-validation/tests-frozen.json | 189项标签测试指纹，12项新增且原测试不改 |
| 20261021-tagging-iteration-029-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-029-validation/used001-audit.json | 逐篇核心数量、证据和来源 |
| 20261021-tagging-iteration-029-validation/used001-baseline-metrics.json | 冻结1.4.21预测对同一gold重算，仅开发基线 |
| 20261021-tagging-iteration-029-validation/used001-frozen-output-hashes.json | 新预测/旧输入/协议/映射冻结 |
| 20261021-tagging-iteration-029-validation/used001-gold-frozen.json | 历史参考标准hash |
| 20261021-tagging-iteration-029-validation/used001-metrics.json | 固定开发P/R/F1及逐篇错漏，非独立结果 |
| 20261021-tagging-iteration-029-validation/used001-protocol.json | 已用开发角色与原参考来源 |
| 20261021-tagging-iteration-029-validation/used002-audit.json | 逐篇核心数量、证据和来源 |
| 20261021-tagging-iteration-029-validation/used002-baseline-metrics.json | 冻结1.4.21预测对同一gold重算，仅开发基线 |
| 20261021-tagging-iteration-029-validation/used002-frozen-output-hashes.json | 新预测/旧输入/协议/映射冻结 |
| 20261021-tagging-iteration-029-validation/used002-gold-frozen.json | 历史参考标准hash |
| 20261021-tagging-iteration-029-validation/used002-metrics.json | 固定开发P/R/F1及逐篇错漏，非独立结果 |
| 20261021-tagging-iteration-029-validation/used002-protocol.json | 已用开发角色与原参考来源 |
| 20261021-tagging-iteration-029-validation/used003-audit.json | 逐篇核心数量、证据和来源 |
| 20261021-tagging-iteration-029-validation/used003-baseline-metrics.json | 冻结1.4.21预测对同一gold重算，仅开发基线 |
| 20261021-tagging-iteration-029-validation/used003-frozen-output-hashes.json | 新预测/旧输入/协议/映射冻结 |
| 20261021-tagging-iteration-029-validation/used003-gold-frozen.json | 历史参考标准hash |
| 20261021-tagging-iteration-029-validation/used003-metrics.json | 固定开发P/R/F1及逐篇错漏，非独立结果 |
| 20261021-tagging-iteration-029-validation/used003-protocol.json | 已用开发角色与原参考来源 |
| 20261021-tagging-iteration-029-validation/used004-audit.json | 逐篇核心数量、证据和来源 |
| 20261021-tagging-iteration-029-validation/used004-baseline-metrics.json | 冻结1.4.21预测对同一gold重算，仅开发基线 |
| 20261021-tagging-iteration-029-validation/used004-frozen-output-hashes.json | 新预测/旧输入/协议/映射冻结 |
| 20261021-tagging-iteration-029-validation/used004-gold-frozen.json | 历史参考标准hash |
| 20261021-tagging-iteration-029-validation/used004-metrics.json | 固定开发P/R/F1及逐篇错漏，非独立结果 |
| 20261021-tagging-iteration-029-validation/used004-protocol.json | 已用开发角色与原参考来源 |
| 20261021-tagging-iteration-029-validation/used005-audit.json | 逐篇核心数量、证据和来源 |
| 20261021-tagging-iteration-029-validation/used005-baseline-metrics.json | 冻结1.4.21预测对同一gold重算，仅开发基线 |
| 20261021-tagging-iteration-029-validation/used005-frozen-output-hashes.json | 新预测/旧输入/协议/映射冻结 |
| 20261021-tagging-iteration-029-validation/used005-gold-frozen.json | 历史参考标准hash |
| 20261021-tagging-iteration-029-validation/used005-metrics.json | 固定开发P/R/F1及逐篇错漏，非独立结果 |
| 20261021-tagging-iteration-029-validation/used005-protocol.json | 已用开发角色与原参考来源 |
| 20261021-tagging-iteration-029-validation/used006-audit.json | 逐篇核心数量、证据和来源 |
| 20261021-tagging-iteration-029-validation/used006-baseline-metrics.json | 冻结1.4.21预测对同一gold重算，仅开发基线 |
| 20261021-tagging-iteration-029-validation/used006-frozen-output-hashes.json | 新预测/旧输入/协议/映射冻结 |
| 20261021-tagging-iteration-029-validation/used006-gold-frozen.json | 历史参考标准hash |
| 20261021-tagging-iteration-029-validation/used006-metrics.json | 固定开发P/R/F1及逐篇错漏，非独立结果 |
| 20261021-tagging-iteration-029-validation/used006-protocol.json | 已用开发角色与原参考来源 |
| 20261021-tagging-iteration-029-validation/validation.json | 离线软件验收、开发改进及无当前独立结果边界 |

## 标签持续优化第30轮（2026-10-21）

[20261021-tagging-iteration-030.md](20261021-tagging-iteration-030.md)：圆偏振发光一级受控方向，202项局部通过；七组开发补1个正确一级、误标不增、二级不变。原gold不改、同义评价对应先冻后预测，无新独立成绩，第七组封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-030-validation/before-tests.log | 旧版新词表要求12失败与1缺证据错误 |
| 20261021-tagging-iteration-030-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-030-validation/concept-definition.json | 中英文名/定义/别名/排除/无父类理由 |
| 20261021-tagging-iteration-030-validation/development-roles.json | 七组70篇已曝光开发与来源疑点保持 |
| 20261021-tagging-iteration-030-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-030-validation/evidence-delta-summary.json | 新增标题接受和摘要弱提及的区间/hash |
| 20261021-tagging-iteration-030-validation/full-summary.json | 实际全量执行/唯一/重复/失败统计 |
| 20261021-tagging-iteration-030-validation/full-tests.log | 确切1.4.23科学源码全量日志 |
| 20261021-tagging-iteration-030-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-030-validation/literature-tests.log | 202项局部回归 |
| 20261021-tagging-iteration-030-validation/mention-source-audit.json | 192条提及逐字/分层来源 |
| 20261021-tagging-iteration-030-validation/original-audit.json | 逐篇核心数及证据/来源 |
| 20261021-tagging-iteration-030-validation/original-baseline-metrics.json | 冻结1.4.22预测，按相同v11评价对应重算的开发基线 |
| 20261021-tagging-iteration-030-validation/original-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-030-validation/original-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-030-validation/original-metrics.json | 同v11评价固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-030-validation/original-original-v10-metrics.json | 历史v10口径原metrics另存，不与新词表内分母混同 |
| 20261021-tagging-iteration-030-validation/original-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-030-validation/original-semantic-map.json | 同层同维度评价对应；本轮仅used006增加1个，其他原字节保持 |
| 20261021-tagging-iteration-030-validation/protected-after.json | 旧字节不变及007无预测 |
| 20261021-tagging-iteration-030-validation/protected-before.json | 历史输入/gold/回执与007留出指纹 |
| 20261021-tagging-iteration-030-validation/protocol.json | 五科学文件冻结与唯一CPL词表概念改动 |
| 20261021-tagging-iteration-030-validation/retention-audit.json | 1091旧接受/191旧提及原样及新标签/提及各1 |
| 20261021-tagging-iteration-030-validation/semantic-map-audit.json | 旧v10与同v11基线/候选口径，gold和参考数量不变 |
| 20261021-tagging-iteration-030-validation/semantic-mapping-decision.json | 新一对一同层同维度评价对应及不映射依据，先于预测 |
| 20261021-tagging-iteration-030-validation/source-scope-audit.json | 原42科学词条/归属/来源/核心不变 |
| 20261021-tagging-iteration-030-validation/tests-frozen.json | 202项局部测试指纹，13项新增，原测试不改 |
| 20261021-tagging-iteration-030-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-030-validation/used001-audit.json | 逐篇核心数及证据/来源 |
| 20261021-tagging-iteration-030-validation/used001-baseline-metrics.json | 冻结1.4.22预测，按相同v11评价对应重算的开发基线 |
| 20261021-tagging-iteration-030-validation/used001-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-030-validation/used001-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-030-validation/used001-metrics.json | 同v11评价固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-030-validation/used001-original-v10-metrics.json | 历史v10口径原metrics另存，不与新词表内分母混同 |
| 20261021-tagging-iteration-030-validation/used001-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-030-validation/used001-semantic-map.json | 同层同维度评价对应；本轮仅used006增加1个，其他原字节保持 |
| 20261021-tagging-iteration-030-validation/used002-audit.json | 逐篇核心数及证据/来源 |
| 20261021-tagging-iteration-030-validation/used002-baseline-metrics.json | 冻结1.4.22预测，按相同v11评价对应重算的开发基线 |
| 20261021-tagging-iteration-030-validation/used002-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-030-validation/used002-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-030-validation/used002-metrics.json | 同v11评价固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-030-validation/used002-original-v10-metrics.json | 历史v10口径原metrics另存，不与新词表内分母混同 |
| 20261021-tagging-iteration-030-validation/used002-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-030-validation/used003-audit.json | 逐篇核心数及证据/来源 |
| 20261021-tagging-iteration-030-validation/used003-baseline-metrics.json | 冻结1.4.22预测，按相同v11评价对应重算的开发基线 |
| 20261021-tagging-iteration-030-validation/used003-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-030-validation/used003-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-030-validation/used003-metrics.json | 同v11评价固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-030-validation/used003-original-v10-metrics.json | 历史v10口径原metrics另存，不与新词表内分母混同 |
| 20261021-tagging-iteration-030-validation/used003-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-030-validation/used004-audit.json | 逐篇核心数及证据/来源 |
| 20261021-tagging-iteration-030-validation/used004-baseline-metrics.json | 冻结1.4.22预测，按相同v11评价对应重算的开发基线 |
| 20261021-tagging-iteration-030-validation/used004-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-030-validation/used004-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-030-validation/used004-metrics.json | 同v11评价固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-030-validation/used004-original-v10-metrics.json | 历史v10口径原metrics另存，不与新词表内分母混同 |
| 20261021-tagging-iteration-030-validation/used004-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-030-validation/used005-audit.json | 逐篇核心数及证据/来源 |
| 20261021-tagging-iteration-030-validation/used005-baseline-metrics.json | 冻结1.4.22预测，按相同v11评价对应重算的开发基线 |
| 20261021-tagging-iteration-030-validation/used005-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-030-validation/used005-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-030-validation/used005-metrics.json | 同v11评价固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-030-validation/used005-original-v10-metrics.json | 历史v10口径原metrics另存，不与新词表内分母混同 |
| 20261021-tagging-iteration-030-validation/used005-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-030-validation/used006-audit.json | 逐篇核心数及证据/来源 |
| 20261021-tagging-iteration-030-validation/used006-baseline-metrics.json | 冻结1.4.22预测，按相同v11评价对应重算的开发基线 |
| 20261021-tagging-iteration-030-validation/used006-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-030-validation/used006-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-030-validation/used006-metrics.json | 同v11评价固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-030-validation/used006-original-v10-metrics.json | 历史v10口径原metrics另存，不与新词表内分母混同 |
| 20261021-tagging-iteration-030-validation/used006-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-030-validation/used006-semantic-map.json | 同层同维度评价对应；本轮仅used006增加1个，其他原字节保持 |
| 20261021-tagging-iteration-030-validation/validation.json | 离线软件验收、开发概念覆盖改进及无新独立成绩 |

## 标签持续优化第31轮（2026-10-21）

[20261021-tagging-iteration-031.md](20261021-tagging-iteration-031.md)：机器学习分子逆向设计一级受控方向，216项局部通过；七组开发补1个正确一级、误标不增、二级不变。原gold及旧对应保留，新同义评价对应先冻后预测，本轮无新独立成绩，第七组封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-031-validation/before-tests.log | 旧版新要求12失败与1缺少标签证据错误 |
| 20261021-tagging-iteration-031-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-031-validation/concept-definition.json | 中英文名/定义/别名/排除/无父类理由 |
| 20261021-tagging-iteration-031-validation/development-roles.json | 七组70篇曝光开发及来源疑点保持 |
| 20261021-tagging-iteration-031-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-031-validation/evidence-delta-summary.json | 新标题接受证据的区间/hash |
| 20261021-tagging-iteration-031-validation/full-summary.json | 实际全量执行/唯一/重复/失败统计 |
| 20261021-tagging-iteration-031-validation/full-tests.log | 确切1.4.24科学源码全量测试日志 |
| 20261021-tagging-iteration-031-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-031-validation/literature-tests.log | 216项局部回归 |
| 20261021-tagging-iteration-031-validation/mention-source-audit.json | 192条提及逐字/分层来源 |
| 20261021-tagging-iteration-031-validation/original-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-031-validation/original-baseline-metrics.json | 冻结1.4.23预测按相同v12评价口径重算 |
| 20261021-tagging-iteration-031-validation/original-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-031-validation/original-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-031-validation/original-metrics.json | 相同v12评价的固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-031-validation/original-original-v11-metrics.json | 历史v11原metrics另存，不混同词表内分母 |
| 20261021-tagging-iteration-031-validation/original-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-031-validation/original-semantic-map.json | 同层同维度评价对应；本轮used006增加1项，原对应保留 |
| 20261021-tagging-iteration-031-validation/protected-after.json | 旧字节不变及007无预测 |
| 20261021-tagging-iteration-031-validation/protected-before.json | 历史输入/gold/回执及007留出指纹 |
| 20261021-tagging-iteration-031-validation/protocol.json | 科学文件冻结及唯一分子逆向设计概念改动 |
| 20261021-tagging-iteration-031-validation/retention-audit.json | 1092旧接受/192旧提及原样及新增1条接受 |
| 20261021-tagging-iteration-031-validation/semantic-map-audit.json | 旧v11及同v12基线/候选口径，原26/61参考不改 |
| 20261021-tagging-iteration-031-validation/semantic-mapping-decision.json | 同层同维度一对一评价依据，先于预测冻结 |
| 20261021-tagging-iteration-031-validation/source-scope-audit.json | 原43科学词条/归属/来源/核心不变 |
| 20261021-tagging-iteration-031-validation/tests-frozen.json | 216项局部测试指纹，14项新增、旧测试不改 |
| 20261021-tagging-iteration-031-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-031-validation/used001-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-031-validation/used001-baseline-metrics.json | 冻结1.4.23预测按相同v12评价口径重算 |
| 20261021-tagging-iteration-031-validation/used001-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-031-validation/used001-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-031-validation/used001-metrics.json | 相同v12评价的固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-031-validation/used001-original-v11-metrics.json | 历史v11原metrics另存，不混同词表内分母 |
| 20261021-tagging-iteration-031-validation/used001-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-031-validation/used001-semantic-map.json | 同层同维度评价对应；本轮used006增加1项，原对应保留 |
| 20261021-tagging-iteration-031-validation/used002-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-031-validation/used002-baseline-metrics.json | 冻结1.4.23预测按相同v12评价口径重算 |
| 20261021-tagging-iteration-031-validation/used002-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-031-validation/used002-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-031-validation/used002-metrics.json | 相同v12评价的固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-031-validation/used002-original-v11-metrics.json | 历史v11原metrics另存，不混同词表内分母 |
| 20261021-tagging-iteration-031-validation/used002-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-031-validation/used003-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-031-validation/used003-baseline-metrics.json | 冻结1.4.23预测按相同v12评价口径重算 |
| 20261021-tagging-iteration-031-validation/used003-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-031-validation/used003-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-031-validation/used003-metrics.json | 相同v12评价的固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-031-validation/used003-original-v11-metrics.json | 历史v11原metrics另存，不混同词表内分母 |
| 20261021-tagging-iteration-031-validation/used003-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-031-validation/used004-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-031-validation/used004-baseline-metrics.json | 冻结1.4.23预测按相同v12评价口径重算 |
| 20261021-tagging-iteration-031-validation/used004-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-031-validation/used004-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-031-validation/used004-metrics.json | 相同v12评价的固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-031-validation/used004-original-v11-metrics.json | 历史v11原metrics另存，不混同词表内分母 |
| 20261021-tagging-iteration-031-validation/used004-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-031-validation/used005-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-031-validation/used005-baseline-metrics.json | 冻结1.4.23预测按相同v12评价口径重算 |
| 20261021-tagging-iteration-031-validation/used005-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-031-validation/used005-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-031-validation/used005-metrics.json | 相同v12评价的固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-031-validation/used005-original-v11-metrics.json | 历史v11原metrics另存，不混同词表内分母 |
| 20261021-tagging-iteration-031-validation/used005-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-031-validation/used006-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-031-validation/used006-baseline-metrics.json | 冻结1.4.23预测按相同v12评价口径重算 |
| 20261021-tagging-iteration-031-validation/used006-frozen-output-hashes.json | 预测/输入/协议/映射冻结 |
| 20261021-tagging-iteration-031-validation/used006-gold-frozen.json | 旧标准答案指纹 |
| 20261021-tagging-iteration-031-validation/used006-metrics.json | 相同v12评价的固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-031-validation/used006-original-v11-metrics.json | 历史v11原metrics另存，不混同词表内分母 |
| 20261021-tagging-iteration-031-validation/used006-protocol.json | 已用开发角色及原参考来源 |
| 20261021-tagging-iteration-031-validation/used006-semantic-map.json | 同层同维度评价对应；本轮used006增加1项，原对应保留 |
| 20261021-tagging-iteration-031-validation/validation.json | 离线软件验收及开发覆盖改进，无当前独立成绩 |

## 标签持续优化第32轮（2026-10-21）

[20261021-tagging-iteration-032.md](20261021-tagging-iteration-032.md)：固定1.4.24第七组单次独立评测，参考先冻后预测；一级P78.95/R55.56/F165.22、二级P42.31/R21.15/F128.21。综述与扩展摘要型原文保留且范围单列，源码不改、第八组封存，未达到可靠分类。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-032-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-032-validation/development-reuse.json | 七组开发同源码不重跑的原始逐文件hash |
| 20261021-tagging-iteration-032-validation/development-summary.json | 七组70篇固定开发指标/数量/来源 |
| 20261021-tagging-iteration-032-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-032-validation/full-summary.json | 真实全量执行/唯一/重复/失败统计 |
| 20261021-tagging-iteration-032-validation/full-tests.log | 未改1.4.24科学源码全项目日志 |
| 20261021-tagging-iteration-032-validation/identity-audit.json | 10份PDF/冻结上下文字节核对及语义身份边界 |
| 20261021-tagging-iteration-032-validation/independent007-audit.json | 逐篇参考/预测数和证据/来源/身份hash |
| 20261021-tagging-iteration-032-validation/independent007-disjoint-audit.json | 原007与先前70篇身份不重叠 |
| 20261021-tagging-iteration-032-validation/independent007-exposure.json | 首次打开、先参考后预测与已使用时间 |
| 20261021-tagging-iteration-032-validation/independent007-frozen-output-hashes.json | 原输入/抽样/本轮协议冻结 |
| 20261021-tagging-iteration-032-validation/independent007-gold-frozen.json | 27/52参考及79引文先于预测的冻结回执 |
| 20261021-tagging-iteration-032-validation/independent007-metrics.json | 本轮单次独立P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-032-validation/independent007-original-sampling-protocol.json | 原007元信息分层协议原字节 |
| 20261021-tagging-iteration-032-validation/independent007-predictions-frozen.json | 单次预测及科学文件指纹 |
| 20261021-tagging-iteration-032-validation/independent007-protocol.json | 本轮评测与旧抽样版本环境分开 |
| 20261021-tagging-iteration-032-validation/independent007-reference-selection-notes.json | 预测前助手主线选择理由与SI疑点，不含完整原文 |
| 20261021-tagging-iteration-032-validation/independent007-reference-validation-before-predictions.json | 生成预测前逐字参考校验 |
| 20261021-tagging-iteration-032-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-032-validation/next-holdout-receipt.json | 第八组未读/无预测和与80篇无重叠 |
| 20261021-tagging-iteration-032-validation/next-improvement.json | 下一项只诊断主线降解产物分析方法的核心选择 |
| 20261021-tagging-iteration-032-validation/next-selection-exclusions.json | 下轮分层样本按已用身份去重，不按错误选例 |
| 20261021-tagging-iteration-032-validation/protected-after.json | 旧字节不变，原封存快照与实际曝光分开 |
| 20261021-tagging-iteration-032-validation/protected-before.json | 历史冻结输入/参考/回执的只读指纹 |
| 20261021-tagging-iteration-032-validation/protocol.json | 同1.4.24源码及候选/开发先于独立输入打开 |
| 20261021-tagging-iteration-032-validation/reference-concepts.json | 33个评测专用词表外概念，无生产映射 |
| 20261021-tagging-iteration-032-validation/tests-frozen.json | 216项标签测试源码不变，无新增测试 |
| 20261021-tagging-iteration-032-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-032-validation/validation.json | 软件验收与独立结果/主文来源限制分别记录 |

## 标签持续优化第33轮（2026-10-21）

[20261021-tagging-iteration-033.md](20261021-tagging-iteration-033.md)：联合LC/GC-MS降解结果句的实际使用证据，227项局部通过；八组开发补1个正确二级、误标不增、一级不变。无新独立成绩，第八组封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-033-validation/before-tests.log | 旧版新句式缺口 |
| 20261021-tagging-iteration-033-validation/change-definition.json | 唯一实际使用结果句改动与排除范围 |
| 20261021-tagging-iteration-033-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-033-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-033-validation/evidence-delta-summary.json | 新接受/提及来源区间与hash，不公开原科学段落 |
| 20261021-tagging-iteration-033-validation/full-summary.json | 实际执行/唯一/重复及失败统计 |
| 20261021-tagging-iteration-033-validation/full-tests.log | 确切1.4.25全项目测试日志 |
| 20261021-tagging-iteration-033-validation/initial-tests.log | 初版3个局部失败及修正的完整证据 |
| 20261021-tagging-iteration-033-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-033-validation/literature-tests.log | 227项局部回归 |
| 20261021-tagging-iteration-033-validation/mention-source-audit.json | 当前218条提及检查 |
| 20261021-tagging-iteration-033-validation/original-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/original-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/original-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/original-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/original-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/original-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/original-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/original-semantic-map.json | 原有评价对应字节不变，无新增ID/映射 |
| 20261021-tagging-iteration-033-validation/protected-after.json | 旧字节及008封存保持 |
| 20261021-tagging-iteration-033-validation/protected-before.json | 历史文件/008封存的只读指纹 |
| 20261021-tagging-iteration-033-validation/protocol.json | 本轮科学源码与80篇开发口径冻结 |
| 20261021-tagging-iteration-033-validation/retention-audit.json | 1249旧接受、同源提及升为使用及未准入观察保留 |
| 20261021-tagging-iteration-033-validation/source-scope-audit.json | 核心/词表/来源/窗口不变及旧输入/gold/hash |
| 20261021-tagging-iteration-033-validation/tests-frozen.json | 227项测试指纹，11项新增及初测修正说明 |
| 20261021-tagging-iteration-033-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-033-validation/used001-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/used001-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/used001-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/used001-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/used001-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/used001-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/used001-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/used001-semantic-map.json | 原有评价对应字节不变，无新增ID/映射 |
| 20261021-tagging-iteration-033-validation/used002-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/used002-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/used002-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/used002-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/used002-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/used002-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/used002-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/used003-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/used003-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/used003-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/used003-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/used003-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/used003-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/used003-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/used004-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/used004-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/used004-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/used004-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/used004-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/used004-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/used004-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/used005-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/used005-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/used005-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/used005-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/used005-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/used005-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/used005-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/used006-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/used006-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/used006-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/used006-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/used006-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/used006-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/used006-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/used006-semantic-map.json | 原有评价对应字节不变，无新增ID/映射 |
| 20261021-tagging-iteration-033-validation/used007-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-033-validation/used007-baseline-metrics.json | 冻结1.4.24基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-033-validation/used007-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-033-validation/used007-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-033-validation/used007-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-033-validation/used007-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-033-validation/used007-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-033-validation/validation.json | 离线软件验收与开发改进，无新独立成绩 |

## 标签持续优化第34轮（2026-10-21）

[20261021-tagging-iteration-034.md](20261021-tagging-iteration-034.md)：期刊Soc./SOC有界消歧，239项局部通过；八组开发减少1个二级核心误标、TP/FN/一级不变。无新独立成绩，第八组封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-034-validation/before-tests.log | 旧版期刊误识及消歧回执缺口 |
| 20261021-tagging-iteration-034-validation/change-definition.json | 唯一期刊Soc.歧义消除及保留范围 |
| 20261021-tagging-iteration-034-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-034-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-034-validation/evidence-delta-summary.json | 消歧证据来源区间与hash，不公开原段落 |
| 20261021-tagging-iteration-034-validation/full-summary.json | 实际执行/唯一/重复及失败统计 |
| 20261021-tagging-iteration-034-validation/full-tests.log | 确切1.4.26全项目测试日志 |
| 20261021-tagging-iteration-034-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-034-validation/literature-tests.log | 239项局部回归 |
| 20261021-tagging-iteration-034-validation/mention-source-audit.json | 当前227条提及逐字与来源检查 |
| 20261021-tagging-iteration-034-validation/original-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/original-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/original-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/original-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/original-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/original-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/original-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/original-semantic-map.json | 原有评价对应字节不变，无新增ID/映射 |
| 20261021-tagging-iteration-034-validation/protected-after.json | 旧字节及008封存保持 |
| 20261021-tagging-iteration-034-validation/protected-before.json | 历史文件/008封存的只读指纹 |
| 20261021-tagging-iteration-034-validation/protocol.json | 本轮科学源码与80篇开发口径冻结 |
| 20261021-tagging-iteration-034-validation/retention-audit.json | 1245原样接受/6条期刊转提及/所有旧提及来源保留 |
| 20261021-tagging-iteration-034-validation/source-scope-audit.json | 核心/词表/来源/窗口及旧输入/gold不变 |
| 20261021-tagging-iteration-034-validation/tests-frozen.json | 239项测试指纹，12项新增、原227项不改 |
| 20261021-tagging-iteration-034-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-034-validation/used001-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/used001-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/used001-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/used001-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/used001-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/used001-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/used001-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/used001-semantic-map.json | 原有评价对应字节不变，无新增ID/映射 |
| 20261021-tagging-iteration-034-validation/used002-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/used002-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/used002-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/used002-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/used002-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/used002-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/used002-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/used003-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/used003-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/used003-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/used003-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/used003-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/used003-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/used003-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/used004-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/used004-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/used004-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/used004-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/used004-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/used004-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/used004-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/used005-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/used005-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/used005-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/used005-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/used005-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/used005-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/used005-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/used006-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/used006-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/used006-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/used006-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/used006-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/used006-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/used006-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/used006-semantic-map.json | 原有评价对应字节不变，无新增ID/映射 |
| 20261021-tagging-iteration-034-validation/used007-audit.json | 逐篇核心数、接受/来源检查 |
| 20261021-tagging-iteration-034-validation/used007-baseline-metrics.json | 冻结1.4.25基线，同一v12/标准/对应 |
| 20261021-tagging-iteration-034-validation/used007-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-034-validation/used007-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-034-validation/used007-metrics.json | 固定开发P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-034-validation/used007-original-v12-metrics.json | 上一轮原metrics，核对与本轮基线一致 |
| 20261021-tagging-iteration-034-validation/used007-protocol.json | 已用开发角色及冻结输入来源 |
| 20261021-tagging-iteration-034-validation/validation.json | 离线软件验收与开发误标减少，无新独立成绩 |

## 标签持续优化第35轮（2026-10-21）

[20261021-tagging-iteration-035.md](20261021-tagging-iteration-035.md)：固定1.4.26第八组单次独立评测；30/57参考与87逐字位置先冻后预测。一级P87.50/R46.67/F160.87、二级P81.25/R22.81/F135.62，漏标仍明显。中文综述/原文摘要段与参考引用完整性分别记录，软件通过不代表科学可靠；规则不改，009封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-035-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-035-validation/development-reuse.json | 八组同科学源码原开发结果hash |
| 20261021-tagging-iteration-035-validation/development-summary.json | 八组80篇开发指标及每篇核心数/来源，明确沿用 |
| 20261021-tagging-iteration-035-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-035-validation/full-summary.json | 全项目真实执行/唯一/重复/失败统计 |
| 20261021-tagging-iteration-035-validation/full-tests.log | 相同科学源码全量真实执行日志 |
| 20261021-tagging-iteration-035-validation/identity-audit.json | 10PDF/context新鲜hash核对及科学来源边界 |
| 20261021-tagging-iteration-035-validation/independent008-audit.json | 逐篇核心数量、机械位置/来源和输入指纹 |
| 20261021-tagging-iteration-035-validation/independent008-disjoint-audit.json | 008与此前80篇身份无重叠 |
| 20261021-tagging-iteration-035-validation/independent008-exposure.json | 先参考后预测及已使用真实时间 |
| 20261021-tagging-iteration-035-validation/independent008-frozen-output-hashes.json | 输入/抽样及评测协议冻结 |
| 20261021-tagging-iteration-035-validation/independent008-gold-frozen.json | 30/57参考与87位置先于预测冻结 |
| 20261021-tagging-iteration-035-validation/independent008-metrics.json | 单次独立P/R/F1及逐篇错漏 |
| 20261021-tagging-iteration-035-validation/independent008-original-sampling-protocol.json | 原008在1.4.24环境抽样的协议原字节 |
| 20261021-tagging-iteration-035-validation/independent008-predictions-frozen.json | 仅一次预测和科学文件指纹 |
| 20261021-tagging-iteration-035-validation/independent008-protocol.json | 本轮1.4.26评测协议 |
| 20261021-tagging-iteration-035-validation/independent008-reference-selection-notes.json | 预测前主线选择、中文综述及来源限制 |
| 20261021-tagging-iteration-035-validation/independent008-reference-validation-before-predictions.json | 预测前参考证据机械校验 |
| 20261021-tagging-iteration-035-validation/links.log | tools全局链接检查 |
| 20261021-tagging-iteration-035-validation/next-holdout-receipt.json | 009未读无gold/预测且与90篇无重叠 |
| 20261021-tagging-iteration-035-validation/next-improvement.json | 下一轮仅诊断显式主体角色的一级单数host漏标 |
| 20261021-tagging-iteration-035-validation/next-selection-exclusions.json | 已用90篇身份去重，无错误驱动抽样 |
| 20261021-tagging-iteration-035-validation/protected-after.json | 原封存008快照不变，实际曝光分开 |
| 20261021-tagging-iteration-035-validation/protected-before.json | 全部旧冻结材料只读指纹 |
| 20261021-tagging-iteration-035-validation/protocol.json | 科学文件/版本和第34轮候选开发验收先于打开 |
| 20261021-tagging-iteration-035-validation/reference-concepts.json | 34个评测专用OOV概念，非生产映射 |
| 20261021-tagging-iteration-035-validation/tests-frozen.json | 239项标签测试源码不变 |
| 20261021-tagging-iteration-035-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-035-validation/validation.json | 独立结果、软件验收和来源/参考限制分别记录 |

## 标签持续优化第36轮（2026-10-21）

[20261021-tagging-iteration-036.md](20261021-tagging-iteration-036.md)：受控host设备材料角色别名，251项局部通过；九组90篇开发补回2个一级正确核心，误标不增、全部二级不变。旧1376接受原样保留；1旧背景提及在旧运行和基线留档。无新独立成绩，009封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-036-validation/before-tests.log | 旧版host别名/trace缺口的真实失败 |
| 20261021-tagging-iteration-036-validation/change-definition.json | 唯一级受控host设备材料角色及范围 |
| 20261021-tagging-iteration-036-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-036-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-036-validation/evidence-delta-summary.json | 新增角色和旧提及留档的区间/hash，不公开原段落 |
| 20261021-tagging-iteration-036-validation/full-summary.json | 实际执行/唯一/重复/失败统计 |
| 20261021-tagging-iteration-036-validation/full-tests.log | 确切1.4.27全项目日志 |
| 20261021-tagging-iteration-036-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-036-validation/literature-tests.log | 251项标签局部回归 |
| 20261021-tagging-iteration-036-validation/mention-source-audit.json | 全部当前提及逐字/层级来源检查 |
| 20261021-tagging-iteration-036-validation/original-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/original-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/original-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/original-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/original-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/original-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/original-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/original-semantic-map.json | 原有对应原字节，无新ID/映射 |
| 20261021-tagging-iteration-036-validation/protected-after.json | 旧字节及009封存保持 |
| 20261021-tagging-iteration-036-validation/protected-before.json | 全部历史材料/009封存只读指纹 |
| 20261021-tagging-iteration-036-validation/protocol.json | 候选科学源码与90篇开发口径冻结 |
| 20261021-tagging-iteration-036-validation/retention-audit.json | 1376旧接受原样、268旧提及当前、1旧背景提及原件留档 |
| 20261021-tagging-iteration-036-validation/source-scope-audit.json | 44语义ID及旧别名/二级/排序/来源/窗口保持 |
| 20261021-tagging-iteration-036-validation/tests-frozen.json | 251项测试指纹，新增12、旧239项不改 |
| 20261021-tagging-iteration-036-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-036-validation/used001-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used001-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used001-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used001-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used001-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used001-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used001-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/used001-semantic-map.json | 原有对应原字节，无新ID/映射 |
| 20261021-tagging-iteration-036-validation/used002-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used002-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used002-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used002-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used002-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used002-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used002-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/used003-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used003-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used003-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used003-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used003-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used003-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used003-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/used004-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used004-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used004-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used004-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used004-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used004-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used004-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/used005-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used005-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used005-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used005-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used005-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used005-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used005-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/used006-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used006-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used006-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used006-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used006-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used006-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used006-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/used006-semantic-map.json | 原有对应原字节，无新ID/映射 |
| 20261021-tagging-iteration-036-validation/used007-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used007-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used007-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used007-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used007-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used007-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used007-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/used008-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-036-validation/used008-baseline-metrics.json | 1.4.26旧预测，在同v13评价口径重算 |
| 20261021-tagging-iteration-036-validation/used008-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-036-validation/used008-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-036-validation/used008-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-036-validation/used008-original-v12-metrics.json | 原v12指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-036-validation/used008-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-036-validation/validation.json | 软件验收与开发补漏，无新独立成绩 |

## 标签持续优化第37轮（2026-10-21）

[20261021-tagging-iteration-037.md](20261021-tagging-iteration-037.md)：明确发射偶极取向词形，263项局部通过；九组90篇开发补回1个二级正确核心，误标不增、一级/其他标签不变。旧1378接受与269提及原样保留；旧别名跨句fixture问题单列。无新独立成绩，009封存。

| 文件 | 保留理由 |
| --- | --- |
| 20261021-tagging-iteration-037-validation/before-tests.log | 旧版取向别名/trace缺口的真实失败 |
| 20261021-tagging-iteration-037-validation/change-definition.json | 唯一既有发射偶极取向短语别名及范围 |
| 20261021-tagging-iteration-037-validation/check.log | 静态接口依赖检查 |
| 20261021-tagging-iteration-037-validation/diff.log | 差异空白检查 |
| 20261021-tagging-iteration-037-validation/evidence-delta-summary.json | 新增取向依据及来源的区间/hash，不公开原段落 |
| 20261021-tagging-iteration-037-validation/full-summary.json | 实际执行/唯一/重复/失败统计 |
| 20261021-tagging-iteration-037-validation/full-tests.log | 确切1.4.28全项目日志 |
| 20261021-tagging-iteration-037-validation/initial-mixed-fixture-failure.log | 该fixture真实失败，未冒称通过，修为两块独立证据后旧规则仍保持 |
| 20261021-tagging-iteration-037-validation/initial-mixed-fixture.py | 原同块混合fixture：旧通配跨句遮挡新否定短语，原断言保留 |
| 20261021-tagging-iteration-037-validation/links.log | 全局链接检查 |
| 20261021-tagging-iteration-037-validation/literature-tests.log | 263项标签局部回归 |
| 20261021-tagging-iteration-037-validation/mention-source-audit.json | 全部当前提及逐字/层级来源检查 |
| 20261021-tagging-iteration-037-validation/original-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/original-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/original-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/original-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/original-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/original-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/original-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/original-semantic-map.json | 原有对应原字节，无新ID/映射 |
| 20261021-tagging-iteration-037-validation/protected-after.json | 旧字节及009封存保持 |
| 20261021-tagging-iteration-037-validation/protected-before.json | 全部历史材料/009封存只读指纹 |
| 20261021-tagging-iteration-037-validation/protocol.json | 候选科学源码与90篇开发口径冻结 |
| 20261021-tagging-iteration-037-validation/retention-audit.json | 1378旧接受与269旧提及原样保留 |
| 20261021-tagging-iteration-037-validation/source-scope-audit.json | 44语义ID及旧别名/一级/排序/来源/窗口保持 |
| 20261021-tagging-iteration-037-validation/tests-frozen.json | 263项测试指纹，新增12、旧251项不改 |
| 20261021-tagging-iteration-037-validation/update.log | tools全局更新 |
| 20261021-tagging-iteration-037-validation/used001-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used001-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used001-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used001-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used001-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used001-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used001-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/used001-semantic-map.json | 原有对应原字节，无新ID/映射 |
| 20261021-tagging-iteration-037-validation/used002-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used002-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used002-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used002-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used002-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used002-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used002-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/used003-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used003-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used003-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used003-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used003-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used003-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used003-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/used004-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used004-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used004-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used004-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used004-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used004-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used004-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/used005-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used005-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used005-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used005-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used005-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used005-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used005-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/used006-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used006-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used006-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used006-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used006-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used006-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used006-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/used006-semantic-map.json | 原有对应原字节，无新ID/映射 |
| 20261021-tagging-iteration-037-validation/used007-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used007-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used007-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used007-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used007-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used007-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used007-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/used008-audit.json | 逐篇核心数与证据/来源 |
| 20261021-tagging-iteration-037-validation/used008-baseline-metrics.json | 1.4.27旧预测，在同v14评价口径重算 |
| 20261021-tagging-iteration-037-validation/used008-frozen-output-hashes.json | 输入/预测/协议/旧对应hash |
| 20261021-tagging-iteration-037-validation/used008-gold-frozen.json | 旧标准答案hash |
| 20261021-tagging-iteration-037-validation/used008-metrics.json | 固定开发P/R/F1和逐篇错漏 |
| 20261021-tagging-iteration-037-validation/used008-original-v13-metrics.json | 原v13指标，与新基线完全相同，无新概念映射 |
| 20261021-tagging-iteration-037-validation/used008-protocol.json | 已用开发角色和原冻结来源 |
| 20261021-tagging-iteration-037-validation/validation.json | 软件验收与开发补漏，无新独立成绩 |

## 2026-10-22 五轮试验1/5

[20261022-tagging-iteration-038.md](20261022-tagging-iteration-038.md)：激子增殖与高能激子利用主题覆盖，90篇开发，独立结果为空。

| 文件 | 保留理由 |
| --- | --- |
| 20261022-tagging-iteration-038-validation/change-definition.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/check.log | 真实软件检查日志 |
| 20261022-tagging-iteration-038-validation/diff.log | 真实软件检查日志 |
| 20261022-tagging-iteration-038-validation/evidence-delta.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/full-summary.json | 真实执行/唯一/重复/错误统计 |
| 20261022-tagging-iteration-038-validation/full.log | 真实软件检查日志 |
| 20261022-tagging-iteration-038-validation/links.log | 真实软件检查日志 |
| 20261022-tagging-iteration-038-validation/local-test-result.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/local.log | 真实软件检查日志 |
| 20261022-tagging-iteration-038-validation/micro.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/new-semantic-mappings.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/original-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/original-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/original-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/original-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/original-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/original-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/protected-after.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/protected-before.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/protocol.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/retention-audit.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/summary.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/tests-frozen.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-038-validation/update.log | 真实软件检查日志 |
| 20261022-tagging-iteration-038-validation/used-test-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test002-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test002-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test002-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test002-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test002-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test003-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test003-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test003-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test003-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test003-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test003-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test004-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test004-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test004-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test004-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test004-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test004-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test005-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test005-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test005-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test005-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test005-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test005-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test006-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test006-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test006-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test006-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test006-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test006-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test007-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test007-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test007-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test007-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test007-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test007-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test008-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test008-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-038-validation/used-test008-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test008-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/used-test008-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-038-validation/validation.json | 科学开发与软件检查分开 |

## 2026-10-22 五轮试验2/5

[20261022-tagging-iteration-039.md](20261022-tagging-iteration-039.md)：溶液多层成膜的溶剂正交与膜层耐溶剂覆盖，90篇开发，独立结果为空。

| 文件 | 保留理由 |
| --- | --- |
| 20261022-tagging-iteration-039-validation/change-definition.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/check.log | 真实软件检查日志 |
| 20261022-tagging-iteration-039-validation/diff.log | 真实软件检查日志 |
| 20261022-tagging-iteration-039-validation/evidence-delta.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/full-summary.json | 真实执行/唯一/重复/错误统计 |
| 20261022-tagging-iteration-039-validation/full.log | 真实软件检查日志 |
| 20261022-tagging-iteration-039-validation/links.log | 真实软件检查日志 |
| 20261022-tagging-iteration-039-validation/local-test-result.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/local.log | 真实软件检查日志 |
| 20261022-tagging-iteration-039-validation/micro.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/new-semantic-mappings.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/original-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/original-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/original-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/original-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/original-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/original-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/protected-after.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/protected-before.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/protocol.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/retention-audit.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/summary.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/tests-frozen.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-039-validation/update.log | 真实软件检查日志 |
| 20261022-tagging-iteration-039-validation/used-test-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test002-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test002-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test002-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test002-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test002-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test003-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test003-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test003-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test003-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test003-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test003-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test004-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test004-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test004-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test004-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test004-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test004-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test005-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test005-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test005-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test005-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test005-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test005-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test006-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test006-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test006-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test006-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test006-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test006-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test007-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test007-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test007-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test007-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test007-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test007-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test008-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test008-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-039-validation/used-test008-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test008-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/used-test008-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-039-validation/validation.json | 科学开发与软件检查分开 |

## 五轮试验3/5：候选退化保留

[20261022-tagging-iteration-040.md](20261022-tagging-iteration-040.md)：2个正确补充与1个重复页眉误标，未采用。

| 文件 | 保留理由 |
| --- | --- |
| 20261022-tagging-iteration-040-validation/change-definition.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/evidence-delta.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/local.log | 真实局部候选/恢复后检查；非候选全量检查 |
| 20261022-tagging-iteration-040-validation/micro.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/new-semantic-mappings.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/original-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/original-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/original-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/original-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/original-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/original-development-semantic-map.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/per-label-audit.json | 逐篇新增真阳性/假阳性，防止平均分掩盖错误 |
| 20261022-tagging-iteration-040-validation/protected-after.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/protected-before.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/protocol.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/rejection.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/restored-check.log | 真实局部候选/恢复后检查；非候选全量检查 |
| 20261022-tagging-iteration-040-validation/restored-local.log | 真实局部候选/恢复后检查；非候选全量检查 |
| 20261022-tagging-iteration-040-validation/retention-audit.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/summary.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/tests-frozen.json | 失败候选冻结、回归与保留证据；未发布 |
| 20261022-tagging-iteration-040-validation/used-test-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test-development-semantic-map.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test002-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test002-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test002-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test002-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test002-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test003-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test003-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test003-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test003-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test003-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test003-development-semantic-map.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test004-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test004-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test004-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test004-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test004-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test004-development-semantic-map.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test005-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test005-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test005-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test005-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test005-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test005-development-semantic-map.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test006-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test006-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test006-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test006-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test006-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test006-development-semantic-map.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test007-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test007-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test007-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test007-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test007-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test007-development-semantic-map.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test008-development-audit.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test008-development-baseline-metrics.json | 相同评价口径的旧版基线 |
| 20261022-tagging-iteration-040-validation/used-test008-development-frozen-output-hashes.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test008-development-gold-frozen.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test008-development-metrics.json | 冻结开发指标、证据与评价对应 |
| 20261022-tagging-iteration-040-validation/used-test008-development-semantic-map.json | 冻结开发指标、证据与评价对应 |

## 2026-10-22 五轮试验4/5

[20261022-tagging-iteration-041.md](20261022-tagging-iteration-041.md)：光学出耦的主题、问题、模型和角分辨测量覆盖，90篇开发，独立结果为空。

| 文件 | 保留理由 |
| --- | --- |
| 20261022-tagging-iteration-041-validation/change-definition.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/check.log | 真实软件检查日志 |
| 20261022-tagging-iteration-041-validation/diff.log | 真实软件检查日志 |
| 20261022-tagging-iteration-041-validation/evidence-delta.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/full-summary.json | 真实执行/唯一/重复/错误统计 |
| 20261022-tagging-iteration-041-validation/full.log | 真实软件检查日志 |
| 20261022-tagging-iteration-041-validation/links.log | 真实软件检查日志 |
| 20261022-tagging-iteration-041-validation/local-test-result.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/local.log | 真实软件检查日志 |
| 20261022-tagging-iteration-041-validation/micro.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/new-semantic-mappings.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/original-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/original-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/original-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/original-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/original-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/original-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/protected-after.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/protected-before.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/protocol.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/retention-audit.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/summary.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/tests-frozen.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-041-validation/update.log | 真实软件检查日志 |
| 20261022-tagging-iteration-041-validation/used-test-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test002-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test002-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test002-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test002-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test002-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test003-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test003-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test003-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test003-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test003-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test003-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test004-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test004-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test004-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test004-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test004-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test004-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test005-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test005-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test005-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test005-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test005-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test005-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test006-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test006-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test006-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test006-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test006-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test006-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test007-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test007-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test007-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test007-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test007-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test007-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test008-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test008-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-041-validation/used-test008-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test008-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test008-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/used-test008-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-041-validation/validation.json | 科学开发与软件检查分开 |

## 2026-10-22 五轮试验5/5

[20261022-tagging-iteration-042.md](20261022-tagging-iteration-042.md)：跨页重复页眉与正文科学证据分离，复核保留的主体细标，90篇开发，独立结果为空。

| 文件 | 保留理由 |
| --- | --- |
| 20261022-tagging-iteration-042-validation/change-definition.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/check.log | 真实软件检查日志 |
| 20261022-tagging-iteration-042-validation/diff.log | 真实软件检查日志 |
| 20261022-tagging-iteration-042-validation/evidence-delta.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/full-summary.json | 真实执行/唯一/重复/错误统计 |
| 20261022-tagging-iteration-042-validation/full.log | 真实软件检查日志 |
| 20261022-tagging-iteration-042-validation/links.log | 真实软件检查日志 |
| 20261022-tagging-iteration-042-validation/local-test-result.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/local.log | 真实软件检查日志 |
| 20261022-tagging-iteration-042-validation/micro.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/new-semantic-mappings.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/original-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/original-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/original-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/original-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/original-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/original-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/protected-after.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/protected-before.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/protocol.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/retention-audit.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/summary.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/tests-frozen.json | 冻结定义/科学微平均/逐组数量与证据/只读保护 |
| 20261022-tagging-iteration-042-validation/update.log | 真实软件检查日志 |
| 20261022-tagging-iteration-042-validation/used-test-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test002-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test002-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test002-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test002-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test002-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test003-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test003-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test003-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test003-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test003-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test003-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test004-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test004-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test004-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test004-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test004-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test004-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test005-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test005-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test005-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test005-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test005-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test005-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test006-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test006-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test006-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test006-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test006-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test006-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test007-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test007-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test007-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test007-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test007-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test007-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test008-development-audit.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test008-development-baseline-metrics.json | 同一新对应口径下旧预测基线 |
| 20261022-tagging-iteration-042-validation/used-test008-development-frozen-output-hashes.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test008-development-gold-frozen.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test008-development-metrics.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/used-test008-development-semantic-map.json | 该开发组指标/证据/旧gold和预测前对应 |
| 20261022-tagging-iteration-042-validation/validation.json | 科学开发与软件检查分开 |

## 2026-10-22 核心标签五轮汇总

[20261022-core-directions-five-rounds.md](20261022-core-directions-five-rounds.md)：4采用1保留；开发小幅改善，新10篇前后相同，尚不够好。

| 文件 | 保留理由 |
| --- | --- |
| 20261022-core-directions-five-rounds-validation/completion-proof.json | 五轮范围、真实开发变化、软件与旧材料保护、未见下一组回执 |
| 20261022-core-directions-five-rounds-validation/development-comparison.json | 五轮范围、真实开发变化、软件与旧材料保护、未见下一组回执 |
| 20261022-core-directions-five-rounds-validation/final-candidate-protocol.json | 最终规则、词表与源码指纹 |
| 20261022-core-directions-five-rounds-validation/final-candidate-validation.json | 最终确切源码的完整软件门 |
| 20261022-core-directions-five-rounds-validation/independent009-assessment-protocol.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-baseline-metrics.json | 旧1.4.28在相同新10篇参考上的首次比较 |
| 20261022-core-directions-five-rounds-validation/independent009-comparison-summary.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-exposure-used.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-gold-frozen.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-gold.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-identity-audit.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-metrics.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-predictions-frozen.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-reference-concepts.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/independent009-result.log | 真实一次独立执行结果 |
| 20261022-core-directions-five-rounds-validation/independent009-sealed-before-hashes.json | 新10篇同输入独立首次评测的协议、参考先冻、指标、范围、曝光与指纹 |
| 20261022-core-directions-five-rounds-validation/manifest.json | 五轮范围、真实开发变化、软件与旧材料保护、未见下一组回执 |
| 20261022-core-directions-five-rounds-validation/next010-receipt.json | 五轮范围、真实开发变化、软件与旧材料保护、未见下一组回执 |
| 20261022-core-directions-five-rounds-validation/round1-per-label-audit.json | 逐篇新正确/新误标，保留未采用候选 |
| 20261022-core-directions-five-rounds-validation/round2-per-label-audit.json | 逐篇新正确/新误标，保留未采用候选 |
| 20261022-core-directions-five-rounds-validation/round3-per-label-audit.json | 逐篇新正确/新误标，保留未采用候选 |
| 20261022-core-directions-five-rounds-validation/round4-per-label-audit.json | 逐篇新正确/新误标，保留未采用候选 |
| 20261022-core-directions-five-rounds-validation/round5-per-label-audit.json | 逐篇新正确/新误标，保留未采用候选 |

- [20261022-level1-background.md](20261022-level1-background.md)：一级全库后台8进程、任务面板、保护与软件验收；非新增科学准确率评测。

- [全库二级标签后台（2026-10-23）](20261023-level2-background.md)：选定1.4.33全库自动候选，独立二级头、8进程、原文保护与实际发布证据。

- [2026-10-25种子任务状态](20261025-seed-status.md)：全部种子参与澄清、手选独占关闭、原暂停与成品验收出口缺口。
- [本轮只读证据](20261025-seed-status-evidence.json)：控制前后指纹、全部种子准入检查、965份可读卡片的元数据计数与原五篇回执摘要。

- [2026-10-25自动流程修复](20261025-automatic-flow-repair.md)：原会话收取、独立生产验收与非实验手选根追踪完成；守卫及待运行边界。
- [自动流程修复证据](20261025-automatic-flow-repair-evidence.json)：源码、隔离回归、原暂停及原回执保护。

- [20261026-start-all-and-screenshot-repair.md](20261026-start-all-and-screenshot-repair.md)：恢复生产任务、冷启动响应与原所有者定时截图，15分钟通用流程巡检；[实测证据](20261026-start-all-and-screenshot-repair-evidence.json)。

- [20261026-original-receipt-candidate-selection.md](20261026-original-receipt-candidate-selection.md)：原URL恢复首候选受保护不再饿死其他安全槽；[实测证据](20261026-original-receipt-candidate-selection-evidence.json)。

- [20261026-native-quota-retry-clause.md](20261026-native-quota-retry-clause.md)：原生升级或重试提示时间解析、通用回归及原监督交接；[证据](20261026-native-quota-retry-clause-evidence.json)。

- [20261026-review-receipt-material-contract.md](20261026-review-receipt-material-contract.md)：核验原会话版本材料目录及完整自动后继ID合同；[证据](20261026-review-receipt-material-contract-evidence.json)。

- [20261026-collection-empty-health-inventory.md](20261026-collection-empty-health-inventory.md)：恢复会话副账本接入原终态空页维护及防止再导航；[证据](20261026-collection-empty-health-inventory-evidence.json)。

- [20261026-hourly-record-inspection.md](20261026-hourly-record-inspection.md): 15 historical records, shared repair verification, hourly schedule and unresolved workflow evidence; [evidence](20261026-hourly-record-inspection-evidence.json).

- [20261026-recovery-terminal-idempotency.md](20261026-recovery-terminal-idempotency.md): retain failed scientific tasks until guarded preparation commits; idempotent failure reasons; [evidence](20261026-recovery-terminal-idempotency-evidence.json).

- [20261026-recovery-terminal-runtime-validation.json](20261026-recovery-terminal-runtime-validation.json): original-owner full recovery scan finished after handoff; six blocked samples preserve reasons/results, no premature recovery events; external blocks retained.

- [20261026-level2-bounded-failure-recovery.md](20261026-level2-bounded-failure-recovery.md): bounded same-input L2 failures, changed-evidence recovery and primary Catalog path guard; [evidence](20261026-level2-bounded-failure-recovery-evidence.json).

- [20261027-screenshot-shared-deadline.md](20261027-screenshot-shared-deadline.md): one aggregate per-page screenshot deadline, remaining-budget detach and staged timeout evidence; [evidence](20261027-screenshot-shared-deadline-evidence.json).

- [20261027-retired-claim-scan-scope.md](20261027-retired-claim-scan-scope.md): fresh claimed-retired target scope before archive verification, unchanged final lease CAS and real per-page scan timing; [evidence](20261027-retired-claim-scan-scope-evidence.json).

- [20261028-claim-recovery-writer-contention.md](20261028-claim-recovery-writer-contention.md)：真实SQLite竞争回归、候选只读筛选与原所有者非阻塞写锁准入；完整验收及实机交接证据独立记录。

- [20261030-closed-browser-original-collection.md](20261030-closed-browser-original-collection.md)：收取意图跨已确认浏览器关闭epoch的永久阻塞、原证据保护与通用接续；[验证证据](20261030-closed-browser-original-collection-evidence.json)。

- [20261030-review-marker-contract-collision.md](20261030-review-marker-contract-collision.md)：固定核验合同版本误认任务编号导致14槽完整回答拒收；2,874项验收及原所有者14/14实机收取通过，科学/生产准入另记；[证据](20261030-review-marker-contract-collision-evidence.json)。

- [20261030-active-correction-recovery-race.md](20261030-active-correction-recovery-race.md): active correction recovery race; final2887-test acceptance and original-owner32 existing-intent reconciliations verified, with unfinished manual-root gates preserved.

- [20261030-manual-root-empty-response.md](20261030-manual-root-empty-response.md): original manual-root rework conversation ended without a final body; [evidence](20261030-manual-root-empty-response-evidence.json), original-request protections and separate software/production gates.

- [20261030-qualified-seed-progress-clock.md](20261030-qualified-seed-progress-clock.md)：实质进展时钟通用修复、完整验收与原所有者交接证据。[证据](20261030-qualified-seed-progress-clock-evidence.json)。

- [20261030-seed-trace-worker-isolation.md](20261030-seed-trace-worker-isolation.md): original-owner seed tracking scheduling isolation; [evidence](20261030-seed-trace-worker-isolation-evidence.json).
