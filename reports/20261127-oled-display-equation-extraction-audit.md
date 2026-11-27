# OLED 行间公式提取复审与 GitHub 方案比较

2026-11-27，上海时间。最先需要修复的是逐页判定的自相矛盾，以及清晰公式因输出字段缺失而无法进入单篇公式列表。Pix2Text 的独立公式检测和现有整页 JPEG 输入直接匹配，适合作为第二套定位依据。现有 PDF 指纹、页码、原回答、裁图和独立科学核验仍有保留价值。

## 核查范围

只读检查生产队列、冻结图包、原回答、单篇导出和现行 App 代码。14:44 读取 SQLite 事务快照，计划 82,133 个页面任务，已有输出覆盖 3,854 个不同的文章页。按记录计，724 条 equation、3,540 条 non_equation、95 条 uncertain、7 条 unreadable。一页可有多条记录。该快照包括历史 Chrome 和当前 App，后台继续处理。同期遍历的 878 份单篇导出中，24 份页覆盖完整，8 份覆盖完整但有待核项，已批准的训练公式合计为 0。文件遍历和 SQLite 读取各有独立时间边界。

对 5 个 PDF 的 8 个物理页核对原文 SHA256，使用独立的 Poppler 渲染，并与原回答、输出或裁图对照。样本按失败类型、数学密度和容易误收的页面定向选择，适合验证故障，不能估计全库召回率。另运行显示公式、App 队列和报告回归三个测试模块，共 18 项通过。全流程科学准确性不在这些测试的覆盖范围内。

## 已复现问题

| 优先级 | 生产证据与影响 | 建议修复与验收 |
|---|---|---|
| 高 | 历史批次 9178，PDF 第 152 页在同一原回答中既有 non_equation 又有 equation，批次最终为 done。原页下半部有独立式 (5.7)，裁图也包含该式。保存与发布均只比较页面键集合，同页矛盾可以通过。 | 按页分组。non_equation 应为该页唯一结论。允许一页多条公式，也允许在另一位置存在确切的未辨识对象。相互排斥时冻结冲突并本地复核。用该页回放验证。 |
| 高 | 当前 App 批次 8967，PDF 第 142 页（印刷页 140）顶部有无编号的 Rubrène 强度衰减公式。原回答给出了正确的指数结构、9 个真实行号和 bbox，缺少 layout。程序将其降为 uncertain，批次仍为 done，该式从单篇 formulas 列表中排除。95 条 uncertain 中，40 条为裁图与正文/图题重叠，24 条为行号与图片位置不一致，14 条为截取不全，13 条为缺少可靠位置。这 13 条在导出中均缺 layout 且有 bbox 数组；仅对上述实例验证了原图。 | 区分“字段缺失”“区域冲突”和“原页不可读”。优先对原冻结图包本地复核，保留原判。在该实例的内存副本中单独补 layout 后，现有定位器从原行重算出 [418.51,76.23,592.28,125.67]（千分坐标），覆盖页顶公式；不能据此对其他条目批量填字段。 |
| 高，影响 Python 使用者 | 187 条已导出的公式已有 python_mapping_issues，但不在同篇 review_items。其中赋值目标未确认 183 条、等式方向含糊 32 条、角度单位未确认 6 条，类别可重叠。语法合法不足以保证计算含义正确。第 152 页原印刷式 (5.7) 本身两项都有星号，而紧随的说明分别讨论激发态和基态。提取忠实于印刷式，生成的 Python 却恒为零。 | 将映射问题纳入代码待核清单，分别标注“按图转录”和“可计算”。印刷式与正文不一致时保留两者的证据，并冻结 Python 的使用资格。 |
| 中 | complete 的现行定义是“计划页都有返回记录”，uncertain 和 unreadable 也能参与覆盖。App 对新批次发现 unreadable 会转入 review，但允许 uncertain 发布。另一个证据缺口是客户端只要求至少一条本地命令成功；附件 SHA 核对了输入，命令成功不能证明八张图均已被模型逐页检查。 | 分开给出覆盖页、可读页、无冲突页、科学核验公式数。阴性页抽样回看；能取得逐图观测时保存对应图指纹。缺观测时报告证据等级。 |

第 9178 批的原回答与裁图均可回查。页面标识集合的检查位置为 [formula_pilot.py](../oled_formulas/formula_pilot.py#L755) 和 [formula_queue.py](../oled_formulas/formula_queue.py#L128)。位置守卫与降级位于 [display_equations.py](../oled_formulas/display_equations.py#L138) 和 [裁图失败处理](../oled_formulas/display_equations.py#L307)。Python、覆盖与 App 验收逻辑见 [单篇导出](../oled_formulas/formula_queue.py#L203)、[覆盖计算](../oled_formulas/formula_results.py#L177)、[App 批次收取](../oled_formulas/app_queue.py#L268) 和 [客户端回执](../codex_web_client/api.py#L82)。

## 原页抽查

| PDF 物理页 | 观察 |
|---|---|
| [激子扩散论文](</Volumes/ssd-1t-1/paper-library/assets/42ace92c4cad8138ea90c18ff2237f4756593459d372dc8fb1f7d5ae744f5a9b/source.pdf>) 142 | 页顶独立指数式可读，下方正文中的扩散长度等式属于行内。前者在定位合同处降级。 |
| [环化论文](</Volumes/ssd-1t-1/paper-library/assets/3972de425692eab662b508e65559f037c6ac1ff99dc55d31c09622e1778d3a14/source.pdf>) 152、246 | 152 的整页、原回答与裁图确认同页阴阳冲突。246 的两个编号公式和四条无编号积分均有输出，裁图 (C.4) 包含分式和右侧式号。 |
| [聚集诱导发光综述](</Volumes/ssd-1t-1/paper-library/assets/30868c3002627c8e022e03ab04e1629bf0d53a39b25849c124f80532ece15c4a/source.pdf>) 2 | 文字层发现 R = 和 (1b)，原图显示它们是化学取代基和结构编号。无正文行间公式的判定正确。 |
| [荧光团论文](</Volumes/ssd-1t-1/paper-library/assets/53d69ed8588643e47ba9b8f396d2bd48187a2e4d38ee61b4cd0349678c7e3f5c/source.pdf>) 300 | 三张循环伏安图及题注。当前 App 正确排除分子图和坐标轴。 |
| [OLED 材料与器件论文](</Volumes/ssd-1t-1/paper-library/assets/c3dff1d6eb60978a823b80e1673cf5870ca86601093cc34373bad401f4a10caf/source.pdf>) 86、136、155 | 86 页的积分均属表格单元格，136、155 页的关系式与正文共行。三页的阴性判断符合当前提取范围。 |

页 152 的 [保存裁图](</Volumes/ssd-1t-1/paper-library/oled-formulas-20261125/web-organization/display-equations/batches/009178/equations/019.png>) 和页 246 的 [分式裁图](</Volumes/ssd-1t-1/paper-library/oled-formulas-20261125/web-organization/display-equations/batches/010226/equations/008.png>) 可直接复看。

## GitHub 候选项目

核对了上游代码或官方输出说明，链接固定到查询时的提交。本次没有安装权重、运行本地模型或将论文上传给候选项目。下表是功能适配判断，各模型在 OLED 文献上的质量和耗时仍待同页比较。

| 项目 | 最适合承担的步骤 | 本项目需要补的部分 |
|---|---|---|
| **Pix2Text** | 首选行间公式的第二套检测。结果明确区分 isolated、embedding、text，并提供四点坐标、识别文本、置信度。现有整页 JPEG 可直接作为对照输入。[输出源码](https://github.com/breezedeus/Pix2Text/blob/f52e671247c14a29aa59b44e99849e00aee984cd/pix2text/text_formula_ocr.py#L223-L229) | 归一化回原页坐标并核对邻近式号。图内公式、表格和化学结构需要结合区域语义过滤。置信度不能代替逐符号核验。 |
| **PaddleOCR PP-StructureV3** | 第二对照。完整文档版面管线可返回识别串 rec_formula、四点框 rec_polys、公式区域 ID，适合双栏及图表混排。[结果合同](https://github.com/PaddlePaddle/PaddleOCR/blob/dab3fe35379033fdcb2d0e9572fac0b36c9a9ebf/docs/version3.x/pipeline_usage/PP-StructureV3.en.md#L2920-L2925) | 需核对版面类别与“正文独立公式”口径；在本机测运行时间和内存后再决定优先级。 |
| **MinerU** | 需要重做整篇结构解析时比较。官方文档说明了独立公式图、来源页索引和页面几何输出。[输出说明](https://github.com/opendatalab/MinerU/blob/097de7f63f54722c9b805ee1c9a14a0c5b02e078/docs/en/reference/output_files.md) | 记录具体解析后端与坐标基准，零基页索引转换成现有 PDF 物理页码。该版本许可证含附加商业条款。[许可证](https://github.com/opendatalab/MinerU/blob/097de7f63f54722c9b805ee1c9a14a0c5b02e078/LICENSE.md) |
| **LaTeX-OCR / pix2tex** | 已裁出的单个公式图转 LaTeX，适合比较上下标、积分限、矩阵转录。[项目说明](https://github.com/lukas-blecher/LaTeX-OCR/tree/5c1ac929bd19a7ecf86d5fb8d94771c8969fcb80) | 输入阶段已经需要公式图，无法独立衡量整页漏检。 |
| **Docling** | 有整篇 PDF 结构化需求时保留为备选，上游列出布局、阅读顺序、表格和公式理解。[项目说明](https://github.com/docling-project/docling/tree/68a965c936cc0eb978e79d836798169719bde7c3) | 本轮的首要缺口是独立公式检测和裁图归属。对这个目标，前两项的逐框结果合同更直接。 |

## 选型判据

先修逐页冲突和复核清单，再用同一冻结页集比较现行流程、Pix2Text 和 PP-StructureV3。把上述 8 页作为已知回归集，另按论文隔离盲测页，在查看各工具输出前独立标注真值。样本应覆盖无编号、多行、双栏、无文字层、化学图、表格以及含长行内公式的阴性页。按公式实例分别统计召回率、精确率、式号归属、完整裁框率，以及上下标、正负号、分母、矩阵元素的转录错误；单列每页耗时和人工复核量。不能只在现有裁图上评估漏检，也不能只按 LaTeX 字符串相等判定数学转录。现阶段最有价值的试验是让独立检测器找出与 App 判定不一致的区域，并保留原页作裁决依据。
