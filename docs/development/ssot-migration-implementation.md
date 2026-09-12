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
finjuice ssot migrate plan --manifest <capture-manifest> --output <new-plan.json> --json
finjuice --data-dir <active-data-dir> ssot migrate build --plan <new-plan.json> --staging <new-candidate> --json
finjuice ssot migrate verify --candidate <candidate>/manifests/migration-manifest.json --json
```

The plan contains private source locators and per-input evidence. Public output
contains counts, digests, check statuses, and limitations. Treat both the plan
and candidate directory as private financial artifacts. The capture locator is
relative to the plan file, so moving a plan alone can invalidate its locator.
Neither planning nor verification runs existing tagging or transfer rules.

## Implemented preservation

- Every source file is retained byte-for-byte in content-addressed objects, with
  distinct source occurrences even when file content is identical. Directories
  and explicitly absent optional roots remain in the capture and input manifest.
- CSV evidence retains header order, duplicate columns, raw records, quoted
  blanks, unquoted empty cells, missing cells, unknown fields, and duplicate rows.
  Unsupported records retain explicit preservation issues and dispositions.
- Supported transactions, overview facts, and asset snapshots receive typed rows
  and deterministic legacy mappings. Amounts retain their original decimal
  spelling and exact coefficient/scale. Missing currency remains unknown.
- Transaction rows preserve persisted final category, notes, transfer flags and
  group identifiers. The last nonempty hidden category marker becomes the manual
  category; visible manual tags retain their order and duplicates. Original
  marker arrays remain in row evidence. No accounts or owners are inferred.
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
as a completed candidate; retry with a new target and optional
`--parent-attempt-id`.

Verification checks database integrity, foreign keys, content hashes, immutable
plan/manifest bindings, and preserved input dispositions. It reconstructs the M1
capture from candidate objects and verifies that capture, then builds an expected
database and compares all authoritative table values. Only schema-installation
wall-clock metadata is excluded from semantic comparison; the candidate database
bytes are separately hashed. Verification does not need the original capture
directory and does not write to the candidate database.

Adapter replay detects corruption and inconsistency; it is not an independent
parser oracle. Separate synthetic assertions check expected transaction meaning,
exact values, duplicate identity, config status, and raw evidence.

## Remaining gates

- Derived balance/cashflow/insurance/investment/loan rows need a capture-wide
  source-fact lookup before typed foreign keys can be assigned. They currently
  retain opaque row evidence with `unresolved_source_fact` when that field exists.
- Config head selection is not implemented. Revisions alone must not be treated
  as active rules/goals configuration.
- Failed attempts are rejected through their unpublished workspace and missing
  publication authority. A durable failure-phase manifest and validated parent
  attempt lineage are not implemented; `--parent-attempt-id` records a supplied
  identifier rather than proving the preceding attempt. Crash recovery needs
  further acceptance work before operational use.
- Historical audit bytes are retained without recreating a historical event chain.
- No consumer parity, runtime restore, private-data migration, release, activation,
  or operator approval has been verified. Every result reports `cutover_ready=false`.
- #434 must pass its existing non-author review and merge gate. #435 remains open
  for complete typed mappings and acceptance evidence; #440 owns activation.

The governing acceptance contract remains
[ssot-migration-recovery-contract.md](ssot-migration-recovery-contract.md).
