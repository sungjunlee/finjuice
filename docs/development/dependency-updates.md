# Dependency Update Automation

finjuice uses Dependabot to open dependency update pull requests. This is a
maintenance signal, not an auto-merge path: existing CI remains the merge gate,
and maintainers still review each update before merging.

## Cadence

Dependabot checks supported ecosystems weekly on Monday morning in
`Asia/Seoul`.

- `github-actions` runs at 09:00 and groups routine minor and patch action
  updates into one pull request. Major action updates remain separate.
- `uv` runs at 09:30 and reads Python dependency declarations from
  `pyproject.toml`, including `[project.dependencies]` and
  `[dependency-groups]`, while keeping `uv.lock` updated with the declaration
  changes. Routine dev/test/lint updates, optional reporting/analytics updates,
  and runtime patch updates are grouped separately. Runtime minor and major
  updates remain separate for closer review.
- Each ecosystem is capped at five open Dependabot pull requests to limit noise.
- Dependabot applies the `dependencies` label and requests maintainer review.

The weekly cadence, five-PR cap, and grouped routine updates keep maintenance
visible without turning a solo-dev finance-data project into PR triage work.
Because finjuice is privacy-first, local-first, and has no production deployment
pipeline, CI-gated human review is a better balance than auto-merge or
high-frequency dependency churn.

## Triage Checklist

For each Dependabot pull request:

1. Read Dependabot's summary and the upstream changelog or release notes.
2. Check whether the change affects runtime behavior, GitHub Actions
   permissions, supported Python versions, or GitHub-hosted runner behavior.
3. For Python updates, review the `pyproject.toml` and `uv.lock` diff together.
   If Dependabot cannot refresh the lockfile cleanly, run `uv lock` or
   `uv sync --all-extras` locally and include the lockfile diff before merging.
4. Let the existing CI workflows complete. Do not merge a dependency update that
   fails CI unless the failure is understood and fixed.
5. For low-risk green updates, merge normally after review.

Useful local checks for dependency PRs:

```bash
uv run ruff check .
uv run pytest -q
python -c "import yaml; yaml.safe_load(open('.github/dependabot.yml'))"
```

Run broader checks such as `uv run mypy src/` when the update touches typing,
runtime libraries, or any shared behavior.

## Defer Or Hold

Defer a Dependabot PR when the update needs code migration, changes public CLI
or JSON behavior, drops a supported Python version, or requires a coordinated
release note. Keep major version bumps separate unless the migration is clearly
mechanical and CI covers the affected path.

Prioritize security advisory updates, but still review the changelog and CI
results. If a security update cannot be merged quickly, document the reason,
the temporary risk assessment, and the follow-up issue or mitigation.

## Relationship To Weekly Audit

`.github/workflows/audit.yml` runs the existing weekly dependency audit with
`pip-audit` and may open or update security work when known vulnerabilities are
found. Dependabot complements that workflow by proposing concrete update PRs for
Python dependencies and GitHub Actions before updates become emergency work.

The audit workflow stays in place. Dependabot does not replace vulnerability
review, and auto-merge is not enabled.
