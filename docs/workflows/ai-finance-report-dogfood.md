# AI Finance Report Dogfood Workflow

Use this checklist to dogfood `finjuice-report` in Claude Code or Codex. The goal is to
verify that an agent can create useful, reproducible local finance artifacts without a
new CLI AI command, dashboard, hosted service, or LLM call inside finjuice.

## Product Boundary

Most finance apps ship fixed reports: the app chooses the chart, grouping, period, and
workflow. finjuice exposes local Banksalad data as stable CLI JSON, template, query, and
export primitives. The agent recombines those primitives, records the evidence, and writes
a local artifact under `~/.finjuice/exports/ai-reports/`.

Accept reports that prove their numbers. Reject reports that rely on model memory,
unsupported inference, hidden commands, uploaded financial data, or a new AI-facing CLI
surface in finjuice.

## Prerequisites

Run dogfood against local data or a fixture data directory. Do not publish personal
financial sample data.

```bash
finjuice --version
finjuice status --json --detailed
finjuice doctor --json
```

For a fixture or playground data directory, pass the data directory explicitly:

```bash
finjuice --data-dir /path/to/fixture status --json --detailed
finjuice --data-dir /path/to/fixture doctor --json
```

Use the status output to pick a period that exists in the data. If the data directory has
no transactions, import data or route to onboarding before testing reports.

## Privacy Boundary

The source data and generated artifacts stay local unless the user explicitly asks to
share, upload, or publish them. The agent may expose command output in its own context, so
prefer compact summaries over raw full transaction dumps. Redact secrets, tokens, and
unrelated personal notes from `commands.txt` and `evidence.json`.

## Representative Prompts

Run at least one prompt from each row when validating the workflow.

| Prompt | Expected mode | Expected artifact |
| --- | --- | --- |
| `이번 달 소비 리포트 HTML로 만들어줘` | `monthly` | `index.html` or `report.md` plus a companion HTML export |
| `2025년 연간 소비 recap 만들어줘` | `yearly` | annual `report.md` with year or year-to-date limits |
| `최근 카페/외식 지출이 왜 늘었는지 분석해서 리포트로 정리해줘` | `focus-spending` | focused report with an explicit category, tag, merchant, or SQL filter |
| `리포트 만들기 전에 태깅 상태가 충분한지 먼저 봐줘` | `cleanup-aware` | readiness report or a clear route to sibling skill `finjuice-curate` |

Ask for saved artifacts through sibling skill `finjuice-report` if available; otherwise
follow `skills/finjuice-report/SKILL.md` inline. Use sibling skill `finjuice-review` only
for conversation-first reviews that should not write files.

## Dogfood Run

1. Start with the shared preflight:

   ```bash
   finjuice status --json --detailed
   finjuice doctor --json
   ```

2. Send one representative prompt to Claude Code or Codex. The agent should select
   `monthly`, `yearly`, `focus-spending`, or `cleanup-aware` and state the mode in the
   artifact.

3. Confirm that the agent follows the recipe in
   `skills/finjuice-report/references/report-recipes.md`. It should prefer
   `finjuice template run ... --output json`, use `finjuice query --json "..."` only for
   focused questions that templates cannot answer, and use `finjuice export --format html`
   only as an optional local companion artifact.

4. Confirm that the output directory exists:

   ```bash
   ls ~/.finjuice/exports/ai-reports/<report-slug>/
   ```

5. Inspect the artifact pack:

   ```bash
   python -m json.tool ~/.finjuice/exports/ai-reports/<report-slug>/evidence.json
   sed -n '1,220p' ~/.finjuice/exports/ai-reports/<report-slug>/commands.txt
   sed -n '1,220p' ~/.finjuice/exports/ai-reports/<report-slug>/report.md
   ```

   If the run produced HTML, inspect `index.html` instead of `report.md`.

## Good Artifact Requirements

A good artifact contains:

- `evidence.json` with report metadata, command labels, exact command strings, status,
  row counts or compact summaries, block-to-command links, warnings, and artifact paths.
- `commands.txt` with every command needed to reproduce the numbers locally, including
  flags, parameters, and SQL.
- `report.md` or `index.html` with the question answered, period, evidence used, key
  numbers, interpretation, confidence, limitations, and next actions.
- Conservative language for causality. The report may say spending increased in the
  evidence. It should not claim why spending increased unless command output supports the
  cause.
- A clear confidence downgrade when tagging coverage is low, periods are partial,
  templates fail, transfers could distort totals, or the report depends on a user-defined
  keyword filter.

## LGTM Checklist

Use this checklist before calling a generated artifact LGTM.

- [ ] The artifact path is `~/.finjuice/exports/ai-reports/<report-slug>/`.
- [ ] Required files exist: `evidence.json`, `commands.txt`, and `report.md` or
  `index.html`.
- [ ] `commands.txt` contains the exact preflight and recipe commands.
- [ ] Every amount, count, percentage, merchant, category, tag, date range, and trend in
  the report traces to a command label in `evidence.json`.
- [ ] Each report block lists confidence and explains any `medium` or `low` rating.
- [ ] Empty, partial, failed, or conflicting evidence is stated instead of hidden.
- [ ] The report distinguishes fixed app reports from agent-recombinable local reports.
- [ ] The workflow did not add or require a new CLI AI command, dashboard, hosted
  workflow, or LLM inside finjuice.
- [ ] The human report avoids raw full transaction dumps unless the user asked for
  row-level evidence.
- [ ] Next actions map to finjuice commands or sibling skills such as
  `finjuice-curate`, with inline `SKILL.md` fallback when sibling switching is
  unavailable.

## Common Non-LGTM Cases

- The report has polished prose but no `evidence.json`.
- The artifact path uses a repo-local or non-contract report root instead of
  `~/.finjuice/exports/ai-reports/`.
- The report cites charts or totals that do not appear in command output.
- The agent treats `recurring_candidates` as confirmed subscriptions without supporting
  month-bounded evidence.
- The report uses low tagging coverage for strong category conclusions.
- The agent uploads, publishes, or logs personal financial data outside the local
  workflow without explicit user approval.

## When To Stop

Stop before writing a confident report when there are no transactions, `doctor` fails on a
data layout problem, rules validation fails for tag-dependent sections, or the requested
period is outside the available data range. Record the blocker, the command evidence, and
the next command or sibling skill that should resolve it.
