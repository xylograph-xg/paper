# Literature Explorer 初步大纲

## 1. 项目目标

构建一个面向科研工作的自动文献发现系统。

第一版目标不是“自动完成文献综述”，而是完成最核心闭环：

```text
研究主题
→ 网络搜索
→ 文献标准化
→ 去重
→ 相关性排序
→ 候选论文池
→ 人工标记感兴趣 / 不感兴趣
→ 从感兴趣论文继续扩展
→ 新一轮候选
```

核心原则：

> 用户负责判断“这篇论文值不值得继续看”，系统负责扩大搜索范围、整理候选和持续扩展。

---

# 2. 第一版只参考 3 个项目

## 2.1 openalex_search

角色：自动发现逻辑的主要参考。

重点学习：

- topic → query expansion
- OpenAlex 搜索
- embedding relevance
- seed paper 选择
- references / citations 扩展
- 多轮 discovery
- SQLite 缓存
- provenance
- 停止条件

第一版中优先级最高。

---

## 2.2 findpapers

角色：底层文献获取与统一接口参考。

重点学习：

- 多来源搜索接口
- Paper 数据结构
- DOI / 标题去重
- reference / citation snowball
- PDF 获取思路
- JSON / BibTeX 导出

第一版不要求接入所有数据源。

只优先考虑：

- OpenAlex
- Semantic Scholar

---

## 2.3 PaperQA2

角色：后续全文阅读模块。

第一版不整合。

只预留接口：

```python
summarize_paper(paper_id)
deep_read(paper_id)
```

等“文献发现”流程稳定后再接入。

---

# 3. 第一版系统边界

第一版只做：

```text
topic
↓
OpenAlex / Semantic Scholar
↓
统一 Paper 格式
↓
去重
↓
SQLite
↓
embedding relevance
↓
候选文献
↓
人工反馈
↓
citation expansion
↓
下一轮候选
```

暂时不做：

- 自动下载所有 PDF
- 全文解析
- RAG
- 自动写综述
- Zotero 双向同步
- 复杂前端
- 多 Agent
- 自动知识图谱摄入

这些都放到后续阶段。

---

# 4. 第一版目录建议

```text
literature_explorer/
├── README.md
├── config.py
│
├── connectors/
│   ├── openalex.py
│   └── semantic_scholar.py
│
├── models/
│   └── paper.py
│
├── discovery/
│   ├── search.py
│   ├── citation_expand.py
│   ├── query_expand.py
│   └── loop.py
│
├── ranking/
│   ├── embedding.py
│   └── relevance.py
│
├── screening/
│   ├── queue.py
│   └── feedback.py
│
├── storage/
│   └── sqlite.py
│
├── data/
│   └── literature.db
│
├── scripts/
│   ├── search_topic.py
│   ├── review_candidates.py
│   └── expand_interesting.py
│
└── tests/
```

---

# 5. 核心数据结构

## 5.1 Paper

建议第一版统一成：

```json
{
  "paper_id": "",
  "title": "",
  "abstract": "",
  "authors": [],
  "year": null,
  "venue": "",
  "doi": "",
  "openalex_id": "",
  "semantic_scholar_id": "",
  "url": "",
  "citation_count": null,
  "source": [],
  "status": "discovered"
}
```

---

## 5.2 Discovery Record

必须保存“为什么找到这篇论文”。

```json
{
  "paper_id": "",
  "discovery_type": "topic_search",
  "parent_paper_id": null,
  "query": "",
  "run_id": "",
  "score": null
}
```

`discovery_type` 第一版只需要：

```text
topic_search
reference_of
citation_of
similar
```

---

## 5.3 User Feedback

第一版保持非常简单：

```json
{
  "paper_id": "",
  "decision": "interesting",
  "note": ""
}
```

decision：

```text
interesting
reject
later
```

---

# 6. SQLite 第一版表结构

只建立以下表：

```text
papers
paper_sources
discovery_records
user_feedback
embeddings
search_runs
```

不先建立复杂知识图谱。

---

# 7. 第一版核心接口

```python
search_papers(query)

normalize_paper(raw)

upsert_paper(paper)

deduplicate_paper(paper)

rank_candidates(run_id)

record_feedback(paper_id, decision)

get_references(paper_id)

get_citations(paper_id)

expand_from_paper(paper_id)

run_discovery_cycle(topic)
```

---

# 8. Discovery Loop

第一版最重要的是把下面这个循环跑通：

```text
用户输入 topic
        ↓
生成 3~10 个查询词
        ↓
搜索论文
        ↓
标准化
        ↓
去重
        ↓
embedding 排序
        ↓
展示 Top N
        ↓
用户判断
 ┌──────┼──────┐
 reject later interesting
                 ↓
        references / citations
                 ↓
         新候选论文
                 ↓
             再排序
                 ↓
             下一轮
```

---

# 9. 第一阶段开发任务

## P0：先完成

### 9.1 OpenAlex Connector

实现：

```python
search_openalex()
get_openalex_work()
get_openalex_references()
```

---

### 9.2 Semantic Scholar Connector

实现：

```python
search_semantic_scholar()
get_semantic_scholar_paper()
get_semantic_scholar_citations()
```

---

### 9.3 Canonical Paper Model

所有来源统一到一个数据结构。

---

### 9.4 去重

优先级：

```text
DOI
↓
OpenAlex ID / Semantic Scholar ID
↓
normalized title
```

第一版暂时不做复杂 fuzzy matching。

---

### 9.5 SQLite

保证所有搜索结果和状态可恢复。

任何一次运行中断后都可以继续。

---

### 9.6 Embedding Ranking

输入：

```text
topic
paper title
paper abstract
```

输出：

```text
relevance_score
```

---

### 9.7 人工审核

CLI 第一版就够：

```text
[1] interesting
[2] reject
[3] later
```

暂时不开发网页前端。

---

### 9.8 Citation Expansion

只对 `interesting` 的论文自动执行。

防止整个 citation graph 无限扩张。

---

# 10. 第二阶段再做

第一版稳定以后再加入：

## 10.1 PDF 获取

```python
fetch_fulltext()
```

参考：

findpapers

---

## 10.2 Quick Summary

只使用：

title + abstract

输出：

- 研究问题
- 方法
- 核心结论
- 和当前主题的关系

---

## 10.3 Deep Read

再接：

PaperQA2

---

## 10.4 Zotero

等文献筛选逻辑稳定后再加。

---

## 10.5 OLED 知识库

只允许：

```text
deep_read
+
人工确认高价值
```

的论文进入 OLED Knowledge Pipeline。

避免发现阶段直接污染知识库。

---

# 11. GitHub 仓库阅读顺序

只先看三个。

## 第一优先

```text
openalex_search
```

目标：

看懂完整 discovery loop。

重点不是复制代码，而是理解：

- 状态如何保存
- query 如何扩展
- seed 如何选择
- citation 如何扩展
- 怎么避免重复搜索

---

## 第二优先

```text
findpapers
```

目标：

提取可以复用的底层能力：

- source abstraction
- deduplication
- citation snowball

---

## 第三优先

```text
PaperQA2
```

暂时只看：

- 输入输出接口
- 文献索引方式
- metadata model

第一阶段不集成。

---

# 12. Codex 第一次源码分析任务

让 Codex 先只分析：

```text
openalex_search
findpapers
```

不要立即写我们的项目。

要求输出：

```text
01_core_repository_analysis.md
```

回答：

1. 两个项目分别解决什么问题？
2. 哪些代码可以直接复用？
3. 哪些代码只适合参考？
4. Paper schema 有什么差异？
5. SQLite / cache 怎么设计？
6. citation expansion 怎么设计？
7. 去重逻辑在哪里？
8. provenance 怎么保存？
9. 哪些功能重复？
10. 第一版 Literature Explorer 最小实现需要哪些模块？

---

# 13. MVP 验收标准

第一版只要做到以下流程，就算成功：

```text
python search_topic.py "OLED triplet exciton"
```

得到：

```text
20~50 篇候选论文
```

然后：

```text
python review_candidates.py
```

可以逐篇：

```text
interesting
reject
later
```

然后：

```text
python expand_interesting.py
```

自动：

```text
读取 interesting
→ 获取引用 / 被引
→ 去重
→ embedding 排序
→ 生成下一批候选
```

整个过程：

- 可重复运行
- 不重复抓取已有论文
- 不丢用户反馈
- 可以追踪论文来源
- 中断后可以恢复

满足这五项以后，再做全文、摘要、Zotero 和 OLED 知识摄入。
