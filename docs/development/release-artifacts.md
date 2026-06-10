# Release Artifacts

finjuice validates built distributions before release by checking both archive
contents and installed-package behavior.

Release builds also publish provenance and SBOM assets. See
[`release-provenance.md`](release-provenance.md) for artifact attestation,
CycloneDX SBOM, and downstream verification details.

## Smoke Matrix

`scripts/check_package_contents.py` builds the package and verifies that schema
and template resources are present exactly once in the wheel and sdist archives.

`scripts/smoke_installed_artifact.py` then builds fresh artifacts in a temporary
directory, installs each selected artifact into a fresh stdlib `venv`, and runs
the installed console script from outside the checkout:

| Artifact | CLI probes | Resource probes |
| --- | --- | --- |
| wheel | `finjuice --version`, `doctor --json`, `status --json`, `manifest --commands-only --json` | `finjuice.schemas/status.schema.json`, `finjuice.templates/schema.yaml` |
| sdist | `finjuice --version`, `doctor --json`, `status --json`, `manifest --commands-only --json` | `finjuice.schemas/status.schema.json`, `finjuice.templates/schema.yaml` |

The smoke script creates a tiny synthetic data directory for `status --json`.
It does not read the developer's default finjuice data directory.

`scripts/smoke_installed_cli_json.py` adds a wheel-only release gate that runs a
small installed CLI JSON matrix and validates each payload against
`schemas/*.schema.json`. See
[`cli-json-smoke.md`](cli-json-smoke.md) for the matrix and failure categories.

## Adding Probes

Add CLI probes in `command_probes()` in
`scripts/smoke_installed_artifact.py`. Prefer commands that:

- Exit 0 without private user data.
- Emit non-empty stdout.
- Have stable JSON contracts when `json_output=True`.
- Exercise installed package resources or command discovery.

Add packaged resource probes in `RESOURCE_PROBE_CODE`. Keep these focused on
runtime resources that users need after installation, and keep the archive-level
resource list in `scripts/check_package_contents.py` as the source for broad
content coverage.

## Local Debugging

Run the same smoke locally:

```bash
uv run python scripts/smoke_installed_artifact.py
```

Keep the temporary build, venv, and synthetic data directories after a failure:

```bash
uv run python scripts/smoke_installed_artifact.py --keep-temp
```

To narrow a failure to one artifact:

```bash
uv run python scripts/smoke_installed_artifact.py --artifact wheel --keep-temp
uv run python scripts/smoke_installed_artifact.py --artifact sdist --keep-temp
```

Failures include the full captured stdout and stderr for the failed subprocess.
