# GitHub Actions Setup

finjuice uses GitHub-hosted Actions runners for public repository reliability.
All workflow jobs run on `ubuntu-latest`; no project workflow requires a custom
runner.

## Defaults

- Workflows declare top-level `permissions: contents: read`.
- Job-level write permissions are limited to the job that needs them.
- All third-party actions are pinned to full commit SHAs.
- Public pull requests get a fork-safe `Public PR CI` gate without secrets.
- Secret-backed Claude jobs run only after trusted author checks pass.

## Main Workflows

| Workflow | Purpose |
| --- | --- |
| `ci.yml` | Main branch and trusted PR test, lint, security, package gates |
| `public-pr-ci.yml` | Fork-safe PR feedback without secrets or write scopes |
| `docs-check.yml` | Generated docs, schema docs, and workflow trust checks |
| `ci-full.yml` | Scheduled/manual multi-version reliability checks |
| `audit.yml` | Weekly dependency vulnerability audit |
| `codeql.yml` | CodeQL analysis when code scanning is available |
| `scorecard.yml` | OpenSSF Scorecard when code scanning is available |
| `release.yml` | Tag-driven GitHub Release artifacts and attestations |

## Queue Triage

GitHub-hosted runners should normally start quickly. If a job stays queued:

1. Check GitHub Actions service status.
2. Confirm the workflow is not waiting on branch protection or environment
   approval.
3. Rerun the job from the Actions UI if the queue appears stale.
4. If repeated queue delays affect releases, split the heaviest scheduled
   workflow or run it manually after the release.

Use:

```bash
gh run list --limit 20
gh run view <run_id> --json jobs,status,conclusion
```

## Security Notes

Keep secrets out of fork-triggered paths. Prefer `pull_request` over
`pull_request_target` unless a security review explicitly approves the change.
Do not add repository write scopes at the workflow level.

The workflow trust-boundary check enforces these rules:

```bash
uv run python scripts/check_workflow_permissions.py
```

See also:

- [CI Gates](../../development/ci.md)
- [Workflow Permissions](../../development/workflow-permissions.md)
- [Branch Protection](../../development/branch-protection.md)
