# SSOT Preservation Migration and Recovery Contract

Status: accepted design for #430; implementation pending in #431 and later

This document is the executable design contract for moving finjuice from the
current CSV authority to SQLite. Normative words such as **must** and **must
not** are acceptance requirements. Examples use synthetic data only.

## 1. Current state and intended state

As of finjuice 0.7.1 with the observed data schema at version 4, transaction
CSV partitions are authoritative. Imported
XLSX/ZIP files, `rules.yaml`, `goals.yaml`, optional asset/scenario files,
schema metadata, import history, JSONL audit/proposal logs, and other overlays
are separate files. DuckDB opens an in-memory database over CSV. Some mutations
rewrite a partition and append audit separately. The manual category override
is encoded inside `tags_manual` with the hidden prefix
`__finjuice_category_override__:`.

The intended post-cutover state is one active SQLite database, immutable source
objects referenced by it, and versioned configuration/source revisions.
CSV/XLSX/reports are derived outputs. None of this intended state exists merely
because this document is merged.

The #430 private inventory confirms these logical source roles without exposing
their paths or contents: transaction partitions; Banksalad `overview_facts`,
balance, investment, loan, insurance, and cashflow data; XLSX imports and
external ZIP directories; root rules/goals; execution audit and import history;
data Git state; an external wealth overlay; and an image-cache role (currently
empty). Visible manual tags and hidden category markers require separate checks.

The private runtime inventory is deliberately outside this public document. It
records the observed current paths, source state, consumer and scheduler state,
overlay location, data Git state, installed version, and checkout state. Those
facts are an inventory snapshot and must be revalidated before the operation;
their private values are not repeated here.

The suitable off-device destination, encrypted transfer and key recovery,
source-host scheduled transfer/authentication path, retention capacity, RPO/RTO
measurements, isolated restore, and future cutover artifact/dataset evidence
remain **unverified runtime facts** for #431/#432/#439/#440. Tool availability
or remote reachability is not restore evidence. An absent inventory entry is a
cutover blocker, not evidence that the artifact or consumer does not exist.

## 2. Authority, identity, and provenance

### 2.1 Required storage roles

An activated dataset generation contains:

* `finjuice.sqlite3`: the only mutable financial authority;
* `objects/sha256/<first-two>/<digest>`: immutable source bytes;
* `manifests/`: immutable capture, migration, backup, and derived-output
  manifests;
* `derived/<dataset-generation>/<revision>/`: disposable CSV and report
  projections; and
* one activation record outside the generation that names the active release
  and generation together.

The exact directory root is runtime configuration and must not be hard-coded in
the public contract. An object is published only after its bytes are streamed to
a temporary file, flushed, hashed, and atomically renamed. If the target digest
already exists, byte length and digest must match before reuse. Immutability is
enforced by the repository and backup retention/GC rules, not assumed from a
filename.

### 2.2 IDs

* `source_artifact_id` is `sha256:<lowercase-hex>` over exact bytes.
* `source_occurrence_id`, `transaction_id`, `observation_id`, `changeset_id`,
  and other entity IDs are opaque UUID strings. Newly accepted state uses
  lowercase, hyphenated UUIDv4 generated from a cryptographically secure random
  source.
* Migration IDs must be deterministic for the same immutable capture-manifest
  digest and legacy locator. The capture manifest is complete before plan/build;
  neither the output migration manifest nor candidate database hashes are ID
  inputs. `finjuice.migration.v1` uses UUIDv5 namespace
  `fd6b8bfd-e7db-5103-8513-66a572addf54` (UUIDv5 of the URL namespace and
  `https://github.com/sungjunlee/finjuice/migration/v1`). Its UTF-8 name is
  `<capture-manifest-digest>/<record-kind>/<legacy-locator>`: lowercase 64-character
  SHA-256 hex without a prefix, a fixed lowercase record-kind token, and a
  canonical JSON locator (`sort_keys=True`, `ensure_ascii=False`, separators
  `(',', ':')`). No whitespace, Unicode normalization, or path normalization is
  applied to locator string values. Locator schema and record-kind tokens are
  versioned with this namespace.
* A legacy locator includes enough original structure to distinguish duplicate
  occurrences: artifact or partition digest, sheet/table, source row or stable
  CSV ordinal, and legacy key. It must not use `row_hash` alone.
* `row_hash`, `file_id`, source row, old path spelling, and old account text are
  retained in a `legacy_identifier` mapping. Mappings are append-only and may be
  marked superseded, never silently reassigned.

Two identical files may share a source artifact but have separate import
occurrences. Two legacy rows with the same `row_hash` remain two occurrences in
the preservation baseline. Any later deduplication is a semantic changeset.

### 2.3 Exact decimal values

Every authoritative decimal value is represented as:

```text
coefficient: canonical signed base-10 integer text ("0" or "-?[1-9][0-9]*")
scale:       integer in an explicitly bounded non-negative range
unit:        ISO 4217 currency code or a versioned domain unit when applicable
lexical:     exact original text for migrated/source-derived values
```

Its value is `Decimal(coefficient) * 10 ** -scale`; storage scale is 0 through
255. SQLite must not coerce the coefficient through `REAL`; Python code must use
`Decimal`. Schema checks reject non-canonical coefficient text and invalid
scale. Money requires either an uppercase three-letter currency code or the
explicit state `currency_unknown`; unknown currency is never defaulted or
combined with known currency. Currency exponent is a validation/default aid,
not permission to round source precision. Rounding requires a named policy,
mode, target scale, and revision. A source value outside the typed bounds keeps
its exact lexical value as opaque evidence and blocks cutover until a wider
typed contract is accepted.

For source/migration values, construct `Decimal` directly from the lexical
text, without arithmetic under an ambient decimal precision context. Let its
tuple exponent be `e`: use `scale = max(-e, 0)` and its signed tuple digits as
the coefficient, appending `e` zeroes when `e > 0`. Remove leading coefficient
zeroes, but retain source trailing zeroes and scale. All signed zero
coefficients become `"0"`; the lexical value preserves the original sign.
Thus `10.10` becomes `("1010", 2)`, `1.010E1` becomes `("1010", 2)`, and
`1E2` becomes `("100", 0)`. NaN and infinity are not typed values. This fixes
one representation per parsed source quantum; numerical comparisons compare
exact values, and baseline evidence also compares lexical text and scale.
Calculated values use the named calculation/rounding policy's target scale.

Quantities, unit prices, and FX rates use the same coefficient/scale pattern.
An FX conversion records source and target currencies, exact rate, rate
direction, observed/effective time, provider/source artifact, and rounding
policy. Reports aggregate by currency unless a specific FX policy is selected.

Existing JSON numeric fields may remain as compatibility projections only when
the exact value round-trips under the supported legacy domain. Exact sibling
strings such as `amount_exact` must be available before accepting values outside
that domain. A serializer must fail or emit an explicit unsupported-value error
instead of silently rounding an authoritative value.

## 3. Preservation baseline and later corrections

The first migration copies meaning; it does not improve it. For each input
record, it must preserve:

* every row occurrence and legacy identifier, including duplicates;
* exact numeric lexical values and parsed exact values;
* raw and normalized date/time text, null/blank distinctions where observable,
  and timezone uncertainty;
* raw categories, rule category, final category, tags, notes, transfer/review
  flags, confidence, and unsupported columns;
* source artifact/occurrence, parser/schema version, source coordinate, and
  import-history association;
* rules, goals, manual assets/liabilities, scenarios and other inventoried
  config revisions as both exact bytes and parsed status;
* Banksalad transaction and overview/asset facts without interpreting an
  overview balance as a transaction; and
* inventoried audit/proposal/import history and external overlays without
  pretending they are complete.

Unknown columns or unparseable optional values go into a lossless legacy
payload and a typed issue record. A record is quarantined only if the target
cannot preserve it safely. Every manifest input receives one disposition:
`migrated`, `preserved_opaque`, `quarantined`, or `intentionally_absent`, with a
reason. Any unexplained record, key, field, or important quarantine fails the
cutover gate.

The hidden category marker is migrated as follows:

1. retain the original `tags_manual` sequence in legacy payload;
2. recognize markers beginning with `__finjuice_category_override__:` after
   stripping surrounding whitespace, while retaining every non-marker tag in its
   original spelling, order, and multiplicity in the typed visible sequence;
3. reproduce the existing legacy category selection: strip full tag strings,
   ignore empty strings, deduplicate the normalized full strings in first-seen
   order, then select the last marker with a non-empty stripped suffix;
4. store the selected value in explicit `category_manual` and store all marker
   occurrences for evidence; and
5. recompute nothing: persisted `category_final` remains the baseline result.

The imported snapshot of current state gets one synthetic origin revision with
`origin_kind = legacy_current_state`. Its evidence points to the frozen
manifest and legacy audit artifacts. It must not invent event time, actor,
approval, or a historical sequence that the legacy files cannot prove.

After baseline acceptance, a semantic correction is a changeset with an
explicit type such as `account_identity_merge`, `ownership_correction`,
`category_correction`, or `duplicate_resolution`. It records before/after,
reason, evidence, author/agent identity, confirmation state, expected revision,
and reversal link. Baseline parity reports exclude these later changesets.

The complete baseline representation-difference allowlist is: deterministic
CSV quoting/line endings; canonical JSON serialization of an unchanged tag
sequence; canonical decimal coefficient/scale with exact equality and retained
legacy lexical text; and canonical date/time text only when parsed components
and uncertainty are identical and raw text is retained. Each difference uses a
versioned code. Row removal/addition, null-to-blank collapse, reordered tags,
currency defaulting, category/rule recalculation, account renaming/merging,
owner inference, duplicate resolution, or changed totals are semantic changes
and fail baseline parity.

The additional representation allowance `hidden_category_sentinel_extracted.v1`
permits the typed-field split with the entire original sequence retained in
legacy payload and the original visible subsequence retained in typed
`tags_manual`. The implemented audit discriminator is the candidate's sealed
`migration_policy`, not a per-row representation-code column: no per-row
sentinel extraction code is currently emitted. New adapter policy
`legacy_preservation.manual_state.v3` applies the normalized legacy selection
rule above, without normalizing or deduplicating the retained visible
subsequence. For example, markers A, B, A select B because the repeated full
marker A was already seen; a whitespace-only suffix never overrides a prior
category. Previously sealed v1/v2 adapter plans retain their original literal
marker extraction on replay; verifying such a candidate does not certify
corrected manual-category parity. A new v3 plan is required for that parity gate.
Parity checks all three separately; it never compares a typed visible-tag field
directly to the legacy encoded CSV string. This is not permission to discard a
marker or change the effective category.

## 4. Atomic mutation and audit contract

All post-cutover writers call one repository transaction boundary:

1. begin a write transaction and acquire the configured SQLite writer lock;
2. validate schema version, active generation, command scope, and payload shape,
   then compute the canonical request digest;
3. look up `(command_scope, idempotency_key)` before checking expected revision
   or mutable entity state: an existing identical digest returns its stored
   result, while a different digest fails with an idempotency conflict;
4. only for a new key, validate expected dataset revision, referenced IDs and
   domain constraints, then reserve the key/digest in this transaction;
5. write domain state, legacy/provenance links, changeset details, and audit
   event;
6. increment dataset revision exactly once for a state-changing command;
7. store the successful result envelope for identical retries; and
8. commit, then report success.

The same key and digest returns the stored result without a second mutation.
The same key with a different digest is a conflict. Retrying a successful request
at revision N still returns its original result after the dataset has advanced
to N+1 or later; a new key with the stale expected revision fails. A stale
expected revision on a new request,
constraint error, disk/full I/O error, process interruption, or bounded busy
timeout rolls back all state and audit writes. Audit failure cannot be downgraded
to a warning for an otherwise successful financial mutation.

SQLite foreign keys must be enabled on every connection. Schema migration uses
a backup/staging database and a transaction where supported; it runs integrity,
foreign-key, version, and application invariants before publication. A newer or
unknown schema is rejected read-only with an actionable version error. No
automatic destructive downgrade is supported.

Legacy writer fencing is a cutover control. Code may implement and test it
earlier, but normal pre-cutover operation must stay on CSV. During final freeze,
all inventoried writers are stopped, the legacy tree is made unwritable through
the verified runtime mechanism, and stale installations fail closed. A lock
file alone is insufficient because old versions may not understand it.

Current-runtime authoritative CSV writers receive the data root explicitly and
check its activation fence under a coordination lease before filesystem effects
or early no-op success. Data-root and partition paths must reject directory
aliases, including Windows junction/reparse paths, so an inactive alias cannot
write through to an active repository. POSIX writers use shared leases; Windows coordination
may serialize all leases exclusively. Both thread-local and OS-lock waits are
bounded. Separate nested leases in the same thread may reuse the held lease,
while a shared-to-exclusive upgrade is rejected. Cancellation must release local
and OS resources so later operations remain usable. Platform-specific SQLite
object-store, activation, and backup acceptance remains a separate gate from
legacy CSV coordination acceptance.

M1 backup capture is different: it uses only a stopped-writer capture or a
snapshot taken under stopped writers as defined in section 5.2, then releases
that temporary control while CSV remains authoritative. It must not turn on
the permanent legacy fence. In #440,
cutover enters maintenance, stops and fences legacy writers first, captures and
verifies the final baseline under the fence, builds/verifies the final dataset,
activates the release/dataset pair, and opens only the repository writer. The
legacy fence remains active after cutover.

The isolated migration builder is the only write exception during final
maintenance. It may create a new staging candidate; it cannot write the live
legacy tree or the active generation, and its candidate has no authority until
activation.

## 5. Frozen-source migration protocol

### 5.1 Commands and state machine

#431 implements the backup command names and JSON concepts:

```text
finjuice backup create --source <data-dir> --output <new-path> --json
finjuice backup verify <backup-manifest> --json
finjuice backup restore <backup-manifest> --target <empty-path> --json
```

The first legacy backup implementation supports create/restore on Linux and
macOS, where directory metadata, directory fsync, and atomic directory
publication are exercised. Other platforms fail before creating output or
staging. Windows mutation support requires a separately verified metadata,
durability, and empty-target replacement implementation; plain `os.rename`
and POSIX directory file descriptors are not a compatible fallback.

#435 implements the frozen migration command names and JSON concepts:

```text
finjuice ssot migrate plan --manifest <capture-manifest> --output <new-plan> --json
finjuice ssot migrate build --plan <plan> --staging <new-path> --json
finjuice ssot migrate verify --candidate <migration-manifest> --json
```

#440 implements activation:

```text
finjuice ssot activate --release-digest <sha256> --candidate <manifest> --json
```

Any spelling change must update this contract and its acceptance fixtures
before the owning issue's first release.

`backup restore` and migration build default to a new, empty directory and
refuse the active data directory, a non-empty target, symlink/path escape, or an
unverified manifest. Repeating a completed create/build returns the same result
or a distinct `already_complete`; it never modifies the source.

Migration follows `inventoried -> frozen -> captured -> planned -> built ->
verified -> activated`. Each transition writes an immutable manifest. Failure
is terminal for that candidate; retry creates a new attempt linked to it unless
the operation is explicitly proven resumable.

### 5.2 Capture manifest

The capture walks a fixed inventory while all inventoried writers are stopped,
or reads a named filesystem/volume snapshot taken after stopping those writers.
The report records the stopped-writer inventory and capture interval or named
snapshot. A live directory walk plus stat/hash/stat is not an alternative
consistency mechanism. A pre-existing partial legacy operation is preserved as
observed and reported; quiescence does not prove historical atomicity.
The capture records, for every
item: logical role, relative portable path or external inventory ID, type,
size, SHA-256, mode needed for restore, symlink policy, required/optional state,
and disposition. It also records capture tool version, finjuice version, schema
version, platform/runtime versions, data Git commit/dirty-status evidence when
present, and the inventory definition digest.

Absolute paths and host/account details stay in the private report. Files are
stat/hash/stat checked; any size, identity, mtime, or digest change during
capture rejects the candidate and requires a fresh freeze/capture. The manifest
itself has a schema version, canonical encoding, digest, completion marker, and
parent attempt ID. A completion marker is published atomically only after all
referenced bytes are durable and verified.

Build reads only the frozen copy, writes a new staging database/object tree, and
never opens the live legacy tree for mutation. Before and after build it
revalidates every input digest. Plan output contains counts and expected
dispositions by record kind, plus explicit unknown/absent inputs. Verify compares
the built result to the same frozen manifest; it does not compare to a live tree
that may have resumed changing.

## 6. Complete backup and isolated restore

A legacy full backup includes the entire inventoried data tree and every
referenced external artifact: raw XLSX/ZIP, partitions, overview/assets,
metadata, import/audit/proposal history, rules/goals/assets/scenarios/config,
external overlays, data Git state needed for recovery, schemas, and the exact
program/release/dependency/version evidence needed to interpret them. Missing
optional items are manifest entries with `intentionally_absent`; silence is not
completeness.

A post-cutover backup uses the SQLite Online Backup API to capture one
consistent database snapshot, then follows that snapshot's immutable artifact
and config revision references. GC pins the reference set until the backup
completion manifest is durable. Copying a live `.sqlite3`, `-wal`, or `-shm`
file set directly is not a supported backup method.

The backup also includes an immutable copy of the external activation tuple
and the release/dependency evidence it names. Snapshot generation/schema must
match that binding; the backup records the snapshot's current revision
separately from the activation-time revision. Pin the binding while capturing
or reject a changed binding before publication. This closes the backup graph
even though the live activation pointer is outside the generation.

Restore writes only an inactive generation descriptor inside the isolated
target. It never rewrites a source/host activation pointer or opens production
writes. Restore verification explicitly selects the restored data/generation
path and recorded artifact; operational activation is a separate command.

Secrets are never copied in plaintext into a public or ordinary backup. The
private inventory must name required credentials/keys and a separately tested,
encrypted recovery route. A backup is not recoverable until the key route works
without relying on the source machine's active session.

`backup verify` checks manifest/schema support, every digest and size, path
containment, duplicate/conflicting logical roles, completion marker, database
integrity and foreign keys when present, all referenced-object closure, and
required capacity. Verification failure never returns a success status.

An off-device acceptance restore must:

1. obtain the encrypted copy and recovery key without reading the source
   workspace;
2. restore to a new isolated directory on a different failure domain;
3. verify all manifest entries, SQLite `integrity_check`/`foreign_key_check`,
   source hashes, release/schema compatibility, and derived-cache staleness;
4. run representative read queries with the recorded installed artifact;
5. for a post-cutover backup, mutate only the restored copy, read it back, make
   a second backup, and restore that backup; and
6. record measured RPO/RTO, failures, and unresolved dependencies privately.

Whether the chosen device/storage is truly off-device or off-site, how it is
encrypted, how keys are recovered, and whether capacity meets retention policy
are runtime facts to verify in #432/#441.

## 7. Read, JSON, CSV, and DuckDB compatibility

`show`, `status`, `query`, `explain`, `template`, `export`, and existing analysis
commands read one committed database snapshot and include or internally bind the
dataset generation/revision. Human and JSON behavior is compared against the
frozen baseline with explicit ordering, pagination, null, boolean, date/time,
tag, transfer, category, and error-envelope checks.

CLI JSON remains the supported public API. Existing field names and meanings
are retained where #436 marks them compatible. Additive provenance fields
include `dataset_generation`, `dataset_revision`, calculation policy, and
as-of/source timestamps where relevant. `tags_manual` output contains visible
manual tags; `category_manual` carries an override where that surface exposes
it. The legacy sentinel is never emitted as a user tag by typed human/JSON
renderers.

The legacy compatibility CSV codec reproduces the full baseline
`tags_manual` sequence, including hidden markers in original order, from the
preserved payload. Typed human/JSON renderers expose only visible tags. After
an explicit correction, compatibility CSV encodes the current visible tags and
effective manual category under the same documented legacy codec; historical
markers remain evidence, not current overrides. The export manifest identifies
the codec and revision, so baseline parity never compares a later correction
against the old encoded state.

The DuckDB relation `transactions` retains its documented analytical columns
and filtering meaning. Its source changes from direct CSV globbing to a
revision-pinned SQLite-to-Arrow/Polars adapter or a deterministic compatibility
projection. The adapter exposes exact decimals without first converting them
to Python/binary floats. If a DuckDB decimal width/scale cannot represent a
value, the adapter fails explicitly or exposes the canonical exact string; it
does not round silently.

Compatibility CSV is generated in canonical column order, UTF-8, stable row
order, normalized line endings, and deterministic quoting from one revision.
Its manifest contains database generation/revision, schema and exporter
versions, each file digest/count, and generation time excluded from the content
digest. Editing a derived CSV cannot update SQLite. A reader comparing a CSV
manifest to the active revision reports `fresh`, `stale`, `foreign_generation`,
or `invalid`; only `fresh` may be used as the default compatibility source.

Raw SQL remains single-statement and read-only. SQLite is not exposed as an
unrestricted write surface. Existing DuckDB templates must pass baseline
goldens; storage-specific SQL gets an explicit compatibility migration rather
than an implicit semantic change.

## 8. Release, cutover, and no-loss recovery

Pre-cutover backup/create/verify/restore additions may be released as compatible
`0.7.x` changes. The authority switch is a `1.0.0` candidate because the current
release policy assigns breaking data-layout changes to MAJOR. No version file is
changed by #430.

The cutover gate requires: merged CI-clean source; wheel/sdist digest and
provenance where available; a clean isolated install of that exact artifact;
private inventory closure; verified full off-device backup and key recovery;
successful isolated restore; deterministic migration and parity report; all
consumer reads prepared; legacy-writer fence tested against an old installation;
and zero unexplained loss or important quarantine. Passing those preparatory
checks does not itself activate the fence or dataset. The operational sequence
is maintenance entry, legacy-writer stop/fence, final capture and verification,
final dataset build and verification, atomic activation, read smoke, then new
repository-writer enablement.

Activation atomically publishes this tuple:

```text
(release_version, release_artifact_sha256, dataset_generation,
 sqlite_schema_version, dataset_revision, migration_manifest_sha256,
 pre_cutover_backup_manifest_sha256, activated_at)
```

The service opens writes only after re-reading that tuple and completing read
smoke tests. The first real operation is verified without inserting a fake
financial transaction into the operating ledger. A post-cutover full backup is
then created and verified.

Rollback rules are strict:

* Before any committed post-cutover write, stop processes, verify the frozen
  legacy manifest, and atomically reactivate the previous release/dataset pair.
* After a post-cutover write, first fence writers and snapshot the active
  generation including WAL state through the Online Backup API. Never restore
  the old baseline over it. Repair forward, or build a new generation by
  replaying verified changesets/idempotency records onto a preserved baseline.
* If replay is incomplete, keep both generations immutable, expose only a
  read-only degraded mode, and report the unresolved revision range. Do not
  claim rollback success or discard the new records.

## 9. Minimal M4 extension points

The first storage migration implements only the identities and provenance
needed to preserve current facts and support #442-#444. It must not prebuild the
purchase/order/close/adapter domain planned for M5.

Required extension points are:

* `party`, `account`, and `resource` stable IDs with source aliases and an
  explicit `unknown` party/ownership state;
* effective-dated ownership assertions with exact share decimal, evidence,
  confirmation state, and non-overlap/ambiguity validation;
* observations with observed-at, effective/as-of time, collected-at, complete
  or partial scope, source artifact, supersedes link, and confirmation state;
* explicit inclusion/overlap assertions so account summary versus holdings and
  manual versus institutional facts are not automatically double-counted; and
* agent intake records separating immutable evidence, extraction, interpretation
  proposal, user confirmation, and applied changeset, all with idempotency and
  expected revision.

Migration may create unknown parties and unconfirmed aliases. It must not infer
household membership, account ownership, summary/holding inclusion, or semantic
supersession from names or amounts. Those facts are confirmed by later
changesets.

### 9.1 Schema v2 assertion and intake boundaries

The #434 schema v2 gate applies these minimal domain constraints before #435:

* Ownership shares reference exact rates with the unit `ownership_share.v1`.
  A rate in another unit, including an FX rate, is not an ownership share.
  Complete confirmed ownership totals exactly one; partial ownership retains
  an explicit unknown remainder. Share validation uses exact arithmetic.
* Ownership and inclusion/overlap assertions use inclusive calendar-date
  intervals. Each effective boundary is either canonical `YYYY-MM-DD` or null
  for an open boundary. Invalid dates, noncanonical spellings, timestamps, and
  reversed intervals are rejected; no timezone is inferred.
* Active confirmed ownership intervals must not overlap for one account.
  A correction explicitly supersedes an assertion for that account. For one
  ordered entity pair, overlapping active confirmed `excludes` assertions
  cannot coexist with `includes` or `overlaps`. Explicit supersession permits
  corrections, while unknown and unconfirmed evidence remains distinct.
* Intake evidence, receipt occurrences, extraction, interpretation proposal,
  confirmation, and application have separate identities. Proposal deduplication
  includes extraction, command scope, policy version, payload digest, expected
  generation, and expected revision. A stale proposal can be re-proposed against
  a newer revision without inventing a different extraction or policy version;
  the new proposal requires its own confirmation.
* Applying a proposal verifies its confirmation, payload, command identity,
  generation, and expected revision within the mutation transaction. Invalid
  relationships roll back state, audit, revision, and the idempotency reservation
  together. Successful identical retries retain their original result.

### 9.2 Configuration heads and schema evolution

Schema v3 adds canonical rules/goals heads on top of the v2 assertion and intake
contract. Existing v2 databases must use an explicit v2-to-v3 upgrade; changing
the v2 DDL in place is insufficient. Fresh creation and upgrade must converge
on the same validated shape while preserving existing identities, values,
source references, audit, and mutation receipts. The first #435 preservation
candidate targets the latest schema that has passed the #434 gate.

Configuration changes preserve the original document bytes and append a
revision before selecting its canonical head in the same mutation transaction.
A failed change leaves the old head, state, audit, revision, and idempotency
reservation unchanged. Equal document bytes are a no-op only when parsed status,
parser version, and canonical interpretation are also equal. A changed
interpretation retains a new revision even when the source bytes are unchanged.
A no-op receipt identifies the existing canonical head, never an uninserted
revision identifier. The request digest includes the canonical interpretation.

A caller-supplied replay key requires its original generation and revision.
With an automatically generated key, explicit generation or revision values
are independent one-shot concurrency preconditions. Repeating a normal command
uses a new key and domain no-op detection, so A-to-B-to-A remains possible.
CLI transformations such as rule upsert/removal or budget edits bind their
stable operation inputs to the request identity. Replay must precede checks
that depend on the current config, so a successfully removed rule remains
replayable. Read-transform-write preparation must retain the revision it read,
or run inside the mutation transaction; capturing a newer revision after
preparing an older document must never authorize overwriting a concurrent edit.
Manual transaction changes resolve one stable entity;
legacy identifiers may be used only when they resolve without ambiguity.

Mutation results must satisfy the same receipt envelope contract before commit
and during replay. Invalid result/artifact shapes roll back the entire mutation.
Interpretation proposals use object payloads matching the mutation request
contract; extraction evidence may retain an array without making it an
applicable command.

## 10. Synthetic acceptance scenario matrix

All public tests use synthetic artifacts and values. The same check IDs run on
the private frozen baseline, but public output contains only counts and status.

| ID | Synthetic setup and action | Required result |
| --- | --- | --- |
| P01 | Two CSV occurrences share one `row_hash` | Both migrate with distinct IDs and permanent legacy mappings |
| P02 | `tags_manual` contains visible tags and two category markers | Visible order is preserved, last non-empty marker becomes `category_manual`, all raw markers remain as evidence |
| P03 | Persisted `category_final` differs from a newly evaluated rule | Baseline keeps persisted value; difference is not auto-corrected |
| P04 | Blank, null, unknown column, and unparseable optional value occur | Observable distinctions/bytes are preserved and disposition is reported |
| D01 | `10.10`, `0.0037`, a large coefficient, and non-KRW currencies migrate | Coefficient/scale/lexical values round-trip exactly; unlike currencies are not summed |
| D02 | FX conversion needs rounding | Named rate and rounding policy reproduce the result; no implicit float path exists |
| I01 | Same frozen capture manifest is built twice with different attempt metadata | IDs use only the pre-build capture digest and locator; semantic database content matches and output-manifest hashes are never ID inputs |
| I02 | A request succeeds at revision N, then its key is retried with the same/different payload after N+1 or later | Same payload returns its original stored result despite the old expected revision; different payload conflicts; a new key with stale expected revision fails |
| A01 | Process fails between state and audit writes | Transaction rolls back; neither state nor successful audit/revision exists |
| A02 | Two writers use the same expected revision | Exactly one commits; the other reports conflict without lost update |
| F01 | Source file changes during capture | Capture/candidate is rejected and a fresh freeze is required |
| F02 | Referenced overlay is absent or a path escapes root | Manifest is incomplete/invalid; cutover gate fails |
| B01 | Full legacy backup restores to an empty isolated path | All hashes and representative 0.7.x reads match the frozen baseline |
| B02 | SQLite backup is taken during writes | Online snapshot plus referenced objects passes integrity/FK/hash closure |
| B03 | Backup is corrupt, incomplete, lacks space, or target is non-empty | Operation fails explicitly and does not modify source/target authority |
| R01 | `show`, `status`, template and read-only query run before/after | Selected rows, totals, categories, tags, pagination and errors meet compatibility goldens |
| R02 | Derived CSV is edited or active revision advances | SQLite is unchanged and projection reports invalid or stale |
| C01 | Candidate code is installed before cutover | CSV remains active and legacy fence stays disabled |
| C02 | Final cutover activates release and dataset | Activation tuple matches installed artifact and verified manifest before writes open |
| C03 | Failure occurs before first SQLite write | Verified legacy pair can be reactivated without candidate writes |
| C04 | Failure occurs after new SQLite writes | New generation is snapshotted; old backup never overwrites it; replay/fix-forward preserves new records |
| H01 | Unknown account owner is imported, then confirmed later | Baseline remains unknown; a separate reversible changeset establishes dated ownership |
| H02 | Old partial observation follows a newer complete observation | It remains evidence and does not silently replace the complete current view |
| H03 | Same agent evidence is submitted twice | One evidence/proposal lineage exists; confirmation and apply remain distinct |

## 11. Verification report contract

Detailed reports are private and reproducible. They include exact commands,
sanitized logical paths plus a separately protected path map, timestamps,
release/dependency/schema versions, manifest IDs, per-record/key/field
dispositions, exact differences, quarantine reasons, consumer inventory,
backup/key/restore evidence, RPO/RTO measurements, and reviewer sign-off. They
must not fabricate a check for a command that has not been implemented.

The public report uses this privacy-safe shape:

```json
{
  "report_schema_version": 1,
  "run_id": "opaque-id",
  "phase": "migration_verify",
  "started_at": "2026-09-08T00:00:00Z",
  "finished_at": "2026-09-08T00:01:00Z",
  "release": {"version": "1.0.0", "artifact_sha256": "sha256:..."},
  "dataset": {
    "generation": "opaque-id",
    "schema_version": 1,
    "revision": 0,
    "manifest_sha256": "sha256:..."
  },
  "checks": [
    {
      "check_id": "P01",
      "status": "pass",
      "checked_count": 2,
      "difference_count": 0,
      "allowed_difference_count": 0,
      "quarantine_count": 0,
      "evidence_digest": "sha256:..."
    }
  ],
  "summary": {
    "status": "pass",
    "unexplained_loss_count": 0,
    "important_quarantine_count": 0,
    "unknown_runtime_fact_count": 0
  }
}
```

Allowed statuses are `pass`, `fail`, `blocked`, and `not_run`. `not_run` is
never counted as pass. Allowed representation differences have a versioned code
and evidence (for example, canonical line endings); a free-text explanation
alone cannot waive a mismatch. Any unexplained row/key/field loss, unresolved
important quarantine, failed hash/integrity/foreign-key check, unverified
writer, missing referenced artifact, failed off-device restore/key recovery, or
unknown cutover-critical runtime fact makes the gate fail or block.

Public reports must not contain raw rows, amounts, account/party names, merchant
or memo text, original filenames, absolute paths, hostnames, remote addresses,
credentials, key identifiers, conversations, or row-level legacy IDs. Digests
must be newly scoped report/evidence digests where correlation with a public
source could disclose private identity; do not publish raw private artifact
hashes unless the private review explicitly determines they are safe.

## 12. Issue delivery map

| Issue | Contract delivered |
| --- | --- |
| #431 | Legacy complete backup commands, manifest, verification, isolated restore |
| #432 | Actual off-device target, encryption/key recovery, first measured restore |
| #433 | SQLite repository/schema, exact decimals, immutable sources, IDs/mappings |
| #434 | Atomic mutation/audit, revision/idempotency/concurrency, fence capability |
| #435 | Frozen-source plan/build/verify and preservation baseline |
| #436 | CLI/JSON/DuckDB adapters and deterministic derived CSV |
| #437 | Online SQLite snapshot plus referenced-artifact closure and restore mutation smoke |
| #438 | Synthetic/private parity matrix and installed-artifact acceptance evidence |
| #439 | Complete consumer/writer inventory and cutover-mode validation |
| #440 | `1.0.0` artifact install, final migration, activation, first real write and post-cutover backup |
| #441 | Scheduled retention, alerting, recurring off-device restore and measured RPO/RTO |
| #442-#444 | Minimal household identity/observation/agent-intake extensions through explicit changesets |

Implementation issues may refine table names and internal modules. They may not
weaken preservation, exactness, atomicity, completeness, privacy, activation,
or no-loss rollback gates without a superseding ADR.
