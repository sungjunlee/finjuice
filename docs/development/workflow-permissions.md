# GitHub Actions Workflow Permissions

GitHub Actions `GITHUB_TOKEN` permissions should be readable by default. Grant
write access only at the job that needs it, and record the reason here.

Pattern:

- Every workflow declares top-level `permissions: contents: read`.
- Job-level `permissions` may add write scopes only for a documented action.
- When a job declares `permissions`, include all read scopes it still needs
  because job-level permissions override the workflow default.
- All jobs run on GitHub-hosted `ubuntu-latest`; do not add custom runners
  without a security review.
- Jobs that can use secrets must include a trust guard before any secret-backed
  action runs.
- Do not add `pull_request_target` or repository write scopes without a security
  review.

| Workflow | Top-level permissions | Job-level write permissions | Why |
| --- | --- | --- | --- |
| `audit.yml` | `contents: read` | `audit`: `issues: write` | Dependency audit reads code and may create one security issue when vulnerabilities are found. |
| `ci.yml` | `contents: read` | None | Tests, lint, coverage, security baselines, and package checks only read repository contents. |
| `ci-full.yml` | `contents: read` | None | Scheduled/manual matrix, type, and security checks only read repository contents. |
| `codeql.yml` | `contents: read` | `analyze`: `security-events: write` | CodeQL needs code scanning upload access. The write scope is local to the analysis job, which keeps explicit read scopes for repository, Actions, and package metadata. |
| `docs-check.yml` | `contents: read` | None | Documentation gates and generated-doc checks only need checkout access. |
| `claude-code-review.yml` | `contents: read` | `claude-review`: `id-token: write` | Secret-backed Claude review runs only for same-repository PRs from trusted authors. The `public-feedback` job is GitHub-hosted, read-only, and secret-free. |
| `claude.yml` | `contents: read` | `claude`: `id-token: write` | Claude assistant keeps explicit read scopes plus `actions: read` so it can inspect CI results. It requires a trusted `author_association` or maintainer allowlist match before using Claude credentials. |
| `public-pr-ci.yml` | `contents: read` | None | Fork-safe public gate runs without secrets or write access. |
| `release.yml` | `contents: read` | `release`: `attestations: write`, `contents: write`, `id-token: write` | GitHub Release creation and asset upload require repository contents write access. Build provenance attestation requires OIDC token minting plus GitHub attestation persistence. |
| `scorecard.yml` | `contents: read` | `analysis`: `security-events: write` | Scorecard writes SARIF to code scanning when available. Add `id-token: write` to this job only if `publish_results` is enabled for OpenSSF public result publishing. |

The audit and release jobs intentionally keep write scopes local to one job.
The Claude jobs keep their existing job-level read scopes so the action can read
pull request and issue context without inheriting broader defaults. Comment- and
PR-triggered Claude paths are guarded by `author_association` plus the maintainer
allowlist before any Claude secret can be used.

See [code-scanning.md](code-scanning.md) for the private-repository limitations
behind CodeQL and OpenSSF Scorecard.
