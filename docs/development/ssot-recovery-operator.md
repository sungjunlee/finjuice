# Local recovery-graph operator CLI

This is the operator-facing capture, verify, and inactive restore flow for a
local recovery graph. It does not complete GC pinning, off-device copy,
encrypted key recovery, capacity checks, or measured RPO/RTO.

Existing `ssot backup create`, `status`, and `restore` remain snapshot
commands. The graph commands are:

```text
finjuice ssot backup capture-bundle
finjuice ssot backup verify-bundle
finjuice ssot backup restore-bundle
```

Success means the published graph matched independently enrolled expectations
and, for restore, that an inactive workspace receipt was issued. It is not a
recoverable/operational-complete boolean and never activates a host or source.

## Independent expected enrollment

`--expected` is a regular-file JSON document the operator retains separately.
Capture, verify, and restore never fill, copy, or correct it from
`active.json`, a migration candidate, release paths, or the bundle body.

Enroll the same DTO fields as `ExpectedRecoveryGraph` with exact keys and no
duplicates:

- `activation_evidence`: `installed_release_version`,
  `installed_release_artifact_sha256`,
  `verified_migration_manifest_sha256`,
  `verified_pre_cutover_backup_manifest_sha256`
- `activation_sha256`: SHA-256 of the exact enrolled `active.json` bytes
- `release.binding_sha256` and a nested `activation_evidence` object
- `capsule.migration_semantics`, `capsule.pre_cutover_semantics`, and a nested
  `activation_evidence` object
- `wheel_basename` of the form `finjuice-<version>-py3-none-any.whl`

Nested `activation_evidence` values must equal the top-level object. Semantics
are `raw_file_sha256` or `canonical_manifest_digest`. Types are strict: JSON
booleans are not strings, extra keys fail, and duplicate keys fail. Read uses
stable regular-file I/O and does not follow symlinks.

## Commands

`capture-bundle` requires explicit `--source-data-dir`, `--output`,
`--wheel`, `--dependency-lock`, `--binding`, and `--migration-candidate`. It
builds `StaticActivationEvidenceProvider` from the enrolled evidence and calls
`capture_recovery_bundle`. The host `--data-dir` is not the capture source.

`verify-bundle` calls `verify_recovery_bundle` with the same enrolled document.
It does not consult the source workspace.

`restore-bundle` loads expectations, applies the existing active-root,
configuration, and path guards, verifies the full graph, then restores only
`bundle/snapshot` through `restore_workspace`. Human and JSON output keep the
complete seven-field inactive receipt. Before emitting success, the command
requires its source manifest digest, generation, schema, and revision to match
the verified graph receipt. Capture and verify receipts expose
`snapshot_manifest_digest` for this linkage. The command does not write an
activation pointer. A mismatch returns an error without a success receipt;
the already-created inactive workspace can remain for inspection, and a retry
must use a fresh target. Source data and activation records are unchanged.

CLI errors are static and omit source paths and private file contents.
