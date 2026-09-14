# Recovery release evidence helper

`storage.sqlite.recovery_release_evidence` checks a recorded finjuice wheel and
exact dependency lock against a separately trusted build binding. It does not
create a recovery bundle, select activation, install or execute the wheel.

The caller supplies `ReleaseArtifactPaths(wheel, dependency_lock, binding)` and
`TrustedReleaseBinding(binding_sha256, activation_evidence)`. The binding SHA is
the SHA-256 of **raw file bytes**, obtained independently from an approved release
build/source-commit record. Do not calculate this expected value from the
candidate binding or `active.json`. Cryptographic signing is optional hardening,
not an additional requirement imposed by this helper. The helper validates the
supplied relationship; it cannot establish how the caller obtained its trust root.

Binding JSON has exactly these keys:

- `binding_schema_version`: integer `1`, excluding booleans.
- `package_name`: `finjuice`.
- `release_version`: equal to `ActivationEvidence.installed_release_version`.
- `release_artifact_sha256`: lowercase 64-digit raw wheel SHA, equal to the
  independently supplied activation evidence.
- `dependency_lock_sha256`: lowercase 64-digit raw lock SHA.
- `source_commit`: lowercase hexadecimal commit ID of length 40 or 64.
- `build_id`: 1–128 ASCII characters; first character alphanumeric, remaining
  characters alphanumeric or `.`, `_`, `:`, `-`.

Unknown, missing and duplicate JSON keys fail. A manifest self-digest is never a
substitute for the independently supplied raw binding SHA. The lock's relationship
to the release is established by that trusted mapping, not inferred from its
filename, the current checkout or a newly computed local hash.

`verify_release_artifacts(paths, expected)` uses the existing stable regular-file
reader for each of the three files once. It rejects missing, changing, symlink and
special file inputs. All filesystem, JSON and ZIP errors are normalized to a
static `BackupVerificationError` without paths or raw content. No financial rows
or file bytes are logged.

ZIP members are checked without extraction: duplicate names, absolute/parent/
backslash/drive paths, empty path components, symlinks and special files fail.
Exactly one top-level `finjuice-*.dist-info/METADATA` must provide a single exact
`Name: finjuice` and single matching `Version`. Metadata is limited to 8 MiB before
decompression. This verifies the recorded artifact identity and unambiguous
metadata, not wheel installation compatibility, every RECORD entry, dependency
resolution or the entire software supply chain. Actual recorded-wheel installation
and read smoke remain a later acceptance step.

`VerifiedReleaseArtifacts` retains `wheel_bytes`, `dependency_lock_bytes` and
`binding_bytes` with `repr=False`, plus the verified digest/build metadata. Later
bundle publication must copy these retained bytes. Reopening the original paths
would discard the one-read guarantee and introduce a time-of-check/time-of-use
race. The DTO is private recovery evidence; callers must not indiscriminately
serialize it into logs merely because its normal repr excludes the bytes.

This helper does not complete independent trust-root operational wiring, source
GC pinning, migration/pre-cutover manifest closure, the full section 6 recovery
graph, encrypted off-device/key recovery, capacity verification, or measured
RPO/RTO. Canonical config bytes/history already belong to the database/object
closure and are not recopied here.

ZIP central-directory Unicode Path override fields (`0x7075`) are rejected on all supported Python versions, including runtimes that ignore those fields. Original and interpreted member names must agree; malformed extra-field framing is also rejected.

This inventory check follows Python zipfile central-directory names. Local-header-only extra fields are not an installability or cross-extractor compatibility guarantee; full wheel installation/RECORD validation remains outside this helper.
