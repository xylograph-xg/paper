# 核心标签持续优化：第1轮

用户明确要求持续优化、每30分钟检查结果。已创建当前聊天heartbeat `30-2`（每30分钟、ACTIVE），只跟进literature纯Python离线研发；其他旧自动诊断任务保持暂停。授权见infrastructure/docs/authorizations/20261020-tagging-iterations.md，执行顺序见literature/ITERATION.md。

本轮采用方向规则1.2.0、核心筛选策略v2，词表仍为38项。开发集一级精确率从81.25%到87.50%、召回率从59.09%到63.64%；二级指标未变。当前尚无新独立留出成绩，不声称全库准确率或泛化已提高。

## 通用改进

- 研究归属按关键词所在句判断，完整宽上下文仍保存；附近另一句的“we”不再替历史提及提供本文依据。
- 支持“is studied / are fabricated / are synthesized”等被动摘要表达；“Previously we”仍按历史研究处理。
- 区分反应后处理“quenched with water”和发光猝灭；不按任何文章名称或ID设置例外。
- 识别罗马数字章节及EXPERIMENTAL METHODS。原开发集输入保持原字节，不重新抽取窗口来提高数字；章节修复通过通用合成回归验证，新留出采用当前解析器。
- 保存focus_text及其原文起止位置，独立校验宽引文和判定句。候选的分类/核心/输入/词表/评测源码全部冻结。
- 评测工具可排除已用ID并只冻结新留出输入、不生成预测；延后生成的预测必须另外保存指纹回执，并核对文献顺序和输入hash。

## 固定核心标准开发评测

本轮复用20261020-core-directions-v2的冻结输入、gold及SI排除口径，原核心标准不减少、不改写。一级10篇、二级9篇（已知仅SI材料单列）。参考答案是当前助手此前对相同文字的判读，不是外部专家金标准；这些样本已经参与开发。

| 层级 | 规则 | 正确 | 非核心/错标 | 漏标 | 精确率 | 召回率 | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 一级（10篇） | 1.1.0 | 13 | 3 | 9 | 81.25% | 59.09% | 68.42% |
| 一级（10篇） | 1.2.0 | 14 | 2 | 8 | 87.50% | 63.64% | 73.68% |
| 二级（9篇） | 1.1.0 | 9 | 5 | 29 | 64.29% | 23.68% | 34.62% |
| 二级（9篇） | 1.2.0 | 9 | 5 | 29 | 64.29% | 23.68% | 34.62% |

新旧均使用同一个核心标准，一级完全匹配由2/10到4/10，二级仍0/9。二级仍有26个词表外核心方向，尚未通过扩词表改善。本轮保存的122条核心/辅助/继承证据均通过逐字引文、页码及判定句偏移校验；这是机械一致性，不是科学核验通过。

## 新留出集

已按元信息分层、固定SHA排序冻结10篇新文献，明确排除原10篇；只接受当前原文及冻结文本指纹核对通过的主文，预算同为7,000字符。留出集属于有可复用原文的文献子集，不代表所有无原文登记。

当前助手尚未阅读其正文，未生成任何预测，也未制作gold，状态unopened。输入及抽样程序hash已冻结。候选代码与开发评测完成后，才可记录曝光并独立读相同输入制作参考；gold冻结后再生成/查看预测。查看错误后该组即为已用测试，不能继续称为未见留出。当前不能用开发集提高代替该独立结果。

留出输入SHA-256：`f93b446d50e1612925fd055d810c513ba27a33bd63278443dcfc21ea4140e7a4`。

## 中间结果与下一步

- 当前轮完整候选、冻结输入/gold、预测和源码：infrastructure/data/literature-evaluations/20261020-iteration-001/。
- 未见留出：infrastructure/data/literature-evaluations/20261020-holdout-001/；初始冻结清单保持原样，预测后另存predictions-frozen.json。
- 迭代状态：infrastructure/data/literature-evaluations/iteration-state.json。旧输入、gold、预测、指标及科学材料均保留。
- [本轮指标和逐篇差异](20261020-tagging-iteration-001-validation/metrics.json)、[源码协议](20261020-tagging-iteration-001-validation/protocol.json)、[留出冻结清单](20261020-tagging-iteration-001-validation/holdout-frozen-output-hashes.json)。
- 下一轮优先研究取向、溶液加工、深陷阱等通用科学词表定义及别名；如添加语义ID，独立保存与原词表外参考的语义对应，不能更改原gold或以ID差异冒充漏标。候选仍保持少量核心标签及完整辅助证据。

定时任务在本聊天检查并推进一轮，不新增LaunchAgent、分类常驻或CDP连接，不启用本地模型、云API、网页GPT或附件外发，不启动/重载原工作流或全库发布。按[官方定时任务说明](https://developers.openai.com/codex/app/automations/)，本地任务运行需要机器开机、应用运行及项目可访问。

## 验证与当前可用版本

38项literature回归、独立headless页面验证通过。make test本轮执行2397次测试，失败0、错误0、跳过0；运行器报告2186个唯一ID和211个既有重复注册槽位。make check及tools全局update/check_links通过。当前规则/核心/输入/词表/评测源码与首轮冻结快照逐文件一致，新旧输入、gold和预测指纹均保留并核对。

验收后的离线可用版本为literature 0.3.1 / directions-rules-1.2.0，不涉及全库生产发布或正式服务重启。半小时任务仍为ACTIVE；下一轮从迭代状态继续。完整记录见[验证JSON](20261020-tagging-iteration-001-validation/validation.json)、[全量测试](20261020-tagging-iteration-001-validation/full-tests.log)、[定时设置回执](20261020-tagging-iteration-001-validation/automation-receipt.json)和[留出无重复核对](20261020-tagging-iteration-001-validation/holdout-disjoint-audit.json)。
