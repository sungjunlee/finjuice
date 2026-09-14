# Inactive migration recovery capsule

`storage.sqlite.recovery_migration_capsule` preserves an original inactive
migration candidate in a fresh independent capsule. It is not an online backup
of an operating SQLite database, activation, release binding, GC pin or a complete
section 6 recovery bundle.

`ExpectedMigrationCapsule` requires existing `ActivationEvidence` and explicit
`migration_semantics` / `pre_cutover_semantics`: either `raw_file_sha256` or
`canonical_manifest_digest`. Activation evidence values remain plain lowercase
64-character hex, without `sha256:`. The helper compares only the specified
meaning; it never tries both interpretations until one matches. The receipt
retains raw and canonical digests separately and excludes paths and raw data.

`capture_migration_capsule(candidate, destination, expected)` copies four fixed
proof files and exactly the objects referenced by the copied database:

- `candidate/finjuice.sqlite3`
- `candidate/manifests/migration-manifest.json`
- `candidate/manifests/plan-evidence.json`
- `candidate/FINJUICE_MIGRATION_COMPLETE`
- `candidate/objects/sha256/<prefix>/<digest>`

Known `.finjuice` paths and live SQLite WAL/SHM/journal sidecars are rejected.
Before opening the copied DB for its inventory, its raw digest must match the
copied migration manifest. Every source file uses stable descriptor-based reads
or copies. Unknown files/directories, special files and symlinks fail; normal
empty candidate `derived`, `objects` and `objects/sha256` directories are allowed.
There is no live YAML or original capture directory fallback.

Full verification invokes existing `verify_migration` on the **copied candidate**.
That verifier reconstructs the original capture from retained object bytes,
restores inventory metadata and completion marker, runs capture `verify_backup`,
and replays migration adapters to compare semantic state. The original capture
manifest object must equal the migration manifest's capture structure and its
raw digest; its canonical digest is also validated with the original capture
manifest rules. A standalone manifest hash is not accepted as object-closure
proof. Adapter replay remains consistency evidence, not an independent parser.

Publication uses a private sibling staging directory, exclusive file creation,
write-all and strict file/tree fsync. `migration-capsule.json` is written last,
with an exact file inventory and canonical selfdigest, then the capsule is fully
verified. Real-directory identities are rechecked before no-replace rename and
parent fsync. Existing or dangling destinations and source overlaps are rejected;
a concurrently created destination is not replaced. Cleanup only removes the
still-owned staging directory. A post-rename durability failure raises without
a success receipt even if a complete candidate remains for explicit inspection.
This does not promise safety against arbitrary uncooperative filesystem changes.

`verify_migration_capsule(capsule, expected)` checks the exact capsule inventory,
selfdigest, independently supplied migration/pre-cutover identities and the full
copied candidate proof. Synthetic tests delete the original candidate, source and
capture, then verify using only capsule data; tests also cover wrong semantics,
missing objects, mutation, symlinks/special files, overlap, publication races and
fsync failure. No host/source activation is written.

Inventory and receipt equality uses canonical JSON bytes, preserving number and boolean types; Python numeric equality cannot make a float count or size equivalent to an integer.
