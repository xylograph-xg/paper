# Queue and upload bottleneck observation

Shanghai: 2026-10-16T14:29:46.525916+08:00

Queue display combines unprepared, preparing and ready-but-unclaimed tasks. Grid rows 2-5 are always assignment queues. Ready jobs are not necessarily upload-eligible now: target availability, ready head binding, lane guards, channel permission and global upload credits are independent gates.

Latest backlog: {"last_reconciled": 1792132167.814452, "current_tasks": 4, "queued_tasks": 80, "ready_queued_tasks": 35, "preparing_queued_tasks": 45, "paused_queued_count": 0}. Observer page states: {"idle": 15, "complete": 1, "generating": 4}. Verified generating slots: ["08", "09", "10", "15"].

Three old-window retained upload credits persist. Together with a current callback or recently finished retained callback, they can fill the five-credit limit without five native transfers. release_observed waits for a later qualified health snapshot; missing old targets cannot release themselves. Do not clear them based only on missing-page evidence.

The main loop selects at most claim_order[0] per cycle; health, receipt, preparation and reconciliation work precede the next admission. This is a source-confirmed throughput constraint, not a new measured per-function profile.

A new concrete size incompatibility was observed: ZIP 54,849,064 bytes (52.31 MiB) was rejected by the current set_input_files/CDP path at its 50 MiB threshold at 14:23:55. Existing package policy permits under64,000,000 bytes, so it can prepare bundles this transport cannot accept. This is separate from network/protocol failures. The current check does not attribute every historical write_failed to this cause.

Required repair directions: journaled old-credit lifecycle settlement; faster admission independent of long maintenance; align package budget with verified transport capability for new materials, retaining frozen inputs and unknown-request guards; distinguish waiting preparation, ready waiting and uploading in status counts. No production repair or control changes were made in this read-only check.
