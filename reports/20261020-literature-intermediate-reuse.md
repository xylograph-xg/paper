# 文献自动标签中间结果盘点与GitHub参考（2026-10-20）

用户要求先核对已有中间结果，标题摘要定大方向、原文定细方向；不采用逐篇人工标注或人工确认。本轮只读检查，没有模型推理、原文重解析或真实标签写入。

## 实际盘点

主Catalog快照：31,118篇文献，23,818篇有摘要，6,489篇已登记原文。沿当前制卡/核验/修正任务文件夹和card_path父目录检查，不递归扫历史归档。

- 找到3,649份source-context文件，其中制卡1,802份、核验1,847份。
- 制卡通过原paper_id及原文hash匹配并校验冻结context文件hash的有1,659份；核验通过原job_id、任务文献身份、原文hash及冻结context文件hash的有1,366份。
- 两队按文献ID去重，得到**1,838篇**可复用逐页原文文本。文件份数不等于文献数。
- 找到6篇parsed.json，全部包含在上述1,838篇内；经伴随卡片/检查点与主库原文hash绑定。4篇章节非空，2篇章节为空；同时有段落、页码、bbox、图caption及公式候选等字段。
- 4,651篇登记原文在本次索引范围内没有取得上述可验证context；不是断言它们不存在其他历史中间材料。旧packet缺失或身份/版本绑定不足不自动采纳。
- 原文hash来自一致的只读Catalog及账本；本次未对全部原PDF重新hash。正式复用前仍应核对当时实际原文，不能把本次盘点当永久验收。

实际样例路径、字段及两次只读核对计数见[原始盘点JSON](20261020-literature-intermediate-reuse.json)。

## GitHub参考与具体取舍

| 项目 | 本轮读取 | 对当前任务的作用 |
| --- | --- | --- |
| [spaCy](https://github.com/explosion/spaCy) | PhraseMatcher和rule-based matching官方文档/源码资料 | 用受控术语、别名和上下文规则匹配现有文本；不必调用大模型或重解析PDF |
| [YAKE](https://github.com/INESCTEC/yake) | README与无监督关键词说明 | 自动发现词表外术语，形成候选；关键词排名不能直接当科学分类 |
| [GROBID](https://github.com/grobidOrg/grobid) | README的TEI正文、章节、参考文献和坐标合同 | 参考结构化中间表示；仅将来缺结构材料需要评估，不部署新常驻 |
| [Docling](https://github.com/docling-project/docling) | README与DoclingDocument/provenance官方资料 | 参考JSON文档、表格、页/bbox溯源和后续增量复用；未来只评估缺失的版面/OCR能力 |

仓库固定提交见[仓库版本记录](20261020-literature-reuse-repositories.json)。本轮没有安装/运行上述库，没有性能或标注准确率验收。

## 落地设计与变更

设计见[literature/AUTOMATIC_TAGGING.md](../literature/AUTOMATIC_TAGGING.md)。优先直接使用Catalog元信息作一级分类；使用已有source_text/parsed作为二级证据输入；补缺失结构后再做受控词表、章节角色、否定/引用和实际使用/背景提及规则。每条标签回指原文片段、1基物理页、来源文件hash与规则版本。旧parsed的page从0基转换，不能与source_page混用。

source-context只取原文和页索引，不把科学规则模板、旧卡片答案或分数作为分类事实。只缺文本的文献才补本地文本解析，不为了标签重做整包视觉材料。证据不足保持无法判断，不转人工标注。

本轮仅新增盘点/设计文档并同步根规则、README、接口迁移说明和数据包声明。当前人工首版仍待替换，自动标注未上线；该状态如实保留，不用文档声明假装已经禁用旧接口。原始数据、冻结输入、报告、卡片、模型与工作流暂停状态均未修改。
