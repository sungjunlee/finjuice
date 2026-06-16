# Release Process

finjuice follows SemVer-style versioning while it remains pre-1.0:

- `MAJOR`: breaking data layout, CLI JSON contract, or command removal
- `MINOR`: additive commands, templates, skill workflows, or JSON fields
- `PATCH`: bug fixes, docs, internal refactors, and non-breaking skill wording

## Version Surfaces

Keep these surfaces aligned:

- `pyproject.toml` `[project].version`
- `src/finjuice/__init__.py` `__version__`
- `finjuice --version`
- JSON `_meta.finjuice_version`
- `finjuice doctor`
- `CHANGELOG.md`
- git tag `vX.Y.Z`

## Distribution Strategy

Current distribution is a conservative GitHub/`uv tool` developer preview. The blessed
runtime install path is:

```bash
uv tool install git+https://github.com/sungjunlee/finjuice
```

Normal updates should go through the installed skill helper:

```bash
skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json
```

For manual recovery, reinstall from the same GitHub source URL. `uvx` is a one-shot or
fallback path, not the default install mode. GitHub Releases are supported for tagged
source releases; PyPI publishing stays disabled until the gates below and the
[PyPI Trusted Publishing runbook](pypi-trusted-publishing.md) are complete.

Before enabling PyPI publishing:

- Confirm package metadata, wheel contents, and optional extras install cleanly from a built
  artifact.
- Smoke test the installed CLI from the artifact, including `finjuice doctor --json`,
  `finjuice manifest --json`, and representative `--json` commands.
- Verify generated CLI JSON schemas and docs are in sync.
- Decide the compatibility impact using the API policy below and bump versions accordingly.
- Configure PyPI Trusted Publishing with GitHub OIDC and the protected
  `release` environment.

## API Compatibility

The supported public contract is the CLI JSON surface: `finjuice ... --json` output and
the generated schemas in `schemas/` and `docs/reference/json-schemas.md`. Python modules
under `src/finjuice` remain internal and may change until a deliberate `finjuice.api`
facade exists.

## Checklist

1. Decide the next version.
2. Update `pyproject.toml` and `src/finjuice/__init__.py`.
3. Update `CHANGELOG.md`.
4. Run local gates:

   ```bash
   uv run pytest
   uv run ruff check .
   uv run mypy src/
   ```

5. Smoke test installed CLI:

   ```bash
   uv tool install --reinstall --with duckdb .
   finjuice --version
   finjuice doctor --json
   finjuice status --json
   ```

6. Commit the release prep.
7. Tag and push:

   ```bash
   git tag vX.Y.Z
   git push origin main --tags
   ```

8. Confirm the GitHub Release workflow created the release.

## Current Recommendation

Use patch releases on the active `0.7.x` line for non-breaking Banksalad overview
ingest fixes, including snapshot-date or deduplication fixes that affect real imported
data. Reserve the next minor release for additive CLI, JSON, template, or skill
workflow behavior.
