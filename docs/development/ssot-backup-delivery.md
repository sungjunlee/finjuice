# Committed records and filesystem backup delivery

`ssot backup deliver status` compares one observed source snapshot with a single
verified graph in each explicitly selected store. `pending_commit_count` counts
source commits missing from either required lane, including no-op receipts and
associated audit facts. It is `null` when either comparison is unknown or fails
verification. Neither dataset revision nor a journal success substitutes for
reading the current verified graph.

`ssot backup deliver run` captures when needed, copies the graph, verifies the
receiver bytes, publishes the graph, and records durable stages outside the
financial database. A nonzero exit is a backup job failure. It does not undo an
already committed domain mutation. Retry the same worker to rediscover actual
local and receiver coverage; the journal preserves previous verified success
separately from failed attempts. Lost or inconsistent history is unknown.

For a manual transaction edit, explicitly pass `tag --edit <transaction-id>
--delivery-config <absolute-config-path>`. The JSON configuration requires
absolute paths for `expected`, `sender_store`, `destination_store`, and
`control_dir`. To permit capture, also provide all four of `wheel`,
`dependency_lock`, `binding`, and `migration_candidate`. Both stores must have
been initialized against the independently retained expectation. Use a separate
control directory outside the source and both stores. Destinations are never
inferred from ambient state and no shell transport is supported.

The edit first obtains its real durable mutation receipt, then runs delivery.
Human output and the additive `backup_delivery` JSON field report delivery
failure while retaining the edit's successful exit and committed receipt.
Immutable stored `result_json` is unchanged. Repeat the same idempotency key to
replay the original edit and retry delivery without making another domain commit.
The delivery option is rejected for legacy, inspect-only, bulk, or dry-run edits.

Receiver staging directories use private unique names beside published graphs.
A failed ordinary copy cleans up only its own staging tree; unknown or interrupted
staging is retained and never adopted as a healthy copy. Initial registration
begins after the copied graph verifies. Once registration begins, loss or failure
of the baseline registry remains fail-closed and requires a new store; the
started marker and any published graph remain available for diagnosis.

A mounted/local filesystem receiver proves destination verification only. Actual
scheduler registration and first run, independent off-device placement and key
recovery, and measured recovery objectives remain separate operational evidence.
