# 主题时间窗、离场清理与 OpenAlex 401 后备（2026-10-18）

用户要求：

- 主题/Crossref 新发现只取最近 20 年；
- 解释并处理最近 133 篇中被新过滤器判为离场的 42 篇；
- 修复 OpenAlex 401，按维护者判断实现。

实现边界：

- `discovery_max_age_years=20`。OpenAlex topic、S2 topic、Crossref topic 请求带 `from_publication_date` / `year` / `from-pub-date`。队列对非种子关联记录再做一次 `recent_enough` 检查；未知日期保留。种子参考文献/引用链不套 20 年限制，保留基础文献能力。
- 42 篇最近已下载的离场记录标 `metadata.out_of_scope=true`、`scope_classification_source=keyword_policy_20261018`，保留原文资产、卡片和回执，不物理删除。清单见 `data/off-field-quarantine-20261018.json`。工作台/制卡按既有 `out_of_scope` 保护过滤。
- OpenAlex 免费公共额度按 IP 共享；当日额度耗尽会 401。检测到 provider 级 401 时，本轮最多 `seed_fallback_batch=10` 个到期种子改用 DOI-exact Crossref 参考文献后备；不再为 1,000+ 种子同时发请求。引用链仍等待 OpenAlex 额度恢复或配置 `OPENALEX_API_KEY`/S2 key，不伪造引用。
- 已有原文、卡片、人工决定、暂停、未知回执不因本调整改写。未开始新的网页任务或模型请求。

## OA-first discovery follow-up (2026-10-18)

- `topic_workers` 2→4, `seed_workers` 6→8, effective `discovery_timeout_seconds` 240→300; download workers unchanged.
- Crossref topic fallback defaults to `provider_failure`: only when OpenAlex/S2 actually fail, not merely return an empty page. Per discovery run at most 3 queries and 25 Crossref rows may use it; `crossref_topic_fallback` can be set to `always`/`never` and budget/rows remain configurable.
- Rationale: 8h window had 226/264 new records from Crossref fallback and 219 manual-download additions. OpenAlex OA topic results and arXiv/ChemRxiv now get the discovery time; closed Crossref records no longer dominate.
