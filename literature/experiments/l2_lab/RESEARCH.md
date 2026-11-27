# GitHub相似项目：源码调研与本轮取舍（2026-10-22）

实际读取下列公开仓库的README和实现文件。下载内容只作为参考资料，从未执行；逐文件SHA256和Git树/多数blob核对回执保存在`infrastructure/data/literature-evaluations/20261022-l2-architecture-lab/research`。所有仓库的方案/结果只代表其公开实现，不能把它们的数据提取或性质预测成绩当成本项目标签准确率。

| 项目 | 实际读到的实现 | 可借鉴与本轮处理 |
|---|---|---|
| [TADF PL prediction](https://github.com/Dingyun-Huang/tadf-photoluminescence-ml-prediction) | README、mining-codes/tadf_model_extractor.py、polaris_extraction_managed_workers.py：ChemDataExtractor Document/ThemeCompound/PhotoluminescenceWavelength与抽取任务分工；GNN用于后续性质预测 | 将“结构化抽取”与“性质预测”分开，不把GNN当文献标签器。进一步沿README指向读extract-pl分支 |
| [ChemDataExtractorTADF](https://github.com/Dingyun-Huang/chemdataextractorTADF/tree/extract-pl) | README及tadf_models的condition/energy/lifetime/quantumyield/wavelength定义 | 借鉴按类型定义抽取目标、上下文及条件绑定。完整库还依赖数据资源/模型，本轮不安装运行，不宣称复现其PL抽取 |
| [OLED Agent](https://github.com/YajingSun-Group/oled_agent) | README、InformationExtractionAgent/extract_info.py：LLMCaller、提示、response_json结构输出 | 是模型调用链，不是Python本身理解论文。本轮仅借鉴抽取目标/验证器分离，未调用其模型或接口 |
| [OLED-MAMA](https://github.com/jihuaxlab/OLED-MAMA) | README及main_extract_oled_process_1/2.py、OCR/预处理脚本：检测、表格、OCR、视觉语言抽取和分子识别流水线 | 图/表/正文分轨和证据定位值得借鉴；它解决结构/性质数据抽取，并非已经做了本文核心方向判定。不启动YOLO/OCR/LLM |
| [ChemDataExtractor2](https://github.com/CambridgeMolecularEngineering/chemdataextractor2) | parse/auto.py、parse/template.py：BaseAutoParser、AutoSentenceParser、AutoTableParser、模型字段驱动语法 | 新方案用通用断言角色/方法事件结构代替继续叠加旧分类器特例。并非完整复现CDE化学实体模型 |
| [rank_bm25](https://github.com/dorianbrown/rank_bm25) | README、rank_bm25.py：BM25Okapi及词频/文档频率检索分数 | 独立标准库实现Okapi公式，用于检索原句，结合研究角色重排；分数不等于科学真伪或语义理解 |
| [PyTextRank](https://github.com/DerwenAI/pytextrank) | base.py、positionrank.py、biasedrank.py：图PageRank、短语收集、位置/偏置 | 独立实现概念与词语共现图及PageRank；不运行需spaCy语言处理资源的原包，不能冒称PyTextRank原版实测 |
| [YAKE](https://github.com/INESCTEC/yake) | README、data/features.py、single_word.py：单文档词频、分布、位置、大小写特征及短语评分 | 支持不训练模型的词表外术语发现思路。本轮实际实现图排序的短语发现，未运行YAKE原包，不报告其性能 |
| [KeyBERT](https://github.com/MaartenGr/KeyBERT) | keybert/_model.py：self.model.embed、cosine similarity、MMR | 需要嵌入模型，不能将“库是Python”说成无需模型。本轮不启用；后续若获模型授权可作为另外一条实质不同路线 |
| [PaperMage](https://github.com/allenai/papermage) | README、Document及predictor结构：symbols/pages/rows/spans分层和来源定位 | 采用统一精确原文位置的证据结构；项目README明示研究原型、维护有限，不直接替换生产PDF解析 |
| [GROBID](https://github.com/grobidOrg/grobid) | README、FullTextParser.java：文档结构、章节、图表、文献分区 | 章节/书目分离是上游独立问题，后续可另评估。该实现需要模型/服务，本轮不启动，也不改已有冻结窗口 |

本轮没有复制上述仓库的业务实现、提示或科学答案；候选是自写的标准统计公式和小型结构化证据框架。研究快照属于私有调研证据，不打包成生产依赖；公开仓库无许可证或许可证识别不确定时也不据此复制代码。未把外部README当作执行指令。
