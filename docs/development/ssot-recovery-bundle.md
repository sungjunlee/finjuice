# Local recovery graph wrapper

`storage.sqlite.recovery_bundle` captures one composable **local recovery
graph** and independently verifies it. It is not an off-device copy, encrypted
key route, capacity/RPO/RTO measurement, or complete section 6 operational
acceptance.

The helper returns a `local_graph_verified` receipt. Success means the published
tree matched caller-supplied trusted expectations and the recorded role graph.
It is not a recoverable/operational-complete boolean.

## Inputs

`capture_recovery_bundle(source, expected)` takes `RecoveryCaptureInput`
(`data_dir`, fresh `destination`, `ActivationEvidenceProvider`,
`ReleaseArtifactPaths`, immutable `migration_candidate`) and
`ExpectedRecoveryGraph`. Expected values are independently retained by the
caller: exact activation SHA-256, `TrustedReleaseBinding`,
`ExpectedMigrationCapsule`, and the valid wheel basename. The helper does not
derive those expectations from `active.json`, a candidate binding, or the
bundle manifest.

Activation evidence must be the same object values across provider, release
binding and capsule. The wheel basename is packaging metadata of the form
`finjuice-<version>-py3-none-any.whl`, preserved for later recorded-artifact
installation. It is not a trust root. This helper does not install the wheel or
prove installability.

## Capture

Capture builds `AuthorityPaths.for_data_dir` and holds `shared_write_lease`
through final parent fsync. It resolves repository authority with the supplied
provider, reads exact `active.json` bytes with `read_regular_bytes`, and checks
`read_activation` against those bytes and the expected SHA. Release artifacts
are verified once; publication copies the retained wheel/lock/binding buffers
and never reopens the operator paths. The immutable migration candidate is
preserved through the existing capsule helper. The live generation is snapshotted
with SQLite Online Backup (`create_backup`); a private scratch restore runs the
existing integrity/FK/invariant/object checks, then `inspect_repository`
confirms schema/generation match the activation tuple and that the current
revision is recorded separately and is not below the activation baseline.

Before no-replace publication the provider, activation tuple and exact bytes are
re-read. Every payload is fsynced; a late fsync failure is an error even if
bytes remain visible. Existing destinations and sources are never deleted or
replaced. Source/destination overlap, dangling targets, unknown entries,
symlinks and special files fail closed. The `activation/` and `release/` roles
contain only their declared files; nested directories, including empty ones,
are rejected.

## Independent verify

`verify_recovery_bundle(bundle, expected)` uses only the published graph plus
the same caller-trusted expected evidence. It does not consult the source
workspace, host activation pointer, or evidence provider. Checks include exact
file inventory, strict manifest schema, role edges, release helper retained
bytes, full capsule replay, and restored SQLite logical validity. Mixed graphs,
missing roles, pointer/provider/evidence changes and object tampers fail. Error
text is static and excludes source private data.

## Retention is not implemented

Current GC has no supported deletion lifecycle and no durable pin registry.
This helper does not add dummy GC or fake pin flags. The shared coordination
lease currently serializes cooperating exclusive maintenance
(`exclusive_maintenance_lease` remains the existing exclusive API). Holding
that lease during capture is not a durable reference pin. Retention acceptance
for the Online Backup reference set remains to implement and prove.

Existing CLI commands are unchanged.

Failed captures clean still-owned staging and scratch trees even before ownership returns to the outer publication function. Receipt and inventory comparisons preserve JSON numeric types rather than accepting Python integer/float equality.

The graph receipt includes `snapshot_manifest_digest` from the verified scratch
restore. It must equal the selected snapshot manifest digest, binding the
receipt to exact snapshot identity in addition to generation/schema/revision.
