# Finjuice Report Recipes

Use these v1 recipes when a user asks `finjuice-report` to create a persistent finance
report artifact. The recipes keep report generation explicit while preserving the agent's
freedom to recombine finjuice primitives for the user's actual question.

These recipes assume the shared evidence contract in
`skills/finjuice/references/report-contract.md`. Every report block must cite command
evidence. Do not add a new CLI AI command, dashboard, hosted service, or LLM call inside
finjuice for these workflows.

## Product Boundary

Most finance apps provide fixed reports: the app decides the charts, grouping, and
workflow. finjuice is different. The CLI exposes local Banksalad data as stable JSON,
template, query, and export primitives. The external agent chooses the recipe, runs the
commands, records the evidence, and writes a local artifact.

Prefer this order:

1. Use stable templates from `src/finjuice/templates/sql/registry.yaml`.
2. Use `finjuice query --json "..."` only when a template cannot answer the question.
3. Use `finjuice export --format html` only as an optional companion visual artifact.
4. Write `evidence.json`, `commands.txt`, and `report.md` or `index.html` under
   `~/.finjuice/exports/ai-reports/<report-slug>/`.

## Shared Preflight

Run this before every persistent report:

```bash
finjuice status --json --detailed
finjuice doctor --json
```

Use `status` to determine the available date range, transaction count, tagging coverage,
report filter state, and data directory. Use `doctor` to catch missing dependencies or
data layout problems before writing artifacts.

If tagging coverage is below 80%, downgrade category/tag conclusions to no higher than
`medium` confidence. If it is below 60%, use `low` confidence for category/tag claims and
prefer the `cleanup-aware` recipe before writing strong conclusions.

## Recipe: `monthly`

Use for prompts like:

- `이번 달 소비 리포트 만들어줘`
- `2026-04 월간 리포트 HTML로 저장해줘`
- `monthly spending recap`

### Default Command Sequence

```bash
finjuice status --json --detailed
finjuice doctor --json
finjuice template run monthly_spend --param since=YYYY-MM --param until=YYYY-MM --output json
finjuice query --json "SELECT type_norm, COUNT(*) AS transaction_count, SUM(amount) AS net_amount FROM transactions WHERE substr(CAST(date AS VARCHAR), 1, 7) = 'YYYY-MM' AND is_transfer = 0 GROUP BY type_norm ORDER BY type_norm"
finjuice template run tag_breakdown --param since=YYYY-MM --param until=YYYY-MM --param top_n=10 --output json
finjuice template run compare --param baseline_months=PREV-YYYY-MM --param current_months=YYYY-MM --param group_by=category_final --output json
finjuice template run card_spend_summary --param since=YYYY-MM --param until=YYYY-MM --output json
finjuice template run recurring_candidates --output json
finjuice template run anomaly_large_txn --param since=YYYY-MM --param until=YYYY-MM --output json
finjuice template run new_merchants --param days=31 --output json
finjuice template run spending_comparison --param period_days=31 --output json
```

Use the requested month for `YYYY-MM` and the immediately preceding month for
`PREV-YYYY-MM`. If the user says "이번 달", infer the current calendar month and record
`period.source = "inferred_from_user_request"`. If the requested month is outside the
available data range, either use the nearest available month with `low` confidence or
stop and ask whether to import more data.

### Expected Sections

- Overview: period, total spend, transaction count, available data range, confidence.
- Cashflow: spend from `monthly_spend`, income/expense net view from the focused
  `query`, and comparison from `spending_comparison` when comparable data exists.
- Category and tag drivers: top tags/categories from `tag_breakdown`, with coverage
  warning when tagging is weak.
- Category changes: previous-month vs current-month category movement from `compare`.
- Account/card view: top accounts from `card_spend_summary`.
- New or changed behavior: new merchants from `new_merchants`, large transactions from
  `anomaly_large_txn`.
- Recurring charges: recurring candidates relevant to the month, clearly labeled as
  candidates, not confirmed subscriptions.
- Next actions: focused follow-up questions, cleanup suggestions, or commands.

### Empty and Partial Data Handling

- If `monthly_spend` returns no rows, write a short report saying the requested period has
  no spending evidence. Do not manufacture trend commentary.
- If `tag_breakdown` is empty but monthly spend exists, report totals and downgrade
  category/tag interpretation.
- If `spending_comparison` has no prior period, state that comparison is unavailable.
- If `compare` has no previous-month baseline, skip category-change claims and keep only
  current-month category composition.
- If `new_merchants` uses a rolling `days` window that does not exactly match the month,
  state the window in the block and keep it separate from month-bounded totals.
- If `recurring_candidates` spans all data, do not claim a charge happened in the target
  month unless a month-bounded command or query confirms it.

## Recipe: `yearly`

Use for prompts like:

- `2025년 연간 소비 recap 만들어줘`
- `올해 소비 흐름을 리포트로 정리해줘`
- `annual spending review`

### Default Command Sequence

```bash
finjuice status --json --detailed
finjuice doctor --json
finjuice template run monthly_spend --param since=YYYY-01 --param until=YYYY-12 --output json
finjuice template run tag_breakdown --param since=YYYY-01 --param until=YYYY-12 --param top_n=20 --output json
finjuice template run card_spend_summary --param since=YYYY-01 --param until=YYYY-12 --output json
finjuice template run recurring_candidates --param min_occurrences=3 --output json
finjuice template run anomaly_large_txn --param since=YYYY-01 --param until=YYYY-12 --param top_n=50 --output json
finjuice template run pivot --param row=month --param col=category_final --param value=amount --param agg=sum --param months=YYYY-01:YYYY-12 --output json
finjuice template run pivot --param row=quarter --param col=category_final --param value=amount --param agg=sum --param months=YYYY-01:YYYY-12 --output json
finjuice template run pivot --param row=year --param col=merchant_raw --param value=amount --param agg=sum --param months=YYYY-01:YYYY-12 --param top_n_cols=20 --output json
```

Use the requested year for `YYYY`. For "올해", use the current calendar year and mark the
period as year-to-date when the year is incomplete.

### Expected Sections

- Year overview: total spend, active months, transaction count, and whether the year is
  complete or year-to-date.
- Monthly trend: month-by-month totals from `monthly_spend`.
- Top categories and tags: annual drivers from `tag_breakdown`.
- Top merchants: annual merchant concentration from `pivot` with `col=merchant_raw`.
- Seasonality: monthly or quarterly concentration from `pivot`.
- Fixed-cost shifts: recurring candidates and any visible changes in recurring spend.
- Top accounts/cards: annual payment channel concentration from `card_spend_summary`.
- Notable transactions: largest transactions from `anomaly_large_txn`.
- Next actions: cleanup, budget follow-ups, subscription review, or deeper focus reports.

### Empty and Partial Data Handling

- If fewer than three months exist in the requested year, avoid seasonality claims and
  mark trend confidence `low`.
- If only year-to-date data exists, say so in the title or overview.
- If `pivot` returns empty columns because categories are missing, use `monthly_spend` for
  totals and downgrade category sections.
- If recurring candidates cover multiple years, label them as historical candidates and
  use a targeted query only if the user needs year-specific subscription evidence.

## Recipe: `focus-spending`

Use for prompts like:

- `카페/외식 지출만 깊게 분석해줘`
- `넷플릭스 같은 구독 지출 리포트로 정리해줘`
- `why did coffee spending rise?`

The focus may be a category, tag, merchant keyword, account, or user-provided group of
keywords. State the focus definition in the report before interpreting numbers.

### Default Command Sequence

```bash
finjuice status --json --detailed
finjuice doctor --json
finjuice template run monthly_spend --param since=YYYY-MM --param until=YYYY-MM --output json
finjuice template run tag_breakdown --param since=YYYY-MM --param until=YYYY-MM --param top_n=30 --output json
finjuice template run merchant_monthly_trend --param merchant=KEYWORD --param since=YYYY-MM --param until=YYYY-MM --output json
finjuice template run spend_by_weekday_hour --param since=YYYY-MM --param until=YYYY-MM --output json
finjuice template run anomaly_large_txn --param since=YYYY-MM --param until=YYYY-MM --output json
finjuice template run compare --param baseline_months=YYYY-MM:YYYY-MM --param current_months=YYYY-MM:YYYY-MM --param group_by=merchant_raw --output json
```

For category or tag focus, prefer `tag_breakdown`, `pivot`, and a focused
`finjuice query --json` over forcing `merchant_monthly_trend`. For merchant focus, use
`merchant_monthly_trend` first. For a custom keyword group, use `query --json` with an
explicit `ILIKE` filter and record the SQL in `commands.txt`.

Useful focus-specific additions:

```bash
finjuice template run pivot --param row=month --param col=tags_final --param value=amount --param agg=sum --param months=YYYY-MM:YYYY-MM --output json
finjuice template run pivot --param row=month --param col=category_final --param value=amount --param agg=sum --param months=YYYY-MM:YYYY-MM --output json
finjuice query --json "SELECT merchant_raw, COUNT(*) AS transaction_count, ABS(SUM(amount)) AS total_spend FROM transactions WHERE amount < 0 AND is_transfer = 0 AND category_final = 'CATEGORY' AND substr(CAST(date AS VARCHAR), 1, 7) BETWEEN 'YYYY-MM' AND 'YYYY-MM' GROUP BY merchant_raw ORDER BY total_spend DESC LIMIT 20"
```

### Expected Sections

- Focus definition: exact category, tag, merchant keyword, or SQL filter used.
- Focus total: total spend and transaction count for the period.
- Trend: comparison against baseline months or recent periods.
- Drivers: top merchants, categories, weekdays/hours, or largest transactions that explain
  the focus total.
- Evidence limits: whether the focus depends on tags, raw merchant text, or user-defined
  keywords.
- Next actions: rule cleanup, subscription cancellation review, budget target, or another
  focus report.

### Empty and Partial Data Handling

- If the focus filter returns no rows, report that no matching evidence was found and
  include the exact filter/command.
- If the focus depends on tags and coverage is low, switch to sibling skill
  `finjuice-curate` if available; otherwise follow `../../finjuice-curate/SKILL.md`
  inline or run `finjuice rules gaps --json` before drawing conclusions.
- If merchant names are inconsistent, use `finjuice explain "KEYWORD" --json` or
  `finjuice show --json --merchant KEYWORD --limit 50` to inspect representative rows.
- If `compare` lacks a baseline, present the current-period deep dive without a trend
  claim.

## Recipe: `cleanup-aware`

Use for prompts like:

- `리포트 만들기 전에 태깅 상태가 충분한지 먼저 봐줘`
- `태깅 상태가 낮으면 먼저 정리하고 리포트 만들어줘`
- `make a report, but check data quality first`

This recipe is a gate in front of another recipe. It decides whether the requested report
can be trusted now or whether the user should improve tagging first.

### Default Command Sequence

```bash
finjuice status --json --detailed
finjuice doctor --json
finjuice rules validate --json
finjuice rules gaps --json
finjuice show --json --untagged --limit 50
```

If coverage is acceptable for the requested report question, continue into `monthly`,
`yearly`, or `focus-spending`. If coverage is weak, stop before writing strong narrative
and switch to sibling skill `finjuice-curate` if available; otherwise follow
`../../finjuice-curate/SKILL.md` inline.

### Expected Sections

- Data readiness: transaction count, available date range, tagging coverage, and rules
  validation status.
- Report risk: which planned report blocks would be affected by weak tags, missing data,
  stale transfers, or failed checks.
- Cleanup queue: top untagged or high-impact gaps from `rules gaps` and `show`.
- Decision: continue now, continue with limited confidence, or pause for sibling skill
  `finjuice-curate` if available; otherwise follow `../../finjuice-curate/SKILL.md`
  inline.
- Next actions: exact cleanup commands or sibling skill route.

### Empty and Partial Data Handling

- If there are no transactions, switch to sibling skill `finjuice-onboard` if available;
  otherwise follow `../../finjuice-onboard/SKILL.md` inline or import/ingest before
  report generation.
- If rules validation fails, fix or switch to sibling skill `finjuice-curate` if
  available; otherwise follow `../../finjuice-curate/SKILL.md` inline before relying on
  category/tag blocks.
- If `rules gaps` returns no actionable gaps but coverage is still low, inspect
  `show --untagged` and explain that more row-level review is needed.
- If the report is merchant-only and does not rely on tags, weak coverage may be a
  limitation rather than a blocker. State this and continue with the narrower report.

## Output Shape

Every recipe should produce the same artifact skeleton:

```text
~/.finjuice/exports/ai-reports/<report-slug>/
  evidence.json
  commands.txt
  report.md
```

Use `index.html` only when the user asks for HTML or when composing around a companion
HTML export. Keep `evidence.json` compact, but ensure `commands.txt` can reproduce all
numbers locally.

Final agent responses should include:

- artifact path
- report mode and period
- confidence level
- important limitations
- suggested next action
