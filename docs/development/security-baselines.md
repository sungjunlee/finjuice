# Security Baselines

finjuice treats Bandit and pip-audit as fail-closed gates. Known accepted
findings live in reviewed JSON baselines under `security/`; new or worsened
findings fail CI.

## Files

- `security/bandit-baseline.json` covers Bandit findings from
  `bandit -r src/ -ll`.
- `security/pip-audit-baseline.json` covers `pip-audit --local` findings from
  the installed uv dev environment.
- `scripts/check_security_baselines.py` runs both tools, writes raw reports to
  `bandit-report.json` and `audit-report.json`, then compares them to the
  baselines.

The PR gate runs in `.github/workflows/ci.yml` because the local comparator run
is well under 60 seconds with the uv cache warm. `.github/workflows/ci-full.yml`
also runs the same comparator for scheduled/manual reliability checks. The
weekly `audit.yml` workflow still creates dependency-audit issues for maintainer
review.

## Baseline Fields

Bandit entries use this stable identity:

- `test_id`: Bandit rule, such as `B608`.
- `filename`: repository-relative path.
- `function`: nearest Python function or class symbol. This avoids churn when
  unrelated edits move line numbers.
- `rationale`: required review note explaining why the finding is accepted.

pip-audit entries use this stable identity:

- `id`: CVE, GHSA, or PYSEC advisory id.
- `package`: affected distribution name.
- `affected_versions`: the audited affected range. For local-environment
  reports that do not include a range, this is recorded as `installed==version`.
- `rationale`: required review note explaining the accepted risk and removal
  condition.

`issue_severity`, `issue_confidence`, `installed_version`, `aliases`, and
`fix_versions` are informational. If a Bandit finding with the same identity
gets a higher severity than the baseline, the gate fails.

## Refreshing

To inspect the current state:

```bash
uv run python scripts/check_security_baselines.py
```

If a new finding is intentional:

1. Review the raw `bandit-report.json` or `audit-report.json`.
2. Prefer fixing or upgrading the dependency.
3. If accepting the finding, add one baseline entry with the stable identity.
4. Write a specific `rationale` with the accepted risk and removal condition.
5. Re-run the comparator and review the JSON diff before committing.

Do not blanket-ignore tools or remove findings without understanding why they
changed.

## Rebasing Paths After a Refactor

When a refactor moves a baselined function to a new file, the Bandit gate sees
the old `filename` disappear and a new one appear, and flags the move as a new
finding even though nothing got worse. Instead of hand-editing the baseline:

```bash
uv run python scripts/check_security_baselines.py --rebase-paths
```

This re-points baseline entries whose `(test_id, function)` identity is
unchanged — and whose recorded severity and confidence still match — but whose
`filename` moved. The reviewed `rationale` is preserved. Genuinely new findings
still fail. `just rebase-baselines` runs this together with the complexity
ratchet's equivalent mode; see `docs/development/code-quality.md`.

## Review Policy

Review both baseline files at least quarterly. Each rationale must be
re-affirmed, tightened, or removed. Temporary dependency vulnerability baselines
should be removed as soon as the locked dependency can be upgraded to a fixed
version.

## Self-Test

Run:

```bash
uv run python scripts/check_security_baselines.py --self-test
```

The self-test injects synthetic Bandit and pip-audit findings into empty
baselines. It exits 0 only when the comparator rejects those added findings,
which proves the gate fails closed.
