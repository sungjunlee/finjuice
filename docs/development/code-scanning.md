# Code Scanning

Finjuice uses two repository-level security signals that sit beside the normal
pytest, ruff, mypy, and dependency-audit gates:

- CodeQL performs semantic static analysis for Python and reports code scanning
  alerts when GitHub code scanning is available.
- OpenSSF Scorecard evaluates repository security posture, such as branch
  protection, pinned actions, token permissions, and vulnerability reporting.

These workflows inspect repository source and workflow metadata. They should not
read user transaction data, asset data, exports, `.env`, or local data stores.

## CodeQL On Private Repositories

`.github/workflows/codeql.yml` runs on pushes and pull requests to `main`, on a
weekly schedule, and through manual dispatch. The workflow grants only
`contents: read` at the top level and grants `security-events: write` only to
the `analyze` job so CodeQL can upload code scanning results.

This repository is currently private. GitHub requires GitHub Advanced Security
for CodeQL code scanning on private repositories. Without GHAS, the CodeQL
`github/codeql-action/analyze@v3` step can fail when it tries to upload results.
The workflow keeps that analyze step as `continue-on-error: true` and writes a
job summary explaining the likely GHAS limitation.

Maintainer options:

- Enable GitHub Advanced Security for the private repository, then rerun CodeQL.
- Wait until the repository is public, then rerun CodeQL.
- After CodeQL is stable for the repository plan, remove `continue-on-error`
  from the analyze step if it should become a blocking signal.

## OpenSSF Scorecard

`.github/workflows/scorecard.yml` runs on branch protection rule changes, pushes
to `main`, a weekly schedule, and manual dispatch. The Scorecard job writes a
SARIF file, uploads it as a workflow artifact, and attempts to upload it to code
scanning when GitHub supports that path for the repository plan.

`publish_results` is set to `false` because the repository is private. Published
Scorecard results go to the public OpenSSF transparency log and are intended for
public repositories. Once the repository is public and the maintainer wants that
public signal, update `.github/workflows/scorecard.yml`:

```yaml
publish_results: true
```

The job-level `id-token: write` permission is intentionally scoped to the
Scorecard job only when `publish_results` is set to `true`, because public
Scorecard result publishing uses OIDC. Keep it omitted while public publishing
is disabled.

## Finding Results

- Check the workflow run summary for private-repo limitations or upload notes.
- Download the `scorecard-sarif` workflow artifact for Scorecard details.
- Use `Security > Code scanning` for CodeQL and Scorecard SARIF results when
  GitHub code scanning is enabled for the repository plan.

See [workflow-permissions.md](workflow-permissions.md) for the token permission
rationale and [branch-protection.md](branch-protection.md) for required check
expectations.
