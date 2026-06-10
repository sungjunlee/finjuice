# Workspace Discovery Guide

Use this guide after the Runtime Preflight succeeds and before workflow-specific
commands. Discovery is read-only and should not mutate user finance data.

## Command Roles

- `finjuice index --json --privacy compact`: first workspace map. Use it to identify
  initialized/missing collections, available data domains, privacy levels, and safe next
  inspection commands without exposing local paths.
- `finjuice checkup --json --privacy compact`: first health snapshot. Use it when the
  workflow needs actionable next steps, warnings, or cross-domain readiness before deeper
  analysis.
- `finjuice status --json`: detailed data health. Use it after `index` or `checkup` when
  the workflow needs transaction counts, date range, tagging coverage, or rules file
  details.
- `finjuice manifest --json`: CLI/API capability discovery. Use it when command syntax,
  safety class, JSON schema refs, global options, or privacy profile support must be
  verified before choosing commands.

## Default Sequence

1. Run `finjuice index --json --privacy compact`.
2. If the workspace is initialized and the workflow needs health or next actions, run
   `finjuice checkup --json --privacy compact`.
3. Run `finjuice status --json` or `finjuice status --json --detailed` only when the
   workflow needs data health fields that are not present in the index/checkup summary.
4. Run `finjuice manifest --json` only for CLI contract or capability lookup; do not use
   it as a finance data source.

## Routing Cues

- `index.workspace.status` is `uninitialized` or required collections are `missing`:
  route to onboarding before analysis.
- `index.collections[].status` shows transactions/assets/reports are missing: avoid
  commands that assume those collections exist.
- `checkup.summary.status` is `needs_attention`: follow `next_actions` before long-form
  analysis when the user has not asked for a specific report.
- `status.tagging.untagged_count` is high: route curation/cleanup before presenting
  confident category trends.
