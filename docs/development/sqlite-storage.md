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

## Minimal isolated example

This example uses synthetic bytes in a temporary directory. `finalize()` makes
the candidate database visible only after validation. Leaving the builder
context without finalizing discards the unpublished database. Original objects
already published by that attempt remain in the selected generation directory;
abort does not delete source bytes. The caller must account for those retained
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
Duplicate legacy `row_hash` values remain separate occurrences. Legacy mappings
are retained permanently, and supersession is an additional relationship.

`ExactValue` stores a canonical integer coefficient as text, scale from 0 to 255,
and original lexical evidence. Money requires a known currency or explicit
`currency=UNKNOWN_CURRENCY`. Quantities and rates use versioned units. Parsing and
reconstruction do not depend on the ambient Decimal precision and do not pass
through binary floats. Typed values outside the supported contract must be
retained as opaque evidence and resolved before cutover.

## Inspection and schema safety

SQLite schema version is separate from the legacy CSV schema and backup-manifest
versions. Connections enable foreign keys, and validation checks the application
identity, schema metadata, SQLite integrity, and foreign-key consistency.
Unsupported versions are rejected; no destructive downgrade is attempted.

Inspection operates on a separate checked DB/WAL copy. Opening the original with
ordinary SQLite read-only mode can change SHM state, while `immutable=1` can miss
uncheckpointed WAL state. The snapshot helper rejects observed source changes
and rollback journals. This inspection mechanism does not replace the stopped
writer or filesystem-snapshot boundary required for a migration baseline.

Schema changes build and validate a separate candidate and preserve the source
DB and its sidecars on failure. Candidate builders use DELETE journaling and
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
`~/.cache/finjuice/sqlite-inspection`.

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
must not be inferred from the storage foundation alone.
