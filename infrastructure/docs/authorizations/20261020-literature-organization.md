# 文献标签与主题学习子项目授权（2026-10-20，本聊天）

用户先提供“基础元信息＋多维标签＋证据记录＋主题学习集合”方案，要求：

> 以这种要求，新建一个子项目文件夹，先做初步的功能

方案明确：六维科学标签与学习用途分开；受控词表、别名归一、证据与输入指纹、人工决定保护、多条件筛选、主题集合；普通检索覆盖全部已拉取文献，精选/精读准入保持；“后续采用模型标注时，沿用现有模型、外发与暂停边界；本次只是方案设计”。

随后用户要求参考：

- https://github.com/Dingyun-Huang/tadf-photoluminescence-prediction
- https://github.com/YajingSun-Group/oled_agent
- https://github.com/jihuaxlab/OLED-MAMA/

本轮实现独立 `literature` 物理项目及公开API、独立侧库、工作台页面与JSON入口。通过core公开只读投影读取主Catalog；不改变原文、卡片、分数、主阅读状态、精选准入和工作流暂停。参考仓库只读评估，新增可选候选术语及材料/图表/条件证据定位，不复制模型调用或执行上游脚本。

无自动标注、模型外发、100篇试标、全库回填、新LaunchAgent、CDP连接或恢复暂停授权。没有重启生产工作流；旧工作台进程须正常重启后加载新页面。本轮测试只用临时库、本机HTTP及独立headless浏览器；真实主库仅只读盘点。实现合同和评估见根目录literature/README.md、REFERENCES.md。
