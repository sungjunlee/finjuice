# Report Evidence Contract

Use this contract for AI-generated finance report artifacts. It is shared by
`finjuice-report`, `finjuice-review`, and `finjuice-diagnose` so report narrative stays
grounded in finjuice evidence instead of model memory or unsupported inference.

## Boundary

finjuice provides local-first data primitives. The AI agent may decide what to inspect,
compose commands, interpret results, and write narrative, but it must not invent numbers.
Every amount, count, date range, percentage, merchant, category, tag, asset value, budget
value, and trend claim in a report must trace to one of:

- a `finjuice ... --json` command response
- a `finjuice template run ... --output json` result
- a `finjuice query --json "..."` result
- a deterministic export artifact from `finjuice export`
- a clearly labeled user-provided value

Do not add a new CLI AI command, dashboard, hosted service, or LLM call inside finjuice
for this workflow. The report workflow is skill orchestration over existing CLI
primitives.

## Artifact Directory

Write persistent AI report artifacts under:

```text
~/.finjuice/exports/ai-reports/<report-slug>/
```

Use a stable slug such as `2026-04-monthly-review`, `2026-yearly-summary`, or
`subscriptions-focus-2026-04`.

## Required Files

Each persistent report artifact should contain these files:

- `evidence.json`: structured command, template, query, and export evidence, or compact
  summaries of large outputs. Include command labels, timestamps when available, periods,
  row counts, and error/empty states.
- `commands.txt`: exact commands used to produce the evidence. Keep enough flags and SQL
  text for reproducibility. Redact only secrets or user-approved sensitive literals.
- `report.md` or `index.html`: the human-readable report. `report.md` is the default;
  `index.html` may be used when the agent composes around `finjuice export --format html`
  or other local visual artifacts.

Optional companion files, such as exported HTML reports, charts, or CSV extracts, may be
included when they are referenced from `evidence.json` and the report.

## `evidence.json` Shape

Use this minimal shape for `evidence.json` so report artifacts are easy to validate and
reproduce:

```json
{
  "report": {
    "title": "Monthly Spending Review",
    "slug": "2026-04-monthly-review",
    "created_at": "2026-04-26T12:00:00+09:00",
    "period": {"start": "2026-04-01", "end": "2026-04-30", "source": "user_request"}
  },
  "commands": [
    {
      "label": "status_detailed",
      "command": "finjuice status --json --detailed",
      "status": "ok",
      "row_count": null,
      "summary": {"coverage_pct": 87.2}
    },
    {
      "label": "tag_breakdown",
      "command": "finjuice template run tag_breakdown --output json",
      "status": "ok",
      "row_count": 12,
      "summary": {"top_category": "식비"}
    }
  ],
  "blocks": [
    {
      "title": "Top spending categories",
      "commands_used": ["status_detailed", "tag_breakdown"],
      "key_numbers": {"total_spend": 1234567},
      "confidence": "high"
    }
  ],
  "artifacts": [
    {"path": "evidence.json", "kind": "evidence_pack"},
    {"path": "report.md", "kind": "human_report"},
    {"path": "commands.txt", "kind": "reproducibility_log"}
  ],
  "warnings": []
}
```

Keep summaries compact. Large command outputs may be summarized here as long as
`commands.txt` preserves the exact command needed to reproduce them locally.

## Required Report Blocks

Each report section or evidence-backed block must carry this shape:

- `title`: short section name.
- `question`: the user question or decision this block answers.
- `period`: exact period covered, including whether it came from CLI output, user input,
  or inference from available data.
- `commands_used`: command labels or exact commands that produced the evidence.
- `evidence_summary`: compact summary of the relevant rows, aggregates, files, and any
  omitted details.
- `key_numbers`: the amounts, counts, percentages, and date ranges used in the narrative.
  Each number must be traceable to `commands_used`.
- `interpretation`: the AI-written explanation. Keep causal language conservative unless
  the evidence directly supports it.
- `confidence`: `high`, `medium`, or `low`, with a reason when not `high`.
- `follow_up_actions`: concrete next steps, preferably mapped to finjuice commands or
  sibling skill workflows.

For conversational reviews that do not write files, preserve the same block discipline in
the answer even if the fields are rendered as prose instead of literal YAML or JSON.

## Evidence States

Handle incomplete evidence explicitly:

- Empty evidence: say that the command returned no rows or no usable data. Do not fill the
  gap with guesses.
- Partial evidence: state which period, account, template, or data type is missing and
  downgrade confidence.
- Failed evidence: record the command, error code or message, and whether the report
  skipped the block or used a narrower fallback.
- Conflicting evidence: present both sources, identify the conflict, and avoid a single
  definitive conclusion until the user or a follow-up command resolves it.
- Large evidence: summarize in `evidence.json`, but preserve the exact command in
  `commands.txt` so the user can reproduce the full output locally.

## Confidence Downgrades

Use `high` confidence only when the relevant commands succeed, the period is adequate, and
the key data types for the report question are present. Apply each downgrade only to the
claim or block that depends on that data dimension. Downgrade to `medium` or `low` when
any of these apply:

- Tagging coverage is low for the report question. Below 80% coverage should usually be no
  higher than `medium`; below 60% should usually be `low` for category/tag conclusions.
- The available date range is too narrow for the claim, such as a trend based on one
  partial month or less than two comparable periods.
- Required asset, budget, net worth, or goal data is missing, stale, or outside the
  requested period.
- Template, query, export, or status commands fail and the agent uses a fallback.
- `report_filters` or `--no-filter` materially changes totals. State which view was used.
- Transfer detection is missing or stale for a cash-flow claim where internal transfers
  could distort totals.
- The user asks for causality, prediction, or advice that goes beyond observed
  transaction evidence.

When confidence is `low`, prefer follow-up actions such as sibling skill
`finjuice-curate` if available; otherwise follow `../../finjuice-curate/SKILL.md`
inline, run `finjuice rules gaps --json`, import missing data, or rerun a failed command
before making strong recommendations.

## Privacy and Local-First Rules

- Keep artifacts local unless the user explicitly asks to share, upload, or publish them.
- Do not include raw full transaction dumps in the human report unless the user asks for
  row-level evidence.
- Redact secrets, passwords, access tokens, and unrelated personal notes from
  `commands.txt` and `evidence.json`.
- Do not log financial data to external services as part of the workflow.
- Prefer compact summaries over unnecessary raw data duplication.

## Minimum Evidence Pack

For a basic spending report, collect at least:

```text
finjuice status --json --detailed
finjuice template run monthly_spend --output json
finjuice template run tag_breakdown --output json
```

Add targeted `template run`, `query --json`, `rules gaps --json`, asset, budget, or net
worth commands based on the report question.
