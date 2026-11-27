# 工作台稳定性静态审查报告

- 任务校验标识：QODER-WORKBENCH-334bf7ae6139（用户原文写作 “QODER- WORKBENCH-334bf7ae6139”，中间空格按笔误处理）
- 实际模型：Qwen3.8-Flash（任务指定标识），推理强度：极高
- 审查日期：2026-10-18
- 审查类型：只读静态源码审查（未运行服务、未执行测试、未连接 Chrome/CDP、未写数据库）
- 项目根：/Users/xiaoyanhao/project/paper/workbench
- 产物写入方式：Python `os.open(..., O_CREAT|O_EXCL)` 独占创建，未使用覆盖式重定向

---

## 1. 审查范围与方法

### 1.1 读取的规则与边界

1. 父目录规则 `/Users/xiaoyanhao/project/paper/AGENTS.md`（当前生效规则，含浏览器/外发边界、卡片保护、只读审查不构成启动授权）。
2. `/Users/xiaoyanhao/project/paper/infrastructure/all/RULES.md`（接口—说明—登记同步要求；本任务为只读，不触发 `sync_tools.py`）。
3. `/Users/xiaoyanhao/project/paper/workbench/README.md`（含 2026-10-14 审核修复段落：16 业务槽 / 64 握手槽 / 2 秒握手期限 / 16KiB 头部预算、上传暂存默认 1GiB 与 7 天 TTL、`/api/reveal-local` 合同）。
4. `/Users/xiaoyanhao/project/paper/workbench/interface.json`（唯一 Python 出口 `web__serve`，CLI 模块 `workbench.workbench_service`、`workbench.upload_storage`）。

因此本报告只主张“当前源码可证明”的缺陷；README 与历史授权只作为合同背景，不用来推断代码行为，也不据历史报告得出任何结论。

### 1.2 审查的主目标文件（全文读取）

| 文件 | 行数 | 关注点 |
| --- | --- | --- |
| `workbench/web.py` | 501 | 并发与共享状态、槽位与超时、请求体容量、错误恢复 |
| `workbench/workbench_service.py` | 113 | 服务重复启动、退出与信号、访问记录、就绪轮询 |
| `workbench/upload_storage.py` | 68 | 上传容量、跨进程锁、回收与幂等 |
| `workbench/workbench.html` | 437 | 前端刷新互斥、超时/取消、重复提交、渲染成本 |
| `workbench/api.py` | 16 | 出口解析方式（确认无实现复制、无导入副作用） |

### 1.3 为验证结论而读取的必要公开接口

- `infrastructure/core/catalog.py`：`connect()`（L178-188，`with` 退出即 `db.close()`）、`enqueue()`（L467-486）、`jobs_page()`（L502-504）、`retry()`（L605-613）、`jobs` 表定义与 `one_active_job` 唯一索引（L120-125）。
- `infrastructure/core/workflow_priority.py`：`sort()`/`annotate()`（L47-125）。
- `infrastructure/core/runtime.py:17-31`：`alive()`（`os.kill(pid,0)` + macOS `proc_pidinfo` 僵尸判定）。
- `infrastructure/core/services.py:96-110`：`atomic_json()`、`validate_pdf()`。
- `workbench/reading/log_output.py:40-45`：`spawn_logged()`（子进程内轮转，stdout/stderr 为 DEVNULL，无父进程排水线程）。
- `cards/web_card_queue.py:16,133-140`：`web_card_jobs.selection` 为 `TEXT NOT NULL`，`jobs()` 为 `SELECT * FROM web_card_jobs ORDER BY updated`（无上限）。
- 运行解释器核对：`/Users/xiaoyanhao/venv/bin/python` = Python 3.13.16（`commands/启动文献工作台.command` L9 的 `PAPER_PYTHON`），`socketserver.ThreadingMixIn.process_request` 与 `process_request_thread` 源码已按该版本核对，`hashlib.file_digest` 存在。

### 1.4 遵守的限制

未修改任何源码、配置、数据库、冻结证据、卡片或暂停记录；未启动/重启/终止任何进程；未接触 Chrome/CDP；未运行任何会影响真实状态的测试；未读取凭据；未执行 git 提交或全局同步；未调用其他模型；未启动任何与本次只读审查无关的工作流。除本 MD 外未新建任何文件。

---

## 2. 发现总览（按严重程度排序）

P0（可直接造成数据损坏或科学验收误判）：本次未发现。

| 编号 | 严重度 | 主题 | 位置 |
| --- | --- | --- | --- |
| F-01 | P1 高 | `/api/discover` 的去重键不含 `seed_id`，第二篇文献的“寻找相关文献”被静默丢弃却返回 200 | `web.py:453-457` + `core/catalog.py:124-125,467-486` + `workbench.html:289,121` |
| F-02 | P1 高 | `/api/state` 每次轮询做无上限全表工作（`web_card_jobs` 无删除路径、逐行 JSON 解析、全量序列化并计入 ETag），随库规模单调增长 | `web.py:280-286` + `cards/web_card_queue.py:133-140` + `core/workflow_priority.py:57-88` |
| F-03 | P1 高 | 前端 `refresh()` 互斥标志只在请求 settle 后清除，`fetch` 无超时/`AbortController`：一个悬挂请求使 `refreshing` 永久为真，界面静默停止更新且不再报错 | `workbench.html:123-129,98-117,436` |
| F-04 | P1 高 | 上传容量：done 任务哈希不一致时临时 PDF 被永久钉住并绕过 TTL，1GiB 配额可被永久占满，之后所有导入恒返回 400 | `upload_storage.py:26-40,55-59` |
| F-05 | P1 中高 | 请求体先整体缓冲进内存再检查配额；单请求上限 60MiB、业务槽 16 → 峰值约 960MiB；`settimeout(30)` 只是单次 socket 操作空闲超时，慢速客户端可无限期占住槽位 | `web.py:349-354,399/419,186,56` |
| F-06 | P2 中 | `_dispatch` 中线程启动失败仅释放槽位、未 `shutdown_request`，泄漏客户端 socket fd（与 `process_request` 的正确处理不一致） | `web.py:90-91` 对比 `web.py:62-63` |
| F-07 | P2 中 | 复用探测把 HTTP 层的 503（服务在跑但槽位满）当作“没有服务”，误报“端口被占用”，并在该误判路径执行 `init_seeds()` 写库副作用 | `web.py:110-134` |
| F-08 | P2 中 | 访问记录是单一文件、不含端口隔离：多端口互相覆盖后，启动器对已在运行的实例报“工作台启动失败”，或打印不含 `#access=` 令牌的链接 | `web.py:110-125,137` + `workbench_service.py:26,39-40,78` |
| F-09 | P2 中 | 同一份损坏/不合规访问记录在 `serve()` 内被吞掉，在 `run()` 路径是致命 `RuntimeError`，无自愈边界；无监听者时后台服务也拒绝启动 | `workbench_service.py:24-28,91` 对比 `web.py:117-121` |
| F-10 | P2 中 | 错误处理器可对已发送的响应二次写入状态行：`reply_file` 只吞 3 类异常，其余 `OSError` 逃逸到 `reply(503/500)`，导致响应帧错乱 | `web.py:210-215` + `web.py:329-334,492-499` |
| F-11 | P2 中 | 三个上传类 POST 全程持有 `upload_lock`，其中 `prepare()` 每次上传都对所有 done 任务的归档原文做全量重哈希（O(N×PDF) SSD 读），导入类请求被完全串行化 | `web.py:337-339` + `upload_storage.py:20-31,55-58` |
| F-12 | P3 低 | ETag 指纹未覆盖 `runs`/`job_counts`/`jobs`，但它们属于响应体：304 时“后台任务与检索记录”面板可长期陈旧 | `web.py:281-286` |
| F-13 | P3 低 | `reply_file` 以 `fstat` 大小声明 `Content-Length`，与实际写出字节可能不一致（卡片图/裁图被重写时截断或超发） | `web.py:210-215` |
| F-14 | P3 低 | 批量导入为顺序 `await` 循环且无超时/取消：单个卡住的上传无限期阻塞其余文件，行文本停留在“上传中” | `workbench.html:272-284` |
| F-15 | P3 低 | `renderJobs` 连续 4 次 `innerHTML=`/`+=` 重建任务块，每 10 秒重置 `#jobs`（`max-height:420px;overflow:auto`）滚动位置并重复解析 | `workbench.html:183-191` |
| F-16 | P3 低 | 大图查看仅设 `img.onload`，无 `onerror`：图片请求失败时右侧视图空白且无提示 | `workbench.html:416` |
| F-17 | P3 低 | 全局点击处理器不禁用按钮，与 `#saveNote`/`#startContinuous` 的显式禁用不一致；对非幂等写路径放大 F-01 | `workbench.html:289` 对比 `workbench.html:293,297,407` |

---

## 3. 发现详情（源码证据与触发条件）

### F-01（P1）“寻找相关文献”被静默丢弃，却提示成功

证据：

- `workbench/web.py:453-457`
  ```python
  if parsed.path=='/api/discover':
      if data.get('seed_id'):
          catalog.get(data['seed_id'])
      jid=catalog.enqueue('discover',payload=data)
      return self.reply(200,{'job_id':jid})
  ```
  `pid` 未传，故 `enqueue(kind='discover', pid=None, payload={'seed_id': ...})`。
- `infrastructure/core/catalog.py:467-486`：去重查询为 `WHERE kind=? AND ifnull(paper_id,'')=?`（参数 `pid or ''`），命中即 `return existing[0]`；`seed_id` 只存在于 payload，不参与去重键。
- `infrastructure/core/catalog.py:124-125`：`CREATE UNIQUE INDEX one_active_job ON jobs(kind,ifnull(paper_id,'')) WHERE state IN ('queued','running','waiting_storage')`，即“paper_id 为空的 discover”全局只能有一个活跃任务；即使绕过 L475 检查，插入也走 `except sqlite3.IntegrityError` 并返回既有 job id（L481-486）。
- `workbench/workbench.html:289`：`if(b.dataset.related)action(()=>post('/api/discover',{seed_id:b.dataset.id}))`；`workbench.html:121` 的 `action()` 无条件 `message('已保存，后台会继续处理。')`。

触发条件：任一 discover 任务处于 `queued`/`running`/`waiting_storage`（含 `enqueue_daily` 的全通道检索、其他种子的扩展、上一轮尚未跑完的扩展）时，点击任意文献的“寻找相关文献”。

影响：新种子的引用/参考文献扩展从未登记；界面显示成功且刷新后无该任务（`state.jobs` 只显示那条既有任务）。属于静默丢动作，用户无从发现；对以“文献发现产出”为目标的流程是可证明的功能缺陷。

修复建议：`/api/discover` 改为 `catalog.enqueue('discover', data['seed_id'], {**data,'trigger':'manual_related_expansion'})`，即以种子 DOI 作为 `paper_id` 参与去重键（与 `catalog.set_seed` L463-464 的做法一致）；或为 `enqueue` 增加 `dedupe_key` 参数。同时在返回体里区分“新建”与“复用既有任务”，前端复用情形提示“同一种子的扩展已在队列中”，不得一律提示“已保存”。

### F-02（P1）`/api/state` 的每轮成本无上限，随库规模单调增长

证据：

- `workbench/web.py:277-281`：`web_jobs=web_queue(catalog,config)`，随后 `etag` 用 `json.dumps([...web_status,progress,fetch_status,review_state,correction_state,concurrency],sort_keys=True)` 做 SHA-256；`web.py:286` 把 `jobs:catalog.jobs_page(100)` 与整份 `page` 一并放进响应。
- `cards/web_card_queue.py:133-140`：`jobs()` 为 `SELECT * FROM web_card_jobs ORDER BY updated`（无 `LIMIT`），传入 `config` 时再走 `workflow_priority__sort`。
- `infrastructure/core/workflow_priority.py:57-88`：逐记录 `json.loads(source['selection'])`，并对 `paper_card_scores` 做 `LEFT JOIN card_review_jobs` 后逐行 `json.loads(item['review_result'])`；`paper_ids` 是队列内全部 paper_id 的集合。
- `infrastructure/core/catalog.py:502-504`：`jobs_page` 为 `SELECT * FROM jobs ORDER BY CASE... ,created DESC LIMIT ?`，排序表达式不可用索引，需对全表做排序。
- 全仓 grep 仅 `cards/tests/test_audit_regressions.py:23` 出现 `DELETE FROM web_card_jobs`：生产代码不删除已完成/受保护行，因此 `web_card_jobs` 与 `jobs` 单调增长。
- 前端每 10 秒轮询一次：`workbench.html:436` `setInterval(...refresh(),10000)`；`web_jobs` 只在渲染时 `slice(-100)`（`workbench.html:188`），服务端仍发送全量。

触发条件：`config.web_cards.enabled` 为真（当前常驻形态）且已打开任意一个工作台标签页。

影响：每个标签页每 10 秒触发一次“全队列表扫描 + 全量评分 JOIN + 逐行 JSON 解析 + 全量序列化 + 全量哈希”，在业务槽只有 16 个（`web.py:56`）且数据库 `timeout=20`（`core/catalog.py:179`）的前提下，`/api/state` 变慢会直接吃掉槽位并使其他请求得到 503（`web.py:81-89`）。这是容量侧可证明的自放大：库越大 → 轮询越慢 → 越容易 503 → 前端还会对 503 做最多 2 次重试（`workbench.html:110-111`）。

修复建议：(a) `web_queue` 增加状态过滤与上限（如仅 `queued/preparing/ready/needs_inspection` + 最近 N 条完成），或为面板提供独立的分页端点；(b) ETag 只覆盖参与比较的字段，304 时跳过 `web_jobs`/`jobs_page` 的取数；(c) 把 `jobs_page` 的排序表达式换成可索引的 `state` 优先级列或先取 `created DESC LIMIT` 再在内存排序；(d) 前端把轮询间隔与可见性/标签页数量挂钩（`workbench.html:436` 已判 `visibilityState`，可再加失败退避）。

### F-03（P1）一个悬挂的请求让前端永久停止刷新

证据：

- `workbench.html:123-129`
  ```js
  async function refresh(){
    if(refreshing){refreshQueued=true;return refreshPromise;}refreshing=true;
    refreshPromise=(async()=>{try{do{...await fetchJSON('/api/state?...')...}while(refreshQueued);}finally{refreshing=false;refreshPromise=null;}})();
    return refreshPromise;
  }
  ```
- `workbench.html:98-117`：`fetchJSON` 内部只用 `await fetch(path,options)`，没有 `AbortController`，也没有 `setTimeout` 竞速；重试只覆盖 GET 且最多 2 次。
- `workbench.html:436`：定时器每 10 秒调用 `refresh()`。

触发条件：任意一次 `/api/state` 或 `/vendor/runtime-status.json` 请求既不 resolve 也不 reject（服务端已 accept 但迟迟不返回、代理/链路半开、上传大对象期间链路拥塞等），此时 `refreshing` 保持 `true`。

影响：之后所有 `refresh()` 调用（含用户点“刷新”、翻页、暂停/恢复后的 `await refresh()`）只返回同一个悬挂 promise，界面不再更新、`message()` 也不报错，表现为“工作台卡住但没有提示”。这是纯前端可证明的失效模式，且不依赖任何历史结论。

修复建议：给 `fetchJSON` 加显式期限与取消：`const c=new AbortController();const t=setTimeout(()=>c.abort(),deadline);try{r=await fetch(path,{...options,signal:c.signal})}finally{clearTimeout(t)}`，并为 `refreshPromise` 增加最长存活时间（例如 60 秒后强制 `refreshing=false` 并提示“本轮刷新超时”）；`refreshing` 置位应改为在 `finally` 中同时清理悬挂 promise。

### F-04（P1）done 任务哈希不一致时，临时上传被永久钉住并绕过 TTL

证据：

- `upload_storage.py:26-31`：`state=='done'` 时读取归档原文计算 `sha`，仅当 `sha==paper['asset_hash']` 才 `completed.add((source,sha))`；非 done 一律 `protected.add(source)`。
- `upload_storage.py:36-42`
  ```python
  done=any(source==resolved and sha==hashlib.sha256(path.read_bytes()).hexdigest() for source,sha in completed)
  if not done and any(source==resolved for source,sha in completed):continue
  if done or time.time()-info.st_mtime>ttl_seconds:eligible.append(...)
  ```
  L39 的 `continue` 发生在 L40 的 TTL 判断之前：只要某 done 任务的 `source` 指向该文件而哈希不相等（`completed` 里有同 `source` 但不同 `sha`），该文件既不回收也不受 TTL 约束。
- `upload_storage.py:32-42`：`total` 统计目录内全部合规 PDF（含被继续跳过的），`prepare()`（L55-59）用 `result['bytes']+incoming>max_bytes` 直接抛 `ValueError`。

触发条件：导入任务已 `done`，但归档原文与当时暂存的字节不一致（典型为后续版本替换、接受稿覆盖、SSD 侧文件被重写而 `asset_hash` 未同步，或 done 记录指向的旧暂存文件名仍在）。

影响：这些“僵尸文件”永久占用 1GiB 默认配额；配额一旦被填满，`prepare()` 对**所有**后续导入恒定抛 `ValueError('上传暂存额度不足；保留已有材料')`，经 `web.py:492-493` 变成 400，导入通道彻底不可用，而 `python -m workbench.upload_storage --apply` 也清不掉它们（同一 L39 逻辑）。

修复建议：把“被 done 任务引用但哈希不一致”归为显式保留类别并单独统计与上报（不并入 `max_bytes` 额度），或改为按 `protected`/`pinned`/`collectable` 三态分类并在 `pinned` 上仍受一个更长的硬 TTL 约束；同时让 `prepare()` 的额度检查只计 `collectable`，并在拒绝前返回一份“钉住文件清单”供人工确认。

### F-05（P1 中高）请求体先满额缓冲、配额后判；单请求周期无总期限

证据：

- `web.py:186`：`self.connection.settimeout(30)`（socket 级“单次阻塞操作”空闲超时，不是请求总期限）。
- `web.py:349-354`
  ```python
  length=int(self.headers.get('Content-Length','0'))
  if not 0<length<=60*1024*1024: raise ValueError('请求体大小不合法')
  ...
  body=self.rfile.read(length)
  ```
  整个 body 先进内存；
- `web.py:399`（`/api/import-batch`）与 `web.py:419`（`/api/import`）：`prepare(catalog,config,len(body))` 在读取之后才做配额与磁盘检查。
- `web.py:56`：`request_slots=BoundedSemaphore(16)`；`web.py:81-89` 槽位不足直接 503。

影响：(1) 内存上限为 `60MiB × 16 ≈ 960MiB`，`max_bytes` 只约束磁盘、完全不约束在途内存；(2) 慢速客户端每 29 秒送一个数据块即可无限期占住一个业务槽（每次 `recv` 都重置 30 秒），16 个这样的连接即令工作台对所有请求返回 503；握手阶段的 2 秒总期限（`web.py:67-75`）只保护头部，派发后没有任何总期限。服务只监听 127.0.0.1 并经 Tailscale 限定入口，因此这是容量/可用性缺陷而非远程攻击面，但在链路拥塞（与当前授权中反复出现的上传波动场景一致）下会真实触发排队与 503。

修复建议：改为边读边校验并设总期限——读取阶段用 `deadline`（如 60 秒）包裹的循环分块读入，超限即丢弃并关闭连接；配额/磁盘检查前移到读取之前（用 `Content-Length` 与当前 `collect` 结果预估），`write_upload` 改为分块落盘而非内存聚合；`prepare` 的额度语义拆成“磁盘配额”和“在途内存配额”两项并分别记录。

### F-06（P2）`_dispatch` 在派发线程启动失败时泄漏 socket

证据：

- `web.py:90-91`
  ```python
  try:super().process_request(request,address)
  except Exception:self.request_slots.release();raise
  ```
- 已核对 Python 3.13.16 的 `socketserver.ThreadingMixIn.process_request`：仅 `threading.Thread(...)` + `t.start()`；`t.start()` 抛 `RuntimeError: can't start new thread` 时**不会**调用 `shutdown_request`，`process_request_thread` 的 `finally: shutdown_request` 也永不执行。
- 对照 `web.py:62-63`：握手线程启动失败时正确地 `self.handshake_slots.release();self.shutdown_request(request)`。

触发条件：线程资源耗尽（与 F-05 的槽位/慢连接堆积同时发生概率最高），或 `super().process_request` 抛出其他 `Exception`。

影响：每次发生泄漏一个客户端 fd；在 fd 上限（macOS 默认 256/进程）附近会形成正反馈——越是资源紧张越泄漏，最终 `accept` 失败。同时异常继续向上抛给 `socketserver.handle_error`，日志被 traceback 淹没。

修复建议：与 `process_request` 对齐：
```python
try:super().process_request(request,address)
except BaseException:
    self.request_slots.release()
    self.shutdown_request(request)
    raise
```

### F-07（P2）复用探测把 503 当作“没有服务”，误报端口占用并附带写库副作用

证据：

- `web.py:110-116`
  ```python
  with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url,timeout=2) as response:
      existing=response.read(4096)
  reuse=b'<title>'+'文献阅读工作台'.encode()+b'</title>' in existing
  except (OSError,ValueError):reuse=False
  ```
  `urllib.error.HTTPError` 是 `OSError` 子类，因此服务正忙时 `web.py:81-89` 返回的 503 会落入 `except` → `reuse=False`。
- 随后 `web.py:128-129`：`Catalog(...)` 且 `if not background:init_seeds(catalog,config)`（写库）；`web.py:131-134`：绑定同一端口必然 `OSError` → `RuntimeError('端口 {port} 被其他服务占用；请使用 --port 指定其他端口。')`。
- 对照 `workbench_service.py:47-48`：`probe()` 对 503 有专门分支“现有工作台正忙，未重复启动”。同一件事在两个入口给出互相矛盾的判定。

触发条件：已有工作台在运行但 16 个业务槽被占满（F-02/F-05 的正常后果），此时直接调用公开出口 `web__serve`（`interface.json` 的唯一 Python 出口）或 `workbench_service.run()` 派生的子进程。

影响：给出错误归因（“端口被其他服务占用”）和错误指引（换端口），并可能在“其实已在运行”的情况下执行一次多余的 `init_seeds()` 写库；换端口还会导致访问记录被覆盖（见 F-08）。

修复建议：把复用探测改为区分三态——捕获 `urllib.error.HTTPError`：`code==503` → 视为“已在运行且正忙”，直接走 `reuse` 分支并提示稍后重试（或按 `Retry-After` 有界重试探测本身）；`4xx/2xx` 按标题判定；仅连接层 `OSError` 才判定为未运行。`init_seeds()` 应移到确认要真正启动服务器之后再执行。

### F-08（P2）访问记录单文件跨端口互相覆盖，导致假“启动失败”或丢失令牌

证据：

- `web.py:137`：`atomic_json(Path(config['catalog_path']).parent/'workbench-access.json',{...,'port':port,'token':token,...})` —— 目录内只有一个记录文件，后启动者无条件覆盖。
- `workbench_service.py:26`：`if record.get('port')!=port:return {}` —— 记录端口不同即视为无记录。
- `workbench_service.py:34`：`if not record or not alive(record.get('pid')):return None` —— `start()` 因此决定派生新服务。
- `web.py:110-125`：子进程 `serve()` 只看页面标题判定复用；且 `web.py:117-121` 只有当“记录端口匹配且 `alive(pid)`”时才把 `#access=<token>` 拼进 URL，然后 `print('文献工作台已在运行：'+url)` 并 `return`（子进程正常退出）。
- `workbench_service.py:78`：`if process.poll() is not None:raise RuntimeError(f'工作台启动失败，详情见 {log_path}。')`。

触发条件（源码可构造的具体序列）：端口 A(8767) 有活跃服务，其记录被端口 B(8768) 的启动覆盖为 `{port:8768,pid:222}`；随后用户点击 8767 的启动器：
1. `probe()` → `access()` 端口不符 → `{}` → 返回 `None` → `start()` 派生子进程；
2. 子进程 `serve()` 标题探测命中 A → 打印“已在运行”并退出；
3. `start()` 轮询看到 `poll()` 非空 → 抛 “工作台启动失败，详情见 …workbench-service.log”。

同一分支中，若 8767 上确有服务但记录端口不符，`web.py:120` 的令牌拼接被跳过，`web.py:122` 打印的是不含 `#access=` 的裸链接；由于 `/` 免鉴权（`web.py:237`），用户打开的是必然弹登录框的页面，而它需要的令牌只在 B 的启动器输出里。

影响：已在正常运行的服务被报告为“启动失败”；可访问链接与令牌不可得；重复点击启动器反复派生子进程（每次都跑一遍 `Catalog()` 与标题探测）。属于“服务重复启动与退出”维度的可证明缺陷。

修复建议：(a) 记录文件名按端口隔离（`workbench-access-<port>.json`），并在 `access()` 里保持同样隔离；(b) `serve()` 的复用分支增加“`/api/workbench-health` 实查 + 记录端口不符时按 `X-Paper-Token` 无从拼接即明确提示口令来源”，而不是打印半截链接；(c) `start()` 的子进程退出码/末行日志透传给用户，区分“已在运行”（视为成功）与“启动失败”（真失败）。

### F-09（P2）同一份坏记录：`serve()` 容忍、`run()` 致命，缺少自愈边界

证据：

- `workbench_service.py:24-28`：`access()` 对无法解析 JSON 抛 `RuntimeError('工作台访问记录不可读，保留原服务等待核对。')`，对 `token` 不满足 `[A-Za-z0-9_-]{32,128}` 抛 `RuntimeError('工作台访问口令记录不正确。')`；`workbench_service.py:91` 的 `previous=access(config,port)` 在 `run()` 内、绑定端口之前执行，异常直接终止后台服务启动。
- `workbench_service.py:33-34`：`probe()` 调用同一个 `access()`，`start()` 的轮询循环（`workbench_service.py:77-83`）不捕获 `RuntimeError`。
- `web.py:117-121`：读取同一文件时用 `except (OSError,ValueError,KeyError):pass` 静默容忍。

触发条件：记录文件被截断/字段异常（例如非本版本写入、外部工具编辑、磁盘写入被中断留下的旧格式），且 `port` 字段与本次端口一致。

影响：在没有监听者的情况下后台服务也拒绝启动，而代码同时把该记录解释为“保留原服务等待核对”，两条路径互相矛盾；且没有任何有界自愈（既不会备份重建，也不会退回新生成令牌），需人工删除文件才能恢复。

修复建议：统一两处语义——`run()` 侧把“记录不可读/口令不合规”降级为可恢复事件：完整归档原文件（保留原字节与新记录双指纹）后新生成令牌继续启动，并在 stdout/日志显式记录“口令已轮换，旧链接失效”；`serve()` 侧不再静默 `pass`，至少打印一条判定依据，使两侧对同一状态给出同一结论。

### F-10（P2）错误处理器对已发送响应二次写入，破坏响应帧

证据：

- `web.py:210-215`
  ```python
  def reply_file(self,path):
      with path.open('rb') as stream:
          self.reply_headers(200,...,os.fstat(stream.fileno()).st_size)
          try:
              for block in iter(lambda:stream.read(256*1024),b''):self.wfile.write(block)
          except (BrokenPipeError,ConnectionResetError,TimeoutError):pass
  ```
  只吞 3 类异常；`ECONNABORTED`（103，普通 `OSError`）、`EBADF` 等逃逸。
- `web.py:329-334` 与 `web.py:494-499`：`except (OSError,...)` / `except Exception` 分支无条件 `self.reply(503/500,...)`，而 `reply()`（`web.py:191-195`）会再次 `send_response` + 头 + 体；`BaseHTTPRequestHandler` 不记录“头已发送”，`reply_headers`（`web.py:197-208`）也没有。

触发条件：正在流式返回 `/asset`、`/vendor/*` 或大 JSON 响应时发生非上述三类的写失败（链路中断、图片文件被并发改写导致读错、磁盘 I/O 错误）。

影响：在已发出的二进制/HTML 字节之后追加一行 `HTTP/1.0 503 ...`，客户端得到畸形响应（Chrome 表现为 `ERR_CONTENT_LENGTH_MISMATCH` 或图片解码失败），且服务端日志里看不到真正的根因（`traceback.print_exc()` 打的是二次写入的异常）。同一缺陷还会把 F-13 的截断问题伪装成“服务暂不可用”。

修复建议：在 `Handler` 里跟踪发送状态（例如 `reply_headers` 置 `self._responded=True`），错误分支若已 `_responded` 则只做 `self.close_connection=True` + 日志，不再写第二个响应；`reply_file` 的 `except OSError` 放宽到整类并记一条含路径与已写字节数的诊断。

### F-11（P2）上传路径全程持锁做 O(N) 全量重哈希，导入请求被串行化

证据：

- `web.py:337-340`：`/api/import`、`/api/import-batch`、`/api/bind-upload` 三类 POST 整体包在 `with upload_lock(catalog):return self._do_POST()` 内；`_do_POST` 内含 `self.rfile.read(length)`（`web.py:353`）与落盘、`validate_pdf`、`enqueue`。
- `upload_storage.py:12-15`：`fcntl.flock(..., LOCK_EX)` 为全进程/全机互斥。
- `upload_storage.py:20-31` + `upload_storage.py:55-58`：`prepare()` 每次上传都 `collect(catalog,apply=True)`，对**每一个** `state=='done'` 的 import 任务读取整份归档原文做 `hashlib.file_digest`，并 `catalog.get(row['paper_id'])` 逐条查询。

触发条件：done 的导入任务数量增长（常驻制卡流程必然增长）且用户在页面做批量导入。

影响：单次上传的持锁时长 ≈ 全部历史原文的一次全量读（SSD/外接卷上可达数十秒至分钟级），期间其他上传请求全部阻塞在 `flock`；叠加 F-05（读取 body 也在锁内）与 30 秒 socket 超时，表现为“批量导入越用越慢、后面的文件超时”。同时该工作在读请求槽内进行，挤占 F-02 的同一批槽位。

修复建议：(a) 把 `collect` 拆成“额度快查”（只 `stat`，不重哈希）与“回收”（后台有界执行，或由 `python -m workbench.upload_storage --apply` 独立触发）；(b) 对已核对的 `(source, sha)` 结果按 `paper_id + asset_hash + mtime` 做持久缓存，避免重复读同一份原文；(c) `do_POST` 的锁范围收窄到 `prepare/write_upload/enqueue` 的必要短临界区，把 body 读取移出锁外。

### F-12（P3）ETag 指纹漏掉响应体字段，304 返回陈旧任务面板

证据：`web.py:281` 的指纹只包含 `page['revision']`、`parsed.query`、`model_state`（去 `checked_at`）、`web_status`、`progress`、`fetch_status`、`review_state`、`correction_state`、`concurrency`；而 `web.py:283-286` 的响应额外包含 `runs`、`job_counts`、`jobs`（`catalog.jobs_page(100)`）与 `page` 的行内容。`web.py:282` 命中即 `reply(304)`。

触发条件：`jobs` 表内任务状态变化（例如 `queued→running`，或新增一条 `runs`）但上述被哈希字段恰好一致（同分/同计数互换、状态在 `running` 内部推进都可能满足）。

影响：`#runDetails` 展开的“后台任务与检索记录”（`workbench.html:173-195`）保持旧数据，直到其他字段变化才刷新；面板显示的排队数/状态与实际不一致，用户可能据此误判后台进度。

修复建议：把 `runs`、`job_counts` 与 `jobs` 的关键列（`id,state,updated`）纳入指纹；或把任务明细拆到独立端点并使用各自 ETag；前端 `#runDetails` 展开时（`workbench.html:270`）强制绕过缓存取一次。

### F-13（P3）`reply_file` 的 `Content-Length` 可能与实际写出字节不一致

证据：`web.py:212` 用 `os.fstat(stream.fileno()).st_size` 声明长度，随后 `web.py:214` 以 256KiB 分块读到 EOF 写出；两者之间文件可被并发改写（卡片图像、`display/*.png`、`media-evidence.json` 在制卡/修正流程中会被重写，`/asset` 直接映射卡片目录，见 `web.py:319-321`）。

影响：文件变短 → 写出字节少于声明长度，客户端等待至连接关闭并报截断；文件变长 → 超发字节，因 `BaseHTTPRequestHandler.protocol_version` 默认 `'HTTP/1.0'`（`web.py:184-208` 未覆盖）且响应后关闭连接，不至于污染后续响应，但仍表现为图片解码残缺。属于低危但可证的完整性问题。

修复建议：`reply_file` 改为先取 `(st_size, st_mtime, st_ctime)` 快照，流式写出时限制不超过快照长度，若实际写出与声明不符则在日志记录差异；对可能被重写的证据文件优先返回按内容寻址的副本或加 `If-Range`/强校验的 `ETag`。

### F-14（P3）批量导入顺序循环无超时与取消

证据：`workbench.html:272-284`：`for(let i=0;i<files.length;i++){... const {data:out}=await fetchJSON('/api/import-batch',{method:'POST',...body:f}); ...}`；`fetchJSON` 无 `AbortController`/期限（见 F-03），`#batchImport` 的 `onchange` 一开始就 `e.target.value=''`（L273）已无法通过输入框取消，也没有“停止”按钮。

触发条件：单个上传因链路拥塞长时间不返回（服务端在读 body 上无总期限，见 F-05）。

影响：队列里其余文件无限期等待，行文本停留在“上传中”；用户无法取消，且由于写请求被有意设计为不自动重试（`workbench.html:106,112`），只能整批重来。

修复建议：为每个文件加显式期限与“取消”入口（`AbortController` + 每行一个取消按钮），并把批次改为有界并发 + 完成计数；对确认未送达的失败文件明确提示“回执未确认，请刷新后核对再决定是否重试”，而不是仅 `row.textContent=f.name+' · 未导入：'+err.message`。

### F-15（P3）任务面板每轮重建四遍并重置滚动

证据：`workbench.html:183`（`#jobs`.innerHTML=…）、`184`（`innerHTML=fetchTimes+innerHTML`，整块再解析一次）、`188`/`190`/`191`（三次 `innerHTML+=…` 拼接制卡/核验/修正表），`#jobs` 样式为 `max-height:420px;overflow:auto`（`workbench.html:12`）；`renderJobs` 由 `render()`（`workbench.html:268`）与 `toggle`（`270`）调用，故 10 秒轮询即触发一轮。

影响：`#jobs` 的滚动位置每轮丢失（节点被替换），任务较多时每轮解析大 HTML 造成主线程停顿；与 `#runs` 分支（`workbench.html:192-194` 显式保存并恢复 `open` 状态）的处理方式不一致。

修复建议：改为一次组装字符串后单次赋值，或复用 `renderPapers` 的增量 diff 思路；写入前后保存并恢复 `#jobs` 的 `scrollTop`。

### F-16（P3）大图加载失败无兜底

证据：`workbench.html:416`：`img.onload=()=>setImageScale('fit');img.src=button.dataset.zoomSrc`，只设 `onload`；`setImageScale`（`workbench.html:413`）依赖 `img.naturalWidth`。

触发条件：证据图请求失败（SSD 未挂载时服务端返回 400 “文件不可用，请连接 SSD 或完成处理”，见 `web.py:323-324`；或 F-10/F-13 导致的截断）。

影响：`#imageViewer` 已展开并占据 2/3 布局（`workbench.html:20-22`），但显示空白破图，无文字提示，用户不知道该回退到“阅读原文 PDF”。

修复建议：补 `img.onerror=()=>{...显示“图像不可用（可能未连接 SSD），请用原文 PDF 链接”...}`，并在 `onload` 之前隐藏/占位。

### F-17（P3）写操作按钮的重复提交防护不一致

证据：`workbench.html:289` 的全局点击处理器直接 `action(()=>post(...))`，不禁用按钮、不跟踪在途状态；对比 `workbench.html:293`（`b.disabled=true`/`finally` 恢复）、`workbench.html:297`（`button.disabled=true`）、`workbench.html:407`（`button.disabled=true`）。

影响评估（严格区分）：多数写路径在数据库层是幂等的——`enqueue` 依赖 `(kind,ifnull(paper_id,''))` 唯一活跃索引（`core/catalog.py:124-125,467-486`），`retry` 对同类型活跃任务显式报错（`core/catalog.py:605-613`），`/api/reading` 有 `note_version` 冲突保护（`web.py:440-445`）。真正被放大的是 F-01（`/api/discover` 的 `seed_id` 不入键）与 `/api/decision` 之类的事件重复。因此本条记为“防护不一致 + F-01 的放大因素”，不单独主张其他重复提交危害。

修复建议：在 `action()` 内加“同一动作在途时禁用并提示”，或给每个 `data-*` 按钮统一 `b.disabled=true` 与 `finally` 恢复；`/api/discover` 按 F-01 修复后重复提交自然收敛。

---

## 4. 已核对、判定为不构成缺陷的点

为避免把设计选择误报为缺陷，以下逐项给出源码依据：

1. 数据库连接不泄漏：`infrastructure/core/catalog.py:178-188` 的 `connect()` 是 `@contextmanager`，`finally: db.close()`；因此 `web.py:283-285`、`catalog.get/list/page/jobs_page` 不存在“with-connection 只提交不关闭”的 fd 泄漏。`Catalog` 仅持有 `self.path`，每次取新连接，跨线程共享该对象安全。
2. `request_slots` 的正常释放路径完整：`web.py:93-95` 在 `process_request_thread` 的 `finally` 释放；已核对 Python 3.13.16 的 `ThreadingMixIn.process_request_thread` 自身吞掉 `Exception`，故与 `web.py:91` 的显式释放不会双重 release（`BoundedSemaphore` 也不会被超释）。泄漏仅存在于 `BaseException`（`KeyboardInterrupt`/`SystemExit`）这一未证实路径，归入“待验证风险”。
3. 单例与崩溃安全：`workbench_service.py:88-90` 用 `LOCK_EX|LOCK_NB` 拒绝同端口重复后台启动，`workbench_service.py:65-66` 用阻塞 `LOCK_EX` 串行化启动器；`flock` 由内核随进程释放，`SIGKILL` 后无残留锁文件问题。
4. 写请求不自动重试：`workbench.html:106,110-112` 的 `transient` 判定仅对 GET 生效，非 GET 明确提示“操作回执未确认，请刷新状态核对后再决定是否操作”，与 AGENTS“写请求回执不明不重试”合同一致。
5. 鉴权与路径收敛（本次审查未见越权）：`web.py:236-237` 免鉴权面仅 `/` 与 `/vendor/` 白名单后缀；`web.py:247-252` 与 `web.py:319-321` 都做 `resolve()` + `is_relative_to(root)` + 后缀白名单，`card_image_asset`（`web.py:36-48`）同样收敛在卡片目录内；`web.py:228-229` 用 `secrets.compare_digest`；`web.py:343-347` 的 POST 同时校验 Host 与 `X-Paper-Token`，Origin 存在时校验来源。
6. 前端 HTML 净化：`workbench.html:67-70` 用 `DOMParser` + 标签白名单，清空全部属性后仅对 `A` 且 `^https?://` 重新放行 `href`，并统一 `target=_blank rel=noopener noreferrer`；公式占位符在净化后按 `esc()` 回填（`workbench.html:70`）；KaTeX 调用显式 `trust:false`（`workbench.html:398`）。本次未发现可用注入点。
7. CSV 公式注入已中和：`web.py:31-33` 的 `csv_text` 对 `= + - @ \t \r \n` 前缀加前导单引号，`/export/manual.csv`（`web.py:303-309`）逐字段套用。
8. CSP 每请求新生成 nonce：`web.py:240-241` 与 `web.py:203-204`，`script-src` 只放行 `self` + 本次 nonce，无固定 nonce 复用。
9. `spawn_logged`（`workbench/reading/log_output.py:40-45`）在子进程内做轮转，父进程不持有管道、不建排水线程；`workbench_service.py:75` 传 `stdin=DEVNULL, close_fds=True, start_new_session=True`，未见句柄泄漏。`workbench_service.py:92` 忽略 `SIGHUP`，关闭启动器终端不影响后台服务。
10. `upload_lock` 覆盖了“检查配额 + 写文件 + 入队”的一致性窗口（`web.py:337-339`），`bind-upload` 的文件名走 `re.fullmatch(r'[0-9a-f]{32}\.pdf')`（`web.py:446-450`），无法用客户端提供的名字穿越目录。

---

## 5. 待验证风险（源码可疑但无法在本次只读条件下证明为缺陷）

1. `web.py:91` 的 `except Exception` 不含 `BaseException`：若在 `super().process_request` 期间投递 `KeyboardInterrupt`（前台 Ctrl-C），槽位会永久丢失。需实机注入信号验证，不能由静态阅读断定。
2. 无 HTTP keep-alive：`Handler` 未设 `protocol_version`（`web.py:184-208`），默认 `'HTTP/1.0'`，每个图像/资源都新建连接；服务端先关闭会进入 `FIN_WAIT_2/TIME_WAIT`。对 macOS 临时端口与 64 握手槽的实际压力需压测，本次未测。
3. 突发连接丢弃阈值：`handshake_slots=64` 且非阻塞获取失败即 `shutdown_request`（`web.py:60-61`），2 秒头部期限（`web.py:67-75`）。分块极慢发送请求头的真实客户端（弱链路经 Tailscale）会被当作攻击处理。属容量策略，是否构成实际可用性损失需实测。
4. `isCardJob` 的 `JSON.parse`（`workbench.html:172`）在渲染路径无 `try`：`web_card_jobs.selection` 由 `json.dumps` 写入（`cards/web_card_queue.py:16,98`），正常不会非法；一旦该行被外部改坏，异常会沿 `render()`（`workbench.html:268`）抛出，被 `refresh()` 的 `catch` 转成 `message(e.message)`（`workbench.html:126`），使列表下方的统计/工作流控制区整轮不更新。对照 `core/workflow_priority.py:59-61` 服务端已有 `try/except` 容错，前端未对齐。风险成立与否取决于是否存在非法 `selection`，本次未查询数据库。
5. `workbench_service.py:93-94` 的 `stop(*_):raise KeyboardInterrupt`：若 SIGTERM 恰好投递在 `serve()` 的 `finally`（`web.py:173-180`）执行 `killpg`/`wait(timeout=5)` 期间，异常可能替换正在进行的清理，使 worker 未被回收；需要信号时序实测。
6. `web.py:312-315` 的 `/asset?file=source.pdf` 分支直接使用 `paper['asset_path']` 且未做根目录约束（同函数另一分支 `web.py:319-321` 有 `is_relative_to`）。该值来自内部写入的数据库，属纵深防御缺口而非当前可触发缺陷；是否需要收敛应由目录内 `asset_path` 的真实取值分布确认（本次未读数据库）。
7. `upload_storage.py:33-42` 只扫描 `folder.glob('*.pdf')` 且要求 32 位十六进制名：任何非规范命名的残留（异常中断产生的临时名）既不计入额度也不被回收。是否存在此类残留需检查运行目录。
8. 前端 `detailState`/`cardHTML`（`workbench.html:49`）只在节点消失时删除对应项、无容量上限；长时间停留并跨库翻页的内存增长幅度未测量。
9. `web.py:158-180` 的前台 worker 清理：`SIGTERM` 之后未再 `wait()`，launcher 随即退出。是否会留下短命僵尸取决于子进程对 SIGTERM 的处理，本次未观察真实 worker。
10. `/api/state` 在 304 分支仍执行全部取数（`web.py:277-286` 的顺序：先算 ETag 再取 `runs`/`job_counts`/`jobs`），说明 F-02 的成本在缓存命中时**并未**节省，只是省了写出。真实收益需按运行环境量化。

---

## 6. 建议的处置顺序

1. 先修 F-01（静默丢动作 + 返回体不区分复用）与 F-03（前端刷新永久悬挂）：二者分别影响产出正确性与可观测性，改动局部、可离线回归。
2. 再修 F-05/F-11（在途内存与配额检查顺序、锁内全量重哈希）：这是“导入越用越慢/503”的直接来源，与 F-02 的轮询成本共同决定业务槽 16 是否够用。
3. F-04（永久钉住绕过 TTL）需先明确产品语义：若“哈希不一致即保留”是保护要求，应把它移出 `max_bytes` 额度并单独上报，而不是让它静默吃满配额导致全通道 400。
4. F-06、F-09、F-10、F-12、F-13 属小改动、低风险，可与上述同批提交（各自加离线回归：槽位释放计数、响应帧不重复、ETag 覆盖字段、配额拒绝路径）。
5. F-07、F-08 需要一并调整“复用判定与访问记录”的合同（端口隔离记录 + 503 三态判定 + 子进程退出码透传），建议作为同一个逻辑提交，避免两个入口再次出现互相矛盾的判定。
6. 任何接口/配置语义变化（访问记录文件名、`/api/discover` 载荷与去重键、ETag 覆盖范围、上传配额语义）须按 `infrastructure/all/RULES.md` 第 3、4、6 条同步 `interface.json`/`README.md`/工具卡并运行全局 `sync_tools.py update` 与 `check_links.py`；本次为只读审查，未执行这些命令，也未修改任何登记。

## 7. 验证限制

- 本报告全部结论来自源码静态阅读；未启动工作台服务、未执行 `make test` 或任何项目测试、未发起任何 HTTP 请求、未连接 Chrome/CDP、未读写数据库/卡片/冻结输入/暂停记录。
- 涉及运行时的判断已按实际启动解释器核对（`/Users/xiaoyanhao/venv/bin/python` = Python 3.13.16，`socketserver` 与 `hashlib.file_digest` 为真实实现），但**未**实测并发量、槽位余量、`/api/state` 的 P95 耗时、fd/内存增长曲线，也未验证 macOS 下的 `TIME_WAIT` 压力。
- F-01 的“去重键不含 `seed_id`”与 F-08 的“多端口互相覆盖”是按源码与数据库唯一索引构造的具体序列（`core/catalog.py:124-125,467-486`；`web.py:110-137`；`workbench_service.py:26,34,78`），未在当前运行实例上复现，故属“源码可证明”而非“已实测复现”。
- 未读取凭据、`workbench-access.json` 实际内容、`uploads/` 目录与 SSD 状态；因此 F-04/F-10 的第 6、7 条待验证项只能标注为需现场检查。
- 本报告不构成科学验收，也不改变任何暂停、身份/版本、范围、人工决定与未知回执保护；引用与行号对应 2026-10-18 工作区当前源码（分支 `codex/20261014-183905-d72da3-t003`）。
