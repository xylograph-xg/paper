# Read-only parallelism diagnosis

Captured Shanghai time: 2026-10-16T14:23:32.685913+08:00

Generation capacity remains 20 fixed pages shared across all three lanes. Each internal lane limit remains 20. Upload admission remains 5, authorized on 2026-10-11. Commit 6300efc did not lower generation capacity to 5. Current persisted minimums are cards=8, review=8, correction=1; these are current controls, not the default 8/4/3.

Final fresh page counts: {"idle": 15, "complete": 3, "generating": 2}. Verified generating slots: ["09", "10"]. Complete state does not establish complete collection or scientific acceptance. Slot 04 had a state-read timeout during the earlier sample and was complete in the final sample. Observer age: 2.924 seconds.

Final main status age: 3.449 seconds. Final actual generation count: {"cards": 1, "review": 1, "correction": 0}. Submission channel allowed: True. Final upload budget: 4/5, consisting of 1 unfinished submission callback and 3 retained entries. Callback count does not prove live byte transfer.

Earlier at 14:20-14:22 the latest main status (14:17:33) recorded budget 5/5 with four retained entries. By 14:23:29 it refreshed, slot 13 had been released and another callback admitted. Three old retained targets remain outside the current window; their last uploads ended with settlement timeouts at 13:47:49, 13:47:57 and 13:50:21. They consume three of the five admission credits, leaving at most two for current submissions. Missing pages alone cannot establish unsent requests or authorize clearing retained credits.

Code release_observed requires a newer no-upload snapshot of the exact target, or a confirmed original-owner replacement receipt. Old targets without such terminal evidence retain global upload credits after a window change. Recovery needs original-owner journaled settlement with request protection; raising the upload cap or clearing missing targets would bypass evidence guards. This check identifies the retention path but does not claim closure/unsent evidence sufficient for release.

The main status was 175-262 seconds behind a fresh observer during earlier samples, then recovered. This is an observed long main-loop interval, not a currently stale status or proof of a specific blocking function. No Python stack was captured.

Recent natural upload cohorts, grouped by start time: [{"minutes": 15, "started": 4, "native_upload_ok": 3, "failure_kinds": {"TimeoutError": 1}, "unfinished": 0}, {"minutes": 60, "started": 12, "native_upload_ok": 7, "failure_kinds": {"settle_timeout": 4, "TimeoutError": 1}, "unfinished": 0}, {"minutes": 120, "started": 42, "native_upload_ok": 27, "failure_kinds": {"settle_timeout": 11, "write_failed": 3, "TimeoutError": 1}, "unfinished": 0}]. Native upload success is separate from send, answer collection and scientific acceptance.

Only original-owner public files were read. No CDP connection, page operations, controls, queue mutations, production edits or pause changes.
