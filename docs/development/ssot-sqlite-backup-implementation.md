# SQLite backup publication implementation

The complete recovery contract remains in
`ssot-migration-recovery-contract.md`, section 6. This implementation checkpoint
addresses safe local publication and shared byte verification for #437. It does
not complete the activation/release binding, reference pinning, inactive restore
descriptor, private recovery or operating CLI acceptance gates.

## Independent attempts

`storage.sqlite.backup.create_backup(database, destination_root)` creates a private
attempt, captures SQLite through its Online Backup API, copies the snapshot's
recorded source objects, and validates the captured repository. Each attempt has
its own database, object tree and version-1 `backup-manifest.json`.

The complete attempt tree is flushed and published with a no-replace directory
rename beneath `attempts/<attempt-id>/`. Only after verification does publication
atomically replace `backup-current.json` and flush the parent directory. The
pointer contains exactly `pointer_schema_version`, `attempt_id`, `manifest_path`
and `manifest_digest`. The digest is the referenced manifest's canonical
self-digest; the path is relative to the container.

Previous attempts are never reused, pruned or replaced. Repeated captures of
unchanged content preserve payload digests but create new attempt identities.
There is no retention GC or claim that concurrent completion order represents the
highest source revision. A failed attempt is not a failed financial mutation.

Failure before pointer publication leaves the previous selected attempt intact.
Directory fsync failures propagate, including after a rename has already taken
effect: the call returns no successful receipt. A published but unselected attempt
may remain available for explicit verification. Failure after pointer replacement
can leave the new pointer visible despite unconfirmed crash durability; the
previous attempt remains independently intact. Inspection after a restart does
not retrospectively prove that the failed fsync succeeded.

## Verification and compatibility

Create finalization, status and restore use one strict receipt/payload verifier.
It checks exact manifest keys, duplicate JSON keys and file paths, one database
entry, canonical object paths, sizes, digests and the complete declared file tree.
Regular-file reads use no-follow descriptors and check file/ancestor stability.
Symlinks, special files, unlisted files and unrelated directories cannot satisfy
the verifier. Writes handle partial writes and reject zero progress.

Restore first verifies its source, copies into a separate empty directory, checks
database integrity, foreign keys, application invariants and source references,
then verifies and flushes the resulting tree. It does not modify the source
generation or install an activation pointer. Its current target remains a direct
version-1 layout; the required explicit inactive descriptor is a later gate.

Direct version-1 backups remain readable and restorable under the stricter
verifier. Creating into such a destination is rejected without modifying it; use
a new container. Unknown fields, links, duplicate entries or extra payload that
older status checks overlooked are verification failures. No compatibility file
is written beside the new container pointer.

The existing Python result fields and privacy-safe `to_dict()` shapes are retained.
The result's `manifest_path` identifies the actual published attempt. The legacy
`finjuice backup` CLI is unchanged; this checkpoint does not silently route its
full-tree contract through a SQLite-only backup.

These are local self-digested receipts, not authenticated evidence against someone
who can rewrite both the payload and its receipt. Snapshot byte consistency does
not replace external activation/release binding or source-reference GC pinning.
Operational acceptance still requires the recorded artifact, private corpus,
off-device/key recovery, restored manual mutation and rebackup, and measured
recovery results specified by #437 and the recovery contract.
