# 二级架构对照实验 0.1.0

这是独立实验候选，未接入正在运行的一级或生产标签侧库。两条路线独立实现，不导入旧classifier/focus的准入与排序代码；旧规则只在评测器中作为对照调用。

1. **证据检索**：同一原文窗口切分成保留位置的证据片段，BM25检索已定义概念，结合章节、研究目标、实际使用及元信息相关性排序。没有BERT或外发模型。
2. **证据概念图**：建立同段/邻接证据中的概念图，PageRank用本文目标/结果作偏置，再按方法使用、机制/问题角色选择核心。开放短语图排序单独列出词表缺口，不自动作为标签。

两方案共享35个现有二级受控概念及别名，保持标签粒度和原窗口。这轮先检验架构，不同时扩充词表来混淆收益。核心数量不凑数、不硬截；每个标签最多保存3条证据是证据展示预算，不是标签数上限。算法仍是词汇与轻量断言结构，不能冒称语义大模型或完整科学理解。

## 文件与边界

| 文件 | 内容 |
|---|---|
| [api.py](api.py) | 两独立分类入口、固定阈值、词表匹配、纯检索/图排序、精确证据检查 |
| [text.py](text.py) | 原句位置映射、通用断言角色、BM25、PageRank、开放短语发现 |
| [concepts.json](concepts.json) | v19的35个二级概念、原别名与英文检索定义；无文献ID/标题分支 |
| [evaluation.py](evaluation.py) | 唯一允许读gold的评测器；旧基线和两方案对照、OOV、逐篇错漏与证据检查 |
| [__main__.py](__main__.py) | 离线stdin/stdout JSON，不读主库/原文文件，不写生产标签 |
| [interface.json](interface.json) | 输入/输出/失败/副作用与候选状态 |
| [__init__.py](__init__.py) | 无副作用包入口 |
| [RESEARCH.md](RESEARCH.md) | GitHub原源码调研、可借鉴与不可直接复现之处 |
| [测试](../../tests/test_l2_architecture_lab.py) | 元信息不能证明二级、方法核心/辅助、历史/否定/假设、精确页码/区间与OOV计分 |

运行示例：`python -m literature.experiments.l2_lab --strategy retrieval < inputs.json > candidate-predictions.json`。输入必须事先由授权流程冻结及核对来源；本入口不自行解析PDF。相同输入重复运行应给出相同科学标签；运行耗时等性能信息由评测器另记。

## 评测纪律

原核心10篇和已用009共20篇仅作开发；SI-only沿用既有资格，不删难例。010只在候选、参数、开发结果及软件门冻结后首次打开。助手先读程序同样输入冻结参考，再生成3组预测，看过错误后不再调参。输入、gold、评价映射、代码和报告各自保存指纹，参考不会进入分类程序。

原生产根目录Python、classifier/focus/taxonomy和一级8进程不变；不启用本地/云/网页模型、不下载模型权重、不执行外部项目代码、不恢复其他暂停。新包只作为明确标注的离线实验包含在发行文件中，不提升为生产入口。

## Version 0.2.0: third architecture and measured outcome

[claim_api.py](claim_api.py) is a separate, typed-field pipeline: extract scientific targets, actual methods and result explanations before concept normalization. The two initial classifiers remain unchanged. This is a lightweight grammar, not the complete ChemDataExtractor implementation. CLI also accepts `--strategy claim_frames`.

20 previously exposed papers,19 eligible for L2,87 reference labels: baseline F1=46.15%; retrieval=40.00%; assertion graph=39.39%; claim fields=35.09%. Claim fields increase precision from69.77% to74.07%, but recall falls from34.48% to22.99%. All3 candidates are retained without adoption. Fresh010 stays unopened; there is no new independent scientific assessment.

Open phrase outputs are unnormalized phrases, not verified out-of-vocabulary scientific concepts: some are known terms, repeated material names or PDF noise. They are never counted as correct controlled tags.
