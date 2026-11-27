# 文献拉取效率修复（2026-10-17）

范围：`fetch` 与 `infrastructure/core` 的拉取链路；未改卡片、核验、修正、浏览器窗口或任何暂停状态。运行数据只做了一次有证据的 OpenAlex 冷却纠正，未清队列、未重置其他来源、未重发未知请求。

## 1. 修复前的事实

- 20:33 起本机代理把 DNS 解析到 `198.18.0.0/15`（fake-IP），`public_url()` 将所有 PDF 地址判为内网；20:33 后 48 次获取尝试 0 成功。
- `classify()` 把该 `ValueError` 判成 `deterministic`，fast URL 被永久排除；fetchpdf 十个来源全部在发请求前被拒。
- 13:39 的 OpenAlex 401 触发 86,400 秒全局冷却；1,002 个 seed 全部 deferred，即便同一请求在 21:14 已连续 3 次返回 200。
- 发现链约 660 轮/天，每轮 200–300 条记录、0 入队、约 1,000 条告警、5MB checkpoint + 5MB raw；checkpoint 每次 `emit` 全量重写。
- 24h 2,754 次获取尝试换 9 篇；`needs_manual_download` 18,590，`fetch_targets` terminal 17,468。

## 2. 已实施的修改

| 修改 | 文件 | 行为 |
| --- | --- | --- |
| 本机代理 fake-IP 兼容 | [services.py](../infrastructure/core/services.py)、[public_http.py](../fetch/public_http.py) | 仅接受“主机名经 DNS 解析到 198.18.0.0/15”的地址；字面 IP 仍拒绝，RFC1918/loopback/link-local 仍拒绝；TLS 主机名校验不变 |
| 守卫错误可重试 | [fetch_policy.py](../fetch/fetch_policy.py) | `指向本机或内网`/`连接地址指向` 归为 `transient`，不再永久拉黑 URL；目标 6 次上限仍生效 |
| OpenAlex 401 有界退避 | [network.py](../fetch/network.py) | 401 改为 60s→120s→…→最多 3600s；403 出版商 WAF 仍保留 24h 长冷却 |
| 种子通道短路 | [discovery_bridge.py](../fetch/discovery_bridge.py) | provider 已在冷却时只运行有界 Crossref 后备，其余 seed 标 deferred；运行中首次 401 后停止后续 seed 请求 |
| seed 轮换 | [discovery_bridge.py](../fetch/discovery_bridge.py) | 每轮从不同 offset 开始，避免后段 seed 长期饿死 |
| checkpoint 节流 | [discovery_bridge.py](../fetch/discovery_bridge.py) | 默认每 2 秒最多写一次，轮末强制写一次；不再每次 emit 全量重写 |
| 发现空转退避 | [fetching.py](../fetch/fetching.py)、[first_round.json](../infrastructure/config/first_round.json) | 连续 0 入队时 60→240→960→3600 秒退避；有入队立即回到 60 秒 |
| 接口登记 | [core/interface.json](../infrastructure/core/interface.json) | 新增 `services__is_public_address` 公开出口 |

新增配置：

```json
"discovery_empty_backoff_max_seconds": 3600,
"discovery_checkpoint_seconds": 2.0
```

## 3. 运行状态纠正

- 仅对 `openalex` 一个 key 做了一次有证据的纠正：原 `retry_at` 为 2026-10-18 14:09（24h 冷却），在 3 次相同请求均返回 200 后缩短为 5 秒探测，`failures=0`。
- 证据文件：[network-state-reconcile-20261017.json](../infrastructure/data/network-state-reconcile-20261017.json)。
- 未修改其他 provider 的冷却，未清退避，未重发任何旧请求。
- `local.paper.fetch` 已正常重载：service PID 93102，worker PID 93106，`control_error`/`dispatch_error` 均为空。

## 4. 实测验证

| 验证 | 结果 |
| --- | --- |
| `public_url('https://www.nature.com/...pdf')` | 通过（此前 REJECT） |
| 字面 `http://198.18.0.5/`、`10.0.0.1`、`127.0.0.1` | 仍拒绝 |
| `dial_public(('www.nature.com',443))` | 连接成功，peer `198.18.0.77` |
| 直链下载 | 2,638,824 字节，`%PDF-1.4`，sha256 `b0c161d4…` |
| fetchpdf 多来源 | `source=unpaywall`，7 次请求，2,638,824 字节 |
| 临时 Catalog 全链路获取 | `acquisition=available`，身份校验与内容寻址写盘成功 |
| OpenAlex 探测 | HTTP 200，state 的 `retry_at` 清零 |
| 重载后实时获取 | 3 次 fast/fallback，失败原因是真实 403/SSL 超时；不再出现“指向本机或内网” |
| 发现退避 | 22:15 一轮 311 条记录、0 入队，`empty_streak=4`，下一轮约 23:15 |
| 种子告警 | 最近一轮 seed status 告警从 1,010 降到 10；`seed-rotation.json` 已推进；1,010 个 seed 仍因 OpenAlex 间歇 401 暂缓 |

测试：

- `fetch` 全量：165 tests，PASS。
- `core` workflow：13 tests，PASS。
- `make check`：14 projects / 234 files / 344 exports，PASS。
- 全局 `check_links`：PASS。
- 全工作区 `make test`：2,268 tests；`fetch`、`cards`、`review`、`correction`、`browser`、`core`、`maintenance` 等通过；`workbench/reading` 的 5 个 HTTP JSON 回归错误与本次改动无关（单独复现仍失败，属既有测试/错误响应体问题）。

## 5. 仍未解决/未实施

1. **OpenAlex 401 仍间歇出现**：21:50、21:54 的探测仍收到 401，21:58 后探测恢复（`code=None, failures=0`）。这说明不是单纯陈旧状态，可能是代理出口节点或上游策略。代码已把影响限制在最多 1 小时，但根治需要稳定出口或 `OPENALEX_API_KEY`。
2. **闭源出版商 403 天花板**：Wiley/ACS/Elsevier/RSC/AIP 仍以 403 为主；当前修复不改变“约 75% 的存量没有自动 OA 路径”的事实。建议下一步做 Unpaywall/OpenAlex 预检 + 闭源短路，预计可把 fallback 的 43 秒/篇降到数秒，并回收约 900 篇存量。
3. **数据保留未动**：DB 1.9GB、raw 39GB、672k excluded 仍保留。清理需要单独的删除授权。
4. **真实获取恢复速度**：队列中大量目标处于 15 分钟–24 小时退避，修复后不会立刻批量重试；这是既有保护，未提前解除。重载后到 22:16 尚无新的生产下载，3 次 fast/fallback 为真实 403/SSL 失败，0 次守卫错误；22:15 的发现轮次仍为 0 入队，下一轮约 23:15。

## 6. 结论

这次修复解决的是“本机网络门 + 守卫误判 + 单点 24h 冷却 + 发现空转”四个可确认问题，恢复了下游真实网络能力；不把并发从 72 再提高，因为瓶颈从来不是槽位。真正的日产量仍由出版商可达性和 OA 覆盖决定。
