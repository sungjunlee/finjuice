# SQLite preservation storage

The `finjuice.pipeline.storage.sqlite` package implements the storage foundation
for an isolated preservation candidate. The active 0.7.x CLI still uses the
existing CSV dataset. Creating or validating a database does not activate it.
The authority and cutover rules remain in
[ADR-0014](../architecture/decisions/0014-sqlite-authoritative-storage.md) and the
[migration/recovery contract](ssot-migration-recovery-contract.md).

## Storage roles

`GenerationPaths` names the roles below a caller-selected generation directory:

| Path | Role |
| --- | --- |
| `finjuice.sqlite3` | Candidate relational state; authoritative only after verified activation |
| `objects/sha256/<prefix>/<digest>` | Immutable original bytes |
| `manifests/` | Preservation and verification evidence |
| `derived/` | Regenerable projections, never a source of truth |

`SourceObjectStore` streams and hashes original bytes before atomic publication.
Existing objects are reused only after their length and hash are checked.
Separate source occurrences can reference the same object without merging their
provenance or legacy records. Source objects must be retained alongside the
database; copying the SQLite file alone is not a complete generation backup.
File-based publication requires a canonical source path without symlinked
ancestors. Resolve an approved system alias explicitly before calling
`publish_source_path` or `publish_path`; the file API rejects aliases rather than
silently following them.

New generation directories use mode `0700`, and new database staging files use
`0600`. Existing writable namespace directories must already be private; the
write APIs reject group/other-accessible directories instead of changing their
permissions. Read-only source inspection does not alter source permissions.

## Minimal isolated example

This example uses synthetic bytes in a temporary directory. `finalize()` makes
the candidate database visible only after validation. Leaving the builder
context without finalizing discards the unpublished database. Original objects
already published by that attempt remain in the selected generation directory;
abort does not delete source bytes. The builder rejects an existing database,
but it does not resolve operational activation or legacy runtime fences. Callers
must select an isolated candidate directory; they must never reuse an active
generation path, including during recovery. The caller must account for those retained
objects when inspecting or retiring a failed candidate. The immutable
`builder.published_artifacts` tuple remains available after abort; `abort()`
also returns that receipt.

```python
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.repository import RepositoryBuilder, RepositoryReader

with TemporaryDirectory() as directory:
    paths = GenerationPaths(Path(directory).resolve() / "candidate")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        artifact = builder.publish_source(BytesIO(b"synthetic source bytes"))
        assert not paths.database.exists()
        info = builder.finalize()

    with RepositoryReader(paths.database) as reader:
        assert reader.info == info
        assert reader.rows("source_artifacts")[0]["source_artifact_id"] == artifact.artifact_id
```

## Identity and exact values

New entity IDs are UUIDv4. Migration IDs use the versioned UUIDv5 namespace and
canonical locator from the recovery contract. The immutable capture-manifest
digest is an input to this identity; a candidate database hash is not.
Each migration-derived UUIDv5 entity has one immutable identity record containing
its capture digest, record kind, and canonical locator. Publication checks the
derivation against the entity ID. Later legacy aliases do not replace this
identity record. Duplicate legacy `row_hash` values remain separate occurrences.
Legacy mappings are retained permanently, and supersession is an additional
relationship.

`ExactValue` stores a canonical integer coefficient as text, scale from 0 to 255,
and original lexical evidence. Money requires a known currency or explicit
`currency=UNKNOWN_CURRENCY`. Quantities and rates use versioned units. Parsing and
reconstruction do not depend on the ambient Decimal precision and do not pass
through binary floats. Source/migration values retain their occurrence provenance;
identical numeric values from different occurrences must not be deduplicated into
one source value. Typed values outside the supported contract must be
retained as opaque evidence and resolved before cutover.

## Inspection and schema safety

SQLite schema version is separate from the legacy CSV schema and backup-manifest
versions. Connections enable foreign keys, and validation checks the application
identity, schema metadata, SQLite integrity, and foreign-key consistency.
Generation/application identity is immutable, revision/schema counters cannot
move backwards, and the immutable migration ledger must match the current schema.
Typed source records must bind observation and provenance to the same occurrence;
config revisions must name the artifact belonging to their occurrence.
Unsupported versions, including an unrecognized schema v0 bootstrap, are
rejected; no destructive downgrade is attempted. A new builder starts at dataset
revision zero. Only a validated source copy carries an existing revision forward.

Inspection operates on a separate checked DB/WAL copy. Opening the original with
ordinary SQLite read-only mode can change SHM state, while `immutable=1` can miss
uncheckpointed WAL state. The snapshot helper rejects observed source changes
and rollback journals. This inspection mechanism does not replace the stopped
writer or filesystem-snapshot boundary required for a migration baseline.

Schema changes build and validate a separate candidate and preserve the source
DB and its sidecars on failure. Missing, mutable, or corrupt referenced source
objects fail as repository integrity errors. A failed copy can retain objects
already published into its isolated destination; it never publishes the
candidate database or deletes those objects to simulate rollback. Candidate
builders use DELETE journaling and
FULL synchronization. Before introducing WAL for operational writes, verify
that the deployed SQLite runtime includes the
[WAL-reset fix](https://www.sqlite.org/wal.html).

A copy at the current schema version retains the logical dataset generation and
revision. It is a validated replica, not a second activation or a fabricated
schema transition. Operational activation must select the verified target tree
and release; finding a matching generation UUID alone does not activate a copy.

`RepositoryReader`, `inspect_repository`, `validate_repository`, and
`upgrade_repository` accept a keyword-only `scratch_root` for inspection copies.
The default is `$XDG_CACHE_HOME/finjuice/sqlite-inspection` when configured, or
`~/.cache/finjuice/sqlite-inspection`. The scratch root must be private and
outside the inspected generation.

Inspection scratch directories contain private database bytes. Normal context
exit removes the scratch copy, but process termination or power loss can leave
residue. Keep the configured scratch root private and inspect leftovers only
after confirming no inspection process is using them. Do not treat abort or a
failed inspection as proof that every temporary byte has been removed.

## Verification boundary

Public tests use synthetic files and records. Acceptance includes duplicate
legacy occurrences, exact decimals, corrupt objects, unsafe paths, invalid
relationships, unsupported schemas, and source preservation during failed
upgrade. Installed-artifact checks exercise the packaged code separately from
the editable checkout.

Atomic accepted mutations and audit/idempotency state are delivered by #434.
Preservation migration, CLI read compatibility, complete SQLite backup, and
private-data acceptance are delivered by #435 through #438. Their completion
must not be inferred from the storage foundation alone. Publication durability
tests check synchronization order and injected errors; they are not physical
power-loss tests. File data and its directory entry require separate attention
under the [Linux fsync contract](https://man7.org/linux/man-pages/man2/fsync.2.html).

## Required schema v2 migration gate

Before #435 imports any frozen dataset, #434 must supply and test the remaining
[contract §9](ssot-migration-recovery-contract.md#9-minimal-m4-extension-points)
extension points alongside the atomic changeset/audit boundary:

- Effective-dated ownership assertions with exact shares, evidence, confirmation,
  and non-overlap/ambiguity validation.
- Explicit inclusion/overlap assertions for summaries, holdings, and manual versus
  institutional facts.
- Agent intake records separating immutable evidence, extraction, interpretation
  proposals, user confirmation, and applied changesets, with idempotency and
  expected-revision checks.

These belong to schema v2 before the first preservation migration. Schema v1's
account owner field preserves a source assertion; it does not establish confirmed
ownership or authorize ownership calculations. Migration defaults remain unknown
or unconfirmed and must not infer ownership, inclusion, or semantic supersession.
The M5 purchase/order/close/adapter domain is outside this extension gate.
