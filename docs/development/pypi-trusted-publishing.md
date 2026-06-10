# PyPI Trusted Publishing Runbook

PyPI publishing is not enabled for finjuice yet. This runbook documents the
activation path so a future release can switch from the current GitHub/`uv tool`
developer preview to PyPI with one small, reviewed workflow change.

PyPI Trusted Publishing uses GitHub Actions OpenID Connect (OIDC) to mint
short-lived publish credentials at release time instead of storing long-lived
PyPI API tokens in GitHub secrets. Use PyPI's canonical documentation as the
source of truth:

- <https://docs.pypi.org/trusted-publishers/>

## Preconditions Checklist

Do not enable the `publish:` job until every item below is complete.

- [ ] Version surfaces are aligned:
  - [ ] `pyproject.toml` `[project].version` matches the intended tag.
  - [ ] `src/finjuice/__init__.py` `__version__` matches if the version is
        exposed there.
  - [ ] `CHANGELOG.md` has an entry for the tag.
- [ ] CLI JSON schema compatibility has been checked against the latest PyPI
      release, or the release is explicitly documented as the first PyPI
      release exception.
- [ ] Installed-artifact smoke tests are green for the wheel and sdist. This
      includes the package artifact smoke and installed CLI JSON schema smoke
      gates added by PR #666 and PR #667, documented in
      [`release-artifacts.md`](release-artifacts.md) and
      [`cli-json-smoke.md`](cli-json-smoke.md).
- [ ] Release artifact attestation and SBOM generation are green for the same
      artifact set. These gates were added by PR #668 and are documented in
      [`release-provenance.md`](release-provenance.md).
- [ ] Repository visibility is public, or the release plan documents how PyPI
      publishing and downstream attestation verification will work from a
      private repository.
- [ ] PyPI project namespace ownership for `finjuice` is confirmed.

## Step-By-Step Setup

1. Create the PyPI project name if it is not already taken.

   For a first release, use PyPI's pending publisher flow so the first trusted
   publish creates the project. If the project already exists, configure the
   publisher from that project's publishing settings.

2. On PyPI, add a Trusted Publisher:

   - Owner: `sungjunlee`
   - Repository: `finjuice`
   - Workflow: `release.yml`
   - Environment: `release`

3. In GitHub repository settings, create the release environment:

   - Open Settings -> Environments.
   - Create an environment named `release`.
   - Add the protection rule `Required reviewers`.
   - List the maintainer as the required reviewer.

4. Uncomment the `publish:` job in `.github/workflows/release.yml` and configure
   it for Trusted Publishing:

   - Keep `environment: release` on the publish job.
   - Add job permissions with `id-token: write`; keep other permissions minimal.
   - Use `pypa/gh-action-pypi-publish@release/v1`.
   - Do not add PyPI username, password, or API-token secrets.

   The publish job should rely on GitHub OIDC plus the PyPI Trusted Publisher
   entry. It should not use `TWINE_PASSWORD` or a stored PyPI API token.

5. For the first publish, target TestPyPI before production PyPI:

   - Add a separate Trusted Publisher entry on TestPyPI.
   - Configure the publish action with `repository-url:
     https://test.pypi.org/legacy/`.
   - Publish the candidate artifact to TestPyPI.
   - Install from TestPyPI in a fresh virtual environment and verify the CLI.
   - Remove the TestPyPI-only action configuration, then switch to production
     PyPI after the same gates remain green.

## Verification After First Publish

After the first production PyPI publish:

```bash
python -m venv /tmp/finjuice-pypi-smoke
/tmp/finjuice-pypi-smoke/bin/python -m pip install --upgrade pip
/tmp/finjuice-pypi-smoke/bin/python -m pip install finjuice
/tmp/finjuice-pypi-smoke/bin/finjuice --version
```

Confirm:

- `pip install finjuice` works in the fresh virtual environment.
- `finjuice --version` matches the release tag without the leading `v`.
- Artifact attestation is visible at
  <https://github.com/sungjunlee/finjuice/attestations>.

## Rollback Procedure

PyPI artifacts are immutable. `pip install twine && twine upload
--skip-existing` is not a rollback mechanism; it only attempts another upload
and skips files that already exist.

If a published PyPI release must be withdrawn, yank the release from PyPI:

- Preferred: use PyPI's project web UI and choose `Yank release`.
- Alternative: use `pypi-cli` with appropriate project-owner authentication to
  yank the release.

If the GitHub release or tag also needs to be removed:

```bash
gh release delete vX.Y.Z
git tag -d vX.Y.Z
git push origin :refs/tags/vX.Y.Z
```

Only delete the GitHub tag when the release should no longer be discoverable as
an official source release.

## Do Not Flip Yet Gates

Do not uncomment or merge the PyPI `publish:` job until:

- Every precondition checklist item is green.
- A maintainer explicitly approves PyPI activation in a release planning issue
  or in the PR description that enables publishing.
- The current repository behavior is still understood as GitHub/`uv tool`
  developer preview until that PR lands.

## Related Documents

- [`release-artifacts.md`](release-artifacts.md)
- [`cli-json-smoke.md`](cli-json-smoke.md)
- [`release-provenance.md`](release-provenance.md)
- [`release.md`](release.md)
