# Release Process

Short rules. Details for artifacts and attestations live in
[release-artifacts.md](release-artifacts.md) and
[release-provenance.md](release-provenance.md).

## Versioning

SemVer while pre-1.0:

| Bump | Use when |
| --- | --- |
| MAJOR (`1.0.0+`) | Breaking data layout, CLI JSON contract, or command removal |
| MINOR (`0.x.0`) | New command, new user-facing flag, or additive JSON field |
| PATCH (`0.x.y`) | Bug fix, docs, internal refactor, non-breaking skill wording |

Do **not** tag a version string that already shipped as an untagged `main`
install. Agents and `uv tool` would see the same number for different code.
`0.7.2` and `0.7.3` were untagged package versions; do not reuse them.

## Changelog

`CHANGELOG.md` follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

- User-facing PRs add a bullet under `## [Unreleased]` (`Added` / `Changed` /
  `Fixed` / `Removed`). Refactor-only PRs skip this.
- Release prep moves those bullets into `## [X.Y.Z] - YYYY-MM-DD` and leaves
  Unreleased empty.
- Do not paste git logs, amounts, merchant names, or local paths.

## Version surfaces

These must match on every tagged release (CI checks the in-tree ones):

- `pyproject.toml` `[project].version`
- `uv.lock` package `finjuice`
- `src/finjuice/__init__.py` `__version__`
- `src/finjuice/pipeline/doctor/skill_runtime.py` `SKILL_RUNTIME_REQUIRED_VERSION`
- skill `--require-version` / `Minimum finjuice` (via `scripts/bump_version.py`)
- `CHANGELOG.md` heading `## [X.Y.Z]`
- git tag `vX.Y.Z` (created **after** the bump PR is on `main`)

## Cut a release

1. Worktree from `origin/main`. Dry-run, then bump and refresh the lock:

   ```bash
   just bump-version-check X.Y.Z
   just bump-version X.Y.Z
   ```

   `just bump-version` runs `scripts/bump_version.py` and `uv lock`.

2. Move `CHANGELOG.md` Unreleased notes into `## [X.Y.Z] - YYYY-MM-DD`.
   Point the `[Unreleased]` compare link at `vX.Y.Z...HEAD`.

3. Check in-tree surfaces, then PR:

   ```bash
   just version-check
   ```

4. After the bump PR is on `main`, annotated-tag the **merge SHA** (not an
   untagged HEAD install of an older number):

   ```bash
   git tag -a vX.Y.Z <merge-sha> -m "Release vX.Y.Z"
   git push origin vX.Y.Z
   ```

5. Wait until workflow `release.yml` on that tag is green and GitHub Releases
   shows `vX.Y.Z` as Latest.

6. Install from the tag, keeping extras already on the tool:

   ```bash
   uv tool install --force --with duckdb git+https://github.com/sungjunlee/finjuice@vX.Y.Z
   finjuice version
   ```

Do not tell agents to run a brand-new command until this install step is done.
`uv tool install git+https://github.com/sungjunlee/finjuice` without a tag
tracks `main` and is not a release.

## Public contract

Supported public contract: `finjuice ... --json` plus `schemas/` and
`docs/reference/json-schemas.md`. Python modules under `src/finjuice` are
internal until a deliberate public API exists.

PyPI stays disabled until
[pypi-trusted-publishing.md](pypi-trusted-publishing.md) is complete.
