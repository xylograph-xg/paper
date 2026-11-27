# 核心标签持续优化：第32轮独立评测

**固定1.4.24单次独立评测与软件检查完成：一级P78.95/R55.56/F1=65.22；二级P42.31/R21.15/F1=28.21。二级漏标及核心区分明显不足，整体仍未达到可靠分类。**

本轮对已封存第七组10篇完成固定directions-rules-1.4.24 / oled-directions-v12 / literature0.5.18的单次独立评测。规则、词表、216项标签测试、输入窗口和包/工作台依赖均不变。一级仍有漏标，二级核心区分及覆盖明显不足；没有根据结果调参或改参考。

## 独立结果

| 层级 | TP/FP/FN | 精确率 | 召回率 | F1 | 词表内召回 | 词表外核心参考 |
| --- | --- | --- | --- | --- | --- | --- |
| level1 | 15/4/12 | 78.95% | 55.56% | 65.22% | 75.00% | 7 |
| level2 | 11/15/41 | 42.31% | 21.15% | 28.21% | 45.83% | 28 |

全部10篇两级均计分，完全匹配一级2/10、二级0/10。参考27个一级、52个二级核心，共79条逐字证据，平均2.7/5.2；程序平均1.9/2.6，范围分别1～3/0～7。通常标签数仅参考，未凑数或截断参考，也未删去词表外方向、综述或摘要型原文。

指标只适用这一次冻结1.4.24/v12。前次1.4.21/第六组的独立成绩属于不同样本/参考，不能据本次分数差异宣称算法前后提升。本轮首次查看结果即标记第七组已用；以后只能作开发，继续调参需新的未见留出。当前独立成绩在规则改变时须转历史并清空current，保留冻结报告。

这是当前助手同输入独立判读，并非外部专家共识。仅从有原文和可复用文本的文献中元信息分层抽样，不是全库无偏准确率。参考核心颗粒度、有限窗口、来源类型也限制分数解释。

## 冻结与曝光顺序

先核对第31轮科学源码、七组70篇开发结果及post-registration验收；五科学文件完全相同。原007抽样协议在1.4.21/v10环境生成，只代表当时抽样环境；新评测目录明确评价1.4.24/v12，inputs/samples与原7000字符窗口字节相同。原007的旧unopened快照不改，实际曝光以本轮independent007/exposure.json和iteration-state为准。

助手逐篇阅读程序相同read-01～10，先写27/52参考及选择理由，在2026-10-21T05:56:22.413040+08:00冻结。当时预测文件不存在；79条参考逐字位置/页码检查后，仅生成一次预测。gold SHA256：`dcd7d2813b5c168224334c8bca88fcc283d03e7cf4243fbfaf9cc92b2c62a18f`。没有评价语义映射或生产词表新增，33个独立词表外概念公开在reference-concepts.json，所有OOV参考仍计入漏标。

评测只写隔离目录。没有将参考答案写入生产标签/规则，没有按标题/文献ID调整程序，没有事后缩减参考、扩大输入窗口或剔除难例。所有旧输入/gold/回执、原文、卡片、评分及人工决定保持只读。

## 逐篇核心数及误差

| 序号 | 文献 | 参考一级/二级 | 输出一级/二级 | 一级正确/误标/漏标 | 二级正确/误标/漏标 |
| --- | --- | --- | --- | --- | --- |
| 1 | Toward a BT.2020 green emitter through a combined multiple resonance effect and multi-lock strategy | 3/7 | 1/7 | 0/1/3 | 4/3/3 |
| 2 | An Ambipolar BODIPY Derivative for a White Exciplex OLED and Cholesteric Liquid Crystal Laser toward Multifunctional Devices | 3/4 | 2/0 | 2/0/1 | 0/0/4 |
| 3 | Sweet spot of energy-level alignment in hyperfluorescent organic light-emitting diodes | 3/6 | 3/5 | 2/1/1 | 2/3/4 |
| 4 | Studies on the photodegradation of red, green and blue phosphorescent OLED emitters | 2/5 | 2/0 | 1/1/1 | 0/0/5 |
| 5 | Aggregation-induced emission from optically active X-shaped molecules based on planar chiral [2.2]paracyclophane | 2/5 | 2/1 | 2/0/0 | 1/0/4 |
| 6 | New Bipolar Green Host Materials Containing Benzimidazole-Carbazole Moiety in Phosphorescent OLEDs | 3/4 | 3/4 | 3/0/0 | 1/3/3 |
| 7 | Tetradentate Cyclometalated Platinum(II) Complexes for Efficient and Stable Organic Light-Emitting Diodes | 3/4 | 1/3 | 1/0/2 | 1/2/3 |
| 8 | Data-driven discovery of organic electronic materials enabled by hybrid top-down/bottom-up design | 2/6 | 1/1 | 0/1/2 | 1/0/5 |
| 9 | A temperature sensor with a wide spectral range based on a dual-emissive TADF dendrimer system | 3/6 | 2/5 | 2/0/1 | 1/4/5 |
| 10 | 昇華可能な軸不斉誘導体による高効率円偏光エレクトロルミネセンス | 3/5 | 2/0 | 2/0/1 | 0/0/5 |

一级：MR全称/缩写与后续TADF结果未关联，OLED名词化当前结果漏准入；综述摘要研究方向未被承接；光降解、温度传感、激光、数据驱动/iSF及结构族仍有词表缺口。泛TADF或分子标签不能在严格核心ID评价中代替更具体MR-TADF/iSF方向。上位检索照常保留，但本轮不做事后层级折算。

二级：部分CT、DFT/TDDFT、时间/温度分辨及降解产物分析只留辅助或漏准入，背景SOC/TTA/ISC和常规主客体升为核心。主体材料研究的载流子平衡/三重态限域、光降解反应、手性诱导、iSF与高通量设计等尚无受控词条。按独立标准保留这些错漏，不把更宽标签多对一映射成命中。

第4篇LC-MS识别卤化降解产物是主线证据，但降解分析方法未进核心；下轮仅诊断这一通用归属/核心选择问题，先核对现有辅助或提及原因，再决定可验证改动。本轮不改规则。第9篇的纯度HPLC/NMR不算降解分析，溶液法OLED制备是明确方法，避免将所有测量一律升级。

## 来源与证据边界

程序接受/辅助/继承证据156/156逐字位置合格，非继承来源139/139、提及来源26/26均100%；79/79参考证据准确定位。原PDF/context字节各10/10匹配，身份和输入指纹逐篇保留。这些是机械合同检查，不是科学可靠性或完整主文来源100%验收。

第2篇是主文含SI可用性说明与参考文献，被分段字段误标supporting information；不据此排整篇。第8篇编号参考文献被标methods，不能当本文方法证据。第3篇KMC只出现在元信息，窗口内没有明确方法段，因此未从摘要补入二级参考。

第7篇是综述章节，二级证据全标review_summary_not_actual_experiment；讨论了器件寿命不代表作者重新实验。第10篇原文件仅三页，当前窗口全部为原文扩展摘要，二级参考全标original_extended_abstract_only，仍纳入同输入计分；不宣称这是主文细方向核验。不用缩小计分集隐藏该限制，后续来源问题须独立处理。

全部10篇窗口截断；本轮无缺失窗口的新样本，不把选段当全篇。未见明确SI-only整篇，但不能仅凭source_kind登记排除所有来源歧义。只有文件hash读取，未打开窗口外科学原文或重解析PDF。

## 开发结果沿用同源码回执

七组70篇为已曝光开发；本轮没有重跑相同预测。五科学文件与第31轮逐字相同，复制summary并保留每组inputs/gold/gold-frozen/predictions/metrics/audit原hash，明确为1.4.24原有开发成绩，不冒称新独立结果或本轮科学改进。

| 开发组 | 一级P/R/F1（%） | 二级P/R/F1（%） | 每篇一级/二级核心 | 接受/继承证据 | 非继承来源 |
| --- | --- | --- | --- | --- | --- |
| original-development | 87.50/63.64/73.68 | 73.68/36.84/49.12 | 1.6/2.2 | 137/137 | 119/119 |
| used-test-development | 100.00/75.00/85.71 | 63.64/33.33/43.75 | 1.8/2.2 | 133/133 | 111/111 |
| used-test002-development | 85.00/70.83/77.27 | 46.88/30.00/36.59 | 2.0/3.2 | 163/163 | 144/144 |
| used-test003-development | 90.91/64.52/75.47 | 67.65/42.59/52.27 | 2.2/3.4 | 186/186 | 170/170 |
| used-test004-development | 100.00/60.00/75.00 | 62.50/26.79/37.50 | 1.5/2.4 | 135/135 | 120/120 |
| used-test005-development | 83.33/57.69/68.18 | 63.64/24.14/35.00 | 1.8/2.2 | 146/146 | 133/133 |
| used-test006-development | 84.62/42.31/56.41 | 62.50/40.98/49.50 | 1.3/4.0 | 193/193 | 177/177 |

原开发二级SI-only排除仅作用于原固定标准的1篇，没有扩大到本轮。原评价对应及旧标准不变。

## 验证

- 规则、词表、216项标签测试源码与第31轮完全相同；make test 2594次执行、2383个唯一ID、211次重复，0失败/错误/跳过，PASS。
- make check（15组件、252生产文件、360导出）、tools全局update/check_links和git diff --check通过；报告登记后还需5项报告测试及再次静态/全局核对，最终回执在本轮post-registration-validation.json。
- 3715个历史文件hash保持，包括原007旧抽样/封存快照；科学源码、参考、预测及第八组封存指纹全部一致。

只更新评测说明、README/ITERATION、工作台说明、模块记录及不可变报告。包和精确依赖仍0.5.18；没有启用本地/云/网页模型、上传附件、全库发布、启动重载常驻/LaunchAgent/CDP或恢复暂停。

## 下一项

第八组10篇已按原只读元信息分层及材料接口冻结，与已用80篇在ID、原PDF SHA及规范化标题均无重叠，组内无重复；科学内容未读、无gold或预测。只按身份去重与预定分层选择，不按本轮预测好坏挑文献。

下一轮只诊断“直接建立降解路径的产物分析方法未选为核心”：核对当前辅助/提及理由，区分实际降解LC-MS与普通纯度测量、文献引用；有依据才做一项通用改动，先通用正反例再八组80篇开发。不同时改全文归属与核心排序，不改输入/gold，不按ID/题名特化。修改科学规则即把本轮1.4.24独立成绩转历史并清空current，第八组继续封存。
