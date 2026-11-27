# 核心标签持续优化：第28轮独立评测

**固定1.4.21单次独立评测与软件检查完成：一级P80.00/R30.77/F1=44.44；二级P62.50/R40.98/F1=49.50。一级漏标明显，整体仍未达到可靠分类。**

本轮固定已验收directions-rules-1.4.21 / oled-directions-v10 / literature0.5.15，对此前封存的第六组10篇进行一次独立评测。没有修改规则、词表、测试、输入窗口或包/工作台依赖。一级召回偏低，二级细方向也有缺口；软件检查通过不能替代分类质量。

## 单次独立结果

| 层级 | TP/FP/FN | 精确率 | 召回率 | F1 | 词表内召回 | 词表外核心参考 |
| --- | --- | --- | --- | --- | --- | --- |
| level1 | 8/2/18 | 80.00% | 30.77% | 44.44% | 42.11% | 7 |
| level2 | 25/15/36 | 62.50% | 40.98% | 49.50% | 69.44% | 25 |

两级都保留全部10篇，完全匹配均0/10。参考为26个一级、61个二级核心，共87条逐字证据；部分文章有多条独立机制与问题，2～5仅作参考，未硬截标准。没有把参考数量减少来提高召回。一级平均输出1.0个核心（范围0～2）、二级4.0个（范围0～8），不凑数；参考平均2.6/6.1。

该结果仅适用本轮冻结1.4.21/v10。前次1.4.14在另一组10篇的独立结果保留为历史，样本和标准不同，不将这次二级召回差异声称算法前后提升。第六组已在第一次查看结果时标为已用测试；今后只能作开发，规则变动后必须清空current独立结果并保留本轮冻结历史。

这是同输入助手参考，不是外部专家共识。样本来自有原文和可复用文本的元信息分层筛选，不能推广成全库无偏准确率。词表外方向、颗粒度差异和来源疑点也限制分数解释。

## 冻结顺序与不可变记录

先核对第27轮源码、六组开发结果及post-registration验收，五科学文件完全相同。原第六组抽样协议在1.4.14/v7时生成，其旧rule_version描述抽样时环境，原文件不改；本轮新目录明确评价版本为1.4.21/v10，复制完全相同inputs/samples及7000字符预算。原第六组旧sealed快照仍不可变，当前实际曝光以本轮independent006/exposure.json和iteration-state为准，不再把旧sealed字段当尚未使用。

当前助手逐篇阅读程序相同的read-01～10输入，先写26/61参考并在2026-10-21T03:27:09.742814+08:00冻结gold与判读说明。当时预测文件不存在，87条参考引文逐字/页码检查后才生成一次预测，另存predictions-frozen回执，评测从未进入生产规则或标签。gold SHA256为`0233da0434ac1b3ac72667b78c5c12bf16cac75d9dc343332ebf5a851dd1dce3`。没有gold-to-production语义映射；32个独立词表外概念的层级/维度/名称定义公开保留reference-concepts.json，全部继续计入漏标。

没有根据看到的错误修改参考、规则、别名、阈值或窗口；没有全库发布或启动模型、网页、常驻/CDP。原输入、身份、原文、旧gold、卡片、分数和历史人工决定保持只读。

## 逐篇数量与主要缺口

| 序号 | 文献 | 标准一级/二级 | 输出一级/二级 | 一级正确/误标/漏标 | 二级正确/误标/漏标 |
| --- | --- | --- | --- | --- | --- |
| 1 | Hybridization of short-range and long-range charge transfer excited states in multiple resonance emitter | 2/7 | 1/4 | 0/1/2 | 4/0/3 |
| 2 | A state-switchable TADF macrocycle for multi-analyte sensing and hydrogen gas-driven emission enhancement | 3/6 | 1/4 | 1/0/2 | 1/3/5 |
| 3 | Late-stage direct double borylation of B/N-based multi-resonance framework enables high-performance ultra-narrowband deep-blue organic light-emitting diodes | 3/7 | 1/7 | 1/0/2 | 5/2/2 |
| 4 | Deep-learning-based inverse design model for intelligent discovery of organic molecules | 3/5 | 2/0 | 1/1/2 | 0/0/5 |
| 5 | Intercluster aurophilicity-driven aggregation lighting circularly polarized luminescence of chiral gold clusters | 3/5 | 0/0 | 0/0/3 | 0/0/5 |
| 6 | Guest concentration, bias current, and temperature-dependent sign inversion of magneto-electroluminescence in thermally activated delayed fluorescence devices | 3/7 | 1/8 | 1/0/2 | 5/3/2 |
| 7 | The degradation mechanism of multi-resonance thermally activated delayed fluorescence materials | 2/5 | 1/3 | 1/0/1 | 2/1/3 |
| 8 | An oligomer approach for blue thermally activated delayed fluorescent emitters based on twisted donor-acceptor units | 2/6 | 1/6 | 1/0/1 | 4/2/2 |
| 9 | Regio- and conformational isomerization critical to design of efficient thermally-activated delayed fluorescence emitters | 3/7 | 1/6 | 1/0/2 | 3/3/4 |
| 10 | Lanthanide complexes with d-f transition: new emitters for single-emitting-layer white organic light-emitting diodes | 2/6 | 1/2 | 1/0/1 | 1/1/5 |

一级常见缺口是背景定义之后的本文命名/结果延续未承接、词表外主题，以及当前被动句中间有修饰语。如第5篇明确“were for the first time fabricated”，现有连续were fabricated模式没有识别；第1篇只剩泛泛的object.molecule，遗漏MR-TADF和OLED主线。反方向，第4篇机器学习主体材料设计被标成磷光发光主题。

二级覆盖缺少包合传感/MD/MMGBSA、双硼化、氧化降解/本体电解、构象动力学、稀土d-f等方向。部分已有方法与机制留在辅助或漏准入；也把CT、ISC、SOC、TTA、猝灭等支持性描述升为核心。例如第2篇包合主体不是半导体主客体掺杂，泛object.host_guest在本参考中不算命中。更宽泛的CT标签不能代替局域/电荷转移发射切换这一细方向；公开精确匹配规则与逐篇结果，不事后做多对一折算。

## 来源与证据边界

接受/辅助/继承证据187/187逐字位置合格，非继承分层来源173/173，提及层级来源32/32；87/87参考证据精确一致。原PDF字节和冻结source-context字节分别10/10匹配，输入/原文指纹逐篇保留。机械合格只说明原句、区间和层级一致，不表示科学可靠性或主文来源验收100%。

第5篇输入呈现Fig.S系列及实验前页，疑似SI主导，但登记source_kind=registered_main_article；本轮没有看窗口外封面或正文，不能直接断言已确认SI-only，也不能宣称主文身份核验通过。该篇两级仍计分，未用剔除难例提高指标；原始关键金属亲和机制没有出现在同一二级窗口，不从元信息补入二级参考。第8篇相反，原文包括Article/Received/主文标题/引言，却被块元信息统标supporting information；不能凭section字段排掉这些真正的本文内容。

全部10篇原文窗口均截断，当前仍无缺失窗口的新增样本；没有把有限文本误称全篇科学核验。SI疑点、主文误分段与身份hash保护分别记录，后续可做来源诊断，不能覆盖本轮原输入或结果。

## 开发集结果，沿用同源码冻结回执

六组60篇是曝光开发。本轮没有重跑这些相同预测；五科学文件与第27轮逐字相同，复制其summary并保存输入/gold/预测/metrics/audit的逐文件hash，明确为1.4.21原有开发结果，不冒称新独立测试或新改进。

| 开发组 | 一级P/R/F1（%），与第27轮相同 | 二级P/R/F1（%），与第27轮相同 | 每篇一级/二级核心 | 接受/继承证据 | 分层来源 |
| --- | --- | --- | --- | --- | --- |
| original-development | 87.50/63.64/73.68 | 73.68/36.84/49.12 | 1.6/2.2 | 137/137 | 119/119 |
| used-test-development | 100.00/75.00/85.71 | 63.64/33.33/43.75 | 1.8/2.2 | 133/133 | 111/111 |
| used-test002-development | 85.00/70.83/77.27 | 46.88/30.00/36.59 | 2.0/3.2 | 163/163 | 144/144 |
| used-test003-development | 90.91/64.52/75.47 | 67.65/42.59/52.27 | 2.2/3.4 | 186/186 | 170/170 |
| used-test004-development | 100.00/60.00/75.00 | 62.50/26.79/37.50 | 1.5/2.4 | 135/135 | 120/120 |
| used-test005-development | 83.33/57.69/68.18 | 63.64/24.14/35.00 | 1.8/2.2 | 146/146 | 133/133 |

开发的旧SI-only排除口径仍只作用原固定标准那1篇，没有扩大到新第六组。没有修改语义对应表或删除旧难例。

## 验证

- 规则、词表、177项标签测试源码与第27轮完全相同；make test 2555次执行、2344个唯一ID、211次重复，0失败/错误/跳过，PASS。
- make check（15组件、252生产文件、360导出）、tools全局update/check_links和git diff --check通过；报告登记后还需5项报告测试及再次静态/全局核对，最终回执在本轮post-registration-validation.json。
- 3159个历史文件hash保持，包括原006旧抽样/封存快照；科学源码、参考、预测及第七组封存指纹全部一致。

仅更新literature评测接口说明、README/ITERATION、工作台说明、模块登记和不可变报告；包和工作台依赖仍0.5.15，没有源码或配置启动副作用。

## 下一项

第七组已通过原有只读元信息/材料接口确定并冻结10篇，与已用70篇在ID/原文SHA/规范化标题均无重叠，组内亦无重复；正文未读、无gold和预测。只按身份去重与固定元信息分层选择，不按本轮预测或错误筛选。

下一轮只尝试摘要被动当前结果中的有界插入修饰语，如were for the first time fabricated；先通用本文/历史/引用/未来/否定/比较正反例，再七组70篇曝光开发。只改摘要归属，不同时放宽原文FOCUS、主文来源或词表；保留原句位置和所有gold，不按文献ID/标题特化。规则一变即将本轮独立结果转历史，第七组继续封存。
