# 核心标签持续优化：第35轮独立评测

**固定1.4.26单次独立评测与软件检查完成：一级P87.50/R46.67/F1=60.87；二级P81.25/R22.81/F1=35.62。二级漏标仍明显，分类尚不可靠。**

本轮完成固定 directions-rules-1.4.26 / oled-directions-v12（44词条）/ literature0.5.20 对第八组10篇的单次独立评测。科学源码、239项标签测试、词表、包和依赖不变。没有根据留出集结果调整规则或参考。当前二级召回明显不足。

## 单次独立结果

| 层级 | TP/FP/FN | 精确率 | 召回率 | F1 | 词表内召回 | 词表外核心参考 |
| --- | --- | --- | --- | --- | --- | --- |
| level1 | 14/2/16 | 87.50% | 46.67% | 60.87% | 63.64% | 8 |
| level2 | 13/3/44 | 81.25% | 22.81% | 35.62% | 41.94% | 26 |

全部10篇两级计分，两级完全匹配均0/10。参考30/57个核心标签，共87条逐字定位，平均3.0/5.7；程序输出16/16个，平均1.6/1.6，范围一级1～2、二级0～6。常见数量仅供参考，不以删参考、凑数或硬截取获得好成绩。34个OOV出现全部计漏标，词表内指标仅作补充。

本次与1.4.24第七组使用不同样本和参考，不能从分数差异宣称算法前后提高。第八组首次查看预测即标记已使用，后续仅用于开发；这一次独立成绩只属于冻结1.4.26，科学规则改变时必须转历史并清空当前独立成绩。

当前助手先读相同输入制作参考，并非外部专家共识。抽样限于元信息分层和可复用原文材料，10篇不是全库无偏准确率；核心颗粒度及有界窗口也会影响分数。机械证据合格不等于科学标签正确。

## 冻结顺序与保护

先核对第34轮1.4.26候选/八组80篇开发及完整验收。五个科学源码hash完全相同，239项测试源码冻结。原008在1.4.24环境按元信息抽样，评测目录另记固定1.4.26；不是事后改原抽样协议。输入、样本及7000字符窗口与原008逐字相同。原unopened快照不改，实际曝光由本轮independent008/exposure.json和iteration-state记录。

助手逐篇读read-01～10，30/57参考和选择理由在 2026-10-21T07:27:54.319545+08:00 冻结；当时预测文件不存在。87条参考逐字位置及页码校验后只生成一次预测。gold SHA256：`6c3f0b7b3065d867b7d6188f6cd29824595bd03f54dfff7e0ec02ff23957983a`。本轮无新增生产词条、无语义评价映射；34个评测专用OOV概念公开在reference-concepts.json，概念定义来自先冻gold，不是事后新增科学规则。

参考未进入生产规则或标签；原文、卡片、评分、人工决定、旧冻结输入/gold/回执保持只读。程序未按文献ID或标题特化，没有扩大输入窗口或剔除难例。

## 逐篇核心数和误差

| 序号 | 文献 | 参考一级/二级 | 输出一级/二级 | 一级正确/误标/漏标 | 二级正确/误标/漏标 |
| --- | --- | --- | --- | --- | --- |
| 1 | Efficient deep-blue fluorescent material serving as emitter and host for high-performance organic light-emitting diodes | 4/6 | 1/1 | 1/0/3 | 1/0/5 |
| 2 | Simple structured hybrid WOLEDs based on incomplete energy transfer mechanism: from blue exciplex to orange dopant | 3/6 | 2/2 | 1/1/2 | 2/0/4 |
| 3 | A Three Boron doped B/O/N Multi-Resonant TADF Emitter for Improved Reverse Intersystem Crossing Rate and Efficient Pure Blue Organic Light Emitting Diodes | 3/7 | 2/6 | 2/0/1 | 4/2/3 |
| 4 | Unraveling the Degradation Mechanism in FIrpic-Based Blue OLEDs: II. Trap and Detect Molecules at the Interfaces | 3/6 | 2/0 | 2/0/1 | 0/0/6 |
| 5 | Research Progress on Aggregation-Induced Delayed Fluorescence in Materials and Devices | 3/7 | 2/1 | 2/0/1 | 1/0/6 |
| 6 | Pure Hydrocarbon Materials as Highly Efficient Host for White Phosphorescent Organic Light‐Emitting Diodes: A New Molecular Design Approach | 3/6 | 2/0 | 2/0/1 | 0/0/6 |
| 7 | Correlation between ionic mobility and luminescent stability in double-layer p–i–n OLED architectures | 3/5 | 1/4 | 1/0/2 | 3/1/2 |
| 8 | Efficient calculation of electronic coupling integrals with the dimer projection method via a density matrix tight-binding potential | 2/4 | 1/0 | 0/1/2 | 0/0/4 |
| 9 | Efficient OLEDs Based on Slot-Die-Coated Multicomponent Emissive Layer | 3/5 | 2/2 | 2/0/1 | 2/0/3 |
| 10 | Electroluminescence emission pattern of organic light-emitting diodes: Implications for device efficiency calculations | 3/5 | 1/0 | 1/0/2 | 0/0/5 |

一级已有词漏标8次，其中主体材料2篇、MR客体应用、HF、AIE、OLED、磷光和聚合物各有漏标。第8篇把引言应用列表中的OLED当主要方向。第2篇磷光分支被单列核心，而白光器件主线/不完全转移缺失。MR客体存在不代表第1篇普通荧光主体本身成为TADF发射体。

二级已有词漏标18次，另26次为词表外核心方向；第4、6、8、10篇细标签均空。时间分辨、主客体/供受体、TDDFT、降解分析、猝灭及偶极取向存在漏准入或仅辅助。三次误标是第3篇主客体/非辐射、第7篇主客体从辅助条件提升为核心。误标不表示这些现象在全文不存在，而表示不符合先冻核心粒度。

第4篇实际色谱/ESI-MS联合降解证据分散跨块，当前方法仍落mentions，不能因修过相关规则便声称已覆盖。第5篇中文综述有RISC/能隙/猝灭/运动限制主线，但英文词形及归属规则覆盖不足；第10篇核心取向研究仅入辅助。离子输运、半空间出光、DIPRO/PTB及热稳定性仍有词表缺口。

下一轮只诊断主体角色的一级识别：第1、6篇标题明确以host描述新材料，现有object.host别名仅匹配host material/molecule和少数限定词，单数host标题不匹配；第6篇仅命中旧主体引言而留mentions。先检查通用正反例，有依据才做一项受约束别名/角色改动；不开放无约束host，不同时修改二级归属或核心排序。

## 来源与参考限制

程序接受/辅助/继承证据131/131、非继承层级来源111/111、提及来源42/42定位合格；参考87/87逐字位置正确。原PDF与冻结context各10/10哈希匹配，逐篇输入/原文指纹保留。以上只证明位置、层级和字节合同，不证明完整主文核验或科学真值。

第5篇为中文综述，二级均标review_summary_not_actual_experiment。引用他人温度/TRPL/器件实验不记为本综述作者实际使用的方法，未知章节名不成为排除难例理由。第3篇RISC速率参考来自原文件摘要段，标original_abstract_within_fulltext_window；不冒称主文速率独立核验。

第6篇只支持热/形貌稳定，不硬映射为器件工作寿命；第7篇摘要有瞬态电流/阻抗方法但原文窗口缺失，二级未据此补入。对其高亮度/寿命数值仅记录原作者陈述，未作外部真实性核验。第9篇氧猝灭属原作者提出解释，保留假说性质，不推断新测RISC/FRET速率或把磷光敏化误当HF。

参考本身也有局限：第8篇DIPRO/PTB复合方法概念由窗口中p5参考方法与p7的PTB结果共同支持，但已冻结的单条定位引用只取p5，因此不能把87/87机械定位解释为每条引文单独完整支持概念。冻结后不增补gold证据或更改答案，保留这项参考审计限制。

全部10篇原文窗口均截断，无缺失窗口新样本；未见明确整篇SI-only，但文件登记与hash不能排除所有来源歧义。不读窗口外科学内容、不重解析PDF，不把原文可用等同全篇科学核验。

## 开发结果（沿用同源码，非本轮重跑）

八组80篇均已曝光。同第34轮五个科学文件hash完全相同，本轮复制原summary并保留各组inputs/gold/预测/指标/audit原hash，不重复评测、也不冒称新独立结果。下一轮加入本组后为九组90篇。

| 开发组 | 一级P/R/F1（%） | 二级P/R/F1（%） | 每篇一级/二级核心 | 接受/继承证据 | 非继承来源 |
| --- | --- | --- | --- | --- | --- |
| original-development | 87.50/63.64/73.68 | 73.68/36.84/49.12 | 1.6/2.2 | 137/137 | 119/119 |
| used-test-development | 100.00/75.00/85.71 | 63.64/33.33/43.75 | 1.8/2.2 | 132/132 | 110/110 |
| used-test002-development | 85.00/70.83/77.27 | 46.88/30.00/36.59 | 2.0/3.2 | 163/163 | 144/144 |
| used-test003-development | 90.91/64.52/75.47 | 67.65/42.59/52.27 | 2.2/3.4 | 186/186 | 170/170 |
| used-test004-development | 100.00/60.00/75.00 | 62.50/26.79/37.50 | 1.5/2.4 | 135/135 | 120/120 |
| used-test005-development | 83.33/57.69/68.18 | 63.64/24.14/35.00 | 1.8/2.2 | 145/145 | 132/132 |
| used-test006-development | 84.62/42.31/56.41 | 62.50/40.98/49.50 | 1.3/4.0 | 193/193 | 177/177 |
| used-test007-development | 78.95/55.56/65.22 | 46.15/23.08/30.77 | 1.9/2.6 | 154/154 | 137/137 |

原开发集固定SI-only二级排除1篇不变，本轮两级均10篇计分；旧评价对应与核心标准不改。

## 验证

- 五科学源码、44词条、239项标签测试与第34轮相同；make test 2617次执行、2406个唯一ID、211次重复，0失败/0错误/0跳过，PASS。
- make check、tools全局update/check_links及git diff --check通过，完整计数见check.log；登记后追加5项报告测试及静态/联动复核，最终见本轮post-registration-validation.json。
- 4149个历史材料文件hash保持，科学源码、测试、gold、预测与下一组封存指纹均一致。

仅更新离线评测说明、模块/接口评测元信息、README/ITERATION和报告登记。保持0.5.20精确依赖；不启用模型、不上传、不全库发布、不启动/重载服务、LaunchAgent或CDP，不恢复暂停。

## 下一组

第九组10篇已按原元信息分层和只读材料接口冻结；与已用90篇的文献ID、原文SHA256及规范化标题均无重叠，组内无重复。科学内容未读，无gold/预测；不按本轮错误挑选，封存指纹在next-holdout-receipt.json。下一轮只能在已使用九组中诊断通用host角色，候选和开发验收完成后才能决定何时打开新的未见组。
