# Trusted-host CLI runtime

Ordinary `finjuice` has no launch path that injects activation evidence. Tests
and a trusted host may pass `activation_evidence_provider` through Typer
`ctx.obj`; `StaticActivationEvidenceProvider` does not bind that evidence to a
data root. This runtime is the missing operator bridge for that injection.

It is not activation, cutover, consumer conversion, or operational acceptance.

## Trust boundary

The operator independently retains an enrollment file and supplies its SHA-256
as a pin. That pin authorizes the enrollment document. `active.json`,
`FINJUICE_DATA_DIR`, and other untrusted data files cannot approve a root,
release, or evidence set.

Enrollment is not a copied activation pointer. It names an authorized data
root, independent activation evidence, and separately retained release
artifacts. The runtime verifies those artifacts with
`verify_release_artifacts`, then requires the currently imported `finjuice`
package files to match the approved wheel members. A matching version string
on a different installed wheel cannot claim that identity.

## Operator entry

Host flags are not added to the ordinary CLI:

```text
python -m finjuice.pipeline.cli.host_runtime \
  --enrollment <retained-enrollment.json> \
  --digest <sha256> \
  -- status --json
```

Host options end at `--` or the first CLI argument; command values cannot
replace the enrollment pin. Compact root options are checked too.

Remaining arguments are passed to the existing Typer app after the enrolled
`--data-dir` is forced. A mismatched root-level `--data-dir` is rejected
before any command runs. The runtime does not create activation records,
change permissions, or mutate source trees.

## Enrollment document

Exact keys, no duplicates, regular file, no symlinks:

- `data_root`: absolute authorized data directory
- `activation_evidence`: the existing four evidence fields
- `release.binding_sha256` and nested `activation_evidence` (must equal the
  top-level object)
- `artifacts.wheel`, `artifacts.dependency_lock`, `artifacts.binding`:
  absolute paths to independently retained files
- `wheel_basename`: `finjuice-<version>-py3-none-any.whl`

Release binding JSON stays on the existing exact-key contract in
[ssot-recovery-release-evidence.md](ssot-recovery-release-evidence.md).
Malformed, incomplete, symlink, digest, root, release, or imported-code
mismatches fail closed with a static error. New errors and logs must not
include private raw values, paths, or financial rows.

## Installation and copied datasets

Export the production dependency lock with the `analytics` extra when the host
will run query, explain, or analytics consumers. A base-only lock omits DuckDB.
Retain that exact lock in the independently approved release binding.

When transferring a verified generation, preserve immutable object permissions
as well as bytes. Validate object lengths and hashes after extraction and reject
write permission bits before opening the repository. Changing the validation
rule is not a substitute for preserving the copied generation correctly.

Default transaction query, status, explain, and export use proven primary
partition scope plus native records. Preserved historical rows remain in the
repository; status source diagnostics still report their separate scope.
