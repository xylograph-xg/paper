# OLED/TADF 参考仓库评估（2026-10-20）

本轮按用户提供的三个仓库读取README和相关源码，固定下列提交。仅借鉴数据建模和溯源设计；没有安装依赖、运行仓库脚本、下载权重、导入其数据集或复用其模型通道。以下观察是源码审阅，不是性能验收。

| 仓库与提交 | 实读材料 | 对当前项目的价值 |
| --- | --- | --- |
| [tadf-photoluminescence-prediction](https://github.com/Dingyun-Huang/tadf-photoluminescence-prediction/tree/e797660a49a15395398b9cc9809a732d4231500f) | README；`mining-codes/tadf_model_extractor.py`；`src/data_processing/tadf_dataset.py`；`src/gnn/gnn_config.yaml` | PL实验数据与分子SMILES、溶剂条件分开；图神经网络/分子指纹属于研究方法，预测值与实验值需要明确区分 |
| [oled_agent](https://github.com/YajingSun-Group/oled_agent/tree/3603cb6064d902141e724859e47f8780151b71de) | README；`InformationExtractionAgent/extract_info.py`；`InformationExtractionAgent/llm/prompt.py`；`InformationExtractionAgent/llm/call_llm.py` | 材料与器件分层，主客体、多掺杂、多层发光结构分别表示；缺失留空，保留原单位；每个发光体/器件配置须独立对应 |
| [OLED-MAMA](https://github.com/jihuaxlab/OLED-MAMA/tree/8e44b39ad781ad1175330c0901b1b90a197ce114) | README；`tongyi_get_mol_dict_from_table_img.py`；`MLs/create_dataset_mol_get_properties_energy.py`；`MLs/create_dataset_mol_get_properties_lem.py` | 分子代号—图像—SMILES—表格属性需要明确对应；同一性质可以有多组数值及条件；表格标题、脚注和物理页定位都是证据 |

## 本版实际采用

1. 在原有文献标签证据中新增 `locator`，单独保存 `entity`（材料/分子代号）、`table`、`figure`、`conditions` 原文文本。它们与PDF物理页、原文哈希和逐字依据共同保存，不会自动识别结构或换算数值。
2. 提供明确点击才导入的OLED候选词表，共19项；含TADF、主客体/多掺杂/多层结构、RISC、PL测量、图神经网络、分子指纹、OLED及独立学习用途。仅供词表起步；新词全部候选，已有词表与别名决定保留，没有任何文献因此被打标签。学习用途来自用户方案，不宣称来自参考仓库。
3. 方法标签的 `used` 与 `mentioned` 分开。某文献介绍图神经网络，并不能据此标为“本文实际使用图神经网络”。
4. 数值属性不作为自由标签，也不从其他仓库的数据集写回本库。首版保持质量分、核验分读取原记录，科学验收独立。

## 后续属性记录的建议接口（本版未实现）

若增加用于比较实验数据的 `observations`，建议每条记录至少包含：

- 本项目文献ID、原文哈希、具体材料/器件实体ID、原文分子代号；SMILES需独立证据与确认状态，缺失时不能猜。
- 性质键（如PL/EL波长、PLQY、PF/DF寿命、ΔE_ST、S₁/T₁、k_RISC、EQE）与原始数值文本、原始单位；原始精度保留。
- 观测类型：实验/计算/模型预测/文献引用；不能混排为同一种实验事实。
- 溶剂、相态、温度、气氛、主体、客体、掺杂比例、器件配置及表脚注；未给出则明确缺失，不从常识补齐。
- 同一实体、同一性质下允许多组条件和重复实验，不简单取最大值；比较时明确实验条件是否可比。
- 来源页/表/图/行列定位、原始引文、输入/生成版本、自动候选/人工决定和逐条变更记录。

## 不照搬的实现与原因

- `oled_agent` 的器件指标提示倾向提取最大值，会丢失条件和分布；本项目比较学习应保留每条独立记录。
- `OLED-MAMA` 的表格提示包含依据数值范围推断PLQY百分比再乘100的规则；本项目不据范围推断单位，也不改写原值。需要换算时另存规范值、明确规则和证据。
- 上游抽取脚本有独立DeepSeek/Qwen服务配置和失败重试；当前项目不接入这些通道，不复制自动重试，既有GPT网页版、唯一所有者、未知回执和暂停保护持续生效。
- 不能以分子预测任务替代文献分类，也不能将GNN预测准确度当作文献质量或卡片核验分。

许可：第一、第三仓库根目录标MIT；第二仓库GitHub元信息未报告根许可证。本轮没有复制这些仓库的实现或数据。若后续实际引入实现或数据，应单独核对对应文件、依赖和数据许可，以及论文引用要求。
