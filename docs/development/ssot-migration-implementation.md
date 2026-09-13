# Inactive preservation migration (#435)

This first implementation is stacked on the unmerged #434 storage/mutation work.
It prepares synthetic preservation candidates; it does not satisfy the complete
#435 acceptance gate or authorize activation. No private dataset was used to
validate this implementation.

## Commands

Use a verified, frozen M1 capture produced by `finjuice backup create`. Planning
without `--output` reads the capture and prints a summary. Building requires a
new private plan file:

```sh
finjuice --data-dir <active-data-dir> ssot migrate plan --manifest <capture-manifest> --output <new-plan.json> --json
finjuice --data-dir <active-data-dir> ssot migrate build --plan <new-plan.json> --staging <new-candidate> --json
finjuice ssot migrate verify --candidate <candidate>/manifests/migration-manifest.json --json
```

The plan contains private source locators and per-input evidence. Public output
contains counts, digests, check statuses, and limitations. Treat both the plan
and candidate directory as private financial artifacts. The capture locator is
relative to the plan file, so moving a plan alone can invalidate its locator.
Neither planning nor verification runs existing tagging or transfer rules.
Saving a plan applies the existing repository, active-data, and capture isolation
boundaries. The Python API requires `active_data_dir` when `output` is supplied;
the CLI supplies it from the existing data-dir context. A read-only preview does
not require an active-data boundary.

## Implemented preservation

- Every source file is retained byte-for-byte in content-addressed objects, with
  distinct source occurrences even when file content is identical. Directories
  and explicitly absent optional roots remain in the capture and input manifest.
- CSV evidence retains header order, duplicate columns, raw records, quoted
  blanks, unquoted empty cells, missing cells, unknown fields, and duplicate rows.
  Unsupported records retain explicit preservation issues and dispositions.
  A row marked `preserved_opaque` may also have supported typed fields; its reason,
  typed record counts, and issues must be read together. The disposition does not
  claim that the row has no typed representation.
- Supported transactions, overview facts, and asset snapshots receive typed rows
  and deterministic legacy mappings. Amounts retain their original decimal
  spelling and exact coefficient/scale. Missing currency remains unknown.
  Unsupported transaction types and invalid asset/fact field combinations are
  retained as evidence with explicit issues before financial typed insertion.
  Analysis and build use the same checks without reclassifying invalid values.
- Transaction rows preserve persisted final category, notes, transfer flags and
  group identifiers. New v4 plans retain v3 manual-category selection using the frozen
  legacy normalization and duplicate-marker semantics described below; visible
  tags retain their original spelling, order, and duplicates. Original marker
  arrays remain in row evidence. No accounts or owners are inferred.
- Configuration revisions retain source bytes and parse status. Config decimals
  represented as lexical strings have an explicit representation issue. Raw
  XLSX/ZIP, audit history, overlays, and unsupported formats remain source evidence.
- One source-backed `other` config revision records `legacy_current_state` at
  dataset revision zero. Its evidence is the original capture manifest object.
  No old audit sequence, actor, approval, or event time is invented.

## Candidate lifecycle and verification

The builder checks the frozen capture and its complete tree inventory before
and after reading it. It rejects active, overlapping, nonempty, symlinked, and
repository-contained destinations. A hidden sibling attempt is populated and
verified before atomic directory publication. A matching completed retry is
reverified and returns `already_complete`. An incomplete attempt cannot be used
as a completed candidate. After an accepted attempt fails, its retained target name is
rejected by the journal precheck; retry with a different target and the retained
`--parent-attempt-id` in the same staging parent directory.
Publication I/O failures may remove unpublished work, but phase evidence lives
outside that workspace. A failure after directory publication can leave a
complete candidate that must be reverified before an `already_complete` retry
is accepted; it must not be relabelled as a failed parent.

Verification checks database integrity, foreign keys, content hashes, immutable
plan/manifest bindings, and preserved input dispositions. It reconstructs the M1
capture from candidate objects and verifies that capture, then builds an expected
database and compares all authoritative table values. Only schema-installation
wall-clock metadata is excluded from semantic comparison; the candidate database
bytes are separately hashed. Verification does not need the original capture
directory and does not write to the candidate database.

Existing adapter policies v1/v2/v3 explicitly select SQLite schema v4 for building,
validation and semantic comparison. The reader selects the exact v4 table registry;
a later runtime default cannot silently add tables to old digests. Unsupported
requested versions and mismatched database headers fail closed. Runtime defaults
require schema v5. New `legacy_preservation.overview_reports.v4` plans build v5;
v4 schema contents and table enumeration remain available to the old policies.
A separate v4-to-v5 upgrade adds empty report tables without reinterpreting opaque
rows or changing the original candidate. It does not copy the old migration manifest
and cannot claim the old candidate's sealed digest.

Adapter replay detects corruption and inconsistency; it is not an independent
parser oracle. Separate synthetic assertions check expected transaction meaning,
exact values, duplicate identity, config status, and raw evidence.
Synthetic exception tests cover ENOSPC and ordinary failures during capture-copy
and repository-replay verification, publication failure cleanup, and a parent
sync failure after publication. They check scratch cleanup and unchanged source,
capture, and candidate evidence. These injected failures do not establish a
free-space sizing rule or hardware power-loss guarantee, and no disk was filled for testing.
Separate process-kill checks exercise actual OS lock release and recovery before
and after directory publication.

## Remaining gates

- Canonical five-role overview reports now have typed values under the new v4 policy,
  but source-fact relationships remain explicitly unverified, ambiguous or missing.
  A unique alias is not occurrence proof. Old policies retain their opaque derived
  representation. Noncanonical paths, incomplete report schemas and invalid values
  still retain original evidence with issues. Full private-capture coverage and
  #436 consumer parity remain acceptance gates; typed storage alone is insufficient.
- New plans select canonical rules/goals heads from the frozen primary data root
  as described below. Other configuration copies remain preserved revisions;
  missing or invalid canonical documents are not replaced with alternative copies.
  Older policy plans retain their original unselected-head behavior.
- Durable phases and validated retry lineage are implemented below. Physical
  power-loss behavior and operational recovery remain separate evidence gates.
- Historical audit bytes are retained without recreating a historical event chain.
- No consumer parity, runtime restore, private-data migration, release, activation,
  or operator approval has been verified. Every result reports `cutover_ready=false`.
- #434 must pass its existing non-author review and merge gate. #435 remains open
  for complete typed mappings and acceptance evidence; #440 owns activation.

The governing acceptance contract remains
[ssot-migration-recovery-contract.md](ssot-migration-recovery-contract.md).

## Canonical configuration baseline policy

The existing runtime reads exactly `rules.yaml` and `goals.yaml` at the primary
legacy data root (`Config.rules_file` and `Config.goals_file`). Sealed private
plans using `legacy_preservation.config_heads.v2`, manual-state v3, or overview-report
v4 select those captured revisions as baseline heads. Nested files, external roots, `.yml`
and `.json` copies remain distinct evidence; neither filename similarity, byte
identity, parse success nor modification time grants them canonical status.
The retained `config_head_requires_explicit_selection` issue on an alternative
marks that revision as unselected; it does not require replacing an existing
canonical head or grant the alternative authority.

The selected head retains the exact source bytes, occurrence, revision ID and
parsed status. An invalid canonical document is still the actual canonical
source, marked invalid with an explicit issue; a valid alternative cannot silently
replace it. If the canonical file is absent there is no head. A selected head is
baseline state, not a historical edit: `updated_changeset_id` stays null and the
head timestamp is the immutable capture completion time, not an invented edit time.

A missing policy field means the original `legacy_preservation.v1` behavior;
explicit v1 also replays that behavior. Unknown policy values fail before build
publication or successful verification. The policy is sealed into the plan and
bound by the candidate's existing plan-evidence digest. Plan analysis and source
replay use the same policy. V2 generation IDs include the policy so a v1 candidate
without heads cannot share a generation/revision identity with the v2 baseline.
Source occurrence and config revision identities remain unchanged. The v2 config-head
policy itself did not change CLI flags or SQLite schema; v4 overview policy separately selects v5.
This preserves old candidates without treating their missing heads as completion
of the new canonical-config requirement. Runtime activation and consumer parity
remain separate acceptance gates.

## Manual category policy

The `legacy_preservation.manual_state.v3` policy retains v2 canonical config-head
selection and freezes the existing legacy manual-category interpretation. New
`legacy_preservation.overview_reports.v4` plans retain the same interpretation. It strips full tag strings, ignores empty strings, deduplicates
those normalized strings in first-seen order, and chooses the last marker with
a nonempty stripped suffix. The implementation is local to the frozen adapter:
future changes to the runtime helper cannot silently reinterpret a sealed plan.

Only marker recognition and `category_manual` use that interpretation. The typed
visible sequence keeps each original non-marker string, including whitespace and
duplicates. Legacy payload and source bytes retain all markers and original tags.
Persisted `category_final`, `tags_final`, notes, and other manual state remain
unchanged; this extraction does not run tagging or recompute a category.

Existing v1/v2 plans still replay their original literal extraction. Their
verification proves their own policy, not v3 category parity. A new v3 candidate
has a distinct policy-scoped generation ID while preserving original source and
entity identities. It must pass the new manual-state parity checks before
cutover; no existing candidate is silently rewritten.

The sealed plan policy is the implemented discriminator for extraction semantics;
there is no emitted per-row sentinel representation-code field. Consumer parity
must distinguish original stored visible tags from the normalized legacy display
view instead of using storage equality as proof of display equality.

## Durable attempt journal and retry lineage

Each accepted build creates a private journal below the staging parent's
`.finjuice-migration-attempts/<attempt-id>/` before creating its work directory.
Numbered sealed records form a digest-linked sequence: started, building, built,
publishing, published, verified. The build records each phase after completing
the preceding phase; `built` includes the staging content verification. Caught
failures append a terminal failure record containing the exception class, never
the exception message or financial payload. Every record is fsynced and published
exclusively from a unique temporary file, then its directory chain is synced.
Existing records are not overwritten. Pending partial files are not phase records.

A nonblocking POSIX file lock is held for the entire attempt. A requested parent
must have a valid journal bound to the same sealed plan and capture. Unknown,
tampered, live, successful and mismatched parents are rejected. No PID or lockfile
presence is treated as proof of liveness. A retained nonterminal chain can be
classified as interrupted only after acquiring its OS lock and excluding a
published target. That classification is preserved in the child's sealed parent
evidence; the original journal and abandoned workspace stay unchanged.

When storage also rejects the failure record, the original exception and earlier
durable records remain; a terminal record is not claimed. Failure before the
initial record becomes durable never starts repository population. This protocol
provides process-crash evidence, not a guarantee that a failed device can retain
new bytes or that physical power-loss recovery has been tested.

New candidate manifests use `finjuice.migration.v2` and require portable attempt
evidence, including the parent chain. Verification works from that candidate
without the external journal. Original `finjuice.migration.v1` manifests still
verify/retry under their sealed adapter policy; the old reader rejects v2 rather
than silently ignoring its required evidence. The SQLite schema and original
source/parser identities do not change. A copied completed candidate can be
verified without its journal, but starting a linked retry requires the retained
private journal in the staging parent. Preflight rejections before an attempt
is accepted do not create phase evidence.

Target-name history is checked before starting a build; this check is not a
per-target concurrency lock. Concurrent publishers still rely on the existing
exclusive directory publication and empty-target identity checks, so a second
writer cannot replace an already published nonempty candidate. A corrupt sibling
journal fails this history check closed because its target history is unknown.
Preserve the damaged journal and workspaces for diagnosis; an independent fresh
plan/build can use a new isolated staging parent. Do not delete or edit evidence
to bypass the check, and do not claim a linked retry if the parent evidence
cannot be verified. This recovery path does not modify the original source.

## Reported overview policy

New v4 plans recognize the canonical `banksalad/<role>/YYYY/MM/<role>.csv` paths for
balance, cashflow, insurance, investments and loans. They store report details on
existing deterministic row observations, with original provenance and raw payloads.
The native overview projection tables and their same-occurrence fact FKs stay unchanged.
No fake fact, owner, account, derived calculation or selected reference is generated.

All report numbers are parsed before typed insertion. Invalid numbers or blank dates
retain the whole original row with issues instead of leaving partial typed values.
Optional missing amounts remain absent, not zero. Money keeps exact lexical values;
missing currency remains unknown. Cashflow has no currency in the frozen source schema:
an extra currency column remains unknown-field evidence and cannot supply currency
semantics. Nullable-value reports still preserve their original currency text.
Rates keep the original lexical value and explicit legacy units without percent conversion.

The capture-wide index includes all mapped original fact rows, including invalid typed
facts. Known report and transaction roles take priority over incidental fact-like extra
columns. Identical files still have different occurrences. All rows are emitted before
candidate edges, so file order does not decide references. No alias candidate means
`missing`, one means `unverified`, and more than one means `ambiguous`; none is selected.
The storage validator independently checks the complete same-capture candidate set,
original locators and aliases, report-kind/path binding, value/provenance/unit bindings,
matching detail and assessment rows. Immutable guards reject replacement inserts,
updates and deletes.

A supported report with an unresolved reference retains `preserved_opaque` with reason
`typed_report_with_unverified_reference_or_extra_evidence` and a reference-status issue.
Read that reason alongside typed counts; it does not mean the report amount is absent.
All new tables participate in schema-v5 semantic replay. Original v1/v2/v3 candidates
continue to replay exactly schema v4. See [ADR-0015](../architecture/decisions/0015-cross-file-overview-derivation.md).

Canonical report paths are relative to each captured root. A second root with the same
relative path keeps a separate occurrence and report; this is not the primary-root
authority rule used for config heads. Capture-wide references may therefore remain
ambiguous across roots. No owner or preferred source is inferred.

Duplicate-header and ragged CSV rows retain source bytes and ambiguity issues but do
not create mapped observations. They cannot enter the observation-based reference
validator. Typed report rows, assessment status, and specific extra-field issues must
be read together; the disposition reason is only a summary.

The validator skips known transaction/report paths before decoding fact-candidate
payloads. It still materializes the capture's migration source-row metadata and payload
strings. Peak memory and duration on the actual frozen private corpus remain a
pre-cutover acceptance gate; synthetic correctness tests do not establish production
capacity.
