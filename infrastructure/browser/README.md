# 专窗与共享调度

唯一所有者、固定20槽、制卡/核验/修正分配、上传/发送锁、真实生成观测、材料FIFO、回执收取、坏页归档与恢复。

这是独立源码与接口文件夹，正式包名为 `browser`。跨项目只调用 `browser.api` 或本项目声明的CLI/JSON接口；不存在跨目录源码链接。

## 为什么选择、为什么保留

保留单CDP所有者以及8/4/3/5固定分组，避免重复连接、抢页、错配回答和未知请求重发。上传最多5路，提交串行；恢复阈值沿用当前已授权的各队P85原值。

## 接口与运行

- [interface.json](interface.json)：版本、依赖、全部公开出口及真实实现签名。
- [api.py](api.py)：接口入口，返回原函数/类对象，保留参数、异常与共享对象身份，不另复制实现。
- [pyproject.toml](pyproject.toml)：可单独构建/安装的Python子项目。

公共符号以 `模块__符号` 命名，避免各模块的 `status`、`enabled` 等同名函数冲突；模块出口用于保留已有有状态接口。调用参数、返回值与异常见真实函数签名及源码，不由适配层改写。

```python
from browser.api import attempt_history__index_attempts
```

运行依赖：[cards](../../cards/README.md)、[codex_desktop_chat](../../../tools/codex_desktop_chat/codex_desktop_chat/README.md)、[core](../core/README.md)、[correction](../../correction/README.md)、[reading](../../workbench/reading/README.md)、[review](../../review/README.md)。

CLI/子进程入口：`python -m browser.web_pool_open`, `python -m browser.web_upload_retry`。标准输入JSON桥仍使用原请求/响应结构，不混入诊断输出。

从 paper 根目录按需运行：

```sh
PYTHONPATH=infrastructure/bootstrap:.:../chatgpt_playwright infrastructure/environments/test/bin/python infrastructure/maintenance/test_runner.py --project browser
make check
```

可用支持PEP 517/660的安装器按本目录 `pyproject.toml` 独立安装。宿主负责安装接口依赖和提供 `PAPER_WORKSPACE_ROOT`；当前运行环境沿用现有虚拟环境，避免目录整理触发依赖重装或服务重启。

## 内部全部实现与功能

以下清单列出本项目每份实现及其顶层函数、类和类方法；测试、说明与配置在下节单列。辅助内部函数不是跨项目授权出口。

| 文件 | 功能 | 内部函数 / 类方法 | 保留原因 |
| --- | --- | --- | --- |
| [shared_page_repair.py](shared_page_repair.py) | Journaled page repair on the existing owner connection, never task resends. | `_sha`、`atomic_text`、`atomic_bytes`、`_sync`、`_registry`、`_allowed`、`_inventory`、`_records`、`_entry_for`、`_persist_pool`、`_record_cas`、`_capture_png_on_owner`、`_capture_mhtml_on_owner`、`_archive_png`、`_restorable_repair_blank`、`_archive`、`_journal`、`_candidate`、`_relocate_archived_ledgers`、`_recover_orphan_review`、`_terminal_empty_restart`、`_hourly_idle_restart`、`_hourly_missing_slot_request`、`_authorized_missing_slot`、`_retry_unused_candidate`、`_resume`、`_maintenance_allowed`、`_manual_block`、`bounded_recheck`、`stalled_page_fallback`、`run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [owner_browser_calls.py](owner_browser_calls.py) | Bound protocol/worker waits on the resident Playwright loop. | `bounded_call` | 当前公开接口或生产链使用；避免复制实现 |
| [upload_quota.py](upload_quota.py) | Read visible upload-limit reset times and guard retries of unsent requests. | `reset_time`、`visible_notice`、`_reset_timestamp`、`unsent_page` | 当前公开接口或生产链使用；避免复制实现 |
| [upload_trace.py](upload_trace.py) | Append-only, desensitized upload attempt evidence shared by the uploader and the observer. | `configure`、`root`、`reset`、`owner_identity`、`identity_fields`、`append`、`begin`、`finish`、`active`、`attempt`、`bind_request`、`lookup_request`、`record_network`、`network_projection`、`desensitize` | 当前公开接口或生产链使用；避免复制实现 |
| [upload_retry_policy.py](upload_retry_policy.py) | Bounded backoff for proven unsent review upload failures. | `PolicyIntegrityError`、`enabled`、`_settings`、`install`、`_ddl`、`_present`、`material_identity`、`upload_failure`、`_receipt_id`、`window`、`_validated`、`_stored`、`record_failure`、`settle_success`、`_packet_identity`、`_identity_for`、`cooling`、`annotate`、`due`、`first_eligible`、`guard`、`summary` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_claim_recovery.py](shared_claim_recovery.py) | Recover exact page leases from ended receipts, independently of retry limits. | `release_untouched`、`abandoned_unsent`、`_recover_abandoned`、`_preparation_only`、`locate_retired_receipt`、`recover_claims` | 当前公开接口或生产链使用；避免复制实现 |
| [attempt_history.py](attempt_history.py) | Complete immutable receipt indexing and submission gates, including archives. | `read_attempt`、`_read_attempt`、`attempt_order`、`_index_attempts`、`index_attempts`、`submission_history` | 全量递归扫描先解析各账本根目录，常规文件复用单次元数据读取，符号链接仍按原路径规则核对 |
| [startup_page_restart.py](startup_page_restart.py) | Owner-only, explicitly target-bound restart of stalled startup pages. | `safe`、`draft_hash`、`schedule_stalled`、`run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [web_message_text.py](web_message_text.py) | Read full user DOM text and expand bound messages through the existing owner. | `select_user_text`、`read_user_text`、`read_user_text_async`、`expand_original_user` | 当前公开接口或生产链使用；避免复制实现 |
| [account_readiness.py](account_readiness.py) | 有效账户UI与恢复后自动核对 | `READINESS_UI_SCRIPT`、`recheck` | 原观察器内部共用；不操作登录或验证码 |
| [shared_page_health.py](shared_page_health.py) | Read-only health evidence for fixed shared pages; no close/create or writes. | `_sha`、`_file_sha`、`_dense`、`_formal`、`snapshot_page`、`_normal`、`_fingerprint`、`_stable`、`_records`、`_prompt`、`_receipt`、`_uncollected_history`、`_saved`、`_saved_prefix`、`_empty_saved`、`_homepage_idle`、`_completed_target_history`、`completed_homepage`、`_completed_homepage_error`、`classify` | 当前公开接口或生产链使用；避免复制实现 |
| [browser_recovery.py](browser_recovery.py) | Bounded recovery of the dedicated Chrome; never repeat a submitted request. | `targets`、`owned_ids`、`main_chrome_pid`、`enroll`、`open_owned_pages`、`check_health`、`quarantined_slots`、`pool_capacity`、`maintain_pool` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_workbench_move.py](shared_workbench_move.py) | One explicitly authorized background workbench move on the original owner. | `run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [original_upload_http1.py](original_upload_http1.py) | 唯一所有者的下一合法新材料原始PUT一次对照 | `matches`、`forward_headers`、`OriginalPutProbe[claim, read, save, arm, restore]`、`configure`、`restore`、`armed`、`system_proxy`、`error_evidence`、`material_intent`、`native_settled`、`OriginalPutUploads[for_material, restore]` | 持久独占意图防止跨所有者重传；仅整ZIP、原HTTPS目标、原头、严格TLS及真实响应；不新增CDP连接 |
| [owner_upload_jobs.py](owner_upload_jobs.py) | Cooperative page submissions on the one resident Playwright thread/loop. | `OwnerUploadJobs[__init__, targets, available, budget_targets, pending_by_lane, pending_targets_by_lane, release_observed, start, pump, reap, drain]` | 当前公开接口或生产链使用；避免复制实现 |
| [window_screenshots.py](window_screenshots.py) | 原所有者定时固定槽截图 | `request`、`status`、`_same_slot`、`_prune`、`capture`、`run` | 每60秒保存真实视口及指纹，无新连接、导航或发送 |
| [web_page_observer.py](web_page_observer.py) | Ten-second observation on the existing Playwright connection, also during uploads. | `status_script`、`inspection_stage`、`inspection_error`、`responsive_lock`、`_review_markers`、`_review_identity`、`response_identity`、`PageObserver[__init__, start, update, stop, inspect_windows, inspect, _record_login, check, run]` | 单次DOM状态读取、检查轮次/阶段证据；任务标识排除已知合同标题中的版本名，保留重复/外来任务、唯一URL与完整实际提示守卫 |
| [receipt_history_groups.py](receipt_history_groups.py) | Group diagnostic histories once, preserving receipt order and lexical paths. | `group_histories` | 当前公开接口或生产链使用；避免复制实现 |
| [browser_start_request.py](browser_start_request.py) | 原所有者执行显式启动及已确认退出浏览器的有界恢复 | `request`、`run_once`、`_recover_closed` | 两次缺失实查、原登记归档、nonce防重及恢复限频；不关闭存续浏览器 |
| [web_upload_retry.py](web_upload_retry.py) | Scoped quota watcher: captures visible reset notices and resumes unsent jobs at reset. | `read`、`alive`、`scope`、`capture`、`watch` | 当前公开接口或生产链使用；避免复制实现 |
| [api.py](api.py) | 公开接口入口，延迟返回唯一实现对象 | `__getattr__`、`__dir__` | 当前公开接口或生产链使用；避免复制实现 |
| [page_retirement.py](page_retirement.py) | Close only finished owned slots when a user lowers desired concurrency. | `may_retire`、`retire_excess` | 当前公开接口或生产链使用；避免复制实现 |
| [gpt_model_policy.py](gpt_model_policy.py) | Main-paper GPT model order; verify exact native model and High before send. | `model_quota`、`verify`、`configure`、`configure_session` | 当前公开接口或生产链使用；避免复制实现 |
| [web_page_queue.py](web_page_queue.py) | Durable page-affine queues and background material preparation (no browser). | `install`、`assign`、`next_ready`、`prepare`、`MaterialProducer[__init__, start, stop, run]` | 当前公开接口或生产链使用；避免复制实现 |
| [web_media_storage.py](web_media_storage.py) | Keep web input payloads on the mounted SSD, receipts in the local catalog tree. | `require_volume`、`bind_inputs`、`require_config_storage` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_pool_store.py](shared_pool_store.py) | Locked, optimistic entry updates for the shared page pool. | `PoolConflict[]`、`PoolSnapshot[__init__]`、`load_pool`、`mark_verified_blank`、`begin_request`、`failed_request`、`_lock`、`save_pool` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_window_start.py](shared_window_start.py) | Explicit startup initialization, executed on the sole owner's connection. | `run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_window_owner.py](shared_window_owner.py) | Window registration and dispatch guards used only by the existing CDP owner. | `registry_path`、`check_endpoint`、`refresh_requested`、`observe`、`require_slot`、`require_reusable` | 当前公开接口或生产链使用；避免复制实现 |
| [web_editor_input.py](web_editor_input.py) | Edit a background composer on the owner's connection without OS focus. | `replace` | 当前公开接口或生产链使用；避免复制实现 |
| [web_upload_bundle.py](web_upload_bundle.py) | Shared ZIP prestore for newly submitted web-card materials; never alters old attempts. | `prepare_web_upload` | 当前公开接口或生产链使用；避免复制实现 |
| [web_submission_guard.py](web_submission_guard.py) | Final frozen-input and human-decision checks for shared source-only sends. | `check` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_page_dispatch.py](shared_page_dispatch.py) | Pure allocation of the keeper's fixed pages between independent task lanes. | `_limit`、`_pending`、`_budgets`、`_legacy_dispatch`、`_arrival`、`_queue_records`、`_fifo_dispatch`、`dispatch` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_window_tabs.py](shared_window_tabs.py) | Create one inactive tab in an exact Chrome window through a temporary worker. | `TabCreationError[__init__]`、`blank_url`、`probe_support`、`_candidate`、`_worker`、`_confirm_cleanup`、`create_in_window` | 当前公开接口或生产链使用；避免复制实现 |
| [restored_web_draft.py](restored_web_draft.py) | Clear only an exact archived, explicitly unsent pipeline draft on a new slot. | `evidence`、`verified_blank`、`clear` | 当前公开接口或生产链使用；避免复制实现 |
| [web_pool_open.py](web_pool_open.py) | Enroll an explicitly user-opened blank GPT page; create a page only on an explicit startup click. | `shared_mode`、`shared_window_record`、`shared_maintenance_request`、`request_shared`、`eligible`、`ensure_startup_page`、`request` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_page_backlog.py](shared_page_backlog.py) | 专窗二十槽混合排队。页首和准备检查只读实际绑定文献；原所有者发现写锁竞争时本轮延后派发。 | `enabled`、`_policy`、`fixed_reservations`、`install`、`_tables`、`_idle_borrow_targets`、`_allowed`、`_json`、`_source_records`、`_unsent`、`_stat_key`、`_digest_version`、`_fingerprint`、`_guard`、`_fifo`、`eligible_records`、`rows`、`binding`、`check_binding`、`check_claim_binding`、`mark_claimed`、`rollback_claim`、`remove_binding`、`_head`、`head_ready`、`check_head_binding`、`_destinations`、`_write_binding`、`_cleanup`、`_reservation`、`reconcile`、`preparation_head_ids` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_transport.py](web_card_transport.py) | Owned web pages, per-provider capacity, persisted failover and error cleanup. | `DeferredWeb[]`、`UncertainWeb[]`、`UploadStageFailure[__init__, stage]`、`ProviderFailure[__init__]`、`failure_kind`、`UPLOAD_STAGE_BY_KIND`、`_zip_identity`、`_upload_failure`、`Router[__init__, choose, block]`、`provider_page_count`、`require_no_verification`、`collect_owned`、`owned_error_cleanup`、`release_gpt_pool`、`resume_known_response`、`formal_gpt_url`、`wait_gpt_upload_ready`、`wait_gpt_upload_settled`、`_dismiss_chat_only_notice`、`submit_gpt_background`、`request`、`run_with_failover` | 当前公开接口或生产链使用；避免复制实现 |
| [browser_inventory.py](browser_inventory.py) | Observe CDP pages without creating/closing tabs; tolerate closing-page races. | `enumerate_pages` | 当前公开接口或生产链使用；避免复制实现 |
| [web_card_pool.py](web_card_pool.py) | Persistent CDP connection; reconcile saved replies before reusing owned tabs. | `identify`、`normalize_json_escapes`、`record_channel_failure`、`record_upload_network_failure`、`refresh_browser_pages`、`pump_owner_wait`、`keep_connection_after_error`、`owner_error_status`、`refresh_concurrency`、`reconcile_blank_pages`、`maintain_shared_backlog`、`shared_upload_limit`、`shared_submission_status`、`run_pool` | 当前公开接口或生产链使用；避免复制实现 |
| [collective_page_restart.py](collective_page_restart.py) | Mass technical failure recovery; no permission to resend any request. | `_bound_upload_bundle`、`_verified_cached_attachment`、`episode_targets`、`active`、`eligible`、`timed_unsent_restart`、`failed_upload_eligible`、`failed_upload_restart` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_workflow_activity.py](shared_workflow_activity.py) | Project observed parallel work, keeping reservation and menu limits separate. | `observed`、`project` | 当前公开接口或生产链使用；避免复制实现 |
| [authorized_unsent_restore.py](authorized_unsent_restore.py) | One-shot, explicitly authorized restoration on the resident owner's connection. | `sha`、`validate`、`run_once` | 当前公开接口或生产链使用；避免复制实现 |
| [stall_timeouts.py](stall_timeouts.py) | Lane-specific fault deadlines calibrated from frozen recovery evidence. | `timeout_seconds` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_workflow_queue.py](shared_workflow_queue.py) | Immutable arrival evidence for three lanes sharing the registered page pool. | `install`、`register`、`heads`、`bind_ready`、`claim_ready`、`check_claim`、`release_claim`、`rollback_claim`、`active_targets`、`refill_backlog`、`backlog_dispatch` | 当前公开接口或生产链使用；避免复制实现 |
| [shared_browser_window.py](shared_browser_window.py) | Read-only window isolation and stable slots for the shared GPT page pool. | `WindowIsolationError[]`、`enabled`、`_valid_window_id`、`_owned_set`、`snapshot_windows`、`read_window_inventory`、`_checked_inventory`、`validate_registry`、`register_window`、`reconcile_window` | 当前公开接口或生产链使用；避免复制实现 |

## 测试、说明及配置清单

- [pyproject.toml](pyproject.toml)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [interface.json](interface.json)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [tests/browser_shared_page_health.py](tests/browser_shared_page_health.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_submission_guard.py](tests/test_web_submission_guard.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_page_dispatch.py](tests/test_shared_page_dispatch.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_workflow_activity.py](tests/test_shared_workflow_activity.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_pool_store.py](tests/test_shared_pool_store.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_media_storage.py](tests/test_web_media_storage.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_lane_controls.py](tests/test_shared_lane_controls.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_upload_bundle.py](tests/test_web_upload_bundle.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_browser_window.py](tests/test_shared_browser_window.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_workflow_queue.py](tests/test_shared_workflow_queue.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_backlog_owner.py](tests/test_shared_backlog_owner.py)：离线/隔离回归，验证当前合同。
- [tests/test_gpt_model_policy.py](tests/test_gpt_model_policy.py)：离线/隔离回归，验证当前合同。
- [tests/browser_shared_page_repair.py](tests/browser_shared_page_repair.py)：离线/隔离回归，验证当前合同。
- [tests/test_owner_browser_calls.py](tests/test_owner_browser_calls.py)：离线/隔离回归，验证当前合同。
- [tests/test_authorized_unsent_restore.py](tests/test_authorized_unsent_restore.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_page_queue.py](tests/test_web_page_queue.py)：离线/隔离回归，验证当前合同。
- [tests/test_browser_inventory.py](tests/test_browser_inventory.py)：离线/隔离回归，验证当前合同。
- [tests/__init__.py](tests/__init__.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_window_tabs.py](tests/test_shared_window_tabs.py)：离线/隔离回归，验证当前合同。
- [tests/test_restored_web_draft.py](tests/test_restored_web_draft.py)：离线/隔离回归，验证当前合同。
- [tests/browser_rich_editor_input.py](tests/browser_rich_editor_input.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_window_entrypoints.py](tests/test_shared_window_entrypoints.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_workbench_move.py](tests/test_shared_workbench_move.py)：离线/隔离回归，验证当前合同。
- [tests/test_startup_page_restart.py](tests/test_startup_page_restart.py)：离线/隔离回归，验证当前合同。
- [tests/test_attempt_history.py](tests/test_attempt_history.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_page_backlog.py](tests/test_shared_page_backlog.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_page_health.py](tests/test_shared_page_health.py)：离线/隔离回归，验证当前合同。
- [tests/test_browser_recovery.py](tests/test_browser_recovery.py)：离线/隔离回归，验证当前合同。
- [tests/test_network_resilience.py](tests/test_network_resilience.py)：原PUT错误触发新派发冷却、原材料保持、额度优先及诊断头脱敏。
- [tests/test_browser_start_request.py](tests/test_browser_start_request.py)：离线/隔离回归，验证当前合同。
- [tests/test_collective_page_restart.py](tests/test_collective_page_restart.py)：离线/隔离回归，验证当前合同。
- [tests/browser_editor_input.py](tests/browser_editor_input.py)：离线/隔离回归，验证当前合同。
- [tests/test_retry_owner_responsiveness.py](tests/test_retry_owner_responsiveness.py)：离线/隔离回归，验证当前合同。
- [tests/browser_modern_attachment_health.py](tests/browser_modern_attachment_health.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_window_owner.py](tests/test_shared_window_owner.py)：离线/隔离回归，验证当前合同。
- [tests/test_upload_quota.py](tests/test_upload_quota.py)：离线/隔离回归，验证当前合同。
- [tests/test_upload_attempt_trace.py](tests/test_upload_attempt_trace.py)：临时证据目录验证意图先落盘、目录未登记不启动上传、结束回执写失败仍停在 upload_started 且阻止发送、unknown 不记 finished、异常消息脱敏、技术失败与四类非上传失败分流、5 路交错互不串 ZIP、重打包标记。
- [tests/test_upload_retry_policy.py](tests/test_upload_retry_policy.py)：真实临时Catalog验证回执只计一次、退避窗口、材料键独立与损坏兜底。
- [tests/test_shared_backlog_upload_cooldown.py](tests/test_shared_backlog_upload_cooldown.py)：真实混合排队验证冷却跳过head但不移页、不释放领取。
- [tests/test_shared_window_start.py](tests/test_shared_window_start.py)：离线/隔离回归，验证当前合同。
- [tests/browser_composer_consistency.py](tests/browser_composer_consistency.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_page_observer.py](tests/test_web_page_observer.py)：离线/隔离回归，验证当前合同。
- [tests/test_login_ui.py](tests/test_login_ui.py)：隔离真实DOM中的登录控件、弹窗、认证跳转与科学内容排除；原观察器持久暂停、槽位提示及不凭登录控件消失自动恢复。
- [tests/test_requested_refresh.py](tests/test_requested_refresh.py)：原所有者一次刷新、未知导航回执不重放、输入/上传/登录/验证/已发送保护。
- [tests/browser_shared_window.py](tests/browser_shared_window.py)：离线/隔离回归，验证当前合同。
- [tests/test_owner_upload_jobs.py](tests/test_owner_upload_jobs.py)：离线/隔离回归，验证当前合同。
- [tests/test_receipt_history_groups.py](tests/test_receipt_history_groups.py)：离线/隔离回归，验证当前合同。
- [tests/test_shared_page_repair.py](tests/test_shared_page_repair.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_card_pool.py](tests/test_web_card_pool.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_message_text.py](tests/test_web_message_text.py)：离线/隔离回归，验证当前合同。
- [tests/test_web_pool_open.py](tests/test_web_pool_open.py)：离线/隔离回归，验证当前合同。
- [docs/网页App共用ZIP预存.md](docs/网页App共用ZIP预存.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/制卡与核对共享专用窗口.md](docs/制卡与核对共享专用窗口.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/五页并行上传与串行发送.md](docs/五页并行上传与串行发送.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/网页长提示完整回执核对.md](docs/网页长提示完整回执核对.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/桌面Chat与千问控制实测.md](docs/桌面Chat与千问控制实测.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/四任务与共享网页调度.md](docs/四任务与共享网页调度.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/手动打开GPT后的页面池恢复.md](docs/手动打开GPT后的页面池恢复.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/共享页面混合排队与补充.md](docs/共享页面混合排队与补充.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/核验上传失败退避.md](docs/核验上传失败退避.md)：S002技术退避的计数条件、守卫位置、兜底与回退说明。
- [docs/坏页自动检查与替换.md](docs/坏页自动检查与替换.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。
- [docs/网页队列与10秒检测.md](docs/网页队列与10秒检测.md)：当前接口使用说明或配置；实际规则以AGENTS和实现为准。

## 数据、并发和权限边界

2026-11-14：上传派发每 5 秒检查一次，制卡材料队列空闲时每 3 秒再查。专窗回答观测仍按 10 秒，故障页检查仍在上轮结束后等 30 秒；派发触发间隔与附件上传和发送的锁、超时无关。

唯一已登记窗口的已授权操作及其账本；导入接口不连接浏览器。 原文、卡片、冻结输入、回执与人工决定保留原存储位置。暂停、原文/版本身份、真实领取、未知提交不重发及科学验收要求不变。接口导入、测试或文档阅读不构成启动/外发授权。

当前配置入口是 [config](../config/README.md)，共享状态合同见 [data](../data/README.md)。共用Catalog通过core API持有事务；不复制数据库、锁或共享浏览器所有者。

## 已删除与保留的证据

旧独立模型实验、旧Streamlit/旧article应用、重复符号链接、旧平铺测试和旧一次性迁移脚本已删除；本项目测试已使用正式包名。逐文件删除原因与指纹见 [清理审查](../../reports/physical-isolation-cleanup.json)。历史评审和原授权用于追溯原请求，保留不表示可恢复旧任务。

## 调度停滞修复（2026-10-14）

shared_page_health 的固定页快照在原所有者事件循环并行读取，每页读取有3秒期限；只有已核对原窗口的登记target参与，检查失败保持不完整，关页/复用仍逐页实时重核。shared_page_repair保持原P85、两轮、归档、nonce和CAS保护，记录整轮真实耗时。

web_page_observer只把本地回执文件索引移至后台文件线程；所有DOM/CDP操作仍在原连接和原事件循环，原10秒调度保持。attempt_history为缓存访问提供线程同步，保留原字节hash、文件身份/mtime/ctime变化检查。shared_claim_recovery在同一健康轮复用已核对诊断hash；每次复用先核对dev/inode/size/mtime_ns/ctime_ns和预期hash，不缓存错误，也不跳过原账本唯一性与领取CAS。

新增tests/test_health_batch_and_cache.py检验一页延迟不串行拖住其他页及缓存被改写后失效；test_web_page_observer验证慢文件扫描不阻塞驱动时钟。没有改变未知请求、用户暂停、登录/额度或科学核验合同。

文件索引的缓存清理先计算一次规范根，再比较已规范化缓存路径的完整目录前缀；不为每个文件重新resolve根或遍历适配路径父目录。没有页面/固定target时观察器不扫描回执。完整回执树仍用于主调度与历史未收请求保护，不通过缩小历史范围提升速度。

## 剩余页面恢复（2026-10-14）

空白换行使用strip核对，不阻挡有完整归档的未知故障页恢复；真实草稿、生成、上传、验证与额度继续保护。旧核验账本未保存upload_bundle时，_bound_upload_bundle只从同一review_id的原packet读取，并通过review.api.check_packet核对job_id、完整输入、实际提示、原图和ZIP指纹；不改冻结账本。_verified_cached_attachment只供已登记、从未提交的nonce候选恢复附件使用：支持Chrome数字后缀，完整校验ZIP清单与内容、包名指纹；有原请求则不能绕过其packet绑定。

locate_retired_receipt可使用已核对诊断归档中的ledger-before原字节作为证据；必须与原账本SHA及target相同，无相同原文或存在歧义仍保护，当前账本不覆盖。_retry_unused_candidate仅对原窗口登记、无任何请求、无草稿/附件/生成/验证/额度的初始化网络错误，按原启动P85和两轮30秒检查归档后重试初始化。

原create_unknown不重复同一创建操作。_authorized_missing_slot接受单次明确授权的missing-slot-recovery-request.json，或2026-10-22授权的一小时自动新epoch：绑定原journal/nonce/slot/window/创建时间及槽位hash，原所有者实时盘点恰有19个登记页，旧target和nonce不存在、原归档hash保持；旧未知操作独立保存，每次授权新epoch最多一次；自动新epoch再失败须再等待一小时。未开启hard_restart_after_seconds时不自动新增epoch。tests/test_remaining_recovery.py和test_shared_page_repair验证误配、损坏、用户草稿、未授权和重复执行保护。

## 2026-10-14 原提示展开

`web_message_text.expand_original_user` 将仅含空白/换行的输入框视为空，仍要求原 target、唯一正式 URL、实际提示 SHA 与可见前缀一致，并排除生成、上传、登录、额度及真实新草稿。只由原所有者在提交锁内点击本地“显示更多”，不导航、不发送、不修改回执。

## 2026-10-14 当前卡住溯源修复

`shared_page_health._homepage_error_notice`在明确未发送且无未收历史的空白主页中识别有可见UI出处的加载故障；相同指纹二次稳定核对后才按原归档/nonce/CAS流程替换，不让报错主页进入健康可派发集合。登录、验证、额度、草稿、上传、生成、他人页面和未知回执继续保护。

`shared_workbench_move.pending`先只读核对原移窗日志；verified/cancelled_target_missing不争用提交锁，待维护记录仍在锁内重核。快照新增`composer_available/model_controls`只读诊断字段；输入区不可见的主页不派发新任务。原唯一所有者执行全部网页观测和恢复，未新增CDP或常驻。

## 2026-10-14 派发吞吐与补页CAS

[reusable_home.py](reusable_home.py)提供prepare：在原所有者提交锁和复用守卫之后，复用已实查空白可用的首页，避免每篇重新加载；已完整收取的会话仍导航首页，随后等待真实模型按钮再执行原严格GPT/High配置。读取不完整、草稿/附件/生成/验证/额度或UI错误变化阻断导航。选择保留页面既有加载状态，是为减少本站首页加载失败与控件未就绪；不跳过原请求或模型验收。tests/test_reusable_home.py覆盖无重载、必要导航、变化保护和模型控件缺失。

shared_page_repair新增_rebase_registry和_sha_text：新修复日志保存原槽位、全局登记身份和各槽位哈希；其他槽位确实变化且本槽原字节、全局身份不变时，保存旧/新登记指纹再继续原操作，最终写入仍全文件CAS。旧日志仅已确认关闭、无nonce/创建意图、原池仍绑定本修复、原槽/账本/完整归档一致时可显式登记当前槽基线；未知创建、同槽或全局变更仍阻断。不补造旧基线，不重发原请求。tests/test_shared_page_repair.py增加跨槽恢复、同槽拒绝、旧已关闭恢复及未知创建保护。

旧日志接续时，原账本仍在当前路径必须保持原SHA；原路径已因原授权重试移走时，仅接受同一文献history下唯一、原字节SHA及target完全一致的旧回执，保存原路径→归档路径/哈希绑定。现存当前账本变化或历史归档不唯一仍阻断；不覆盖/恢复旧控制或回执。

原页面客户端超时不证明实际附件上传已经结束。健康快照读取原composer中的真实可见上传进度并纳入指纹；classify、批量/超时重开及发送前首页准备均保护实际上传。只在进度真正消失且原失败材料/回执重新核对后沿用原恢复规则；不取消上传或重发。新增独立真实DOM用例区分composer进度、隐藏进度和其他区域进度。

客户端回调结束后仍有真实上传进度的target继续占用原上传预算；原5页上限只限制新领取，不取消或关闭已经活动的页面。web_card_pool.upload_budget_targets合并原上传协程和实查原生上传页，记录upload_budget_used/native_upload_wait_targets。PageObserver在同一原连接上为原注册页接入request/response/requestfailed观察，保存web-upload-network.json；只记录target、域名、方法、状态、错误类型与`upload_attempt_id`，不保存签名URL、头、正文，不接入其他窗口或重发网络请求。_update_network_pages/_network_event维护监听和脱敏记录，原观察间隔及生成验收独立。S001把网络事件改为按「请求发起时该页所属的上传attempt」归属：`request`事件用Playwright请求自身的稳定标识调用`upload_trace.bind_request`绑定当时`active(target)`的attempt，随后迟到的`response`/`requestfailed`只沿用这条绑定，绝不按target的最新任务重算；查不到绑定就记`attributed=false`并保留，不猜。errors[]仍是最近100条的原形状，累计证据改为追加写`upload-attempt-events.jsonl`，所有者重启后旧attempt标识与网络事件都仍在文件里可查。归属口径已收紧到与代码一致：`request`发起时该页没有活跃attempt（所有者重启后`_ACTIVE`为空是主要来源）仍写入JSONL并记`attributed=false`，不猜归属，也不因查不到绑定而丢弃整条阶段记录；只有读不到请求稳定标识（Playwright私有`_guid`缺失）的`request`确实无法绑定，改为计入`web-upload-network.json`的`attribution_counters.request_without_key`可见告警，迟到事件缺标识计`late_without_key`，已绑定计`request_bound`，两者都进`network_report()`而不静默全丢。`upload_trace.finish()`落盘前对`stages`/`settle`/`attachment`三棵子树内全部字符串叶子过`desensitize`，内核把进度条读取异常原文写入`settle.error`时同样只留脱敏摘要；`review/card_review_lane.py`写入`upload_retry_receipts.reason`的异常文本也先经同一函数。

原nonce登记的新页尚未创建任何请求、全量target历史为空、never_submitted未被begin_request清除时，观察错误导致ready_blank变成needs_inspection不应丢失未使用归属。classify允许原修复归属和完整历史证据继续走原稳定错误归档/替换；关闭前重新全量核对原target历史。无完整历史、submission_unknown或任一历史请求仍保护，既有请求不重发。

OwnerUploadJobs.retained/budget_targets在协程结束时立即保留原target预算，release_observed仅接受结束之后的完整实查且uploading=false才释放，封住健康检查间隔内先释放后再发现原生上传的空隙。新领取和同target复用均受保留预算约束；drain仅结束原协程，不取消浏览器上传或生成。test_owner_upload_jobs增加旧观察、仍上传、观察失败不释放与新鲜停止证据才释放的回归。

## 原候选与卸载回执恢复（2026-10-15）

`shared_page_repair._resume`对已保存但停在create_unknown的候选，必须实时核对唯一原nonce、相同target及专窗，才推进candidate_created；保留原卸载回执及登记/账本CAS。候选缺失、重复或身份冲突不创建、不导航。临时扩展最终卸载状态在断开会话前再次交给on_created持久保存，断开失败异常携带同一候选。

已登记候选的卸载回执仍为false时，仅原所有者在提交锁内调用`_confirm_cleanup`：读取完整Extensions.getExtensions，限定本日志extension目录；残留扩展须为唯一直属slot-extension目录且manifest/worker与原helper一致，才卸载并再次确认消失。没有该目录的已安装扩展时以实时清单证明不存在。其他扩展不动、不重新安装，不删旧证据；核对错误或暂停继续保留opening。恢复证明保留原candidate与原错误，科学验收独立。

## 核验上传失败退避（2026-10-15，S002）

`upload_retry_policy.py`只处理**已明确结束、从未点击发送的原生上传技术失败**：回执状态`not_sent`、`send_click_started`为false、带有限`finished`时刻，且带`upload_failure_stage`（entry入口未就绪／attach_write外内核写入`input[type=file]`失败／attach_visible附件始终未露头／settle上传未结算；旧`attach`标签仍可读，已入库回执继续冷却，但不再新产出）。策略键为lane＋job_id＋inputs_digest＋ZIP SHA，另存`failure_receipt_id`（由原回执自身的created／finished派生）；同一回执在双扫描、并发线程与所有者重启后都只计一次，`next_eligible`只由回执结束时刻加窗口推出，所以扫描或重启既不能补计失败也不能延长冷却。窗口默认5／15／60分钟，第三次及以后按配置低频继续自动重试；成功发送只清连续计数，`total`与回执证据永久保留。

暂停、额度、访问验证、材料变化和未知回执都不写入本策略：它们由原通道门与不重发保护处理。策略记录损坏或该材料清单读不到时按“非到期”兜底——保留材料与真实格位、停止该材料新领取，并在派发处显式报错，绝不当成零失败。回退只需`card_review.upload_retry.enabled=false`：记录与恢复链退回原行为，两张证据表继续保留，禁用不会给任何旧请求开重发入口。

`shared_page_backlog._head`对冷却中的未领取核验材料只做跳过（与暂停队同类），not-ready、缺材料和归属变化仍照原样挡住本页FIFO；`reconcile`把冷却记录钉在原target并计入`physical_queued_tasks`与新的`upload_cooldown_tasks`，但不计入可派发库存，因此85／100触发不会把冷却材料冒算成活动任务。`shared_workflow_queue.heads`（非混合入口）和`eligible_records`遵循同一策略。`web_card_transport.UploadStageFailure`是`RuntimeError`子类，原文案与旧捕获不变；`shared_workflow_queue.install`经原到达链创建证据表，读路径从不建表。制卡额外2次、专项修复次数与科学失败计数均未改动，页池、固定槽与P85阈值未改动。

`upload_trace.py`＋`web_gpt.upload_files_detailed` 实现 S001 的上传归因（原 `upload_started/upload_finished` 只带 `at/result`，任何原因都被压成 `failed`）：

- 每次上传一个 `upload_attempt_id`（uuid4 hex），开始/结束事件都带 lane／job_id／paper_id／target、ZIP SHA 与字节数、仓外内核 `source_sha256` 与 Playwright SDK 版本；结束还带 `failure_kind`、`retryable_upload`、`stage`、`exception_type`、`receipt_sufficient` 与逐段耗时。
- 内核侧失败分类为 `zip_preparation`／`prompt_box_unavailable`／`missing_file_input`／`entry_disabled`／`write_failed`／`attachment_not_shown`／`attachment_reused`／`settle_timeout`／`settle_unreadable`；paper 侧另加 `entry_not_ready`／`full_page_settle_timeout`／`paused`／`quota`／`verification`／`input_changed`／`unknown`。**暂停、额度、访问验证、模型核对与冻结材料变化一律不计为可重试上传失败**；是否计一次退避由内核自己的 `retryable_upload` 决定（`UPLOAD_STAGE_BY_KIND.get(kind) if retryable else None`），只有 `missing_file_input`／`entry_not_ready`→entry、`write_failed`→attach_write、`attachment_not_shown`→attach_visible、`settle_timeout`／`full_page_settle_timeout`→settle 这些可重试分类才映射到 S002 的 `UploadStageFailure.stage` 进入退避；stage 标签本身不再足以让一次失败可重试。
- 进度条读不到不再直接当失败了事：最多 `SETTLE_READ_RECHECKS=2` 次**只读**重查，绝不重新 `set_input_files`；仍读不到记 `settle_unreadable` 并保持 unknown，不伪造 finished、不排入退避。
- `receipt_sufficient` 只在“原附件回执确认新增＋整页复核无进度条”时为真；进度条消失本身不再单独充当完成证明，原发送守卫照旧。
- 目录未登记或开始意图写不进 `upload-attempt-events.jsonl` 时抛 `DeferredWeb`，**根本不启动上传**；结束回执写不进同样抛 `DeferredWeb` 阻止发送，该 attempt 在 JSONL 里留在 `in_progress` 供核对；未知结果只记 `unknown`。
- 意图记录与实际送达包体 ZIP SHA 不一致时写 `zip_identity_mismatch=true` 并保留 `intent_zip_sha256`，不冒称同一材料。
- 事件只存脱敏字段：签名 URL 的路径与 query 在落盘前由 `desensitize` 剥掉，头与正文从不入库。
- `web_gpt.upload_files` 的返回值与异常语义完全保持（等于 `upload_files_detailed(...)['ok']`），旧调用方与旧捕获不变；`upload_files_detailed` 是新增具名公开出口。attempt 账本新增 `upload_attempt_id` 与 `upload_diagnostic`，冻结 packet／prompt 文件不加字段。
- 实测在役的两条派发链（`web_card_pool` 制卡／修正经`submit_gpt_background`、`review/card_review_lane` 核验经同一函数）都通过 `upload_context`＋`on_identified` 由原账本写入者自己落标识；诊断写入不抢占活动/未知页，也不重发任何原请求。第三条 `web_card_transport.request()` 是未在 `interface.json` 导出的遗留路径：共享专窗登记存在时它在任何页面动作之前抛 `DeferredWeb`，现网配置下不会执行到 `upload_trace`，其 `upload_trace.configure(folder.parents[2])` 已收口为「仅当目录尚未登记时才登记」，因此既不会被它重定向到别处，也保留 `run_with_failover(..., request_fn=request)` 已声明的默认实现与独立非专窗入口的首次登记能力。
- `cards.web_card_service.code_version()['module_sha256']` 实测 117 键（112 个源码/别名键＋5 个 `dependency:*` 键：`web_gpt.core`、`web_gpt.package`、`web_gpt.zip_uploads`、`codex_desktop_chat.bundles`、`playwright.sdk`）；监督器整体字典比较，新增键即差异，这是首次交接必须实跑的一项。
- 声明卫生（S001 F-6／最终闸门第 2 节末段）：`browser.api` 出口按实测消费者收口，只保留确有跨项目调用者的名字。本轮撤回 10 个「已声明但零调用者」出口——`upload_retry_policy.{install,enabled,due,cooling,upload_failure,window}`（这四个的仓内调用者都用 `from .upload_retry_policy import …` 包内直连，`install` 由 `shared_workflow_queue.install` 同侧调用）与 `upload_trace.{reset,attempt,append,owner_identity}`（前三者仅测试与包内使用；`owner_identity` 本来也未声明）；同时接入两个此前无人使用的出口：`upload_trace.desensitize`（核验道 `reason` 落盘）与 `upload_retry_policy.PolicyIntegrityError`（领取层捕获）。`make check` 的 `public_exports` 因 9 个实际存在的声明被撤回而由 344 降为 335（合同数 73→67）。

## 2026-10-15 大面积上传停滞

[恢复授权](../docs/authorizations/20261015-twenty-page-upload-recovery.md)允许原所有者处理有终止网络证据、明确未点击发送却仍显示原生上传的页面。`failed_upload_eligible`核对P85、结束回执、同target原PUT、全部输入/ZIP/实际提示与草稿指纹，`failed_upload_restart`要求两次相隔30秒实查。`shared_page_repair`沿原完整归档、关闭前重核、固定槽CAS及nonce链执行；上传回调仍活跃、生成/已发送/未知、用户新草稿、登录/额度保持保护。原生上传计数不因回调返回而释放，恢复通过真实关页回执确认。

`original_upload_http1`默认关闭，本轮配置只给`20261015-one-original-put`一次持久epoch。原所有者同一线程/事件循环的Playwright API context转发下一合法新材料的原PUT，完整body必须等于原ZIP SHA；只允许原HTTPS上传主机，原Host/长度先核对再由客户端正确生成，认证/Cookie等原头保留。严格TLS、重试0、重定向0，原始状态/响应回给页面；错误不伪造成功，不确定不回退重传。下一材料先独占reservation，即便请求不可见也消耗这一材料名额；PUT意图独占创建并fsync后才联网，已有同材料意图阻断原生重传；重启重装原target防重钩子。ServiceWorker或部分PUT无法观察到整包时保持原生路径，不声称协议实验完成。SDK锁定本机验证的1.63.0；显式代理存在时拒绝配置实验，不暗改代理。只记录主机、字节/hash、归属、耗时、真实状态，不保存URL签名、头部凭证或正文。

发送按钮90秒只读等待移出全局提交锁；设置/填提示/实际点击仍在原锁内，重新核对提示、暂停、页面归属和原输入后才发送。就绪门耗时在门结束时记录，失败不再写成ready。`ReviewLane.reconcile_submissions`只从原结束回执恢复丢失的队列确认（submitting→needs_user或submitted），排除活跃回调，不释放页面、不变ready；原错误继续原有恢复链。`first_eligible(..., diagnostics=...)`记录并隔离损坏策略，不阻断后续健康材料，SQLite/诊断写失败不跳过原失败收尾。

新增测试：[原PUT合同](tests/test_original_upload_http1.py)、[失败上传保护与两轮](tests/test_collective_page_restart.py)、[原归档生命周期](tests/test_shared_page_repair.py)、[同循环上传和锁](tests/test_owner_upload_jobs.py)。本机隔离Chrome/HTTPS测试及真实运行观察分别记录于[诊断目录](../../reports/twenty-page-stall-20261015T155655/)，不代替科学验收。

第二阶段[技术细化](../docs/authorizations/20261015-system-proxy-upload-fix.md)：原生结束上传失败回执可以独立证明取消条件，旧环形网络错误缺失不伪造也不阻断已授权恢复。PageObserver初始化先归档原网络投影，标明historical/原owner；新上传归因仍按原请求ID。HTTP/1.1 context读取并复用原macOS HTTPS代理/bypass；PAC/自动发现/SOCKS-only未核对则拒绝。首次线上直连对照unknown保留，跨epoch`material_intent`阻断原材料领取和恢复；第二次只选另一合法材料。`promote_on_native_success`仅在该次真实2xx、fulfill及原生完整结算全部具备后启用后续新材料传输，每材料独立持久意图、零重试，未知不晋级。恢复防重钩子仅装原固定登记窗口内页面，合并同target多份旧意图，保留移出专窗页面。网络例外仅存类型/错误码/摘要SHA，不落签名或认证头。TLS隔离负例使用错误DNS名；IP目标在生产白名单之外。


## 节点波动与浏览器退出恢复（2026-10-15）

用户明确不固定代理节点。`browser_start_request.run_once`在原所有者轮询中处理已就绪、现已退出的专用浏览器；`_recover_closed`要求有效原登记、相同profile/端口、相隔30秒两次缺失实查及归档，限制为每小时2次、间隔5分钟。部分初始化、未知启动、存续进程和人工验证不重开，旧材料账本保持。`shared_window_start`直接使用有界快照的真实输入框和错误状态，缺失控件不再触发逐页等待。

`shared_page_health`同时识别有真实UI来源的两种主页重试文案；错误或无输入框页面不计健康，原归属、全部历史、两轮稳定、归档/CAS和账户保护仍成立。`web_page_observer`只为原固定页保留白名单错误头，`web_card_pool.record_upload_network_failure`仅将已归因原PUT的明确传输错误接入原五分钟冷却。未归因、ERR_FAILED/ABORTED和HTTP拒绝不触发自动重传，原观察/收取继续。`Router.block`禁止网络错误缩短或覆盖尚未结束的额度等待。授权见[节点波动恢复](../docs/authorizations/20261015-network-resilience.md)。

`shared_page_repair._resume`在关闭前证据变化时，若旧计划仍为`archived`且没有nonce或候选，核对原归档、账本和槽位，逐字保存旧计划后标记`cancelled`；仅清除该计划自己的待修复标记，原页重新实查，不沿用旧故障证据。用户草稿保持，变化后的故障重新累计两轮；`close_intent`及创建回执不明仍保留，不取消重开。`test_shared_page_repair`覆盖旧计划滞留、安全退出和未知关闭操作保护。

`test_browser_start_request`覆盖两次实查、存续进程、部分启动、人工验证、恢复限频和写入中断后的同一nonce；`test_shared_window_start`验证缺失输入框不拖住其他19页；`test_shared_page_health`覆盖短文案、来源、草稿/活动保护和无输入框；`test_network_resilience`覆盖网络事件、冷却、原材料保持和错误头白名单。实际节点切换不作为生产故障注入，隔离测试与真实运行结果另记。

## 登录提示与本轮小包检查（2026-10-15）

`shared_page_health.LOGIN_UI_SCRIPT`统一读取可见登录按钮、链接、明确登录弹窗及已知认证地址，不依赖旧testid；文章/回答、草稿、隐藏控件和外站链接不作登录证据，认证query不落盘。`PageObserver.inspect`在原连接每轮先读这一只读证据，即使发送通道已暂停也继续观测。登录页明确投影`state=login_required`、`login=true`及UI来源；`_record_login`保留原通道字段并持久登记原target/固定槽位，重复同证据不刷控制事件，不自动清除人工门。

`OwnerUploadJobs.release_observed`接纳原维护流程完整的无上传实查及`replaced`完成回执。2026-10-16进一步将成功上传/发送的已持久提交回执直接释放容量；`release_missing`仅对已经结束的回调，以原所有者两次相隔30秒的完整目标清单、同一新窗口epoch和先写归档释放旧target容量，不改变原未知请求或原材料的重发权限。当前仍上传、单次缺页、清单不完整、epoch变化或归档失败继续保留。状态输出`retained_upload_targets`，授权见[独立执行循环](../docs/authorizations/20261016-independent-upload-and-collection.md)。

`owner_work_lane.py`中的`OwnerWorkLane`、`start`、`_run`、`stop`、`drain`负责在原Playwright线程/事件循环内每0.5秒尝试一次上传准入，同一回调不重入。它不新建连接、线程或服务。`web_card_pool.refill_uploads`核对原owner、暂停/额度、完整新鲜20槽窗口证据和原登记，复用混合队列公开领取合同，按现有文章分数/最低目标与FIFO一次补足最多5个上传提交。收取中的target与上传target排他，其他页面无需等待维护或回答结束。

`web_page_observer.PageObserver.inspect`独立检测完成、原会话/材料/提示身份和稳定性，最终账本CAS后保存原回答；不获取上传发送锁。`web_card_pool`本地处理阶段仅再次核对已保存回答和发布链，生成计数来自新鲜身份观测，不在主循环重复遍历生成正文。`web_card_transport.commit_submitted(path, attempt, *, prior_count, conversation_url)`在原发送回执确认时保留已经独立保存的同绑定回答，目标、创建时间、提示、URL或原回答hash变化即拒绝覆盖；核验`ReviewLane.submit`通过浏览器公开API调用同一实现。

`tests/test_independent_work_lanes.py`验证单原线程5槽处理20项并持续补位、两次缺页证据/epoch/归档失败保护、旧上传快照不重新占用已成功释放名额、提交锁不可用时仍能完整收取，以及晚到提交确认不降级已保存回答；无生产CDP或真实外发。

原固定页跳到认证域仍由原观察器做账户只读检查；只有实时窗口登记仍为present的固定target可补入这一观察集合，发送集合继续仅限ChatGPT。非ChatGPT页不读会话正文、不导航或收取，不观察其他窗口的新页面。

用户明确刷新通过JSON合同`owned-page-refresh.json`请求原所有者：当前owner PID/令牌SHA、授权文档SHA、32位十六进制id、原window_id和唯一slot/target清单绑定。`refresh_requested`只处理仍为浏览器检查失败或已恢复无错误输入框，且全部历史明确未发送、无活动/草稿/账户输入的页面；原锁内完整归档及CAS后保存refresh_intent，再reload一次。done、refresh_unknown及blocked不自动重试，不更改固定登记、队列或账户暂停。结果写回同一请求，完整诊断在owned-page-refreshes/id/slot下。

account_readiness.recheck只自动核对观测来源账户门：原20个登记target全部具有新鲜同窗口的正面账户UI及输入框证据，无登录/验证/错误/额度，两次实查相隔至少30秒，控制/登记CAS不变且原owner仍获准时解除该账户门。账户控件同时支持原testid和新版中英文“打开个人资料菜单”可访问标签；输入框支持真实role=textbox/contenteditable，不要求旧id。它不改变队列暂停、不输入登录资料、不处理验证码；缺失、其他来源人工门或证据变化保持等待。account-recovery.json保存核对阶段，控制事件保留原门。

- [tests/test_account_readiness.py](tests/test_account_readiness.py)：两次原20页有效账户核对、陈旧/缺页/登录/窗口归属/暂停阻断及控制CAS。

上传传输另记录原请求的2xx/3xx响应与requestfinished元数据，继续绑定请求开始时的attempt；不写签名URL、正文或认证头。这些成功传输证据不进入旧错误环、不触发网络冷却，也不解除原生附件就绪门。HTTP传输完成、180秒内原生附件结算、模型发送和回答分别记录；用户明确保留180秒附件结算阈值，不把settle_timeout等同于网络中断。

最低并行的上传准入同时考虑该队原真实活动target和当前上传/待证实原生上传target的并集。原OwnerUploadJobs记录领取时的lane；同target不重复计数，结束回调仍等待原生结算/原维护替换回执，不提前释放预算。这样尚未生成、没有核验分的新制卡不会因核验/修正正在上传而继续被当作三队全空闲。仅修正既有minimum_priority占用输入，不改队内分数/FIFO、固定target、暂停或既有请求；不把上传计数投影成界面的实际生成并行。

## 同步与重复观测异常修复（2026-10-16）

原观察器每轮对同页分别读取账户、挑战、停止按钮、轮次、回答数量，20页共用原事件循环时产生多轮往返。现在status_script一次返回这些状态，同时记录发送按钮禁用与上传指示；发送按钮灰色不等同上传字节仍在流动。当前assistant轮次才能确认complete，旧答案加用户complete不构成完成。3秒DOM读取、状态与收取分别5秒协程期限、10秒周期及180秒附件结算保持；事件循环阻塞或取消耗时会使实际墙钟超出期限，因此另记真实耗时。

20页轻量状态先统一发布，再并行执行独立的归属/回答稳定性/收取检查；后者失败保留先前成功状态，并以receipt_state、receipt_failed_stage和独立receipt_check_id记录。只有实际核对成功才写activity_verified和identity_checked_at，完整保存仍单独记录saved。稳定性复查时生成恢复必须更新状态，不能将旧complete配上新时间。已保存且无生成页不反复读取提示/正文作收取身份核对；activity_verified、复用及关页仍由各自原实时守卫决定。外层检查截止保留原target、checked_at、唯一round_id/check_id、开始/结束、failed_stage/error_type和耗时，page_state耗时与原循环延迟独立记录。web-page-observer-errors.jsonl只追加真实失败轮次的脱敏元数据，按diagnostic_kind区分状态读取与收取失败，避免分钟快照被当作独立故障计数；不保存URL、提示、回答或凭据。

隔离DOM回归覆盖灰色按钮无进度、隐藏停止按钮、旧回答与用户完成标记；调度回归覆盖一慢页不影响其余19页及失败阶段/编号保全。完整回答的原URL/材料/实际提示/正文hash/CAS、提交锁、暂停、登录/额度与未知回执保护保持。线上错误比例须用交接后的新检查编号统计，旧65条分钟样本不改写。

## 附件额度提示新鲜度（2026-10-16）

`upload_quota.visible_notice`仅一次DOM读取当前可见的原生alert/dialog/menu/popover等提示，排除消息、科学正文、草稿、侧栏和隐藏节点；不读取旧`__paperUploadNotices`字符串环，也不扫描整页正文。原生菜单展开后由同一读取重新核对，不把body文字推入永久额度缓存。`LIVE_NOTICE_SCRIPT`用文档内提示身份和首次实见时间锚定相对期限；同节点同文案连续可见时不随轮询延长，消失后不再作为当前限制。

重置时间解析也覆盖原生升级提示中的“或在 05:48 后 后重试”及“可于…再上传”：重试指令必须位于同一有界句内，无关套餐时间、无重试说明及已过时钟不能推断恢复。继续保留原提示、首次实见时间及原通道冷却；上线不回填或清除旧额度记录，原所有者下一次真实可见提示读取才应用新解析。

返回保留notice/observed_at/source，并增加evidence_version=2、read_kind、notice_id和first_observed_at。真实可见但没有未来重置时间的提示仍返回对象，not_before_utc/retry_after_shanghai为null；`_reset_timestamp`统一兼容，原Router以15分钟冷却探测处理，不声称网站已恢复。旧实验capture仅接纳有未来时间的提示，仍暂停。本修复不清除现存provider等待、不恢复暂停、不重发未知或已发送材料；完整测试/接口/联动检查后只由原监督器正常交接。

隔离真实DOM回归覆盖历史字符串拒读、干净输入区可通过原就绪门、连续提示不滚动续期、消失后失效、无时间/过期但仍可见提示继续阻断，以及科学文字/隐藏节点排除。授权及证据见[额度读取修复](../docs/authorizations/20261016-quota-notice-freshness.md)。

真实首轮暴露5任务争抢旧全局锁而在30秒提前失败：锁中包含网页准备/模型设置及最长60秒正式URL回执等待。2026-10-16将各target独占的复用检查、导航、模型设置和点击后只读确认移到锁外；领取确认、持久发送意图与唯一点击仍在原锁内。发送前重新核对模型/强度，暂停/原slot守卫在本页准备前再核对。`test_parallel_preflight_and_send_receipt_wait_do_not_hold_global_lock`以5个同线程并发管线验证预检/回执等待不占全局锁，唯一点击仍持锁。

## 2026-10-16 流程稳定性修复

[owner_http1_transport.py](owner_http1_transport.py) 是原所有者内的私有HTTP/1.1原PUT适配器：通过系统curl、原代理、stdin传签名URL/头和临时原字节，异步等待不占驱动线程；严格TLS，零重试/重定向，真实响应回到原页。沿用original_upload_http1持久意图、跨epoch拒绝重传及2xx/fulfill/native_settled三重推广门。Curl失败也记unknown，不能回退重放。

owner_browser_calls复用原连接的只读浏览器会话；取消某个检查不取消其他检查的会话取得。shared_window_owner每次仍发送真实Browser.getWindowForTarget，登记变化、移出专窗或两次有界读取失败均拒绝权限。shared_page_repair全量快照不持提交锁，各target及旧journal分别维护，原归档/CAS/nonce/暂停守卫和owner恢复回调继续在锁内；web_card_pool排除在维护中的target，其他合法页可独立派发。responsive_lock在原进程中FIFO等待原跨进程文件锁，发布实际锁等待/持有耗时；不把3秒窗口检查异常记成空字符串。

PageObserver使用带receipt_schema=1的同一时点身份/正文/状态快照，4次renderer读取完成原身份、两轮稳定和最终CAS；不取发送锁，3秒单次/5秒收取期限不改。旧式逐项读取仍保留完整守卫用于兼容。晚到诊断不得降级已经完整保存的同绑定回答。commit_submitted的prior_count=None只允许保留已保存原回答，不补造发送前回答计数。

50MiB以上的冻结ZIP在浏览器传输前明确阻断。新材料48MB硬预算（visual-budget-v3）、24MB软目标保留全页与全部DPI步骤；旧包不改写。新通用公式规则要求JSON序列化/解码往返自检，不修补旧科学公式。

新增[tests/test_pipeline_reliability.py](tests/test_pipeline_reliability.py)覆盖并发会话取得、取消隔离、公平锁、4快照收取、最终身份/生成/CAS变化拦截、原始字节/响应/HTTP1和拒绝重定向/失败重传/不可信TLS；共享页测试另覆盖批量快照不持锁和逐target维护回调。授权见[本轮流程修复](../docs/authorizations/20261016-pipeline-reliability-repair.md)。

实机3975738的26MB对照未拿到响应，旧unknown禁止重放。后续按[小包与总量准入](../docs/authorizations/20261016-small-original-put-and-byte-admission.md)：OwnerUploadJobs(..., byte_limit=None)可选已准入ZIP字节预算；start(..., zip_bytes=None)/can_accept按当前回调和保留证据计入，不等同于实时传输。生产32MB总体量，小包最多5页，最高排序超预算大包单独放行，未知大小保守计满预算；成功提交或原停止证明释放。OriginalPutUploads(..., max_probe_zip_bytes=None)/OriginalPutProbe同名限制只约束首次未推广对照，生产8MB，过大包不占用对照且不重排任务；推广仍要求2xx/fulfill/native_settled。测试覆盖5小包、大包单独、未知大小、失败保留及协议对照不被大包消耗、取消持久unknown。

实机后续：只有生产已提供target_lease独占时，shared_page_repair的长归档/补页等待不持发送锁，on_checked_page队列恢复仍短暂取原锁；默认旧调用仍保持锁保护。require_slot只在本槽和全局身份完全不变时接受其他槽revision变化。发送点击有3秒期限，超时保存原未知意图。web_upload_bundle.check_zip_size/UploadSizeError为新增公开本地容量检查，在任何网页准备前拒绝54.85MB等不支持的旧包，record_channel_failure明确跳过本地体积异常；不触页面/账户门，不改包。详见[后续授权](../docs/authorizations/20261016-target-maintenance-and-local-size-failure.md)。

[local_file_upload.py](local_file_upload.py) 在原所有者连接上用DOM.setFileInputFiles交付本机ZIP路径，避免set_input_files把整包base64塞入控制连接。local_file_paths显式开启；每次核对本机Chrome进程、登记端点、target、精确input与两次ZIP指纹/暂停守卫。追加attachment_write意图/完成/unknown；不确定不回退或重复赋值。既有原PUT、原生附件结算、180秒和最终发送保护不变。离线边界测试见[tests/test_local_file_upload.py](tests/test_local_file_upload.py)。

2026-10-17：shared_workflow_queue.active_targets卡片仅查原live页面相关paper_id/state/selection，核验只读id/paper_id/state，不读取全库历史result正文。原target/唯一URL/原回执/新鲜度/暂停及已发送保护判断不变。与core候选范围评分查询共同减少原CDP线程的同步数据库遍历。

2026-10-17：原run_pool登记core纯读取检查点，仅当前原线程的非dispatcher greenlet处理已有Playwright循环，正常退出恢复原回调。不扩展连接/页面/任务；保持写事务原子性及原3/5/180秒。attempt_history.read_attempt作为公开只读指纹缓存供核验账本索引复用，诊断_path/SHA不写回原回执。

最终发送守卫返回后、实际点击前再次检查stopping；读取期间新到的暂停阻止点击，原意图保留，不新增重试或伪造未发送回执。

2026-10-17：owner_upload_jobs.unstarted_proof只证明本回调没有native文件赋值/发送，不授予页权。note_unstarted仅允许当前执行fiber登记；回调正常结束且容量证据落盘后归还其名额/字节，不设released水位，旧health实际上传继续计数。普通False/异常、intent/written/unknown或证据失败仍保留。修复54.85MB本地拦截却占满32MB准入的情况；回归见tests/test_unstarted_upload_capacity.py。

2026-10-17：material_intent先读跨epoch真实PUT意图，再读已持久预留；armed不冒称实际传输。制卡/原文修正在任何原页操作前拦截已占用的同lane/job/paper/ZIP材料，保留原回执并退出新派发；核验原前置检查复用此合同。原传输中最终防重仍保留，不对当前合法上传新产生的自身预留追加发送阻断。

2026-10-20：手选根种子全环节第一顺位，重试/恢复保留同一身份；`core.api.workflow_priority__seed_first`以只读、稳定排序保留原记录对象和组内次序。材料分配、核验准备、混合补充及跨队列上传准入统一种子优先；退避、次数、暂停、固定槽位和未知回执保护保持。见[授权](../../../paper/infrastructure/docs/authorizations/20261020-manual-seed-first-all-stages.md)。

上传字节预算也保留种子第一顺位：可派发种子等待现有上传释放字节时，不让普通小包持续占用下一份容量；原上传正常完成，原未知容量保留。`web_card_pool._seed_admission`在两个原上传入口使用同一规则。

2026-10-20：当前5篇手选根种子三版独立优选。`cards.seed_trials`由现有材料线程每60秒推进；逐版原文核验后只选择完整通过、至少85且无重大/缺材料的最高真实核验分，无合格版沿用原修正循环。原卡/回执/报告、固定槽位、暂停、未知与重试计数保留。`independent_request`仅为新准备材料的中性独立请求标识，写入原文上下文/实际提示并记录输入指纹；旧冻结包不改。旧百万优先级不作为质量分展示，优先身份独立标注。见[固定授权](../../../paper/infrastructure/docs/authorizations/20261020-manual-seed-three-candidates.md)。

2026-10-22：[一小时故障兜底](../docs/authorizations/20261022-one-hour-page-restart.md)。`hard_restart_after_seconds=3600`保留较短P85；原所有者对超时缺页创建未知进行两次30秒完整盘点后，按原归档/槽位CAS进入新epoch，旧未知保留，新epoch再失败仍等待一小时。临时扩展清理不明不续建。`_relocate_archived_ledgers`仅接受原history内唯一同SHA账本，保存旧修复日志及路径迁移证据，避免归档迁移造成无限旧路径报错；科学请求未知、暂停及活动保护不变。测试覆盖小时边界、两次观测、未知扩展保护、逐字节历史迁移及损坏拒绝。

`_hourly_idle_restart`对仍有技术错误、原回答已完整保存或原账本明确未发送的空闲页，以错误/页面/账本指纹持续计时，超过一小时进入同一完整归档及关闭前重核链；活动/未知请求、草稿附件、登录和额度排除。

2026-10-22：[页面吞吐修复](../docs/authorizations/20261022-page-throughput-repair.md)。`shared_pool_store.acknowledge_submitted`在原文件锁内只合并同target/材料/会话的提交确认，保留已收回答；`web_card_pool`和`ReviewLane`不降级已完成队列状态。`shared_page_health`以实际终态和唯一原请求识别terminal_empty，`_terminal_empty_restart`在原提交超过1小时及两轮30秒同证据后走原归档换页，不重发、不计科学失败。`_recover_orphan_review`仅在完整稳定实时证据、原packet/卡片/来源/提示/正文和任务均一致时恢复缺失收取账本，明确原sender/time/model未知；完整保存旧状态与证据。旧窗口无nonce计划只退役，不创建。离线回归在原页面健康、修复、池存储测试文件。

`owner_upload_jobs.active_lease_targets(root)`是只读公开接口；`OwnerUploadJobs`在回调安排前保存原owner PID/token SHA及target领取，在回调结束后移除，写入失败不启动页面操作。自动问题扫描与shared_claim_recovery均跳过仍活跃的领取，避免旧not_sent证据误释放新回调；回调结束保存失败暂保留领取，后续pump重试，不伪造结束。没有新线程/CDP或常驻。测试验证先持久领取、原token变化失效、回调结束释放。

本轮相关文件补充：

| 文件 | 边界与保留理由 |
| --- | --- |
| [owner_upload_jobs.py](owner_upload_jobs.py) | 原事件循环上的回调、字节预算、原生活动结算及持久占用；保留避免额外CDP或线程操作页面。 |
| [shared_pool_store.py](shared_pool_store.py) | 全池乐观合并与同请求ACK合并分别校验；不以旧快照覆盖新任务或完整回答。 |
| [shared_page_repair.py](shared_page_repair.py) | 原归档/nonce/CAS生命周期，终态空回答处理和严格观察恢复回执；不派发旧请求。 |

现场复查补充：browser_inventory只对同一Playwright Page对象、同一browser/context身份缓存一次已成功查询且成功detach的target绑定，弱引用不保留关闭页面；导航不改变target。断连、关闭、新对象、上下文变化、查询/分离失败均不继承缓存。原Browser窗口实时清单和require_slot/关闭前指纹核对保持，缓存不是关页授权。避免每轮20页重复renderer attach超时；原健康检查仍记录真实错误。测试覆盖一次成功后复用、关闭/断连失效与未知detach不缓存。

提交ACK的kind/paper_id/review_id/correction_id来自发送时冻结的原回执，不从可被其他协程刷新后的池快照推断；迟到ACK遇到新任务必须拒绝，不能将新任务指向旧会话。提交回执补充真实paper/kind和correction身份。回归包含“本地快照与文件都已刷新为新任务，旧ACK仍拒绝”。

_restore_displaced_review follows matching previous-job chains to the original frozen folder. It restores exact archived sent-receipt bytes only after stable original target/URL/prompt/packet/version/answer checks, refuses any new claim or attempt, keeps auto folders and old job pointers as evidence, and collects the original response without resending. It is separate from observation-only recovery when no original receipt is available.

2026-10-23：核验媒体目录新增物理准备文件夹指纹，防止同一核验ID的重排候选覆盖原冻结PDF。已发送旧材料仅可从原ZIP按每文件及整体指纹恢复到独立verified-inputs视图；旧损坏字节、原packet、实际提示和回执均保留，不生成新输入或重发。

2026-10-23现场交接暴露另一项阻塞：原主循环在queue.select全库补选时发生database is locked，并在进入页面巡检前退出本轮。补选迁至现有MaterialProducer第0工作线程，完成后60秒节流，单独记录状态/错误；浏览器主循环只读其上一完整结果，不新建线程或连接，扫描失败不跳过原页面观察/收取。

2026-10-23：种子独占使用core.api.seed_focus__*：混合队列过滤普通任务，未领取普通绑定存证并保留源队列/FIFO；claimed不动。最终上传及点击前再次读开关，已发送回答仍收取。现有材料第0线程每60秒跟踪种子；页面归档原证据被种子追踪引用。

2026-10-23派发复核：完整原回答已经核对的旧会话出现`Unable to load site`时，`classify`也将其作为站点错误处理，先等稳定实查，再由原所有者完整归档和CAS核对后替换。此前该错误没有匹配PAGE_FAILURE，健康记录保持completed_saved且不可替换，重试却反复被发送前检查拒绝。新检查不改变额度、暂停、活动上传/生成、草稿、原回答绑定或未知请求保护，也不授予原请求重发。

## 2026-10-25 原唯一会话收取恢复

| 文件 | 全部入口与保留理由 |
| --- | --- |
| [original_receipt_recovery.py](original_receipt_recovery.py) | `inspect_pending`只读核对原提交/关闭归档/冻结材料/原文/槽来源；`run_once`由唯一原所有者每30秒接续，最多开启一个新的原URL读取；`collection_ledgers`向原10秒观察器提供精确收取副本。`_read/_formal/_identity/_verify/_journal_index/_retirement/_pending/_has_draft/_blank/_idle/_enabled/_source/_navigate/_promote/_retire_closed_empty/_retire_closed_browser`分别维护JSON/正式URL/原字段、原字节CAS、归档索引及两种原历史格式、手选第一顺位、干净页/暂停准入、原输入、预导航持久意图与完整回答回写。无发送、上传、关页或创建CDP/target。 |
| [tests/test_original_receipt_recovery.py](tests/test_original_receipt_recovery.py) | 真实隔离SQLite、原账本不变、单原URL导航、原target保留、完整回答接续、未知导航不重放、prepared中断接续、旧归档/完整target历史、同队空闲槽借用、claimed/草稿/生成/上传/暂停/版本/槽CAS及副本变化保护。 |

只读公开API为`original_receipt_recovery__inspect_pending(config,catalog)`。运行接续使用现有owner和逐target维护独占/短提交锁；优先原逻辑槽，空白页或已完整保存且通过原复用守卫的健康完成页可用于原会话读取；借用同队或共享空闲固定槽时分别记录原槽与观察槽，不移动材料/FIFO。原账本未完整收取前不改target/发送时间/模型，原始归档和新副账本均保留。观察器副本失败不跳过其他页面观测，未知/空回答不伪装完成。新模块通过原共享池和素材/核验后继入口接续，不新增常驻。

## 定时截图与冷启动响应

`window_screenshots__request(config)`只请求现存所有者采集，`window_screenshots__status(config)`报告原PID仍活跃及130秒内的新鲜度。原观察器独立任务每60秒采集原专窗20槽，逐页采集前后核对真实窗口/登记，最多3路、单页合计6秒及整轮45秒；窗口前核对、附着会话、截图、窗口后核对和落盘共用单页截止时间，收尾detach只用剩余时间（耗尽后仅给一次最小调度，不追加2秒）。原浏览器连接不变，失败和缺页如实记录。capture_schema_version=2记录error_stage、stage_seconds、真实起止与总耗时，整轮取消也保留已执行阶段；只在detach阶段取消时，保留此前已完成前后窗口核对并落盘的JPEG，清理错误独立记录；真实调度延迟不裁剪为配置上限。普通轮次保留30份，问题目录写入pin.json后不自动清理。截图只读，不改变原10秒收取观测、导航或上传。

`maintain_shared_backlog(..., checkpoint=None)`无活跃登记页时保留绑定、返回waiting_pages，先让启动恢复继续；`shared_page_backlog.reconcile(..., checkpoint=None)`在写锁外预热原文全字节哈希时按ContextVar隔离回调，定期让出原循环。锁内仍重新检查源文件完整版本与队列归属，不用近似指纹；正常退出在检查点停止准备，不改暂停或回执。

- [tests/test_window_screenshots.py](tests/test_window_screenshots.py)：专窗边界、登记变化、采集隔离与有界保留；阶段累计截止、慢页不阻饿后槽、detach不追加预算及整轮取消阶段保留。

原1,024项LRU已改为每条实际路径只保存当前已核对版本；文献数超过旧容量不再在写锁内全量重读。版本变化仍全字节重算并替换旧版本，内存随实际观察到的路径数增长，不随同一路径的历史版本累积。超1,024文件与源文件变更由共享队列回归验证。

原材料线程停止信号经 automatic_issue_handler.run_once(..., stopping=None) 与 workflow_recovery.run_once(..., stopping=None) 传至既有 review_cycle.run_once；历史 failure_count(..., stopping=None) 在每份历史报告前检查，当前完整科学检查结束后再次核对再决定是否推进。停止时保留原报告/计数/任务，不继续后续恢复、收取请求或科学重做，不将中断算作科学失败。

2026-10-26截图巡检：原会话恢复原先在元数据层只取第一个候选；若该页真实草稿/占用或观测失败，会跳过整条原请求，遗漏后续安全页。现逐候选在原target独占内实查专窗及完整空闲/已保存复用守卫，失败只阻断本target；每轮按target去重记录candidate_waits，下一轮重新实查。选中后仍重新获取独占和原提交锁，完整重复槽CAS、原材料/提示/关闭归档及真实复用守卫，不导航受保护页、不重发。新增三项真实回归覆盖首候选草稿、读取失败和独占占用，存在安全后备页时仅原URL读取可继续；19项原会话恢复回归通过。

原所有者实查所有可用候选的draft_sha256均为01ba4719c80b6fe911b091a7c05124b64eeece964e09c058ef8f9805daca546b（单换行），原健康流程已判healthy_blank/completed_saved。恢复专用守卫现仅将字符串strip后非空视作草稿；显式非字符串值保持阻断。只改变空输入判断，不清空输入框、不改原提示或科学文字，附件/上传/生成/验证/额度/未知及完整已保存复用守卫保持。21项定向回归包含原生换行空编辑器、完成页换行、不可读输入及文字草稿保护。

原回答晋升前的实时完整核对也复用_has_draft：空框原生换行不再阻断晋升；原回答完整字节、hash、唯一URL、实际提示与无生成检查仍全部保留。回归在副本完整收取时提供换行空框，确认原target/发送字段不变并只晋升原完整回答。

原会话材料守卫分别使用制卡包上级目录和核验账本同级版本目录，缺包不向父级或其他版本回退。核验原请求和观察器共用完整且唯一的材料标识比较，包含自动后继ID后缀；源文件、原卡片、逐文件输入、提示、唯一URL和原回执保护继续独立核对。

旧TTL移出恢复、无发送账本的明确原回答恢复和未发送草稿归属同样保留完整自动后继ID，不以24位基础前缀查找其他任务；原恢复权限、人工/版本保护、未知发送者字段和完整归档守卫保持。

原会话收取副账本经原身份/提示/完整关闭归档及页面归属核对后，同时供健康维护使用；终态空回答继续执行原一小时、两轮相隔30秒、唯一原提示/会话、完整归档及正常定槽替换守卫。恢复意图仅在原替换journal完成且副账本/历史hash一致后记为retired_empty，保留原请求和副账本原字节，answer_collected=false且不得重发，不把页面释放当作科学或生产完成。

健康盘点只对已验证副账本增加内存标识_collection_recovery，不改回执字节；非terminal_empty的副本继续由原观察器收取和原_promote处理，健康维护不修路径、不重绑paper_id、不发布或复用该副本回答。归档释放与科学成功分开。

原所有者的完整历史回执扫描使用本线程协作检查点：每约50毫秒让原Playwright事件循环处理观察、截图、超时和清理回调。后台索引线程不继承该回调；停止异常中止本轮扫描并保留证据，不以空索引继续派发。完整递归扫描、账本stat/hash核对、历史未知请求保护及实际发送前复核保持。检查点不在缓存锁内执行，退出时恢复原回调。

Archived-receipt resolution and retired-page evidence scans also use the owner-only cooperative checkpoint between read-only items. These checkpoints precede BEGIN IMMEDIATE; cache locks and lease write CAS never yield. Original byte/hash, unique-target, archive and active-upload guards remain.

Retirement archive verification is limited to a fresh snapshot of currently claimed targets whose pool entries are retired_replaced and have no active upload lease. Unrelated journals are skipped before diagnostic hashing and archived-receipt traversal; no retirement candidates means no journal traversal. The final write CAS still reads current claimed rows and retains all original guards. A claim arriving after the read-only snapshot is conservatively deferred. Per-page health evidence includes retirement_scan target/journal/verified counts and actual duration.

Claim recovery first uses a fresh read-only claimed-row snapshot as a negative candidate filter. Busy/unknown pages and retired claims without complete proof never request the SQLite writer lock. Eligible candidates use connection-local busy_timeout=0 before the original BEGIN IMMEDIATE; writer contention is recorded as claim_recovery.deferred_database_busy and deferred to the original owner's next normal pass, retaining original health/evidence instead of poisoning it as page_maintenance failure. The current-row write CAS repeats every original guard and only examines snapshot keys; new concurrent claims wait for the next scan. Actual lock wait is recorded, never clipped. No request resend, source-job/scientific mutation, retry reset or new owner is authorized. Two real SQLite contention regressions preserve original receipts/leases, then verify only an eligible original lease releases after the other writer exits.

已建立但借用页随整个浏览器关闭而消失的原回答收取意图，不再永久挡住后续收取。仅原所有者核对新启动请求链、旧完整20槽登记、同端点、两次相隔至少30秒的进程缺失/端点不可用证据和完整原回执后，归档旧proof/attempt/prompt原字节并标记retired_closed_browser。新窗口epoch使用独立副账本ID，重新沿原同队/共享空闲槽守卫读取唯一原URL；原模型请求绝不重发。同epoch未知导航、已有原回答、材料/提示改变或关闭证据不全继续保护。_retire_closed_browser只结束旧收取页面意图，不表示原请求结束或科学通过。 关闭证据的 request_id 必须按归档 request.json 的最近启动请求核对，并逐字重算包含旧 registry 的 identity；复用窗口时，它可与 registry.startup_request_id 的最初创建请求不同。初始化原专窗时保留已有关闭归档 registry.json 的原字节。

核验任务身份解析仅将固定标题“制卡与核验共用同一合同（card-review-standard-v3）：”视为规则版本元信息；未限定语境的同名词元、未知版本、第二任务及重复任务编号仍保留为冲突。原任务完整ID（含后继后缀）、实际提示完整指纹、target、唯一正式URL和稳定回答守卫不变。此私有修复同时作用于原观察器、健康核对与原会话恢复；没有新增浏览器、上传、发送或科学改判入口。回归覆盖真实合同文本及完整原回答保存。

2026-10-30: web_page_queue.MaterialProducer owns one local seed-evidence-tracker thread. _trace_seeds calls the existing core monitor every60 seconds, independently of long worker0 recovery/selection/preparation; material worker count and priority are unchanged. start/stop share the existing owner and stop event, join the inflight evidence unit, and never start a resident entry, process, CDP/browser or model channel. seed-tracking-worker.json records actual owner/thread/start/finish/duration/completed/failed rounds; errors remain in seed-tracking-error.json and retry at the normal interval. The monitor only reads production and preserves local evidence, including during pauses. Its heartbeat never changes qualified-material-v2 progress or grants send/requeue permission. The existing monitor file lock prevents concurrent trace writes. tests/test_web_page_queue.py proves three checks continue while material work is blocked, errors are retained before recovery, and stopping drains exactly one inflight check without overlap. This removes seed-trace starvation; historical recovery throughput remains separately open.


## 健康空闲页跨队借用（2026-11-06）

[本轮授权](../docs/authorizations/20261106-idle-page-lending.md)。`backlog.idle_borrow_enabled=true`时，`shared_page_idle(target_id, identity, idle_since)`在原Catalog记录完整盘点确认的ready/ready_blank空闲页。当前活动、未知领取、草稿/附件/上传、保护绑定及不完整盘点不能取得借用资格；页面材料/会话/状态身份变化重新计时，相同身份跨轮次/重启保留原时间。超过原健康配置中所属队P85实值后，先保留本队合法未领取待办所需页面，包括准备中材料，再将余页列入`reconcile.idle_borrow_targets`。原派发入口核对该资格，原固定身份和最低并行不变；原队有新工作时仅收回未领取绑定，已领取借用任务继续原页执行。原材料指纹、不可变到达次序及最终提交守卫继续生效。

当前助手/系统轮次状态节点（包括新DOM中无助手角色属性、但有独立activity-header/aria-live的当前活动头）精确显示“分析已暂停”等停止标记、无生成/上传/草稿/附件且原唯一请求一致时，busy状态也进入原terminal_empty流程；仍须原请求一小时、两轮30秒同证据及完整归档再换页，原请求不重发。没有明确停止标记的思考页继续保护。隔离回归覆盖计时持久化/重置、本队准备页保留、跨队实际派发、原队收回未领取、已领取保护及假停止提示；真实DOM测试使用无网络临时浏览器。

2026-11-10 从原归档 HTML 确认 ChatGPT 在会话当前轮次内以 `aside[role="alert"].text-danger` 显示“消息传输超时。请重试。”或“消息流中的错误”。健康快照单独记录当前轮次的这两种提示，仍以原请求指纹、唯一正式会话、无正文和原一小时、两轮实查、完整归档条件决定换页。侧栏、旧轮次、正文引用、未知提交和有截断正文的会话继续受原保护。维护盘点在处理待续归档之后取全量账本，移除其前一份未使用的全量扫描。

已归档修复续跑时，若账本原路径已被另一明确 target 的回执复用，只在唯一历史副本的字节指纹等于原账本时跟随原文件。原路径仍属同一 target 或历史副本缺失、不唯一时保留旧计划。路径迁移有前态和指纹记录，随后仍需完整盘点、槽位核对、归档及实时关闭守卫。

原收取归档的`_retirement`与原归档端对齐PNG/完整MHTML合同。只有缺PNG且存在原所有者resident_cdp_mhtml捕获记录、screenshot_available=false、foreground_changed=false、完整清单与journal逐项hash一致、MIME主地址及非空HTML部分均精确绑定原正式会话时才接受MHTML。错误URL、非完整清单、未知捕获方式及任何文件变化继续阻断；`retired_empty`仅终结原页收取意图，不是回答收取/科学成功，不许可重发。

2026-11-09 长提示输入与已保存槽位接续。原富文本输入在网页上可只留下首段。原所有者在同一富文本输入框内一次写入纯文本段落节点，等编辑器提交文档并逐词核对，再执行两次原完整提示DOM校验。富文本分支无需聚焦，保持原提交锁与实际模型校验。已保存回答仍标busy时，以完整target历史、明确终态、无生成/上传/草稿、原正式唯一URL、实际提示、实时原文及落盘hash证据恢复原槽；尚有未收请求或核验任务身份冲突时继续保护。原所有者在更新前重核完整历史账本CAS与实时证据。

[tests/browser_chat_only_upload_notice.py](tests/browser_chat_only_upload_notice.py)用隔离Chrome验证原中文资料库存储提示、已结算同ZIP、真实关闭按钮、附件隐藏保护及拒绝分支。原所有者只关闭唯一原生“文件仅添加到聊天”提示，先绑定本次已结算的ZIP及弹窗/输入区文件名，再走原模型、附件和完整提示校验。剩余存储空间提示只说明不保存到资料库，真实附件/账户额度仍按原通道控制处理。健康读取保留被弹窗遮住的原附件名称，带附件的未发送恢复同时核对原提示与ZIP。

[formula_only.py](formula_only.py) 为已安装的任务面板保留原公式启动与暂停命令。OLED 行间公式整理的实现、接口和运行说明见[独立项目](../../../tools/oled-formulas/oled_formulas/README.md)。专用窗口、槽位归属、提交锁和浏览器维护仍由本组件提供。

[网页附件与回答收取](web_card_transport.py) 通过同一只读判据检查 ZIP 上传入口、可见额度和禁用菜单，按包实际体积选择上传等待时间，使用 IncompleteWebAnswer 表示原回答尚待收齐。

模型配置的 temporary_home 参数供原 OLED 所有者在显式临时聊天首页使用。首页无模式切换按钮时，核对原生 Chat 菜单无障碍名称，仍需实际模型和 High 复读。

公式模式的账户复核识别来自原专窗的再次登录提示。已成功核对的旧记录字段仅在完全匹配本地历史格式时识别，仍逐页确认实际登录并等待两次新鲜检查。
