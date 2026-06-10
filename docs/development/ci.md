# CI Gates

finjuice uses GitHub-hosted Actions runners for all public repository workflows.
The split is by trust boundary and runtime cost, not by runner type.

## Public PR CI

`.github/workflows/public-pr-ci.yml` is the GitHub-hosted public pull request
gate. It runs on `ubuntu-latest` with `contents: read` permissions, does not use
secrets, and is safe for pull requests from forks.

The public gate installs dependencies with `uv sync --all-extras`, then runs:

```bash
uv run ruff check .
uv run python scripts/check_complexity_ratchet.py
uv run ruff format --check .
uv run python scripts/check_pii_logging.py
uv run pytest --no-cov \
  tests/scripts/test_check_pii_logging.py \
  tests/scripts/test_check_complexity_ratchet.py \
  tests/test_config.py \
  tests/test_schema_registry.py \
  tests/test_ingest_pipeline.py \
  tests/test_tagging_pipeline.py \
  tests/test_master_export.py \
  tests/test_json_schemas.py \
  tests/cli/test_version.py
```

The pytest selection covers the ingest → tag → export pipeline plus config,
schema, and tooling guards — representative enough to catch core regressions on
fork PRs, while staying fast (~5s) so it does not duplicate the full coverage
gate.

## Full GitHub-Hosted Checks

The heavier reliability layer also runs on GitHub-hosted `ubuntu-latest` jobs:

- `.github/workflows/ci.yml` runs the private PR/main smoke gate, including
  the 85% coverage gate, security baseline comparator, package artifact content
  checks, and installed wheel/sdist smoke tests.
- `.github/workflows/docs-check.yml` runs documentation and generated asset
  consistency checks.
- `.github/workflows/ci-full.yml` runs scheduled/manual matrix, type, and
  security checks. Python 3.13 in the matrix enforces the same 85% coverage
  gate; older supported interpreters run the test baseline without duplicating
  coverage collection.

Trusted jobs are guarded at the job level. They run on trusted branch pushes or
same-repository pull requests from `OWNER`, `MEMBER`, or `COLLABORATOR`
authors, plus the maintainer allowlist recorded in the workflow. Fork and public
PRs stay on the secret-free `.github/workflows/public-pr-ci.yml` path.

Security baseline behavior is documented in
[security-baselines.md](security-baselines.md).

Package artifact smoke behavior is documented in
[release-artifacts.md](release-artifacts.md). It stays in `ci.yml` because it is
the installability gate for the default package job.

## Release Gates

Before tagging a release, every gate below must be green on the release commit:

| Gate | Workflow | What it proves |
|------|----------|----------------|
| Public PR CI | `public-pr-ci.yml` | Lint, format, complexity ratchet, focused unit subset — fork-safe |
| Private smoke gate | `ci.yml` | Full pytest suite, 85% coverage, security baselines, package + installed-wheel smoke |
| Full matrix | `ci-full.yml` | Multi-interpreter test baseline, type and security checks |
| Docs check | `docs-check.yml` | Generated docs and asset consistency |

The full pytest suite in `ci.yml` and `ci-full.yml` includes the end-to-end
suite and the performance benchmark described below — they are part of the
required release signal, not optional extras.

### E2E and Performance Signal

- **E2E tests** (`tests/e2e/`, marked `@pytest.mark.e2e`) run the full
  ingest → tag → transfer → export pipeline against the committed synthetic
  fixture `tests/fixtures/e2e/synthetic_banksalad_e2e.xlsx`. The fixture is
  checked in, so these tests do not skip on missing local data. It always
  carries duplicate rows, transfer pairs, malformed rows, and tagging edge
  cases, so deduplication and row-level validation stay exercised on every run
  (`test_synthetic_fixture_edge_cases` asserts this).
- **The performance benchmark** (`test_performance_benchmarks`, marked
  `@pytest.mark.slow`) compares the synthetic pipeline's wall-clock time against
  the reviewed budget in `tests/e2e/perf_baseline.json`, not an arbitrary high
  cap. Re-measure and update that file when the fixture or pipeline changes
  materially.
- E2E and `slow` tests run in the private `ci.yml` / `ci-full.yml` suite. The
  fast public PR gate file-selects a focused unit subset and deliberately does
  not run them, so a fork PR never waits on the full pipeline.

## Complexity Ratchet

Run the local complexity gate with:

```bash
just complexity
```

The gate runs Ruff for `C901`, `PLR0911`, `PLR0912`, `PLR0913`, and `PLR0915`
against `src/`, `scripts/`, `tests/`, and `tools/`, then compares findings to
`tools/ruff_complexity_baseline.json`. New hotspots or higher measured values
fail; reduced or removed findings pass and print a reminder that the baseline
can shrink.

After intentionally reducing complexity debt, update the baseline with:

```bash
uv run python scripts/check_complexity_ratchet.py --update-baseline
```

Review the JSON diff before committing. Only update the baseline for accepted
new debt when a refactor is deliberately deferred.

Keep secrets and private financial data out of every workflow. Prefer
`pull_request` over `pull_request_target` unless a security review explicitly
approves the change.

## Trust Boundaries

GitHub Actions token permissions are documented in
[workflow-permissions.md](workflow-permissions.md). Branch protection and ruleset
expectations for `main` are documented in
[branch-protection.md](branch-protection.md).

Claude workflows are secret-backed and run only after a trusted
`author_association` or maintainer allowlist gate passes. Public PR feedback for
Claude review policy is GitHub-hosted and does not receive secrets.

## Dependency Updates

Dependabot opens weekly Python and GitHub Actions update PRs. See
[dependency-updates.md](dependency-updates.md) for the review checklist, grouping
rules, `uv.lock` handling, and the relationship with the weekly dependency audit
workflow.
