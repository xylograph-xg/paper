# 01 核心仓库源码分析

分析对象：

- `github_rep/openalex_search`（核心逻辑集中在 `openalex_search/scripts/openalex_discover.py`，约 966 行，纯标准库）
- `github_rep/findpapers`（`findpapers/` 包：engine / runners / connectors / core / utils）

分析目的：回答大纲第 12 节的 10 个问题，确定 Literature Explorer 第一版的最小实现方案。

---

## 1. 两个项目分别解决什么问题？

**openalex_search**：解决「从一个研究主题出发，迭代式扩大文献覆盖面」的问题。完整 discovery loop（`run()`，openalex_discover.py L874）：

```text
topic embedding
→ LLM 生成初始查询
→ OpenAlex title_and_abstract.search
→ upsert + provenance(keyword)
→ embedding 与 topic 算 cosine 写入 paper_scores
→ select_seeds() 选种子
→ expand_citations() 后向 references + 前向 citations
→ 从高相似论文提取术语反哺下一轮查询
→ 停止条件判断 → 输出 Markdown/JSON
```

整个流程只依赖 OpenAlex 一个数据源 + 一个 LLM + 一个 embedding 服务。

**findpapers**：解决「多源学术元数据聚合」问题。一条布尔查询串跨 8 个数据库检索、去重合并，外加四条附属流水线：snowball（引文扩展）、similar（相似论文）、get（按 DOI/URL 精确获取）、download（PDF 下载）。架构分层：

```text
Engine（门面）
→ Runner（编排：search/snowball/similar/get/download）
→ Connector（HTTP：限流/重试/解析，注册表插件式）
→ Query（布尔查询 AST → 每库 QueryBuilder）
```

**对我们的意义**：openalex_search 提供「迭代发现」的骨架（loop、状态、停止条件），findpapers 提供「底层获取」的骨架（connector 抽象、合并、去重、容错）。两者互补，功能重叠很少（见 Q9）。

---

## 2. 哪些代码可以直接复用？

### 来自 openalex_search（纯标准库、耦合低）

| 设计/代码 | 位置 | 复用方式 |
|---|---|---|
| 双库 ATTACH：缓存库（papers/embeddings/citation_fetches/citation_edges）+ 任务库（paper_scores/provenance） | L269-340 | 照搬「事实缓存 vs 任务状态」分离思想，但我们按大纲用单库六表 |
| content-hash 缓存键：embedding 以 `sha256("Title:..\nAbstract:..")` 为键，文本变自然 miss | L94-98 | 直接照搬，优于 TTL |
| citation scope_key：`direction|limit=..|from=..|to=..`，同参数永不重抓 | L170 | 直接照搬 |
| `work_key` 三级 ID：OpenAlex ID → doi → title+year | L82-91 | 照搬并扩展（加入 S2 ID 一级） |
| `restore_abstract`：OpenAlex inverted index 还原文摘 | L72 | 直接照搬 |
| `should_stop_for_marginal_gain`：绝对地板 + 相对衰减 + patience 停止规则 | L670-685 | 直接照搬 |
| `select_seeds`：主相似度 + 多个 0.01 封顶加分（provenance 条数、图重现次数、keyword 置信度） | L583-599 | 照搬打分结构 |
| `embed_texts_resilient`：3 次重试 + 失败后二分拆批 | L554 | 照搬模式 |
| 余弦相似度纯 Python 实现 | L104 | 直接照搬 |

### 来自 findpapers（生产级质量）

| 设计/代码 | 位置 | 复用方式 |
|---|---|---|
| ConnectorBase HTTP 层：per-instance 限流锁、双预算重试（429 独立计数）、指数退避封顶 60s + jitter、尊重 Retry-After、日志脱敏 | connectors/connector_base.py | 简化后照搬（我们只需 urllib 版本） |
| 两阶段去重：Pass1 DOI/title+year 主键；Pass2 标题分组 + 预印本年份兼容合并 | runners/search_runner.py `_deduplicate_and_merge` | 第一版只要 Pass1 + 标题 normalize；预印本兼容留作后续 |
| `merge_value` 合并规则：None 让位、字符串取长、数值取大、集合求并、DOI 先到先得 | utils/merge.py | 照搬为 Paper.merge() |
| OpenAlex 解析器：inverted-index 摘要重建、cursor 分页、`fetch_cited_by` | connectors/openalex.py | 参考实现，我们自己写 urllib 版 |
| Semantic Scholar：`/paper/DOI:{doi}/citations` offset 分页、`/recommendations/v1/papers/forpaper/...` | connectors/semantic_scholar.py | 参考接口路径与字段列表 |
| 单源失败降级为警告（`search()` 捕异常返回 []） | connectors/search_base.py | 照搬容错哲学 |

---

## 3. 哪些代码只适合参考？

| 内容 | 原因 |
|---|---|
| openalex_search 的 LLM/embedding 提供方硬编码（sharesai、SiliconFlow/Qwen） | 我们应做 provider 抽象，env 配置 |
| openalex_search 的 `nounish_phrases` n-gram 术语提取 | 纯英文正则、噪音大；第一版用 OpenAlex keywords/topics 元数据即可，不动用 LLM |
| openalex_search 无 cursor 分页（单页 ≤200）、裸 urlopen 无限速 | 参考 findpapers 补限流退避 |
| findpapers 的 query/ 子系统（AST + 8 库 QueryBuilder，800+ 行） | 我们只有两个源，直接用各源原生 search 语法，不需要布尔查询编译器 |
| findpapers 的 web_scraping / IEEE / Scopus / WoS / arXiv / PubMed connectors | OA + S2 已覆盖第一版需求 |
| findpapers 的 DownloadRunner 出版商 URL 模式表 | 脆弱且灰区；第一版不下载 PDF |
| findpapers 的 CrossRef 依赖（snowball 发现通道、默认 enrichment） | OpenAlex 数据源于 CrossRef 且自带引用关系，可完全替代 |
| 向量 JSON 存 SQLite + 全量 Python cosine | 万级以内可用；规模化后再换 sqlite-vec/pgvector |

---

## 4. Paper schema 有什么差异？

| 字段 | openalex_search | findpapers | 我们第一版（大纲 5.1） |
|---|---|---|---|
| 主键 | work_key（OA id/doi/title+year） | `_identity_key()`（DOI 优先，否则小写标题） | paper_id（DOI → OA/S2 id → normalized title） |
| 标题/摘要/作者/年份 | 有（作者只在 metadata_json） | 有（Author 含 affiliation） | 有（authors 存名字列表即可） |
| 来源标识 | openalex_id + doi | Database 枚举集合 `found_in` | openalex_id + semantic_scholar_id + source 列表 |
| 引用关系 | citation_edges 表（图边） | paper.references / cited_by（DOI 列表） | discovery_records + citation 扩展记录 |
| venue | 在 metadata_json | Source 对象（issn/publisher） | venue 字符串 |
| 其他 | citation_count 在 metadata_json | keywords、paper_type、is_oa、is_retracted、funders 等 20+ 字段 | 只保留 citation_count，其余进 metadata_json |

结论：我们的 schema 是大纲 5.1 的最小集，复杂字段一律塞进 `metadata_json` 原文，后续需要再提升为列。

---

## 5. SQLite / cache 怎么设计？

两个项目的共识：

1. **缓存键用内容哈希，不用 TTL**。openalex_search：embedding 键 = (paper_id, model, text_hash)；citation 键 = (paper_id, direction, scope_key)。参数变了自然重新抓，永不过期但永不陈旧。
2. **抓过的事实与任务状态分开**。openalex_search 用 ATTACH 双库；findpapers 不持久化（每次进程内合并）。
3. **每批 commit，断点可续**（openalex_search L550）。

我们第一版按大纲第 6 节用单库六表，吸收上述经验：

```text
papers            事实表：paper_id PK + 全字段 + metadata_json 原文
paper_sources     来源集合：(paper_id, source) PK
discovery_records provenance：(paper_id, discovery_type, parent_paper_id, query, run_id)
user_feedback     人工判断：(paper_id PK, decision, note)
embeddings        (paper_id, model, text_hash) PK，vector_json
search_runs       (run_id PK, topic, started_at, status)
```

另加一张 `citation_fetches(paper_id, direction, scope_key, status)`（大纲之外但必须，否则无法保证「同参数永不重抓」）。

---

## 6. Citation expansion 怎么设计？

**openalex_search**：种子驱动。后向直接用 work 元数据里的 `referenced_works` ID 列表批量抓元数据（ThreadPoolExecutor 16 worker）；前向用 filter `cites:{id}` 单页。防爆炸四层：种子限额（默认 30/轮）→ scope_key 抓取去重 → 边 INSERT OR IGNORE → 轮数/边际收益停止。前向只取单页是规模短板。

**findpapers**：DOI BFS。`SnowballRunner` 每层从 frontier 的 references/cited_by 收集新 DOI，用 GetRunner 逐 DOI 抓元数据；参数有 `max_depth`、`max_papers_per_level`、`max_expansion_per_level`、`direction`；forward 强制要求 OA 或 S2。BFS 发现通道固定走 CrossRef（我们改为 OpenAlex）。

**我们第一版**（大纲 9.8：只对 interesting 论文扩展，这是最根本的防爆炸闸门）：

```text
interesting 论文（未扩展过的）
→ 后向：OpenAlex referenced_works 批量解析（limit 截断）
→ 前向：OpenAlex filter cites:{id}（cursor 分页，limit 截断）
       + S2 /paper/{id}/citations（有 key 时补充）
→ 去重 → upsert → discovery_records(reference_of/citation_of, parent=种子)
→ citation_fetches 标记 complete
→ embedding 排序 → 下一批候选
```

不做人肉 BFS 深度控制——每轮只扩一层，是否继续由用户新一轮反馈决定。

---

## 7. 去重逻辑在哪里？

- **openalex_search**：`work_key()`（L82）三级：OpenAlex ID 末段 → `doi:{lower}` → `title:{lower}|{year}`；`upsert_paper` ON CONFLICT 覆盖。查询级 `seen_queries` 集合；边级主键去重。
- **findpapers**：`search_runner._deduplicate_and_merge()` 两遍：Pass1 `doi:{lower}` / `title:{lower}|year:{year}` 主键；Pass2 标题分组 + 年份兼容贪心合并（解决 arXiv 预印本 DOI vs 出版社 DOI 跨年）。

**我们第一版**（大纲 9.4）：`Paper.dedup_key()` 四级优先级：

```text
DOI（lower、去 https://doi.org/ 前缀）
→ OpenAlex ID
→ Semantic Scholar ID
→ normalized title（lower、去标点、压缩空白）
```

跨源合并时按 `merge_value` 规则补全字段（DOI 先到先得、abstract 取长、citation_count 取大、source 求并）。标题模糊匹配与预印本兼容放到第二阶段。

---

## 8. Provenance 怎么保存？

**openalex_search**：`provenance(paper_id, round, source_type, query_or_seed, score)` 四元组主键，INSERT OR IGNORE 累积；格式化为 `r{round}:{type}:{query}` 写进输出，同时反哺种子打分。

**findpapers**：`Paper.found_in` 集合记录来自哪些数据库；snowball 用 BFS level 隐式记录深度。

**我们第一版**：`discovery_records` 表（大纲 5.2），每篇论文可有多条：

```text
(paper_id, discovery_type ∈ {topic_search, reference_of, citation_of, similar},
 parent_paper_id, query, run_id, score)
```

「第几轮、经由哪条查询/哪篇种子发现」完全可溯源，且同一篇被多条路径发现时全部保留（这本身就是相关性信号）。

---

## 9. 哪些功能重复？

两个项目功能重叠很少，主要在一处：

| 重叠点 | openalex_search | findpapers | 我们的取舍 |
|---|---|---|---|
| OpenAlex 搜索/解析 | 有（含摘要重建、XPAC 参数） | 有（含 cursor 分页、api_key 注入） | 自己写 urllib 版，分页学 findpapers，摘要重建学 openalex_search |
| references/citations 获取 | 有（OA 单源） | 有（OA + S2 + CrossRef 三源） | OA 为主，S2 补充 |
| 去重 | work_key 三级 | 两遍 + 预印本兼容 | 第一版取前者，后者留待第二阶段 |

其余完全互补：loop/状态/停止条件只在 openalex_search；限流/重试/合并/导出只在 findpapers。不存在「两套都要搬」的冗余。

---

## 10. 第一版 Literature Explorer 最小实现需要哪些模块？

综合两个仓库的分析，对照大纲第 4/7/9 节，最小实现为 12 个文件：

```text
literature_explorer/
├── config.py                  # env 配置：DB 路径、API key、embedding provider
├── connectors/
│   ├── base.py                # urllib + 限流锁 + 双预算重试（简化自 findpapers ConnectorBase）
│   ├── openalex.py            # search / get_work / references / citations（cursor 分页 + 摘要重建）
│   └── semantic_scholar.py    # search / get_paper / citations（offset 分页）
├── models/
│   └── paper.py               # Paper dataclass + dedup_key + merge + normalize_title
├── discovery/
│   ├── search.py              # search_papers(query)：双源搜索→标准化→去重→入库→记 provenance
│   ├── query_expand.py        # 确定性扩展：首轮=原 topic；后续从高相关论文的 OA keywords 取词
│   ├── citation_expand.py     # expand_from_paper()：只对 interesting 扩一层
│   └── loop.py                # run_discovery_cycle(topic)：搜索→排序→输出 Top N
├── ranking/
│   ├── embedding.py           # OpenAI 兼容 /embeddings 接口 + (paper_id,model,text_hash) 缓存；
│   │                          # 未配置 API 时降级为词袋重叠打分（保证裸跑可用）
│   └── relevance.py           # cosine + rank_candidates()
├── screening/
│   ├── queue.py               # 待审队列：已打分、无 feedback，按分数排序
│   └── feedback.py            # record_feedback / interesting 列表
├── storage/
│   └── sqlite.py              # 七张表（大纲六表 + citation_fetches）
└── scripts/
    ├── search_topic.py        # python scripts/search_topic.py "OLED triplet exciton"
    ├── review_candidates.py   # 交互式 [i]nteresting/[r]eject/[l]ater
    └── expand_interesting.py  # interesting → 引文扩展 → 排序 → 新候选
```

关键设计决策（与两个参考仓库的差异）：

1. **纯标准库**（urllib + sqlite3 + json），零 pip 依赖，与 openalex_search 一致。
2. **query expansion 首轮不动用 LLM**——初始查询就是 topic 本身（OpenAlex 的 `title_and_abstract.search` 已做全文匹配），后续轮次用高相关论文的 OpenAlex keywords/topics 元数据确定性扩展。LLM 冷启动留作可选 hook。
3. **embedding 可插拔**：配置 `LITEXP_EMBEDDING_*` 环境变量即走真实 embedding；未配置时降级为 title/abstract 词袋与 topic 的重叠打分，保证验收流程裸跑不断链。
4. **停止条件**：`search_topic.py` 单轮产出 20~50 篇候选即完成验收；多轮自动循环（边际收益停止规则）放到 review/expand 闭环稳定之后。
5. **PaperQA2 不集成**，只在 README 预留 `summarize_paper(paper_id)` / `deep_read(paper_id)` 接口说明。
