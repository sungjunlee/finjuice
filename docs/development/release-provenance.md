# Release Provenance And SBOM

Tagged releases produce package artifacts, provenance evidence, and an SBOM so a
downstream user can check what source built the release and what dependency
metadata is inside it.

## Release Outputs

For tag `vX.Y.Z`, `.github/workflows/release.yml` publishes these release
assets:

| Asset | Source | Purpose |
| --- | --- | --- |
| `finjuice-X.Y.Z-py3-none-any.whl` | `uv build --out-dir dist --clear` | Installable wheel artifact. |
| `finjuice-X.Y.Z.tar.gz` | `uv build --out-dir dist --clear` | Source distribution artifact. |
| `finjuice-vX.Y.Z.provenance.jsonl` | `actions/attest-build-provenance` | JSONL Sigstore bundle for the built `dist/*` subjects. |
| `finjuice-vX.Y.Z.cyclonedx.json` | `anchore/sbom-action` | CycloneDX JSON SBOM generated from the built `dist/` artifacts. |

The workflow also uploads the same `dist/*` and `release-assets/*` files as a
single Actions artifact named `finjuice-release-vX.Y.Z-artifacts` with 90-day
retention. That backup is for workflow-run recovery; the GitHub Release assets
are the durable distribution surface.

`anchore/sbom-action` is used because it runs Syft directly in GitHub Actions,
can scan the built `dist/` directory, and emits CycloneDX JSON without adding a
runtime dependency to finjuice. Its automatic release and workflow artifact
uploads are disabled so `release.yml` keeps one explicit naming and retention
policy.

## Verify Provenance

After downloading a release artifact, verify its GitHub artifact attestation.
When the repository is public, use GitHub CLI verification:

```bash
gh attestation verify --repo sungjunlee/finjuice finjuice-X.Y.Z-py3-none-any.whl
gh attestation verify --repo sungjunlee/finjuice finjuice-X.Y.Z.tar.gz
```

While the repository is private, this verification path depends on GitHub plan
support. Artifact attestations are available for public repositories on current
GitHub plans, but private and internal repository attestations require GitHub
Enterprise Cloud and are not available on legacy plans. In supported private
repositories, attestations are not written to the public Sigstore transparency
log. They are stored behind GitHub's attestation API and are visible only to
authenticated users with repository access. Query by the artifact SHA-256
digest:

```bash
digest="$(shasum -a 256 finjuice-X.Y.Z-py3-none-any.whl | awk '{print $1}')"
gh api "/repos/sungjunlee/finjuice/attestations/sha256:${digest}"
```

The downloaded `finjuice-vX.Y.Z.provenance.jsonl` bundle is retained as release
evidence, but the GitHub API or `gh attestation verify` path is the preferred
online verification flow.

## Inspect The SBOM

The SBOM is CycloneDX JSON generated from the built release artifacts. Basic
checks can use `jq`:

```bash
jq '.bomFormat, .specVersion, (.components // []) | length' finjuice-vX.Y.Z.cyclonedx.json
```

For schema validation and richer inspection, use `cyclonedx-cli`:

```bash
cyclonedx validate --input-file finjuice-vX.Y.Z.cyclonedx.json
cyclonedx list components --input-file finjuice-vX.Y.Z.cyclonedx.json
```

Syft can also read and convert the SBOM:

```bash
syft scan sbom:finjuice-vX.Y.Z.cyclonedx.json
```

## Current Limitations

- PyPI publication remains disabled; release provenance covers GitHub Release
  wheel and sdist assets only.
- GitHub-native attestation is used instead of custom signing keys.
- Private and internal repository attestations require GitHub Enterprise Cloud.
  On unsupported plans, GitHub-native provenance is unavailable; retain the
  SBOM and Actions build logs as fallback release evidence, but treat source
  provenance as unverified until the repository is public or on a supported
  plan.
- Private-repository attestation visibility, when supported, is restricted to
  GitHub's attestation API and authorized users. If the repository becomes
  public, the normal
  `gh attestation verify --repo sungjunlee/finjuice <artifact>` flow is the
  downstream verification path.
