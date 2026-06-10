# Branch Protection Expectations

`main` is the release-bearing branch. Treat its branch protection or ruleset as
a repository trust boundary alongside GitHub Actions token permissions.

This document records the required settings. This PR documents expectations only;
it does not call the GitHub branch protection API or mutate repository settings.

## Required Checks

Require these status checks before merging into `main`:

- `CI Lint`
- `CI Test 3.13`
- `Documentation Quality Checks`
- `Package Artifacts`
- `Security Baselines`
- `Public PR Gate`
- `CodeRabbit`
- `claude-review`

Keep check names aligned with the GitHub PR check rollup. If a workflow job is
renamed, update the branch rule and this document in the same change.

Do not require `CodeQL` or `OpenSSF Scorecard` yet. CodeQL code scanning on this
private repository requires GitHub Advanced Security, and Scorecard should first
be observed through scheduled/manual runs and SARIF artifacts. See
[code-scanning.md](code-scanning.md) for the private-repository limitations.

## Pull Request Review

- Require pull requests before merging.
- Require at least `1 approving review`.
- Dismiss stale approvals when new commits are pushed if the repository ruleset
  supports that field.
- Do not weaken existing review or check gates to make automation pass.

## Branch Mutation Rules

- No force-push: do not allow force pushes to `main`.
- No branch deletion: do not allow deletion of `main`.
- Require linear history if the project continues using squash or rebase merges.
  If merge commits are intentionally allowed later, document that exception here.
- Enforce rules for administrators unless a short-lived operational exception is
  explicitly recorded by the owner.

## Manual Settings Path

If GitHub plan/API limits prevent setting these fields programmatically, the
repository owner must apply them in the Settings UI:

- Required status checks and the exact check names above.
- Required pull request review count and stale-review dismissal.
- No force-push and no branch deletion toggles.
- Linear history, when used.
- Admin enforcement or ruleset bypass actor settings.

Use either `Settings > Rules > Rulesets` or
`Settings > Branches > Branch protection rules`, depending on which UI is
available for the repository plan.

## Release Relationship

See [release.md](release.md) for release preparation and tag publishing. The
release workflow may write GitHub Releases from tags, but normal code changes
still flow through `main` and the protection expectations above.
