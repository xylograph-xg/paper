# 核心标签精简试验：同10篇开发样本

已实现literature 0.3.0核心标签：一级通常1～3个、二级2～5个，不凑数或硬截；列表显示核心，辅助证据保留，父分类用于检索。可比较9篇主文的平均标签数从6.44降到3.22。精简改善核心标签精确率，但细方向召回仍低，不能把标签减少当作研究主线识别已经可靠。

## 口径与冻结

本轮重读前次10篇完全相同的标题、摘要及最多7,000字符的原文窗口。当前助手先按核心标准筛选参考标签及明确理由，冻结gold，再生成新规则预测；引文复用前次已验证的逐字原文。新规则未增加科学词表或按文献ID/标题特化，分类不读旧卡片、旧评分、gold或其他文件。纯Python规则，没有本地模型、网页GPT或外发。

这10篇在前次已用于诊断，因此是开发集；没有独立留出集，也没有外部专家金标准。新旧预测均对同一个新核心参考标准计分，不与前次宽标签标准的100%/81.08%精确率直接比较。下面同时给出原始旧输出与仅去掉重复父类后的旧输出，避免把父子重复消除的收益混同于语义改进。

第4篇登记文件已在上轮确认只有Supporting Information。保持旧冻结文本和语义预测不变，二级只单列诊断，不计入主文二级指标。因此一级10篇、二级9篇。另用当前来源守卫重新核对其原始PDF指纹，确认实际输入流程仍阻断该文二级，记录missing_input；来源测试没有替换冻结语义输入。

## 同一核心参考标准下的指标

| 层级 | 策略 | 正确 | 非核心/错标 | 漏标 | 精确率 | 召回率 | F1 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 一级（10篇） | 旧输出原样 | 14 | 15 | 8 | 48.28% | 63.64% | 54.90% |
| 一级（10篇） | 旧输出去重复父类 | 14 | 8 | 8 | 63.64% | 63.64% | 63.64% |
| 一级（10篇） | 新核心策略 | 13 | 3 | 9 | 81.25% | 59.09% | 68.42% |
| 二级（9篇） | 旧输出原样 | 10 | 20 | 28 | 33.33% | 26.32% | 29.41% |
| 二级（9篇） | 旧输出去重复父类 | 10 | 18 | 28 | 35.71% | 26.32% | 30.30% |
| 二级（9篇） | 新核心策略 | 9 | 5 | 29 | 64.29% | 23.68% | 34.62% |



一级核心参考22个，其中4个超出词表；二级核心参考38个，其中26个超出词表。新策略词表内召回分别72.22%和75.00%，但开放词表召回才反映重要方向的实际覆盖缺口。一级完全匹配2/10篇，二级0/9篇。数量变少并不意味着分类完整。

## 数量与逐篇结果

下表列出核心参考数与程序输出数，括号内为一级＋二级。SI的二级语义数只作审计，未发布为主文标签。

| 序号 | 文献 | 参考核心数 | 旧输出数 | 新核心数 |
| --- | --- | ---: | ---: | ---: |
| 1 | Highly efficient multi-resonance thermally activated delayed fluorescence material toward a BT.2020 deep-blue emitter | 2+5 | 3+10 | 1+5 |
| 2 | Theoretical Study of the Exciplex Formation in an m-MTDATA–BPHEN OLED | 2+5 | 3+4 | 2+3 |
| 3 | Orientation distributions of vacuum-deposited organic emitters revealed by single-molecule microscopy | 2+3 | 4+2 | 2+1 |
| 4 | Pure Organic Room Temperature Phosphorescence from Excited Dimers in Self-Assembled Nanoparticles under Visible and Near-Infrared Irradiation in Water.（仅SI，二级单列） | 2+4 | 1+7 | 1+3 |
| 5 | Realizing Highly Efficient Solution-Processed Homojunction-Like Sky-Blue OLEDs by Using Thermally Activated Delayed Fluorescent Emitters Featuring an Aggregation-Induced Emission Property | 3+5 | 7+2 | 4+2 |
| 6 | A Solution-Processable Small-Molecule Host for Phosphorescent Organic Light-Emitting Devices | 3+3 | 4+2 | 2+0 |
| 7 | Direct observation of deep electron traps in aged organic light emitting diodes | 1+4 | 2+0 | 1+0 |
| 8 | 3D Electron Diffraction Structure Determination of Terrylene, a Promising Candidate for Intermolecular Singlet Fission | 2+4 | 0+4 | 0+1 |
| 9 | Multi-Colored Light-Emitting Electrochemical Cells Based on Thermal Activated Delayed Fluorescence Host | 3+4 | 3+4 | 2+1 |
| 10 | High light-quality OLEDs with a wet-processed single emissive layer | 2+5 | 2+2 | 1+1 |



### 1. Highly efficient multi-resonance thermally activated delayed fluorescence material toward a BT.2020 deep-blue emitter

DOI：10.1038/s41467-024-46619-8。

核心是深蓝MR-TADF分子兼顾色纯度和高亮度效率；RISC/SOC、滚降与窄带是主线。常规表征和主体掺杂不列核心。

- 一级参考：多重共振TADF、有机电致发光器件。

- 一级程序：多重共振TADF。

- 一级非核心/错标：无；漏标：有机电致发光器件。

- 二级参考：反向系间窜越、自旋轨道耦合、效率滚降、窄带发射与色纯度、π共轭拓展与蓝光/RISC权衡。

- 二级程序：系间窜越、反向系间窜越、自旋轨道耦合、发光猝灭、效率滚降。

- 二级非核心/错标：系间窜越、发光猝灭；漏标：π共轭拓展与蓝光/RISC权衡、窄带发射与色纯度。

辅助证据保留：有机发光分子、发光量子产率测量、含时密度泛函计算、时间分辨发光光谱、硼氮分子骨架。



### 2. Theoretical Study of the Exciplex Formation in an m-MTDATA–BPHEN OLED

DOI：10.32931/io2309a。

核心是给受体激基复合物形成及CT/能级排列，DFT与多参考对照是关键方法；不把所有磷光/ISC讨论都列主线。

- 一级参考：激基复合物发光、有机电致发光器件。

- 一级程序：激基复合物发光、有机电致发光器件。

- 一级非核心/错标：无；漏标：无。

- 二级参考：电荷转移态、给受体分子体系、密度泛函计算、多参考量子化学计算、激基复合物形成与能级排列。

- 二级程序：电荷转移态、密度泛函计算、给受体分子体系。

- 二级非核心/错标：无；漏标：多参考量子化学计算、激基复合物形成与能级排列。

辅助证据保留：系间窜越。



### 3. Orientation distributions of vacuum-deposited organic emitters revealed by single-molecule microscopy

DOI：10.48550/arxiv.2305.11572。

核心是OLED发光分子的取向分布，单分子显微法与主客体成膜环境；超荧光只是所用发光体背景。

- 一级参考：有机电致发光器件、有机发光分子。

- 一级程序：超荧光与敏化荧光、有机电致发光器件。

- 一级非核心/错标：超荧光与敏化荧光；漏标：有机发光分子。

- 二级参考：主客体掺杂体系、单分子离焦与偏振显微成像、发射偶极取向分布与成膜环境。

- 二级程序：主客体掺杂体系。

- 二级非核心/错标：无；漏标：单分子离焦与偏振显微成像、发射偶极取向分布与成膜环境。

辅助证据保留：有机发光分子、发光猝灭。



### 4. Pure Organic Room Temperature Phosphorescence from Excited Dimers in Self-Assembled Nanoparticles under Visible and Near-Infrared Irradiation in Water.

DOI：10.1021/jacs.9b00859。

摘要核心为水相有机室温磷光和细胞成像；窗口为SI，二级仅单列语义审计，不能代表合格主文输入。

- 一级参考：磷光发光、细胞荧光/磷光成像。

- 一级程序：磷光发光。

- 一级非核心/错标：无；漏标：细胞荧光/磷光成像。

- 二级参考：系间窜越、非辐射衰减、二聚体促进三重态与磷光、水相自组装有机纳米粒子。

- 二级程序：电荷转移态、系间窜越、单晶X射线衍射。

- 二级非核心/错标：电荷转移态、单晶X射线衍射；漏标：二聚体促进三重态与磷光、水相自组装有机纳米粒子、非辐射衰减。

辅助证据保留：含时密度泛函计算、非辐射衰减、发光猝灭。



### 5. Realizing Highly Efficient Solution-Processed Homojunction-Like Sky-Blue OLEDs by Using Thermally Activated Delayed Fluorescent Emitters Featuring an Aggregation-Induced Emission Property

DOI：10.1021/acs.jpclett.8b00344。

核心为TADF/AIE非掺杂OLED，通过异构工程、纯膜和界面通道调控实现溶液加工；RISC速率等参数属支撑。

- 一级参考：有机电致发光器件、热活化延迟荧光、聚集诱导发光。

- 一级程序：聚集诱导发光、激基复合物发光、有机电致发光器件、热活化延迟荧光。

- 一级非核心/错标：激基复合物发光；漏标：无。

- 二级参考：非辐射衰减、非掺杂纯发光层、溶液法器件制备、界面激基复合物与同质结发光通道调控、异构工程调节材料与成膜性质。

- 二级程序：单三重态能隙调控、非辐射衰减。

- 二级非核心/错标：单三重态能隙调控；漏标：界面激基复合物与同质结发光通道调控、溶液法器件制备、非掺杂纯发光层、异构工程调节材料与成膜性质。

辅助证据保留：发光薄膜、有机发光分子。



### 6. A Solution-Processable Small-Molecule Host for Phosphorescent Organic Light-Emitting Devices

DOI：10.2494/photopolymer.29.317。

核心为耐醇小分子主体支持多层溶液法器件与电子注入；量子产率只是常规表征。

- 一级参考：有机电致发光器件、磷光发光、主体材料。

- 一级程序：有机电致发光器件、磷光发光。

- 一级非核心/错标：无；漏标：主体材料。

- 二级参考：主体薄膜耐溶剂性与溶剂正交性、溶液法器件制备、电荷平衡与电子注入。

- 二级程序：无。

- 二级非核心/错标：无；漏标：溶液法器件制备、电荷平衡与电子注入、主体薄膜耐溶剂性与溶剂正交性。

辅助证据保留：有机发光分子、发光量子产率测量、器件运行稳定性。



### 7. Direct observation of deep electron traps in aged organic light emitting diodes

DOI：10.1063/1.1835567。

核心为OLED老化电子深陷阱；伏安测陷阱电荷和瞬态EL是识别该机制的关键方法。

- 一级参考：有机电致发光器件。

- 一级程序：有机电致发光器件。

- 一级非核心/错标：无；漏标：无。

- 二级参考：器件运行稳定性、电子深陷阱与电荷俘获、器件伏安法与陷阱电荷测量、瞬态电致发光。

- 二级程序：无。

- 二级非核心/错标：无；漏标：电子深陷阱与电荷俘获、瞬态电致发光、器件伏安法与陷阱电荷测量、器件运行稳定性。

辅助证据保留：无。



### 8. 3D Electron Diffraction Structure Determination of Terrylene, a Promising Candidate for Intermolecular Singlet Fission

DOI：10.1002/cphc.202100320。

核心为有机晶体结构及单线态裂分可行性；3D电子衍射和固态GW+BSE是主线，DFT几何核对属支撑。

- 一级参考：有机晶体、单线态裂分与有机激子物理。

- 一级程序：无。

- 一级非核心/错标：无；漏标：单线态裂分与有机激子物理、有机晶体。

- 二级参考：三维电子衍射结构测定、GW与Bethe-Salpeter激发态计算、固态单线态裂分可行性与驱动力、晶体堆积与电子激发态关系。

- 二级程序：电荷转移态。

- 二级非核心/错标：电荷转移态；漏标：三维电子衍射结构测定、GW与Bethe-Salpeter激发态计算、晶体堆积与电子激发态关系、固态单线态裂分可行性与驱动力。

辅助证据保留：三重态湮灭、含时密度泛函计算。



### 9. Multi-Colored Light-Emitting Electrochemical Cells Based on Thermal Activated Delayed Fluorescence Host

DOI：10.1038/s41598-017-01812-2。

核心为TADF主体LEC、多色发射和离子掺杂器件，FRET及主客体配比直接决定工作机制；泛化滚降非核心。

- 一级参考：热活化延迟荧光、主体材料、发光电化学池。

- 一级程序：磷光发光、热活化延迟荧光。

- 一级非核心/错标：磷光发光；漏标：发光电化学池、主体材料。

- 二级参考：Förster能量转移、主客体掺杂体系、离子诱导电化学掺杂与原位p-i-n结、多色与白光发射调节。

- 二级程序：主客体掺杂体系。

- 二级非核心/错标：无；漏标：离子诱导电化学掺杂与原位p-i-n结、多色与白光发射调节、Förster能量转移。

辅助证据保留：有机发光分子、Förster能量转移、单三重态能隙调控、发光猝灭。



### 10. High light-quality OLEDs with a wet-processed single emissive layer

DOI：10.1038/s41598-018-24125-4。

核心为低色温健康照明OLED，湿法混合发光层、共主体效率及光谱健康指标；局部猝灭解释非主线。

- 一级参考：有机电致发光器件、健康与低色温照明。

- 一级程序：有机电致发光器件。

- 一级非核心/错标：无；漏标：健康与低色温照明。

- 二级参考：溶液法器件制备、多发光体与共主体混合发光层、共主体改善器件效率、白光显色与光谱相似度、蓝光风险与昼夜节律相关光谱指标。

- 二级程序：发光猝灭。

- 二级非核心/错标：发光猝灭；漏标：溶液法器件制备、多发光体与共主体混合发光层、共主体改善器件效率、白光显色与光谱相似度、蓝光风险与昼夜节律相关光谱指标。

辅助证据保留：主客体掺杂体系。



## 实现及限制

focus.py只按通用证据主线规则筛选：一级优先具体研究方向，省略重复上位类别及泛化对象；二级要求原文已接受证据，并用标题摘要锚点、正文主线和方法辨识度筛选。标题摘要只能帮助判断中心性，不能代替缺失的原文方法证据。常规测量进入supporting_labels；核心父类进入inherited_labels，不显示为额外核心。范围不凑数、不硬截，例5有4个一级标签，例8无可识别一级方向。

辅助及继承证据同样核对逐字引文/页码，自动run及输入按新版本不可变保存；侧库不改写主Catalog、原文、卡片和历史人工决定。标签/集合过滤只用核心与继承分类，辅助保留详情；自由文本搜索继续覆盖原始元信息。旧结果保留旧规则，需显式重新运行才使用新策略。

精简仍会保留非主线内容，例如取向研究中的超荧光背景、单线态裂分中的CT支撑，以及照明研究中的局部猝灭解释；也会错移核心内容，例如FRET。取向、溶液加工、耐溶剂性、深陷阱、单线态裂分、显色/健康光谱等核心方向尚未进入固定38标签词表。这些缺口在评测中如实计漏，没有据此扩大或特化生产词表。

因此当前适合验证“少量核心标签＋详情证据＋上位检索”的产品组织方式，尚不足以宣称自动精细分类可靠。后续规则或词表改进应在本开发集分析，再用新的独立样本验收。

## 中间结果与复现

- [冻结协议](20261020-core-directions-validation/protocol.json)、[核心标准](20261020-core-directions-validation/policy.json)、[指标及逐篇差异](20261020-core-directions-validation/metrics.json)。

- [旧输出原样指标](20261020-core-directions-validation/baseline-raw-metrics.json)、[旧输出去重复父类指标](20261020-core-directions-validation/baseline-leaves-metrics.json)、[SI守卫实测](20261020-core-directions-validation/source-guard-retest.json)。

- 完整同输入、gold、预测、代码快照、10篇隔离侧库：infrastructure/data/literature-evaluations/20261020-core-directions-v2/。原始语义输入/预测不写正式生产侧库；SI只有当前来源保护后元信息结果进入隔离侧库。

- 前次宽标签gold/输入/预测保留在20261020-directions-v1目录，未回改。新结果由literature.benchmark.compare校验冻结材料及参考引文后计算。当前源码与冻结协议hash核对见validation.json。

- [桌面](20261020-core-directions-validation/desktop.png)与[手机](20261020-core-directions-validation/mobile.png)为独立临时数据库合成示例；本轮未重启正式工作台、CDP所有者或暂停工作流。

## 验证结果

本轮literature 31项、reports 5项、workbench 27项共63项相关测试通过；独立headless浏览器验证核心显示、辅助/上位分类详情、鉴权、筛选、集合及移动端无溢出/JS错误。`make test`全部2390项执行通过（测试运行器另报告2179个唯一测试ID、211个既有重复注册槽位），失败0、错误0、跳过0。本轮没有修改修正模块来修复上轮失败；以上仅记录当前工作区实际结果。

`make check`通过（15组件、251生产源码、355公开导出），tools全局update与check_links通过。新旧冻结材料/gold及当前核心源码hash均核对一致。完整记录见[验证JSON](20261020-core-directions-validation/validation.json)、[全量日志](20261020-core-directions-validation/full-tests.log)、[相关测试](20261020-core-directions-validation/targeted-tests.log)和[页面验证](20261020-core-directions-validation/browser.log)。
