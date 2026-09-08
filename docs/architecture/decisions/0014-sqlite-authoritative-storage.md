# SQLite Authoritative Storage with Immutable Sources and Derived CSV

**Status**: accepted
**Date**: 2026-09-08
**Issue**: #430
**Supersedes**: [ADR-0002](0002-csv-partition-storage.md)

## Context and Problem Statement

finjuice 0.7.1 treats monthly CSV transaction partitions as runtime authority.
Rules, goals, imported workbooks, manual assets, import history, audit events, and
other state are separate files. A command can therefore update financial state
and its audit record at different times, relationships cannot be protected by
foreign keys, and a complete backup cannot be inferred from one CSV tree.

CSV remains useful for inspection and exchange, and the existing CLI and DuckDB
surfaces must keep working. It is no longer a safe authority for the planned
preservation migration, household facts, and agent-confirmed corrections.

How should finjuice establish one recoverable authority without changing the
meaning of existing data during the first migration?

## Decision Drivers

* Preserve every legacy occurrence, manual edit, hidden category override,
  source reference, and unknown field before any semantic cleanup.
* Commit financial state, its revision, and its audit evidence atomically.
* Represent money, quantities, and rates without binary floating-point loss.
* Make backups complete from a closed set of referenced artifacts and versions.
* Keep local-first operation and avoid a new database service.
* Preserve the supported CLI/JSON and DuckDB read concepts through adapters.
* Allow a verified cutover and recovery path that never discards post-cutover
  writes.

## Considered Options

1. Keep CSV partitions authoritative and add more manifests and locks.
2. Dual-write CSV and SQLite indefinitely.
3. Use one SQLite database as authority, content-address immutable sources, and
   regenerate CSV and reports as derived artifacts.
4. Replace the local data directory with a hosted database service.

## Decision Outcome

Chosen option: **one SQLite database as authority, immutable source artifacts,
and derived CSV**, because it gives finjuice transactional constraints and a
closed backup graph while retaining local operation and compatibility exports.

The authority depends on the active dataset generation:

| Phase | Authoritative state | Allowed writers |
| --- | --- | --- |
| Current and pre-cutover | Existing CSV/YAML/JSONL data tree | Existing 0.7.x writers |
| Migration build and verification | Frozen legacy manifest for the candidate; existing live tree remains authoritative | Candidate builder writes only a separate staging directory |
| Cutover maintenance window | Frozen final legacy manifest until activation | Live/legacy writers and the repository mutation API are fenced; only the isolated builder may write a new staging candidate |
| Activated generation | One SQLite database plus its referenced immutable source objects | Repository mutation API only |
| Derived output | Never authoritative | Deterministic exporter only; edits are ignored and overwritten on regeneration |

There is no live CSV/SQLite dual-write mode. Compatibility CSV is a projection
of a committed database revision and carries a manifest identifying that
revision. A consumer must reject or label a stale projection.

Source bytes are immutable and identified by SHA-256. Their original filename,
import occurrence, parser version, source coordinate, and observations are
stored as provenance records; a mutable path is not identity. SQLite rows use
stable opaque IDs. Legacy keys such as `row_hash` and `file_id` remain permanent
aliases, not primary keys.

Money, quantities, prices, and exchange rates use an exact decimal contract:
a signed base-10 integer coefficient stored as canonical text, a non-negative
scale, and an explicit currency or unit where applicable. Implementations parse
and calculate with `decimal.Decimal`; they do not pass authoritative values
through `float`. The original legacy lexical value is retained for migration
evidence. Aggregation never adds unlike currencies without an explicit,
versioned conversion observation and rounding policy.

Every accepted mutation creates its state changes, dataset revision,
idempotency result, and audit/changeset rows in one SQLite transaction. An
expected-revision mismatch or busy timeout fails without partial success.
Out-of-band JSONL audit is legacy input after cutover and is not the audit
authority.

The first migration is a preservation baseline. It does not merge accounts,
deduplicate rows, infer owners, recategorize transactions, or reinterpret
assets. Later semantic corrections are explicit reversible changesets with
before/after values, evidence, actor, reason, and affected revision.

The detailed executable contract, migration gates, compatibility rules, backup
contents, and synthetic acceptance scenarios are in
[`ssot-migration-recovery-contract.md`](../../development/ssot-migration-recovery-contract.md).

### Release and activation

The storage cutover is a `1.0.0` release candidate under the current policy,
which defines a breaking data layout as a major change. Backup and inspection
features that do not change the active authority may ship on `0.7.x`. This ADR
does not change the runtime version.

Activation records one verified release artifact digest and one verified
dataset generation together. Installing code, building a candidate database,
or merging its PR does not activate SQLite. Legacy-writer fencing is enabled
only during the actual cutover maintenance window. The cutover order is:
enter maintenance; stop and fence every inventoried legacy writer; capture and
verify the final baseline under that fence; build and verify the final dataset;
then activate the release/dataset pair and open only the new repository writer.
The fence remains in force for legacy writers after activation.

An earlier M1 backup stops all inventoried writers for the capture, or reads a
named filesystem/volume snapshot taken after stopping those writers. A live
directory walk and stat/hash checks alone are not a consistency boundary. CSV
remains authoritative, and this temporary capture boundary is not the permanent
legacy-writer fence used at cutover.

### Rollback boundary

Before the first successful SQLite write, activation may be reverted to the
frozen legacy baseline after verifying its manifest. After any new SQLite write,
the old baseline may be mounted read-only for diagnosis but must not overwrite
the active generation. Recovery first snapshots all new writes, then uses
fix-forward or a verified replay/reapplication into a new generation.

### Consequences

**Positive**:

* State and audit evidence share one commit boundary.
* Foreign keys, uniqueness constraints, revisions, and idempotency can prevent
  orphaned state and lost updates.
* A database snapshot and its immutable reference graph define a verifiable
  full backup.
* CSV, Polars, and DuckDB remain available as read and interchange layers.

**Negative**:

* Binary database diffs are not useful in Git or ordinary text tools.
* Exact-decimal adapters and deterministic exports require more code than a
  direct CSV scan.
* Cutover requires a maintenance window, writer inventory, backup, isolated
  restore, and release/dataset activation controls.

**Mitigations**:

* Generate revision-stamped CSV and privacy-safe verification reports.
* Keep content-addressed source bytes and permanent legacy mappings.
* Exercise the same acceptance contract on synthetic fixtures and a private
  frozen copy before activation.
* Preserve the pre-cutover baseline and require forward recovery after new
  writes.

### Confirmation

This decision is confirmed only when #431 through #440 implement and pass the
gates in the executable contract. #430 accepts the design; it does not claim
that SQLite authority, a complete private inventory, off-device restore, or an
operational cutover already exists.

## Pros and Cons of the Options

### Keep CSV authority

* Good, because current tools already read and write it.
* Bad, because related state and audit files cannot share one transaction.
* Bad, because completeness and referential integrity stay procedural.

### Permanent dual-write

* Good, because old readers could continue unchanged.
* Bad, because partial failure creates two competing authorities.
* Bad, because reconciliation becomes a permanent financial correctness risk.

### SQLite authority with derived CSV

* Good, because it provides local ACID transactions and integrity constraints.
* Good, because the standard-library `sqlite3` runtime needs no server.
* Good, because compatibility files can be regenerated from a named revision.
* Neutral, because source bytes and configuration revisions still need explicit
  lifecycle management outside the database file.

### Hosted database

* Good, because it could centralize concurrency and remote access.
* Bad, because it conflicts with local-first privacy and adds an operational
  service that the current single-user system does not need.

## More Information

ADR-0003 and ADR-0006 continue to assign ETL to Polars. ADR-0004 continues to
assign SQL analytics to DuckDB, but its input becomes a revision-pinned adapter
rather than authoritative CSV. ADR-0007 continues to make CLI JSON the public
agent API. ADR-0010's proposal-first rule remains; applied changes move into the
same atomic repository transaction as their audit state.

---

**Template**: MADR 3.0.0 (Markdown Any Decision Records)
**Reference**: https://adr.github.io/madr/
