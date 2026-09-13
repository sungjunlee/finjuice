# SQLite read compatibility

Issue #436 remains open. The checkpoints below connect canonical transaction, portfolio,
analysis and export reads; they do not establish parity for every consumer, historical
input shape, or arbitrary SQL.

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

Current limitations: remaining validation and diagnostic consumers still need canonical
read coverage, and complete human/JSON/SQL parity remains #436 work. The later sections
record the connected portfolio, partition, analysis and export consumers. SQLite activation
and actual corpus memory, performance, preservation and operational recovery remain
separate acceptance gates.

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

## Repository exports and receipts

Activated `export` reads one validated snapshot for the full master/transaction CSV
and the canonical-filtered reports. Invalid/opaque rules heads fail; `--no-filter`
is the explicit report-filter bypass. HTML/Markdown apply `--period`, while master
and the full transaction CSV remain unfiltered, including under `--format all`.
Dry-run uses pinned counts and describes `exports/runs/<new-run>/` without writing.

Each successful run is published by one directory rename beneath `exports/runs/`.
It contains only newly generated artifacts and `export-manifest.json`; previous
runs and legacy dated outputs are not overwritten or reused for empty results.
Empty master/report outputs are explicitly skipped, while `transactions.csv` still
has its schema header. A failed run removes staging and leaves earlier runs intact.
Active import/refresh now execute this export step and retain preceding mutation
receipts if export fails.

Repository master and transaction CSV keep legacy column order then append UUID,
manual category and exact amount evidence. Hidden manual-category marker strings
remain internal; the explicit manual category represents their meaning. Visible tag
spelling, duplicates, stored final classifications and manual notes are retained.
CSV tags use JSON and spreadsheet formula neutralization remains enabled. These
are derived display artifacts, not a lossless source reimport protocol.

`legacy_export.v1` fixes the calculation basis to the latest valid raw transaction
date, or null for an undated dataset. Date suffixes and report header timestamps use
this basis instead of the wall clock. XLSX creation/ZIP metadata, Plotly IDs and tie
ordering are stable. Equal input revision/options and the same renderer environment
reproduce identical artifact bytes, including after the wall clock changes. Reports
retain legacy Float64 calculations; exact amount evidence is separately exported,
not claimed as exact aggregate accounting.

The manifest links every file digest and byte count to generation, revision, SQLite
schema, read/calculation policy, calculation basis and export options. Keep this
receipt with the report files. `export-verify MANIFEST --json` validates bounded
relative paths, rejects symbolic-link escapes, and compares the receipt with a fresh
validated repository snapshot. `stale` describes the data identity comparison;
`integrity` independently reports modified/missing declared files; extra files are not assessed. Checks do not rewrite
artifacts or trust compatibility CSV. A local receipt is not authenticated: coordinated
edits to both receipt and files cannot be detected as tampering by its own hashes.

Later sections record status, portfolio and checkup integration. Remaining runtime
consumers, private corpus parity/performance and operational cutover retain their
separate #436/operational gates.

The verified CLI runtime uses the project's locked Typer/Click versions. An
unconstrained installation of Typer 0.27.2 changes its command class hierarchy and
breaks the existing Click-based runtime manifest discovery. Operational deployment
must retain the verified lock versions until that separate dependency compatibility
work is completed.

### Repository status and detailed insights

Activated `status` and `status --detailed` select transactions, partition scopes,
canonical rules/goals heads and import provenance through one validated reader.
They never use a live CSV, rules/goals file, import-history file or second analytics
reader. The legacy branch keeps its existing CSV diagnostics. Empty repositories
remain valid status inputs. Stored classifications, tag arrays and notes are not
rewritten by status.

JSON metadata identifies generation/revision/schema and `legacy_status.v1`.
`calculation_as_of` is the latest strictly valid source date, or null. Basic counts
honor canonical report filters, while additive `source_counts` identifies all
stored rows, primary-scope rows, out-of-scope rows and unknown-month rows. Month
counts retain proven empty partitions. Detailed date range retains the legacy
unfiltered source range; its financial metrics use the same canonical filters.
Detailed `active_filters` counts configured filters, while `_meta.filters_applied`
counts filters matching at least one row.

`rules_file` remains a compatibility key: for repository authority its path is
null and its revision/status/update time describe the canonical head. Missing,
invalid and opaque rules remain diagnostic states. Invalid/opaque rules reject
filtered collection; explicit `--no-filter` permits full counts but does not
clear the critical diagnosis. Invalid canonical goals produce an explicit
recurring-savings warning without reading a live replacement; human and JSON
outputs retain the available transaction statistics alongside that warning. SQLite schema
status never suggests CSV migration or `finjuice init`.

Import occurrences distinguish completed native imports, migration captures and
unproven origins. A capture timestamp is never a user import timestamp. Proven
primary `metadata/import_history.csv` records remain separately available from
preserved row provenance. `native_then_legacy_lexical.v1` selects a completed
native import when present; otherwise it follows the legacy timestamp-string
sort over preserved history. Native imports are post-baseline operations, so
unknown-timezone legacy timestamps are not converted or compared to native UTC
clocks. Native occurrence UUIDs remain separate from legacy file IDs; history
rows expose their provenance instead of claiming the capture occurrence was the
original import.

This status checkpoint preceded the portfolio and checkup integrations below.
Doctor and full private-corpus parity remain separate acceptance work.


## Portfolio snapshot evidence

`RepositoryReader.portfolio_snapshot()` and `read_portfolio_snapshot()` detach
portfolio tables from one validated generation/revision. The facade uses the
same independent activation evidence and shared lease as transaction/status
reads; only legacy authority returns `None`. Closed readers fail explicitly.

Asset observations, native overview facts/reports and the five legacy reported
overview domains remain separate source tables. Exact coefficient/scale/lexical
values, quantity/money/rate types, provenance and original aliases remain linked
by their stored IDs. A legacy alias never replaces a UUID. Reference candidates
and missing/unverified/ambiguous assessments are evidence, not verified fact
links. Ownership assertions/shares and directly related entity assertions are
preserved without applying a new ownership or aggregation policy. Unrelated
relation endpoints can remain ID-only as documented by the DTO.

Evidence includes portfolio file scopes, including empty/opaque partition
sources and extra capture roots; transaction-only payloads are excluded.
Selection or aggregation across roots belongs to the future consumer policy.
Native exact values retain their separate cell provenance. Source-backed raw
payloads and account/resource records remain available to later display adapters.

Assets/goals/scenarios configuration has an explicit `selected`, `unselected`
or `absent` state. Selected bytes are object-hash verified and retain parse
status. An unselected preserved revision is never treated as an empty financial
configuration and never triggers live YAML fallback. A consumer must validate financial
configuration semantics before calculating. Frozen older migration policies
are not rewritten to fill their missing heads.

Schema4 reports expose `preserved_observations_only` with preserved observation
and payload evidence; schema5 exposes typed reported tables. Unsupported typed
reports are distinguishable from a supported empty table. The support field
asserts schema capability only, not materialization completeness: upgrading an
older candidate adds empty schema5 tables without converting preserved report
observations. Consumers must inspect unmatched preserved observation evidence
before treating empty typed tables as no report data. This storage
checkpoint alone does not establish CLI parity; subsequent consumer sections
record that work. Combined status/portfolio calculations require a single reader
bundle rather than two independent facade reads.


### Portfolio display and current net worth consumers

`assets status`, `assets show`, `assets balance`, `networth`, and `networth
breakdown` select authority once and calculate from a detached portfolio snapshot.
Active reads do not reopen CSV partitions or YAML configuration. JSON metadata
identifies the generation, revision and display/calculation policy; human output
also identifies the pinned source. Asset holdings keep legacy display values
alongside canonical IDs and exact coefficient/scale/lexical values.

`legacy_portfolio_display.v1` uses primary data-root partition paths and source
row order, retaining empty months. Auxiliary capture roots remain evidence and
do not enter these totals. Native rows use valid snapshot-date months and UUID
order, with explicit native identity labels where no legacy alias exists.
Raw asset commands retain latest-partition behavior; net worth searches backward
past empty months, filters by the requested date, and preserves reported-balance
precedence and manual normalized-name overrides. This is a compatibility policy,
not a new ownership allocation or currency conversion policy.

Net worth validates the selected assets configuration bytes semantically.
`selected_assets_config.v1` rejects invalid or opaque selections. Only an explicit
`absent` state with an empty revision inventory permits the legacy empty manual
configuration (`canonical_absence_empty.v1`). A missing head alone is insufficient:
old-policy unselected revisions and alternative preserved copies fail closed.

Preserved primary rows without typed display values raise a static error rather
than disappearing from totals. In particular, legacy CSV reading tolerates some
incomplete balance headers that frozen migration policies preserve as opaque.
The parity fixture uses the producer's complete nine-column report schema; a
separate regression verifies the incomplete-header rejection. Private-corpus
compatibility for such inputs remains an open preservation/consumer gate.

The combined checkup integration below obtains status and portfolio inputs from
one reader bundle.
No private operational migration or activation is established by these tests.


### Portfolio history and forecasts

`networth history` uses the same detached portfolio source under
`legacy_networth_history.v1`. It visits primary partition months in reverse order,
skips empty months, selects each month's maximum snapshot date, takes the requested
number of available points, then reverses their order. Path months are not replaced
with row-date months. The current selected manual assets and liabilities apply to
all points; historical configuration revisions are not retrospectively selected.
Balance reports and the parent date option do not enter the legacy history result.
Unrelated opaque balance reports therefore do not prevent asset-only history.

`networth forecast` uses `legacy_networth_forecast.v1` with a single detached
portfolio for its starting position, scenarios and goals. It preserves as-of
selection, balance precedence, single/all scenario output and lifecycle calculation.
Scenarios must have a selected, parsed, semantically valid canonical document
(`required_selected_scenarios.v1`). Goals are also fully validated, rather than
reading only the target field. Only explicit absence with an empty goals revision
inventory permits no target (`canonical_absence_no_target.v1`); unselected,
opaque, invalid and alternate-only configurations are not treated as absent.

The byte validators and pure forecast calculations never reopen live files.
Human output and JSON metadata identify the revision, policy and as-of date; JSON
also records configuration selection policies. If a config changes after the
read, the existing result stays pinned and a new read observes the later revision.
Missing start dates still require source observations or an explicit forecast date.
Active configuration/calculation failures use static errors without parser content.


### Combined checkup revision and staged observations

Activated `checkup` obtains transactions, scope, status, portfolio, configuration
selection inventories, exact-import identities and requested verified completion
lookups through one reader. Every canonical domain uses that detached revision;
Python bundles expose `repository` metadata and CLI output places it in `_meta`.
Legacy bundles retain their original shape. `legacy_checkup.v1` preserves the
latest partition month for review and budget, including an empty latest month,
and computes net worth from snapshots and current manual assets without balances.
Unknown-month included rows contribute to all-row metrics without inventing a
partition; auxiliary source rows remain excluded.

Invalid or unselected goals explicitly make budget invalid, the net worth target
unknown and obligation confirmation unavailable. Invalid assets retain an invalid
net worth diagnosis. Rules must supply valid selected filters and notes; unusable
canonical evidence fails with a static error instead of falling back to live files.
Explicitly absent configurations remain distinguishable from preserved unselected
revisions. Fast mode explicitly skips the full review and obligation detectors.

Staged XLSX bytes are captured before the reader opens and are separate filesystem
observations, with observation times and aggregate metadata. A missing imports
directory is an observed absence; other inventory failures fail closed. Each file
is previewed independently against the same baseline (`independent_baseline.v1`),
not against simulated prior files. Only verified exact-import completion is a noop;
legacy filename/history evidence and unverified overlap do not establish completion.
New evidence-only or empty workbooks still count as pending. Per-file capture and
mapping failures are counted; invalid canonical completion evidence fails the whole
checkup. Preview never writes objects, transactions or revisions. Fast mode counts
staged names as unexamined pending files and does not open workbook contents.


### Standalone budget, validation and review

`budget status` and `review` read a minimal analysis bundle containing transactions
and rules/goals selection inventories from one reader. They do not run checkup or
load portfolio tables and import preview identities. Their calculation policies
are `legacy_budget_status.v1` and `legacy_review.v1`, with revision, calculation
month/as-of date and selection metadata. Active goals descriptors use `path=null`
plus canonical authority/selection/revision; legacy filesystem paths remain strings.
`budget validate` validates those selected canonical goals with
`canonical_goals_validation.v1`, including explicit invalid, absent and unselected
states. Human output identifies the canonical source instead of printing `None`.

The standalone calculations deliberately retain their own legacy meanings. Budget
excludes confirmed transfers and shared non-consumption patterns, uses raw tag
strings, projects the legacy CSV null literals (empty string, `NA`, `NULL`)
without modifying canonical evidence, preserves the null category fallback,
chooses the partition path month,
and loads filters lazily only for a present partition. `--no-filter` remains an
explicit bypass of report filters. Review preserves default/untagged/confidence
predicates, their AND combination, sorting and original row hashes. Explicit month
selects a partition and then filters row dates; implicit latest month selects only
the partition. Review does not apply report filters. Its JSON privacy and pagination
retain their existing behavior and include repository metadata in `--max-bytes`.

Review notes use the same selected canonical rules bytes, only when matches exist.
Invalid/unselected notes leave transactions available with a static warning in JSON
metadata and human output. No live rules fallback or global logger toggling occurs.

Preserved primary transaction CSV evidence without corresponding typed transactions
must not masquerade as an empty or complete result. The analysis snapshot records
affected months for unmaterialized row observations, preserved opaque ragged or
duplicate-header rows, and file-level CSV parse failures. It verifies primary source,
capture, locator and provenance associations. Auxiliary roots and normal header-only
empty partitions do not trigger this guard. Budget/review fail for affected selected
months (review all-history checks all months); checkup fails for any such month.
Unrelated complete months and goals-only validation remain available. This guard
does not convert unsupported legacy records, relax frozen migration policies, or
establish full private-corpus parity. The next section records the shared boundary
for other transaction reads; operating activation remains gated.

## Incomplete transaction evidence

The transaction snapshot carries the proven primary partition months containing preserved
CSV evidence that has no typed transaction. Rows, scope, this inventory and the revision
identity come from the same reader. Analysis and checkup reuse that inventory rather than
opening another reader or repeating its query. Opaque source bytes remain preserved.

Consumers check completeness after choosing their scope and before returning empty or
filtered results. Query/template execution, status, explain and export require complete
transaction evidence across all primary partitions. SQL predicates and export periods
filter row dates and cannot prove a narrower source-partition scope. `--no-filter` does
not bypass completeness. Show checks its selected partition month, or every month for
an all-scope search; a different incomplete month does not block an explicit complete
month. True empty partitions keep their existing behavior.

The read facade still returns diagnostic evidence. `export-verify` compares a saved
receipt's revision and artifact bytes without aggregating transactions, so it remains
available with incomplete evidence. An intact receipt is not a transaction-completeness
claim. Failed exports must leave previously published artifacts unchanged. Static public
errors do not expose the preserved row contents. Supporting every opaque historical
record as a typed transaction remains a separate acceptance requirement.

## Canonical assets configuration setup and validation

`networth validate` inspects selected canonical assets bytes from one portfolio snapshot.
The JSON descriptor has a null file path and explicit authority, selection state and config
revision; metadata identifies `canonical_assets_validation.v1`. Explicit absence remains
valid because net worth can use imported asset snapshots without manual configuration.
Preserved but unselected settings are not absence. Invalid or unselected settings produce
static issues rather than parser excerpts or financial values. This configuration-only
check remains available when transaction evidence cannot be projected completely.

`networth init` now supports repository authority. A genuinely absent config is initialized
with version 1 and empty manual-assets/liabilities lists, after semantic validation. It does
not put the legacy example file's fictitious holdings into a canonical ledger. The mutation
uses the observed generation and revision as concurrency preconditions. Existing selected
settings, invalid settings and unselected preserved revisions are never overwritten, and
repeating initialization does not create another revision. A concurrent write causes a
static failure instead of being replaced. Successful output carries the committed revision
under `canonical_assets_initialization.v1`; no live assets.yaml is created or edited.

Legacy initialization still creates its existing example file, and legacy validation keeps
its file diagnostics. Initialization registers structure, not actual family holdings; actual
manual asset input and ownership facts must come from the user or verified source evidence.
These changes do not establish full private-corpus parity or authorize operating activation.

## Canonical rules diagnostics

`rules validate`, `rules test` and `rules gaps` pin their canonical inputs to one analysis
snapshot. JSON metadata identifies the source revision and calculation policy, and human
output identifies repository authority. Edited live rules or transaction CSV cannot change
these activated results. They do not apply rule changes or retag stored transactions.

Validation keeps strict first-error and default collecting behavior. The collecting bytes
loader normalizes float metadata while retaining exact numeric condition lexemes. It
collects errors at their original YAML indices before priority sorting; invalid rules are
excluded from the passed subset. Explicitly absent rules keep the missing-rules error,
while unselected or non-parsed selection evidence cannot become a valid configuration.
Configuration-level errors are not counted as extra rules. File-level parser failures and
invalid-rule details use static public errors rather than source excerpts. Valid-subset
conflict and informational diagnostics retain their existing meaning. In particular,
substring match patterns are not forced to become regex patterns. Invalid actual regex
conditions are diagnosed and cannot reach the matching engine's raw-pattern warning.
Configuration validation remains available with incomplete transaction evidence.

Rule testing keeps the existing matcher, default all-history scope, explicit path-month
selection and separate row-date month distribution. Cross-tag counts use tags_rule, while
samples show tags_final. Sample limit zero still computes complete match counts. The
selected rule must be usable, and the selected transaction scope must be complete before
an empty result can be returned. Report-filter bypass does not bypass these requirements.

Gap analysis compares stored tags and source categories without reevaluating rules, so an
invalid rule config does not prevent this analysis. Gap analysis and coverage simulation
share one detached frame. Merchant classification keeps the first row's tags/category,
amount impact is abs(sum(amount)), and missing merchants still participate in the coverage
denominator. Existing actionable filtering and human/JSON option meanings are retained.
Canonical output breaks equal-count merchant ties by name; the legacy file wrapper keeps
its existing order. Saved canonical reports include generation, revision and policy. This
stable ordering makes repeat reports from one revision deterministic without changing the
classification or arithmetic. Failed incomplete reads do not publish a report.

### Canonical rules list and export

`rules list` and `rules export` select rules and their original bytes from one
repository snapshot. They do not require a complete transaction projection or
evaluate rules. The existing six-field JSON/list projection and guide formatters
remain unchanged; a selected configuration must be marked parsed and satisfy the
rule schema. Execution-specific regex validation remains in `rules validate`.

The `legacy_rules_export.v1` metadata identifies the dataset generation, revision,
and rules revision. Human output also identifies the repository revision. YAML
files preserve the captured bytes, including comments, scalar spelling and line
endings. They do not receive an embedded metadata header. A standalone copied
file has no receipt-based freshness proof; JSON/human provenance is not a claim
that standalone artifact verification is complete.

Existing empty-rule and JSON option behavior remains: human empty exports do not
write a file, and JSON ignores the human format/output options. Active nonempty
human exports and gap reports use atomic output replacement. Destinations in the
configured control/generation, imports, transactions, metadata, assets and
Banksalad input directories, or the four configuration files, are rejected,
including resolved symlink aliases and relocated authority/generation roots.
Reserved-path comparison ignores case and Unicode normalization differences on
all filesystems, including case-sensitive ones. A hardlinked output is replaced without
editing its original inode. Normal external paths and the exports directory
remain available. Legacy file-authority behavior is unchanged.

Canonical gap guidance points to `rules add --help`; it no longer recommends the
active-fenced `rules suggest --apply` command.


### Canonical rules suggestions and merged read helpers

`rules suggest` uses one detached canonical analysis revision for primary/native
transactions and selected rules. Auxiliary captured rows are outside this scope;
incomplete primary projections fail closed. Selected rules must parse; genuinely
absent empty rule inventory means no existing rules. Coverage, merchant context
and tagged-neighbor queries share one in-memory connection. Existing scoring,
transfer exclusions and ambiguous merchant cluster behavior are reused without
report filters. Nonfinite aggregates are rejected rather than replaced with zero.

Metadata uses `legacy_rules_suggest.v1` and includes the selected rule revision.
Canonical `--apply --dry-run` is read-only with `rules_file: null`; actual suggestion
application remains fenced. Human next steps point to supported rule creation.
Saved human reports include provenance and use the protected atomic output helper.
JSON keeps ignoring the human output path. Redacted JSON masks nested rule notes
because generated notes may contain merchant names; raw and compact behavior is
unchanged. This applies to CSV suggestions as well.

PR500's explicit-path compatibility helpers remain available for their bounded
projection tests. `FINJUICE_SQLITE_GENERATION` does not select CLI authority:
`show` and `status` retain activation-evidence verification and pinned snapshots.
An unrelated generation cannot replace either canonical or legacy selected data.
The helpers' row-date month projection is not the canonical source-partition
scope policy. Full #436 consumer and operational acceptance remains open.


### Canonical one-shot automation

`automation run` captures staged XLSX bytes once, then reads one checkup snapshot
for canonical transactions, selected rules and import-completion evidence. It
projects primary/native transactions with the same null/scoping policy as rule
suggestions; semantic validity of unrelated goals does not block these signals.
Incomplete transaction evidence, invalid/unselected rules, missing activation
proof and nonfinite amount cells fail with a static error instead of clear zeros.
Tagging and large-transaction calculations reuse existing SQL/projections and the
normalized transfer view. Threshold zero keeps its existing disabled meaning.
The command performs no import, rule application or scheduled workflow execution.

`legacy_automation_signals.v1` identifies the dataset/rules revision. Thresholds
remain runtime configuration; staged files have separate observation timestamps
and `independent_baseline.v1` metadata. Pending row totals are sums of independent
file previews against that revision, not predictions of a sequential deduplicated
batch. An empty or evidence-only new workbook is pending, while a verified exact
completed import is a no-op. Capture/mapping failures retain only static error
codes in output; broken canonical lookup evidence fails the whole operation.

Canonical sample `validation_skips` is null because exact-import quarantined,
unsupported and uncovered counts are different measures. Their separate aggregate
dispositions appear in metadata. Unknown filenames remain null. Raw, redacted and
compact profiles preserve their established sample handling; merchant amounts
may be null in redacted output and the schema reflects that existing behavior.
Checkup shares the same per-file evaluation while retaining its aggregate output.

## Journal snapshot notes

`journal new` derives its front matter from one validated canonical analysis snapshot
under `legacy_journal_snapshot.v1`. Transaction rows, selected rules/report filters and
goals bytes stay pinned to that revision; live CSV or YAML edits cannot alter the note.
Invalid authority, incomplete transactions, invalid/unselected rules, and non-finite
input or aggregate amounts fail before creating the journal directory or a note.

The existing float calculation uses represented months for averages and the latest
three represented months for rates. `snapshot_metadata.calculation_as_of` is null;
`created` is the local note creation clock, not a financial cutoff. The data range
comes from included rows before report filters. Active filter count reports the
canonical filters actually applied, rather than a separate live filter file.

Absent goals permit existing empty-goal calculations. Invalid or unselected goals
produce a static warning and save null for the six goal-dependent structural and
consumption fields listed in `snapshot_metadata.unavailable_fields`. `active_goals`
is always null with `active_goals_state=not_computed`, because the shared snapshot
calculator does not compute an active-goal list. Unknown values are not saved as zero.

Canonical notes remain external Markdown artifacts. Destination validation protects
canonical/control/configuration/input paths and rejects leaf symlinks. A private
temporary file is published exclusively, preserving existing or concurrently created
notes; this does not claim protection against arbitrary concurrent parent-directory
replacement. Validation precedes the existing optional interactive gitignore prompt. Its canonical
writer also checks protected destinations and atomically replaces an ordinary ignore
file, preserving any hardlinked source inode; symlink ignore files are rejected.
`journal list` and `resume` continue reading historical notes independently of current
financial authority. Legacy note front matter and the three body templates retain
their existing shape. No new JSON command is introduced.

## Reconcile payment candidates

`reconcile` reads included primary/native payment occurrences from one canonical
transaction snapshot under `canonical_reconcile_exact.v1`. It reconstructs Decimal
amounts directly from validated coefficient/scale/lexical evidence, without the legacy
CSV float conversion or two-decimal rounding. UUID payment IDs retain duplicate legacy
row aliases and native rows without aliases. `payment_identity_policy` identifies this
change; ambiguous tie selection is not claimed to be byte-identical to hash ordering.

Missing months permit unmatched evidence, but unmaterialized primary transaction
evidence fails the whole read. Missing/invalid canonical date prefixes and unknown
currencies fail instead of being skipped or defaulted to KRW. Dates retain the legacy
first-ten-character ISO date interpretation. Different currencies do not match; no
conversion, report filters, goals logic, or transfer exclusion is added.

The explicit external evidence file is captured once. Its digest and external basis
are separate from the payment generation/revision in `_meta`, which also records
the requested `window_days`. Human output identifies
the canonical revision and UUID identity. Evidence parsing, source selection and
calculation failures use a static error message. No ledger, match decision or evidence
file is written. Matching decisions remain proposals under the existing algorithm.

Canonical arithmetic uses a dedicated Decimal context and finite exact inputs, with
precision derived from all operand digits/scales and the matcher's maximum five-term
sums. This keeps comparisons, partial thresholds and residuals independent of the
calling process's Decimal settings. Explicit input and search limits reject unsupported
work rather than return a truncated result; these bounds do not claim a bound on JSON
file loading or on all other CLI processing. The legacy CSV path keeps its existing
amount conversion and matcher. This checkpoint does not persist M5 evidence inboxes or
confirmed/withdrawn allocation decisions, and does not establish full private-corpus
or operational acceptance.

The canonical limits are 10,000 total input items, 1,000,000 input coefficient
digits, 1,000,000 evidence/payment pairs, 1,000,000 actual metered work units, and
20,000,000 precision-weighted work units. Individual amounts retain the
100,000-coefficient-digit and 255-scale support boundary. The matcher runs once on
frozen inputs and charges candidate checks, absolute-value
operations and each visited combination's operand count. Early one-to-one and N:M
matches do not consume the cost of unvisited combinations. The scoped meter is
restored after success or failure. Its work units are an explicit proxy rather than
a CPU instruction or wall-clock guarantee. Metadata reports these
limits. The existing five-item search and sixteen-payment candidate cap remain.

Canonical evidence combination searches first exclude amounts above the target,
then skip targets not divisible by the exact common-unit amount GCD and sizes
whose minimum/maximum sums cannot reach the target. These checks preserve the
order of feasible combinations and use exact integer conversion even at the
maximum coefficient/scale boundaries. They add no arithmetic to the legacy path;
payment exact searches also check fixed-size minimum/maximum sums, and partial
searches skip sizes that cannot reach 50% coverage below the target. Searches
remaining after these bounds may still exhaust the explicit work budget.

Like the other consumers, reconciliation follows the shared authority resolver: a
present invalid activation or absent trusted evidence fails, while no activation
pointer selects legacy authority. Removing a pointer after activation cannot be
distinguished from an unactivated root by this consumer; operational mode/binding
protection remains a cutover acceptance concern, not a claim of this adapter. Shared
read coordination may create its control lock; financial and evidence files stay
unchanged.
