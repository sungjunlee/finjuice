# Inactive restored workspace implementation

This implements the isolated typed mutation and rebackup path in recovery
contract section 6. It does not finish #437's external release/dependency binding,
reference pinning, operating CLI or private off-device acceptance.

## Explicit restored copy

`restore_workspace(backup_root, destination)` creates a fresh private workspace.
Its `generation/` contains the existing verified SQLite restore;
`restore-control/descriptor.json` records the restore ID, initial generation,
schema, revision, database digest and source manifest digest. Control files stay
outside the generation payload. No source or host activation file is written.

The receipt describes the snapshot actually restored, including when a container's
current pointer changes after preflight. The descriptor and its parent directories
must be flushed before the call returns a receipt. Failed workspaces remain for
inspection; the call does not return a successful receipt. Existing destinations,
including dangling symlinks, are rejected.

The caller must retain `RestoredWorkspaceReceipt` independently and supply it to
`InactiveRestoreSession`. The session does not discover authority from a marker
alone. Exact descriptor fields, duplicate-key rejection and digests detect changes;
they are local evidence, not authentication against an operator who can rewrite
both the workspace and the independently supplied receipt.

## One typed mutation engine

An inactive session uses `GenerationBinding`, which has no activation tuple.
Active `MutationService` retains its existing lease, independent activation
evidence, revalidation and handler authority. Both call the same typed engine for
manual/config/domain validation, optimistic revision checks, audit, idempotency,
commit receipts and rollback. An error after object publication retains the
immutable object instead of pretending that a database change committed.

Inactive operations hold an exclusive workspace coordination lease and recheck
the descriptor, physical root/generation/database identities and database guards.
The mutation engine revalidates after `BEGIN IMMEDIATE`. Database and SQLite
sidecar hardlinks, symlinks and replaced paths are rejected. Separate handles
coordinate through the same lease; a single handle rejects reentrant operations.
These are checks and advisory coordination for cooperating operations, not a
guarantee against arbitrary concurrent OS-level replacement.

`read_snapshot` materializes a detached result from `RepositoryReader`, and
`backup` captures this explicitly selected database with the Online Backup API.
The physical restore ID distinguishes copies while preserving the original
dataset generation, entities, exact values and historical idempotency receipts.
New intent needs a new idempotency key; old requests retain their replay meaning.

## Initial evidence and current state

The original manifest describes the initial restore. After a committed edit its
database digest is historical and is not rewritten to certify the changed copy.
Current reads validate repository integrity, object closure, generation, schema
and the initial revision floor. At the initial revision the original complete
payload is also checked. A fresh backup records the changed revision and can be
restored into another inactive workspace. Old source backups remain unchanged.

`retire()` writes a durable terminal marker under the workspace lease. Other
handles and receipt-based reopen then fail closed. `close()` invalidates only the
local handle. Future operational activation must retire the copy through this
same coordination boundary before enabling active writes; the current API does
not promote copies or detect activation by an arbitrary external data root.
Retirement tests do not prove that future activation integration is complete.

## Referenced object durability

Source object reuse now flushes its destination directory before returning a
receipt. A visible object can have survived an earlier publisher's fsync failure;
visibility and matching bytes alone do not prove durable publication. Both new
and reused publication retain the content-addressed object on failure. Temporary
file removal flushes the temporary file's actual parent directory.

The previous explicit link-removal branch caught an `OSError` that the real
directory helper wraps as `ObjectStoreError`; ordinary disk errors already
retained the object. The reproduced defect was a later reuse returning success
without retrying directory synchronization. Removing the obsolete removal branch
also makes the preservation rule explicit. This is not a GC pin implementation.

Canonical config heads, all revision rows and exact source object bytes are
already in the snapshot closure. Tests change the live head after capture and
verify that backup, restore and rebackup retain the captured selection/history,
including invalid and unselected configuration. Live YAML is not copied again.
