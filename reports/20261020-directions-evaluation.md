# Python一二级自动标签：10篇同输入评测

**冻结基线结果：一级精确率100%、召回率54.72%；二级精确率81.08%、召回率41.10%。当前词表和语义规则覆盖不足，不能把高精确率解释为完整分类。**

本轮完成literature 0.2.0的Python一二级标注、原文/冻结材料核对、证据窗口、逐字证据、不可变自动输入/结果与工作台自动入口；HTTP/CLI/Library/Store新增人工标签已停用，历史决定保留。没有本地大模型、网页GPT或附件外发。

## 评测方法

先固定38标签词表和分类规则，再按标题摘要元信息分层、以固定SHA256次序选择10篇具有合法现存文字层的真实文献；没有依据预测表现选择样本。随后冻结每篇标题、摘要、最多7,000字符原文证据及程序预测。当前助手独立读相同输入，保存每个参考标签及精确证据，完成gold后才查看预测。

一级标准仅依据标题摘要；二级仅依据相同原文窗口。原文窗口不等于完整论文。参考标准是助手对相同证据的判读，不是多人专家共识或全篇科学核验。原词表之外的重要方向保留为gold.*，计入开放词表漏标，不通过封闭标签列表隐藏覆盖缺口。没有按这10篇增加科学分类规则。

## 总体指标

| 层级 | 标准标签数 | 正确 | 错标 | 漏标 | 精确率 | 召回率 | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 一级：标题摘要 | 53 | 29 | 0 | 24 | 100.00% | 54.72% | 70.73% |
| 二级：原文细方向 | 73 | 30 | 7 | 43 | 81.08% | 41.10% | 54.55% |

词表内召回率：一级67.44%、二级73.17%；词表外标准标签分别10个和32个。完整标签集合逐篇完全一致为0/10，说明仍有重要方向缺失。指标为标签级micro统计，不是“文章准确率”。10篇为诊断分层样本，不代表全库准确率。

## 选择的10篇

| 序号 | 年份 | 分层 | 文献 | DOI |
| --- | --- | --- | --- | --- |
| 1 | 2024 | mr_tadf | Highly efficient multi-resonance thermally activated delayed fluorescence material toward a BT.2020 deep-blue emitter | 10.1038/s41467-024-46619-8 |
| 2 | 2024 | exciplex | Theoretical Study of the Exciplex Formation in an m-MTDATA–BPHEN OLED | 10.32931/io2309a |
| 3 | 2023 | hyperfluorescence | Orientation distributions of vacuum-deposited organic emitters revealed by single-molecule microscopy | 10.48550/arxiv.2305.11572 |
| 4 | 2019 | phosphorescence | Pure Organic Room Temperature Phosphorescence from Excited Dimers in Self-Assembled Nanoparticles under Visible and Near-Infrared Irradiation in Water. | 10.1021/jacs.9b00859 |
| 5 | 2018 | aggregation | Realizing Highly Efficient Solution-Processed Homojunction-Like Sky-Blue OLEDs by Using Thermally Activated Delayed Fluorescent Emitters Featuring an Aggregation-Induced Emission Property | 10.1021/acs.jpclett.8b00344 |
| 6 | 2016 | host_materials | A Solution-Processable Small-Molecule Host for Phosphorescent Organic Light-Emitting Devices | 10.2494/photopolymer.29.317 |
| 7 | 2004 | stability | Direct observation of deep electron traps in aged organic light emitting diodes | 10.1063/1.1835567 |
| 8 | 2021 | theory | 3D Electron Diffraction Structure Determination of Terrylene, a Promising Candidate for Intermolecular Singlet Fission | 10.1002/cphc.202100320 |
| 9 | 2017 | tadf | Multi-Colored Light-Emitting Electrochemical Cells Based on Thermal Activated Delayed Fluorescence Host | 10.1038/s41598-017-01812-2 |
| 10 | 2018 | other_emission | High light-quality OLEDs with a wet-processed single emissive layer | 10.1038/s41598-018-24125-4 |

## 逐篇参考标准与差异

### 1. Highly efficient multi-resonance thermally activated delayed fluorescence material toward a BT.2020 deep-blue emitter

本文开发MR-TADF分子并制器件。正文给出ISC/RISC、SOC、掺杂体系、滚降/猝灭/寿命和色纯度结果；瞬态衰减、TDDFT和绝对PLQY有直接证据。77K单点及Arrhenius速率不足以单独确认所列温度依赖光谱方法；窗口未明确讨论ΔEST调控，不由数值相减补标签。

**一级参考标签**：发光器件；有机发光分子；多重共振TADF；有机电致发光器件；有机发光；热活化延迟荧光。

程序正确：有机发光分子；多重共振TADF；热活化延迟荧光。

错标：无。

漏标：发光器件；有机电致发光器件；有机发光。

**二级参考标签**：π共轭拓展与蓝光/RISC权衡；系间窜越；反向系间窜越；自旋轨道耦合；密度泛函计算；发光量子产率测量；含时密度泛函计算；时间分辨发光光谱；硼氮分子骨架；主客体掺杂体系；窄带发射与色纯度；发光猝灭；效率滚降；器件运行稳定性。

程序正确：系间窜越；反向系间窜越；自旋轨道耦合；密度泛函计算；发光量子产率测量；含时密度泛函计算；时间分辨发光光谱；硼氮分子骨架；发光猝灭；效率滚降。

错标：无。

漏标：π共轭拓展与蓝光/RISC权衡；主客体掺杂体系；窄带发射与色纯度；器件运行稳定性。

### 2. Theoretical Study of the Exciplex Formation in an m-MTDATA–BPHEN OLED

研究m-MTDATA/BPhen给受体对的CT激基复合物，理论同时解释BPhen磷光；属于OLED相关理论研究而非实际器件制备。TADF/RISC多为引言背景和可能性，不作为一级方向或已证实RISC机制。DFT和多参考计算明确；TDDFT在本窗口未明示。

**一级参考标签**：有机发光分子；激基复合物发光；有机电致发光器件；有机发光；磷光发光。

程序正确：激基复合物发光；有机电致发光器件；有机发光。

错标：无。

漏标：有机发光分子；磷光发光。

**二级参考标签**：多参考量子化学计算；激基复合物形成与能级排列；电荷转移态；系间窜越；密度泛函计算；给受体分子体系。

程序正确：电荷转移态；系间窜越；密度泛函计算；给受体分子体系。

错标：无。

漏标：多参考量子化学计算；激基复合物形成与能级排列。

### 3. Orientation distributions of vacuum-deposited organic emitters revealed by single-molecule microscopy

核心是单分子偶极取向分布，C545T为超荧光终端发光体。主体环境也是研究对象；摘要未明确薄膜/聚合物词，不由制膜常识补一级标签。正文PMMA掺杂体系明确。TADF和量子计算属于未来展望，不能判已使用；猝灭一段用于解释成像限制，不作为本文主要猝灭研究方向。

**一级参考标签**：主体材料；有机发光分子；超荧光与敏化荧光；有机电致发光器件；有机发光。

程序正确：有机发光分子；超荧光与敏化荧光；有机电致发光器件；有机发光。

错标：无。

漏标：主体材料。

**二级参考标签**：单分子离焦与偏振显微成像；发射偶极取向分布与成膜环境；主客体掺杂体系。

程序正确：主客体掺杂体系。

错标：发光猝灭。

漏标：单分子离焦与偏振显微成像；发射偶极取向分布与成膜环境。

### 4. Pure Organic Room Temperature Phosphorescence from Excited Dimers in Self-Assembled Nanoparticles under Visible and Near-Infrared Irradiation in Water.

冻结窗口显示补充信息页S1-S14，含实验方法及计算；这些文字足以支持列出的语义标签，但其来源需要单独标为补充材料，不冒称主文。合成时被水quenched是反应淬灭，不能标为发光猝灭。表格给出相对量子产率测量和光子计数寿命，单晶和TDDFT均明确。晶体结构用于解释纳米粒子发光，不据方法名把一级研究对象改成晶体。

**一级参考标签**：细胞荧光/磷光成像；有机发光分子；有机发光；磷光发光。

程序正确：磷光发光。

错标：无。

漏标：细胞荧光/磷光成像；有机发光分子；有机发光。

**二级参考标签**：二聚体促进三重态与磷光；水相自组装有机纳米粒子；系间窜越；密度泛函计算；发光量子产率测量；含时密度泛函计算；时间分辨发光光谱；单晶X射线衍射；非辐射衰减。

程序正确：系间窜越；密度泛函计算；含时密度泛函计算；单晶X射线衍射；非辐射衰减。

错标：电荷转移态；发光猝灭。

漏标：二聚体促进三重态与磷光；水相自组装有机纳米粒子；发光量子产率测量；时间分辨发光光谱。

### 5. Realizing Highly Efficient Solution-Processed Homojunction-Like Sky-Blue OLEDs by Using Thermally Activated Delayed Fluorescent Emitters Featuring an Aggregation-Induced Emission Property

一级是TADF+AIE小分子及非掺杂膜器件；界面exciplex通道被实验设计调控，属于本工作体系。二级证据有RISC速率、ΔEST和非辐射损失，以及掺杂/纯膜比较。引言的泛化ACQ和磷光背景不当本工作专门方向；只报告DF寿命和PLQY值，不由此补具体测量程序。

**一级参考标签**：发光器件；发光薄膜；有机发光分子；聚集诱导发光；激基复合物发光；有机电致发光器件；有机发光；热活化延迟荧光。

程序正确：发光薄膜；有机发光分子；聚集诱导发光；激基复合物发光；有机电致发光器件；有机发光；热活化延迟荧光。

错标：无。

漏标：发光器件。

**二级参考标签**：界面激基复合物与同质结发光通道调控；湿法旋涂制备器件；非掺杂纯发光层；异构工程调节材料与成膜性质；反向系间窜越；主客体掺杂体系；单三重态能隙调控；非辐射衰减。

程序正确：单三重态能隙调控；非辐射衰减。

错标：无。

漏标：界面激基复合物与同质结发光通道调控；湿法旋涂制备器件；非掺杂纯发光层；异构工程调节材料与成膜性质；反向系间窜越；主客体掺杂体系。

### 6. A Solution-Processable Small-Molecule Host for Phosphorescent Organic Light-Emitting Devices

研究耐醇溶剂的小分子主体及溶液法四层磷光OLED；实际主客体为Ir(ppy)3/TCzBP。积分球PLQE测量明确，寿命仅引言背景。主要细方向是溶剂正交性、溶液多层制备和电荷平衡，不能被现有少量机制标签替代。

**一级参考标签**：发光器件；主体材料；有机发光分子；有机电致发光器件；有机发光；磷光发光。

程序正确：有机发光分子；有机电致发光器件；有机发光；磷光发光。

错标：无。

漏标：发光器件；主体材料。

**二级参考标签**：紫外可见吸收光谱；光电子产额光谱测能级；湿法旋涂制备器件；电荷平衡与电子注入；主体薄膜耐溶剂性与溶剂正交性；发光量子产率测量；主客体掺杂体系。

程序正确：发光量子产率测量。

错标：器件运行稳定性。

漏标：紫外可见吸收光谱；光电子产额光谱测能级；湿法旋涂制备器件；电荷平衡与电子注入；主体薄膜耐溶剂性与溶剂正交性；主客体掺杂体系。

### 7. Direct observation of deep electron traps in aged organic light emitting diodes

核心是电老化OLED中电子深陷阱、内电荷与效率损失。化学身份仍未知，不据trap molecule把一级对象强判为分子设计；器件对象属于词表缺项。近乎非发光态作为损失机制的推测需要保留推测身份。封面Articles You May Be Interested In中的TTA属于推荐他文，不能标签当前论文。

**一级参考标签**：发光器件；有机电致发光器件；有机发光。

程序正确：有机电致发光器件；有机发光。

错标：无。

漏标：发光器件。

**二级参考标签**：电子深陷阱与电荷俘获；瞬态电致发光；器件伏安法与陷阱电荷测量；非辐射衰减；器件运行稳定性。

程序正确：无。

错标：无。

漏标：电子深陷阱与电荷俘获；瞬态电致发光；器件伏安法与陷阱电荷测量；非辐射衰减；器件运行稳定性。

### 8. 3D Electron Diffraction Structure Determination of Terrylene, a Promising Candidate for Intermolecular Singlet Fission

本文确定terrylene晶体结构并预测固态单线态裂分潜力；非OLED/TADF研究。当前工作使用3D电子衍射而不是单晶XRD，文中XRD为局限/比较。TDDFT是孤立分子前人结果，TTA是其他材料的反例，均不能当已用方法或当前机制。CT含量、能量驱动力和GW+BSE属于实际固态预测。

**一级参考标签**：单线态裂分与有机激子物理；有机晶体；有机发光分子。

程序正确：无。

错标：无。

漏标：单线态裂分与有机激子物理；有机晶体；有机发光分子。

**二级参考标签**：三维电子衍射结构测定；GW与Bethe-Salpeter激发态计算；晶体堆积与电子激发态关系；固态单线态裂分可行性与驱动力；电荷转移态；密度泛函计算。

程序正确：电荷转移态；密度泛函计算。

错标：三重态湮灭；含时密度泛函计算。

漏标：三维电子衍射结构测定；GW与Bethe-Salpeter激发态计算；晶体堆积与电子激发态关系；固态单线态裂分可行性与驱动力。

### 9. Multi-Colored Light-Emitting Electrochemical Cells Based on Thermal Activated Delayed Fluorescence Host

本工作是TADF主体/磷光客体的LEC，不能把OLED背景和类比当实际OLED主题。FRET、掺杂浓度猝灭及效率滚降均有原文依据。PIC-TRZ的ΔEST和转换率是已知材料背景，不证明本工作研究能隙或RISC。PVK是成膜助剂，其作用被讨论，但不把一级对象泛化为发光聚合物。

**一级参考标签**：发光器件；发光电化学池；主体材料；有机发光分子；有机发光；磷光发光；热活化延迟荧光。

程序正确：有机发光分子；磷光发光；热活化延迟荧光。

错标：无。

漏标：发光器件；发光电化学池；主体材料；有机发光。

**二级参考标签**：离子诱导电化学掺杂与原位p-i-n结；湿法旋涂制备器件；PVK改善成膜形貌；多色与白光发射调节；Förster能量转移；主客体掺杂体系；发光猝灭；效率滚降。

程序正确：Förster能量转移；主客体掺杂体系；发光猝灭。

错标：单三重态能隙调控。

漏标：离子诱导电化学掺杂与原位p-i-n结；湿法旋涂制备器件；PVK改善成膜形貌；多色与白光发射调节；效率滚降。

### 10. High light-quality OLEDs with a wet-processed single emissive layer

一级信息支持OLED、发光分子和共主体优化，以及健康照明应用；磷光机制只在原文窗口明确，不从正文反填一级。二级核心是多发光体单层白光、共主体/浓度和照明品质。高显色白光需要宽光谱，不能当窄带/高色纯研究；视网膜和褪黑素指标不等于做了生物实验。

**一级参考标签**：健康与低色温照明；发光器件；主体材料；有机发光分子；有机电致发光器件；有机发光。

程序正确：有机电致发光器件；有机发光。

错标：无。

漏标：健康与低色温照明；发光器件；主体材料；有机发光分子。

**二级参考标签**：湿法旋涂制备器件；多发光体与共主体混合发光层；共主体改善器件效率；白光显色与光谱相似度；蓝光风险与昼夜节律相关光谱指标；主客体掺杂体系；发光猝灭。

程序正确：主客体掺杂体系；发光猝灭。

错标：无。

漏标：湿法旋涂制备器件；多发光体与共主体混合发光层；共主体改善器件效率；白光显色与光谱相似度；蓝光风险与昼夜节律相关光谱指标。

## 诊断结论与来源修复

主要漏标来自固定词表缺项，例如发光器件/LEC、单分子显微与取向、溶液加工/溶剂正交性、电子深陷阱、3D电子衍射及单线态裂分、健康照明。已知词表内也有保守语境规则漏掉被动句、跨行/缩写和无章节正文。

7个二级错标主要包括：成像限制中的猝灭被扩大为核心问题、合成后用水quench被当成发光猝灭、引言/前人方法/比较材料的TDDFT和TTA被当作本研究，以及引用材料既知ΔEST被当作本工作能隙调控。需要通用词表扩展与语义判断改进，不宜宣称纯关键词已足够。

第4篇登记材料的冻结窗口是S页补充信息，另行只读核对封面确认Supporting Information。上述指标是对相同窗口的语义标签比较，不证明它是主文。发现后在交付输入层加入通用SI-only门：该材料一级仍可运行、二级返回missing_input且0个主文细标签。原冻结输入、预测、gold和基线指标没有回改；单独复测回执保留。参考gold的语义标签只取冻结窗口，封面追加核对仅用于来源审计。

## 可复核材料

- [10篇清单](/Users/xiaoyanhao/project/paper/infrastructure/data/literature-evaluations/20261020-directions-v1/samples.json)
- [完全相同的冻结输入](/Users/xiaoyanhao/project/paper/infrastructure/data/literature-evaluations/20261020-directions-v1/inputs.json)
- [程序冻结预测](/Users/xiaoyanhao/project/paper/infrastructure/data/literature-evaluations/20261020-directions-v1/predictions.json)
- [助手参考标准与逐条证据](/Users/xiaoyanhao/project/paper/infrastructure/data/literature-evaluations/20261020-directions-v1/gold.json)
- [指标及逐篇差异](/Users/xiaoyanhao/project/paper/infrastructure/data/literature-evaluations/20261020-directions-v1/metrics.json)
- [冻结协议](/Users/xiaoyanhao/project/paper/infrastructure/data/literature-evaluations/20261020-directions-v1/protocol.json)
- [SI保护单独复测](/Users/xiaoyanhao/project/paper/infrastructure/data/literature-evaluations/20261020-directions-v1/source-guard-retest.json)

基线源码原字节保存在评测目录frozen-sources，预测和gold分别有hash；同输入结果在pilot.sqlite3独立保存，不写主Catalog或生产标签库。完整参考文本留本地运行数据，不作为公共工具代码或通用规则。

## 交付与验证

组件代码、公开API、依赖、资源、工作台和根规则已同步。现有旧工作台需正常重启后加载新代码，本轮未重启网页任务所有者或恢复暂停。代码不启动全库常驻；只对明确传入ID进行一次本地处理。

功能回归25项通过，覆盖两级隔离、原文/冻结哈希变化、背景/否定、精确引文、SI保护、显式本地补解析、禁止人工写入、幂等和主库只读；另有工作台/报告回归和独立浏览器测试。make check和tools全局update/check_links结果见验证记录。

全项目make test执行2,377项，5项失败均为既有correction.tests.test_correction_producer_scan_interval中的扫描间隔/claim场景，其余无错误或skip；原始日志保留。全量发现时本组件23项，随后追加评测冻结和本地补解析两个测试后本组件25项单独全过。没有修改修正业务来消除这些失败。

最新相关回归合计57项全部通过（literature 25、workbench 27、reports 5）；独立浏览器、make check及全局update/check_links通过。[验证回执](20261020-directions-validation/validation.json)保存当前源码与冻结基线源码的不同指纹和完整测试汇总。
