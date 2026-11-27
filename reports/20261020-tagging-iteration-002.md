# 核心标签持续优化：第2轮

**当前为候选，未提升为已验收版：标签回归与页面检查通过，全项目有1项独立制卡重试测试失败。最近已验收离线规则仍为1.2.0。**

本轮词表从38扩到41，增加发射偶极取向、溶液法器件制备、电荷俘获与深陷阱。固定开发标准二级F1由34.62%到49.12%；首组新10篇第一次独立使用时，二级F1由旧版32.79%到候选38.10%。有改进，但二级精确率仍57.14%、召回率28.57%，不足以宣称精细分类可靠。

## 改动与边界

方向规则1.3.0 / oled-directions-v2 / 核心策略v2，接口包literature 0.4.0。三项新概念均为通用科学方向，有独立稳定ID和定义，不按文献ID、标题或答案设置分支。溶液制备要求正文中有实际制备/旋涂等动作，单纯可溶、溶液吸收谱不构成制备；电荷陷阱与光俘获不同，发光偶极取向与普通晶体取向不同。

分类程序不读取gold或评价对应。开发评测另存先冻结的一对一语义对应：gold.question.emitter_orientation → question.emitter_orientation；gold.method.solution_processing → method.solution_processing；gold.mechanism.charge_trapping → mechanism.charge_trapping。同层同维度、逐条定义，拒绝多对一和未冻结对应。原输入、gold及核心标准字节和数量保持不变。

一级仍只用标题摘要，二级使用相同原文窗口；数量范围只是参考，辅助证据、上位分类检索和逐字定位不变。本轮没有模型调用、附件外发、原服务重启或全库发布。

## 固定开发集：同一核心标准

一级10篇、二级9篇，沿用原已知SI-only排除口径。旧版1.2.0预测在新的独立目录、同一冻结ID对应下重新核对，TP/FP/FN完全复现旧值，避免把改ID当成实际提升。词表内指标按候选41项计算；新旧P/R/F1的标准标签数量保持22/38。

| 层级 | 版本 | 正确 | 非核心/错标 | 漏标 | 精确率 | 召回率 | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 一级 | 1.2.0 | 14 | 2 | 8 | 87.50% | 63.64% | 73.68% |
| 一级 | 1.3.0 | 14 | 2 | 8 | 87.50% | 63.64% | 73.68% |
| 二级 | 1.2.0 | 9 | 5 | 29 | 64.29% | 23.68% | 34.62% |
| 二级 | 1.3.0 | 14 | 5 | 24 | 73.68% | 36.84% | 49.12% |



## 首组新10篇：一次独立评测

该组在第1轮就按元信息分层固定抽出，与原开发集在文献ID、原文SHA及规范化标题上无重叠。候选代码及本轮开发指标先冻结，再写exposure-001记录后第一次读取read-XX；当前助手独立写核心标准，全部gold冻结后才生成/查看候选及旧版预测。旧版使用其真实冻结的classifier/focus/taxonomy代码执行，未用候选词表代替旧词表。

10篇全部保留，一级参考24个、二级42个；没有按预测结果筛掉论文。包含学位论文、多语种/拼接摘要、正文参考片段误分章、原文窗口不足等情况。参考标准是助手判读，不是外部专家共识；每篇最多7,000字符正文，不是全篇审查，不代表无原文的全库。

| 层级 | 版本 | 正确 | 非核心/错标 | 漏标 | 精确率 | 召回率 | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 一级 | 1.2.0 | 18 | 0 | 6 | 100.00% | 75.00% | 85.71% |
| 一级 | 1.3.0 | 18 | 0 | 6 | 100.00% | 75.00% | 85.71% |
| 二级 | 1.2.0 | 10 | 9 | 32 | 52.63% | 23.81% | 32.79% |
| 二级 | 1.3.0 | 12 | 9 | 30 | 57.14% | 28.57% | 38.10% |



一级完全一致6/10，二级0/10。新词表在此组仍缺6个一级核心方向、23个二级核心方向。新版本增加2个正确二级标签，错标/非核心数仍为9。平均核心标签数从3.7到3.9，增加的是正确方向；第3篇仍有过多辅助内容进入核心，不能靠硬截数量代替修复。

## 新样本逐篇参考与错漏



### 1. B‒N covalent bond-involved π-extension of multiple resonance emitters enables high-performance narrowband electroluminescence

DOI：10.1093/nsr/nwae115。

主线为B–N键参与的MR骨架π拓展，兼顾窄带、RISC和滚降；SOC、温度谱、主体配方和取向作为支撑。滚降正文窗口主要给背景和总体器件结果，结合同输入摘要可确认本文改善目标，但不由背景段单独确认定量改善。 本文滚降目标在摘要明确，但选中正文没有直接给出本工作滚降结果，因此二级不列滚降。

- 一级参考：多重共振TADF、有机电致发光器件。

- 一级预测：多重共振TADF、有机电致发光器件。

- 一级非核心/错标：无；漏标：无。

- 二级参考：硼氮分子骨架、反向系间窜越、窄带发射与色纯度、π共轭拓展与蓝光/RISC权衡。

- 二级预测：反向系间窜越、自旋振动耦合、窄带发射与色纯度、发光猝灭。

- 二级非核心/错标：自旋振动耦合、发光猝灭；漏标：π共轭拓展与蓝光/RISC权衡、硼氮分子骨架。



### 2. Carrier dynamics and degradation behavior in exciplex upconversion-type organic light-emitting diodes

DOI：10.35848/1347-4065/ae0133。

ExUC器件通过界面激基复合物、Dexter转移及TTU实现低压和寿命改善；TTU与三重态湮灭上转换为同一过程。位移电流用于电荷积累诊断，背景中的陷阱不等于本文证明的俘获机制。

- 一级参考：有机电致发光器件、激基复合物发光。

- 一级预测：激基复合物发光、有机电致发光器件。

- 一级非核心/错标：无；漏标：无。

- 二级参考：器件运行稳定性、Dexter能量转移、三重态湮灭、位移电流测量、界面电荷积累与复合。

- 二级预测：器件运行稳定性。

- 二级非核心/错标：无；漏标：位移电流测量、界面电荷积累与复合、Dexter能量转移、三重态湮灭。



### 3. Sky-blue Solution-processed TADF and Hyperfluorescent OLEDs via a High-Work-Function PEDOT:PSS:PFI Hole Injection Layer

DOI：10.48550/arxiv.2607.18474。

主线是溶液加工HIL改善注入与层间相容，并推广至TADF/HF器件；MR是终端材料选择，不按新MR分子设计分类。正文窗口支持界面能级/混层抑制和FRET，未提供功函数测量细节，不补标签。

- 一级参考：有机电致发光器件、热活化延迟荧光、超荧光与敏化荧光。

- 一级预测：超荧光与敏化荧光、有机电致发光器件、热活化延迟荧光。

- 一级非核心/错标：无；漏标：无。

- 二级参考：溶液法器件制备、界面能级与空穴注入、层间溶剂正交性与混层抑制、Förster能量转移、窄带发射与色纯度。

- 二级预测：Förster能量转移、自旋振动耦合、溶液法器件制备、给受体分子体系、窄带发射与色纯度、发光猝灭、效率滚降。

- 二级非核心/错标：自旋振动耦合、给受体分子体系、发光猝灭、效率滚降；漏标：界面能级与空穴注入、层间溶剂正交性与混层抑制。



### 4. Visualizing the radical-pair mechanism of molecular magnetic field effects by magnetic resonance induced electrofluorescence to electrophosphorescence interconversion

DOI：10.1103/physrevb.95.241201。

主线是载流子自由基对的自旋混合及磁共振光学读出；不能用普通激发态ISC代替载流子对自旋互转，不能把两通道强度互补全当作非辐射猝灭研究。

- 一级参考：有机电致发光器件、磷光发光、有机自旋与磁场效应。

- 一级预测：有机电致发光器件、磷光发光。

- 一级非核心/错标：无；漏标：有机自旋与磁场效应。

- 二级参考：自由基对自旋混合机制、光学探测磁共振、单重态与三重态载流子对互转。

- 二级预测：发光猝灭。

- 二级非核心/错标：发光猝灭；漏标：自由基对自旋混合机制、光学探测磁共振、单重态与三重态载流子对互转。



### 5. Asymmetric Thermally Activated Delayed Fluorescence Materials With Aggregation-Induced Emission for High-Efficiency Organic Light-Emitting Diodes

DOI：10.3389/fchem.2020.00049。

非对称D1–A–D2骨架结合AIE与小能隙，并比较非掺杂和掺杂器件；常规DFT、温度谱及RISC证明是支撑。

- 一级参考：有机电致发光器件、热活化延迟荧光、聚集诱导发光。

- 一级预测：聚集诱导发光、有机电致发光器件、热活化延迟荧光。

- 一级非核心/错标：无；漏标：无。

- 二级参考：给受体分子体系、非对称分子骨架设计、非掺杂纯发光层、非辐射衰减、单三重态能隙调控。

- 二级预测：反向系间窜越、非辐射衰减。

- 二级非核心/错标：反向系间窜越；漏标：非掺杂纯发光层、非对称分子骨架设计、给受体分子体系、单三重态能隙调控。



### 6. Designing novel host materials for blue phosphorescent organic light-emitting diodes

DOI：原记录未提供。

这是一篇学位论文，摘要存在多语种及拼接信息。窗口集中在三嗪双极主体与附录的场致猝灭，标签仅覆盖所见正文；不把聚合物比较、TTA背景或未给测量数据的长期寿命当作本文核心。

- 一级参考：有机电致发光器件、磷光发光、主体材料。

- 一级预测：主体材料、有机电致发光器件、磷光发光。

- 一级非核心/错标：无；漏标：无。

- 二级参考：主客体掺杂体系、发光猝灭、主体客体能级排列与激子损失、三嗪双极主体材料。

- 二级预测：电荷转移态、主客体掺杂体系、发光猝灭。

- 二级非核心/错标：电荷转移态；漏标：三嗪双极主体材料、主体客体能级排列与激子损失。



### 7. Role of chemical reactions of arylamine hole transport materials in operational degradation of organic light-emitting diodes

DOI：10.1063/1.3006890。

核心为芳胺HTL化学降解、键断裂以及空穴陷阱；色谱/质谱用于产物识别。量子计算和常规电学仅支撑，不把所有损失解释都列作独立核心。

- 一级参考：有机电致发光器件、空穴传输材料。

- 一级预测：有机电致发光器件。

- 一级非核心/错标：无；漏标：空穴传输材料。

- 二级参考：器件运行稳定性、电荷俘获与深陷阱、激发态键断裂与化学降解、色谱与质谱降解产物分析。

- 二级预测：电荷俘获与深陷阱、器件运行稳定性。

- 二级非核心/错标：无；漏标：激发态键断裂与化学降解、色谱与质谱降解产物分析。



### 8. Properties of Coherent Vibrational Wavepackets Critically Depend on the Method of Their Generation

DOI：10.1021/acs.jpcc.4c01485。

理论比较SF与Raman生成相干的机制，使用耦合双发色团的绝热/振电描述；不是本文新做泵浦探测实验。窗口p10为参考文献片段，虽然section误标conclusion也不据此标成本文TDDFT；激光能量轮廓在摘要出现而所见正文没有足够细节，不新增该二级标签。

- 一级参考：振动相干与振动波包、单线态裂分。

- 一级预测：无。

- 一级非核心/错标：无；漏标：单线态裂分、振动相干与振动波包。

- 二级参考：振动相干生成机制、振电量子理论与相干强度建模、耦合发色团与绝热描述。

- 二级预测：无。

- 二级非核心/错标：无；漏标：振动相干生成机制、振电量子理论与相干强度建模、耦合发色团与绝热描述。



### 9. Molecular Design Based on Donor-Weak Donor Scaffold for Blue Thermally-Activated Delayed Fluorescence Designed by Combinatorial DFT Calculations

DOI：10.3389/fchem.2020.00403。

核心为组合DFT筛选强给体/弱给体同质结TADF，以及四态动力学拟合；传统D–A仅为比较，CT发射在摘要有而选中正文缺少直接描述，不据此补二级CT标签。

- 一级参考：热活化延迟荧光、有机电致发光器件。

- 一级预测：有机电致发光器件、热活化延迟荧光。

- 一级非核心/错标：无；漏标：无。

- 二级参考：密度泛函计算、强给体弱给体同质结骨架、四态发光动力学模型、单三重态能隙调控。

- 二级预测：无。

- 二级非核心/错标：无；漏标：四态发光动力学模型、强给体弱给体同质结骨架、密度泛函计算、单三重态能隙调控。



### 10. All-optical manipulation of singlet exciton transport in individual supramolecular nanostructures by triplet gating

DOI：10.1039/d1nh00514f。

超分子纳米结构中用ISC生成三重态群、通过单重态–三重态湮灭门控单重态输运；双激光时间延迟和EPR是核心证据。CT已在文中排除，磷光为识别三重态的支撑读出，不是标题摘要所指主要方向。

- 一级参考：激子输运、超分子纳米纤维。

- 一级预测：无。

- 一级非核心/错标：无；漏标：超分子纳米纤维、激子输运。

- 二级参考：系间窜越、三重态门控激子输运、单重态三重态湮灭、双脉冲空间分辨发光探测、时间分辨电子顺磁共振。

- 二级预测：系间窜越。

- 二级非核心/错标：无；漏标：单重态三重态湮灭、三重态门控激子输运、时间分辨电子顺磁共振、双脉冲空间分辨发光探测。



## 发现与后续

细方向错误包含普通振动耦合被当成自旋振动耦合、材料比较或损失解释被保留为核心；漏标包含主线方法的缩写/复数表达、TTU别名，以及位移电流、四态动力学、自由基对、激子输运等尚未覆盖方向。第8篇的引用片段被输入解析标为conclusion，第6篇论文摘要带拼接内容；这些输入质量问题保留并如实记录，未删除难例或重抽窗口。

已查看第一组测试的错误，后续只能把它作为已使用测试/开发诊断，不能再声称改进后的这组结果仍是未见泛化。本轮在曝光之后没有调整科学规则或词表，保留本次1.3.0候选。第二组新10篇已冻结，与此前20篇无ID/原文SHA/规范化标题重叠，尚未阅读正文、制作gold或生成预测。

## 中间结果

- 开发轮：infrastructure/data/literature-evaluations/20261020-iteration-002/，含原字节gold、语义对应、候选/旧预测、源码快照及协议。

- 首次新样本：infrastructure/data/literature-evaluations/20261020-holdout-001/，含曝光时间、gold及冻结回执、独立预测回执、候选和旧版指标；原初始输入冻结清单未改。

- 下一组未见输入：infrastructure/data/literature-evaluations/20261020-holdout-002/；当前状态由iteration-state.json记录。

- [开发指标](20261020-tagging-iteration-002-validation/metrics.json)、[评价ID对应](20261020-tagging-iteration-002-validation/semantic-map.json)、[新样本指标](20261020-tagging-iteration-002-validation/test-metrics.json)、[旧版新样本指标](20261020-tagging-iteration-002-validation/test-baseline-metrics.json)。

- [首次曝光证据](20261020-tagging-iteration-002-validation/test-exposure-001.json)、[gold冻结](20261020-tagging-iteration-002-validation/test-gold-frozen.json)、[预测冻结](20261020-tagging-iteration-002-validation/test-predictions-frozen.json)、[下一组无重复核对](20261020-tagging-iteration-002-validation/next-disjoint-audit.json)。

## 验证及发布边界

42项标签测试、独立headless页面检查、make check和tools全局update/check_links通过；make test执行2415次，失败1、错误0、跳过0。唯一失败为cards.tests.test_web_card_retry.RetryTests.test_protected_source_review_candidate_is_not_reported_published_or_requeued：预期保护候选状态needs_inspection，实际failed。独立进程只跑该测试同样失败，sys.modules未加载任何literature模块，复现日志已保存；本轮没有修改制卡源码。

因此0.4.0 / directions-rules-1.3.0保留为已评测候选，未称通过全项目验收、未重启工作台或原常驻，latest_validated_rule仍为1.2.0。后续定时检查保留该全局门，同时可继续隔离研发；不通过修改无关制卡逻辑或忽略失败来验收标签版。

完整证据见[验证JSON](20261020-tagging-iteration-002-validation/validation.json)、[全量日志](20261020-tagging-iteration-002-validation/full-tests.log)、[独立复现](20261020-tagging-iteration-002-validation/gate-repro.log)、[失败源码指纹](20261020-tagging-iteration-002-validation/global-gate-failure.json)。所有新旧冻结字节及本轮科学源码指纹核对一致。两版P/R/F1以同一参考语义计分；JSON中词表内诊断统一使用候选41项词表，不能误读成旧版38项覆盖率，见[评价上下文](20261020-tagging-iteration-002-validation/evaluation-context.json)。
