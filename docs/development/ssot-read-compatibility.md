# SQLite read compatibility

Issue #436 remains open. This checkpoint connects transaction reads and the `query`,
`template run`, and `show` commands; it does not establish parity for every consumer, export,
or arbitrary SQL.

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

`query` and `template run` read report filters from the pinned canonical rules bytes.
Local `rules.yaml` or compatibility CSV edits cannot alter an activated query. A head
marked invalid/opaque fails even when its bytes are valid YAML; malformed filter
syntax also fails. Neither case falls back to another copy. `--no-filter` keeps its
explicit bypass.
Repository JSON metadata includes authority, generation, revision, schema and
`legacy_transaction_display.v1`; ordinary legacy output is unchanged.

Manual note edits on migrated rows also preserve original tag spelling, duplicates,
and blank members. This parser exception requires a migration identity and matching
payload/provenance/observation occurrence; native writes keep the canonical parser.
Note-only no-ops and replay receipts report the stored state. Explicit tag/category
requests retain the existing normalization and derived-classification behavior.

Bulk tagging and transfer reads use the same source-backed preservation boundary.
The stored before-state is compared as evidence; proposed derived writes still use
the canonical validator. Explicit retagging recomputes derived fields while retaining
manual/AI/source fields. Transfer recomputation changes only transfer fields and
preserves unrelated classifications and tag arrays. Actual migration regressions
cover preview, apply, audit, no-op and replay, including duplicate and blank members.

Template execution resolves filters after opening its transaction snapshot. Ordinary
SQL and dynamic pivot discovery/aggregation use that same pinned authority and rules;
JSON metadata carries its revision alongside existing template metadata.

Current limitations: other CLI/analysis consumers still need evidence injection and
repository reads; overview/asset read projections, generated exports with revision
manifests/stale identification, partition-pattern repository reads, and complete
human/JSON/SQL parity remain #436 work. SQLite activation and actual corpus memory,
performance, preservation and operational recovery remain separate acceptance gates.

## Show partition scope

`show` uses `legacy_partition_scope.v1` alongside the transaction display policy.
Migrated primary `data` root files matching `transactions/YYYY/MM/transactions.csv`
contribute their original month, even if row dates disagree or are invalid. Empty
captured files participate in latest-month selection. This scope is proven through
transaction/observation/source migration identities and matching provenance evidence.
Other captured roots and nonstandard paths remain preserved and queryable through
`query`, but do not enter the primary legacy `show` partition scope.

Native records use the calendar month of a valid observation `effective_at`, without
timezone conversion. Records with unknown or invalid effective dates are unpartitioned
and remain visible in all-scope searches (`--tag`, `--untagged`, or `--merchant` without
`--month`). Bare `show` selects the latest known month and `--month` selects that scope.
A dataset with only unknown-month records therefore needs an all-scope search.

Source-backed CSV record ordinals restore original row order before the existing
show sorting stages; all-scope reads retain the legacy preliminary ascending datetime
sort. Equal-time transactions therefore keep the same page order as the CSV reader.
Native ties start from stable transaction UUID order.

The scope sidecar and empty-partition inventory are detached in the same reader
snapshot as rows and canonical rules. Scope fields are internal; JSON adds the scope
policy and revision metadata. Tag arrays are decoded for filtering, and the existing
JSON sentinel-stripping/deduplication display behavior remains unchanged. No stored
classification, date, or tag array is rewritten. A future native correction that
reuses a migrated source occurrence must define its scope contract explicitly; the
current importer always creates a new native occurrence, and mixed migration proof
never authorizes a guessed native-month fallback.

## Explain stored state and rule simulation

Activated `explain` searches transactions and loads canonical tagging rules from one
validated snapshot. It retains the non-interactive JSON and `--pick` selection
contract, identifies native rows by transaction UUID, and never applies report
filters to its search. Invalid/opaque canonical rules cannot be bypassed with
`--no-filter`; an unavailable or invalid activated repository never falls back
to CSV.

JSON separately reports `stored_classification` (manual/rule/final categories,
rule/AI/manual/final tags and manual notes) and the current rule simulation.
`classification_basis=current_rules_simulation` and the metadata policy
`current_rules_simulation.v1` identify that calculation. Human output labels both
sections. The simulation uses the complete raw row, including exact amounts reconstructed from canonical coefficient/scale
values, while the selected transaction retains the legacy Float64 display contract.
It does not mutate stored classifications or normalize preserved tag arrays.
Internal manual-category marker tags are omitted from the displayed manual tags.

Enabled condition rules participate in both matching and the trace. Invalid enabled
regex fails without exposing its pattern; disabled regex rules remain ignored.
Unknown rule-field warnings report only their count, not rule labels or field names.
Empty rules and no-match results retain the same revision and calculation metadata.

Compatibility boundaries: the existing `classification.category` fallback may show
the stored final category when no rule supplies a category; `category_rule` identifies
a simulated rule category. Same-date candidates use stable UUID order, not captured
CSV row order. Date filters use `date_raw`, not a guessed observation calendar date.
Explanation matching exposes more row fields than the current bulk-tagging adapter;
these paths do not yet promise identical results for every arbitrary field condition.
Text operations on amounts see the canonical exact representation, not necessarily
the original lexical spelling.
