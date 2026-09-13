# SQLite read compatibility

Issue #436 remains open. This checkpoint connects transaction reads and the `query`
command; it does not establish parity for every consumer, export, or arbitrary SQL.

`RepositoryReader.transaction_snapshot()` materializes current transaction columns,
exact amount/confidence text, provenance-bound original aliases, and canonical rules
bytes from the same validated snapshot. Persisted manual/final classifications and
visible tag arrays are not recomputed. UUID `transaction_id` is separate from legacy
`row_hash`; duplicate aliases retain separate rows, ambiguous aliases are null, and
native records without legacy aliases expose null aliases rather than fabricated IDs.

The authority-aware read facade requires independently supplied activation evidence.
It takes a shared cutover lease while copying the selected generation and rejects a
snapshot older than activation. Validation errors never authorize CSV fallback.
Readers use the existing side-effect-free DB/WAL snapshot machinery; concurrent
changes during capture can produce an explicit retryable inspection failure rather
than a mixed-revision result. The returned data stays pinned after the live revision
changes.

DuckDB registers an Arrow relation made from this snapshot. Compatibility amount and
confidence use the existing Polars Float64 display contract, separately from canonical
exact values. `amount_coefficient`, `amount_scale`, and `amount_lexical` remain queryable;
Float64 aggregates are not advertised as exact accounting totals. Values outside the
finite display range fail explicitly. Valid date columns support DuckDB DATE functions;
invalid/raw date text is retained as text. This does not promise identical inferred SQL
types for every historical CSV input.

`query` reads report filters from the pinned canonical rules bytes. Local `rules.yaml`
or compatibility CSV edits cannot alter an activated query. A head marked invalid/opaque fails even when its bytes are valid YAML; malformed
filter syntax also fails. Neither case falls back to another copy. `--no-filter` keeps its explicit bypass.
Repository JSON metadata includes authority, generation, revision, schema and
`legacy_transaction_display.v1`; ordinary legacy output is unchanged.

Manual note edits on migrated rows also preserve original tag spelling, duplicates,
and blank members. This parser exception requires a migration identity and matching
payload/provenance/observation occurrence; native writes keep the canonical parser.
Note-only no-ops and replay receipts report the stored state. Explicit tag/category
requests retain the existing normalization and derived-classification behavior.

A separate installed probe still reproduces rejection of migrated duplicate tag arrays
in bulk tagging. Bulk tagging/transfer representation, preview and replay must be
verified and completed before operational activation. The note-only correction does
not establish bulk support.

Current limitations: other CLI/analysis consumers still need evidence injection and
repository reads; overview/asset read projections, generated exports with revision
manifests/stale identification, partition-pattern repository reads, and complete
human/JSON/SQL parity remain #436 work. SQLite activation and actual corpus memory,
performance, preservation and operational recovery remain separate acceptance gates.
