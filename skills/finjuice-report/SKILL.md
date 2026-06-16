---
name: finjuice-report
description: |
  Evidence-backed finance report artifact workflow for finjuice. Generates local
  report artifacts from existing CLI JSON/template/query/export primitives, with
  `evidence.json`, `commands.txt`, and `report.md` or `index.html` under
  `~/.finjuice/exports/ai-reports/`. Trigger when the user asks for 월간 리포트,
  연간 리포트, HTML 리포트, spending recap, report artifact, saved report,
  주요소비 분석, or asks to save a finance analysis as a file.
argument-hint: "[monthly|yearly|focus-spending|cleanup-aware] [period or focus]"
compatibility: "Requires finjuice CLI runtime; resolve and run the shared runtime ensure helper before running `finjuice`."
---

# Finjuice Report

## Side Effects

- Modes: `read-only`, `artifact-writing`, `runtime-install/update`
- Reads status, templates, query/export JSON, and report evidence sources.
- Writes report artifact packs such as `evidence.json`, `commands.txt`, `report.md`, `index.html`, and optional exports under the resolved report directory because this skill is explicitly for saved artifacts.
- Runtime ensure may install a missing runtime or update runtime state only under the shared runtime policy.

## Runtime Requirements

- Minimum finjuice: `0.7.0`
- Capabilities: `index`, `checkup`, `status`, `doctor`, `template run`, `query`, `rules gaps`, `show`, `rules validate`, `export`
- Extras: `analytics` (`duckdb`)
- Unsupported fallback: Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because the local finjuice runtime lacks required capability `<capability>`. Do not recommend or run the failed command after preflight failure.

Create persistent, evidence-backed finance report artifacts. Default to Korean report
narrative unless the user asks for English.

## Runtime Preflight

Before running any `finjuice ...` command, load the shared procedure in
`skills/finjuice/references/runtime-preflight.md` to resolve `FINJUICE_ENSURE`, then
run this skill-local gate:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.7.0 \
  --require-command "index" \
  --require-command "checkup" \
  --require-command "status" \
  --require-command "doctor" \
  --require-command "template run" \
  --require-command "query" \
  --require-command "rules gaps" \
  --require-command "show" \
  --require-command "rules validate" \
  --require-command "export" \
  --require-extra analytics
```

If the JSON response has `status: "blocked"`, stop and report its `message`; do not
install `uv` automatically or continue to finjuice commands.

Side-effect mode: artifact-writing. It writes or guides creation of local files under
`~/.finjuice/exports/ai-reports/<report-slug>/`; it is not a chat-only review. For
conversation-first weekly/monthly reviews, switch to sibling skill `finjuice-review` if
available; otherwise follow `../finjuice-review/SKILL.md` inline.

## Boundaries

- Do not add or require a new finjuice CLI command.
- Do not call an LLM from finjuice code.
- Do not build or imply a dashboard, server, hosted workflow, or upload.
- Use existing CLI primitives only: `status`, `doctor`, `template run`, `query`,
  `rules gaps`, `show`, `rules validate`, and `export --format html`.
- Every amount, count, percentage, date range, merchant, category, tag, and trend claim
  must trace to command output or a clearly labeled user-provided value.

## Required References

Load these before writing a report:

- `skills/finjuice/references/report-contract.md` for artifact layout, evidence states,
  confidence rules, privacy rules, and `evidence.json` shape.
- `skills/finjuice-report/references/report-recipes.md` for the exact command sequence,
  report sections, and empty/partial-data handling for each mode.
- `docs/workflows/ai-finance-report-dogfood.md` when dogfooding the workflow or reviewing
  whether a generated artifact is LGTM.

## Mode Selection

- Monthly report: prompts like `이번 달 소비 리포트`, `2026-04 월간 리포트`,
  `monthly spending recap` -> use recipe `monthly`.
- Yearly report: prompts like `2025년 연간 소비 recap`, `올해 소비 흐름`,
  `annual report` -> use recipe `yearly`.
- Focus spending report: prompts like `카페/외식 지출 분석`, `구독 지출 리포트`,
  `why did coffee spending rise?`, `주요소비 분석` -> use recipe `focus-spending`.
- Cleanup-aware report: prompts like `태깅 상태 먼저 봐줘`, `커버리지 낮으면 정리 후
  리포트`, `check data quality before report` -> use recipe `cleanup-aware`.
If the prompt is ambiguous, choose the narrowest recipe that answers the request and state
the selected mode in the artifact. If the user asks for HTML, write `index.html` or create
a Markdown report plus a companion HTML export.

## Workflow

### 1. Resolve Report Intent

Identify:

- mode: `monthly`, `yearly`, `focus-spending`, or `cleanup-aware`
- period: exact month, year, or date/month range
- focus: category, tag, merchant, account, keyword group, or none
- output: `report.md` by default, `index.html` if explicitly requested

Use stable slugs such as `2026-04-monthly-report`, `2025-yearly-recap`, or
`coffee-focus-2026-04`.

### 2. Preflight Data Health

Always start with:

```bash
finjuice index --json --privacy compact
finjuice checkup --json --privacy compact
finjuice status --json --detailed
finjuice doctor --json
```

Load [../finjuice/references/discovery-guide.md](../finjuice/references/discovery-guide.md).
Parse workspace collections and readiness from `index`, next actions and warnings from
`checkup`, then date range, transaction count, tagging coverage, report filter state,
data directory, and failed checks from `status`/`doctor`. If there are no transactions,
switch to sibling skill
`finjuice-onboard` if available; otherwise follow `../finjuice-onboard/SKILL.md` inline
or import/ingest before report generation.

If tagging coverage is below 80%, downgrade category/tag conclusions to no higher than
`medium`. If below 60%, use `low` for category/tag claims and prefer sibling skill
`finjuice-curate` if available; otherwise follow `../finjuice-curate/SKILL.md` inline
before strong conclusions unless the report does not depend on tags.

### 3. Run the Recipe

Follow the selected recipe exactly enough that another agent can reproduce the report.
Prefer template commands from the recipe. Use `finjuice query --json "..."` only for
focus filters or questions the template registry cannot answer.

For HTML companion charts, preview or generate with:

```bash
finjuice export --format html --period YYYY-MM --no-auto-open --json
```

Use the export as evidence only when the command succeeds. If it fails, record the failure
in `evidence.json` and keep the narrative report in Markdown.

### 4. Write the Artifact Pack

Create:

```text
~/.finjuice/exports/ai-reports/<report-slug>/
  evidence.json
  commands.txt
  report.md
```

Use `index.html` instead of `report.md` only when the user asked for HTML or the agent is
composing a local HTML artifact. Optional companion files are allowed only when listed in
`evidence.json`.

`commands.txt` must contain the exact commands run, including flags, parameters, and SQL.
Redact only secrets or user-approved sensitive literals.

`evidence.json` must summarize:

- report title, slug, creation time, and period
- command labels, exact commands, status, row counts, and compact summaries
- report blocks and their `commands_used`
- artifact paths
- warnings, empty evidence, partial evidence, and failures

### 5. Write the Human Report

Each section must include:

- the question it answers
- period covered
- command evidence used
- key numbers
- interpretation
- confidence and reason when not high
- follow-up actions

Keep causal language conservative. Say "spending increased in this evidence" instead of
claiming why unless the command output directly supports the cause.

### 6. Final Response

End with a concise Korean summary:

```text
리포트 생성 완료

- 경로: ~/.finjuice/exports/ai-reports/<report-slug>/
- 모드: monthly|yearly|focus-spending|cleanup-aware
- 기간/초점: ...
- 신뢰도: high|medium|low
- 한계: ...
- 다음 액션: ...
```

If generation is blocked, do not write a fake report. Return the blocker, the command
evidence, and the next command or sibling skill that should resolve it.
