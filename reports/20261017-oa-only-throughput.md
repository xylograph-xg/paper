# OA-only 拉取提速（2026-10-17）

用户决定：不申请 TDM；放弃较闭源、需要真人核验的出版商；优先高成功率来源；允许更高并发以换取总速率。

本次把“按领域全部入队、逐篇试出版商”改为“只自动拉取有 OA/预印本/仓库路径的论文”，并提高高收益通道的并发和发现频率。

## 1. 策略

| 层级 | 处理 |
| --- | --- |
| 高收益 OA | arXiv、ChemRxiv、PMC/Europe PMC、OSTI、HAL、机构仓库、Nature、Cambridge、APS |
| 中等 OA | Springer、IOP、Frontiers、MDPI、IEEE、Silverchair CDN、Zenodo/Figshare/ResearchSquare |
| 闭源/真人核验 | Wiley、Elsevier、RSC、T&F、OUP、Science、ECS、SID、AIP、ACS（除非有 `is_oa` 或绿色副本） |

`oa_only=true` 时：
- 仅有出版商 PDF 链接的记录不再入自动下载队列，标 `excluded`（原因“无自动OA路径”）；
- 有 `is_oa`、`arxiv_id`、`open_access_pdf`、OA/仓库 URL 的记录保留；
- 排序按 `priority=0`（高收益）→ `1`（其他 OA）→ 直接 PDF；
- 主机仍在长 403 冷却时，记录保持 pending，等到 `retry_at`，不占用下载槽位。

## 2. 代码与配置

- 新增 [oa_policy.py](../fetch/oa_policy.py)：`eligible`、`priority`。
- 新增 [requeue_oa.py](../fetch/requeue_oa.py)：受控恢复 OA 存量；先重置 target/URL 账本，再更新 pending，避免 `keep_fetch_policy_pending` 触发器把状态打回 terminal；写 manifest，不发请求。
- [fetching.py](../fetch/fetching.py)：
  - `queue_pending` OA 门、OA 优先级、主机冷却等待；
  - `find_doi` 快速命中已有论文，避免重复 `upsert`；
  - `_locked_retry` 与逐条 `database is locked` 容忍，单条失败不再中止整轮；
  - `run_acquisition` 在启动子进程前检查全部 PDF 主机是否仍在冷却；全部冷却时直接返回 `host_wait`，不再为每次 0.01 秒的 host 冷却启动 Python 子进程；
  - `queue_scan_limit=400`，限制单轮扫描量。
- [discovery_bridge.py](../fetch/discovery_bridge.py)：
  - OpenAlex 记录保留 `is_oa`/`oa_status`；
  - 种子参考文献/被引请求带 `open_access.is_oa:true`；
  - 主题 OpenAlex/S2/Crossref 在 `oa_only` 下只保留 OA 记录。
- [preprints.py](../fetch/preprints.py)：
  - arXiv/ChemRxiv 改为滚动时间窗（`since`/`until`），不再固定快照重扫历史；
  - 仍保留 `last_scan` 覆盖，避免漏窗。
- 配置：
  - `oa_only=true`、`fallback_queue_limit=150`、`queue_scan_limit=400`；
  - `openalex`/`Crossref` 主题查询从 2 条扩到 7 条（TADF、室温磷光、exciplex、triplet harvesting、磷光铱配合物等）；
  - `discovery_timeout_seconds=240`；
  - `discovery_empty_backoff_max_seconds=900`；
  - `osti_enabled=false`（当前 OSTI TLS 握手普遍超时，先移除每篇 10 秒的空等）。
- 并发：`fetch=120`（80 直链 / 40 回退），`worker-fetch.json` 已显示该容量。

## 3. 实测

### 3.1 OA 门对存量的分类

| 状态 | 闭源 | OA |
| --- | ---: | ---: |
| pending | 1,051 | 60 |
| blocked_fetch | 15,401 | 2,086（priority 0: 729；priority 1: 1,357） |

### 3.2 受控恢复

`requeue_oa --max-priority 0 --limit 500` 恢复 500 篇高收益 OA；manifest：[oa-requeue-1792251583.json](../infrastructure/data/oa-requeue-1792251583.json)。

其中 481 篇仍被 ChemRxiv/PMC 等 host 的 403 冷却挡住（ChemRxiv 约 9 小时、PMC 约 10 小时），所以恢复后不会立刻全部下载；没有把它们当作成功。

### 3.3 实际下载

重载后到 2026-10-18 00:19，`download` 事件新增 8 篇：

- APS accepted manuscript（`link.aps.org/accepted/...`）
- IUCr 期刊 PDF
- 6 篇 fetchpdf 多来源成功（事件未记录具体 URL）

第二轮 `requeue_oa --max-priority 1 --limit 500` 恢复了 500 篇（含中等 OA），manifest：[oa-requeue-1792253461.json](../infrastructure/data/oa-requeue-1792253461.json)。该批触发了一次快速 host 冷却 churn：在 00:00–00:16 之间产生约 7,900 次 0.01 秒级 fast 尝试；随后加入 `run_acquisition` 的父进程 host 预检，重启后 direct 活动从 80 降到约 30，fallback 约 13–40，未再出现同一批 host 的 0.01 秒重试潮。

当前 `discovery_pending`：excluded 672,643、blocked_fetch 16,483、done 2,642、pending 1,829、quarantined 12。

对比修复前的 24 小时 9 篇（2,754 次尝试），当前成功集中到 OA 路径；但总日产量仍受**相关 OA 供给**限制，而不是并发槽位。

### 3.4 运行时

- `worker-fetch.json`：capacity `80/40`，state `working`，无 `control_error`/`dispatch_error`。
- 单轮 `queue_pending` 不再因 `database is locked` 中止；已有论文跳过重复 `upsert`，扫描速度明显提升。
- 发现轮次仍会出现 0 入队：Crossref 主题记录多为领域外，`relevant()` 过滤后丢弃；arXiv/ChemRxiv 当轮只产出 0–4 条。OA 门不会把领域外记录放进下载队列。

## 4. 测试

- `fetch`：170 tests，PASS。
- `core` workflow：13 tests，PASS。
- `make check`：14 projects / 236 source files / 344 exports，PASS。
- 全局 `check_links`：PASS。
- 全工作区 `make test` 的 `workbench/reading` 5 个 HTTP JSON 错误仍为既有问题，单独复现失败，与本次拉取改动无关。

## 5. 仍未解决

1. **相关 OA 供给不足**：主题 Crossref 命中率低，arXiv/ChemRxiv 当轮 0–4 条；OpenAlex 种子通道仍间歇 401/cooldown。提高并发不能创造更多可下载论文。
2. **ChemRxiv/PMC 403**：当前分别约 9/10 小时冷却；冷却到期后才可能恢复。
3. **priority 1 存量**：1,357 篇 blocked OA（Springer/IOP/IEEE/MDPI 等）尚未恢复；可在高收益批次消化后分批处理。
4. **闭源 blocked 存量**：15,401 篇仍以 `blocked_fetch` 保留；不影响自动下载，但面板计数仍大。需要时可一次性标 `excluded`（不删除记录）。
5. **OSTI 暂时关闭**：TLS 握手超时；恢复稳定后再启用。

## 6. 结论

这次把“总速率”从“每天对 1.8 万篇闭源论文重复尝试”改成“对高收益 OA 路径集中并发”。总尝试量下降、单篇成功概率提高；在当前 OA 供给下，日下载量仍不会很高。下一步真正能提高日产量的，是扩大相关 OA 发现（更多主题/种子/预印本）和等 ChemRxiv/PMC 冷却恢复，而不是继续加线程。
