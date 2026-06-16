---
name: finjuice-review
description: |
  Weekly or monthly financial review for finjuice. Refreshes data, detects anomalies,
  summarizes spending changes, processes review queue, and suggests new rules.
  Trigger when user says 리뷰해줘, 주간 리뷰, 월간 리뷰, 이번 주 리뷰, 이번 달 리뷰,
  weekly review, or monthly review.
  If the user asks to save a report artifact, create an HTML report, or write files,
  switch to sibling skill finjuice-report if available.
  If sibling switching is unavailable, follow the referenced sibling SKILL.md inline.
argument-hint: "[weekly|monthly]"
compatibility: "Requires finjuice CLI runtime; resolve and run the shared runtime ensure helper before running `finjuice`."
---

# Finjuice Review

## Side Effects

- Modes: `read-only`, `mutating-with-confirmation`, `artifact-writing`, `runtime-install/update`
- Reads status, detailed summaries, templates, untagged queues, explain traces, rule suggestions, and current tagging coverage.
- `finjuice refresh --json` requires explicit user confirmation unless the user directly asked to refresh or reprocess; it can reprocess imports, re-tag transactions, detect transfers, and update generated outputs and runtime data.
- Manual tag edits, rule additions, and final re-tagging mutations require explicit user confirmation after previewing the proposed changes.
- Do not write saved report artifacts from this skill; switch `report.md`,
  `index.html`, and artifact packs to sibling skill `finjuice-report` if available.
  Otherwise follow `../finjuice-report/SKILL.md` inline. Runtime ensure may install or
  update runtime state only under the shared runtime policy.

## Runtime Requirements

- Minimum finjuice: `0.7.0`
- Capabilities: `index`, `checkup`, `refresh`, `status`, `template run`, `show`, `explain`, `rules suggest`, `rules add`, `tag.edit`
- Extras: `analytics` (`duckdb`)
- Unsupported fallback: Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because the local finjuice runtime lacks required capability `<capability>`. Do not recommend or run the failed command after preflight failure.

Run a structured financial review. Use `period_days=7` for weekly and `period_days=30` for monthly. Default to weekly if unspecified. All output in Korean.

## Runtime Preflight

Before running any `finjuice ...` command, load the shared procedure in
`skills/finjuice/references/runtime-preflight.md` to resolve `FINJUICE_ENSURE`, then
run this skill-local gate:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.7.0 \
  --require-command "index" \
  --require-command "checkup" \
  --require-command "refresh" \
  --require-command "status" \
  --require-command "template run" \
  --require-command "show" \
  --require-command "explain" \
  --require-command "rules suggest" \
  --require-command "rules add" \
  --require-command "tag" \
  --require-flag "show:--json" \
  --require-flag "show:--untagged" \
  --require-flag "show:--limit" \
  --require-flag "explain:--json" \
  --require-flag "rules add:--dry-run" \
  --require-flag "rules add:--json" \
  --require-flag "tag:--json" \
  --require-capability tag.edit \
  --require-extra analytics
```

If the JSON response has `status: "blocked"`, stop and report its `message`; do not
install `uv` automatically or continue to finjuice commands.

Default output is a conversational review, but the workflow is not file-safe: refresh,
tag edits, rule writes, and generated outputs can change local finjuice data after the
confirmation gates above. If the user asks for a saved report artifact, HTML report, or
file output, switch to sibling skill `finjuice-report` if available; otherwise follow
`../finjuice-report/SKILL.md` inline instead of turning this review workflow into an
artifact workflow.

## Workspace Discovery

Load [../finjuice/references/discovery-guide.md](../finjuice/references/discovery-guide.md).
Start with `finjuice index --json --privacy compact`, then run
`finjuice checkup --json --privacy compact` to catch stale imports, missing collections,
or high-priority next actions before the review-specific commands. Use
`finjuice status --json --detailed` in Step 1 for the detailed review baseline.

## Final Response Contract

Follow [../finjuice/references/final-response-contract.md](../finjuice/references/final-response-contract.md)
and finish Korean-first. Include these fields in the final answer:

- `evidence_commands`: list `status`, `template run`, `show`, `explain`, `rules suggest`,
  and `tag` commands that support the review.
- `mutations_applied`: refreshes, tag edits, rule writes, final `tag --json`, or `없음`;
  include only mutations the user confirmed or directly requested.
- `files_written`: `없음` unless the workflow routed to `finjuice-report` or another
  artifact-writing skill; do not claim saved files from review itself.
- `skipped_steps`: skipped refresh, anomaly detection, cleanup queue, curation, or report
  routing with the reason.
- `residual_risk`: low tagging coverage, skipped templates, ambiguous merchants, stale
  imports, or insufficient comparison history.
- `next_suggested_action`: one concrete next action such as curation, report generation,
  import refresh, or next review cadence.

## Step 0 — REFRESH

If the user directly asked to refresh or reprocess, run `finjuice refresh --json`.
Otherwise, explain that refresh can reprocess imports, re-tag transactions, detect
transfers, and update generated outputs/runtime data, then ask for explicit user
confirmation before running it.

## Step 1 — OBSERVE

After workspace discovery, run `finjuice status --json --detailed` to get current state:
date range, coverage %, untagged count, monthly totals.

## Step 2 — DETECT

Run these templates (parallel when possible):
- `finjuice template run weekly_anomalies --param period_days=N --param threshold_pct=30 --output json`
- `finjuice template run new_merchants --param days=N --output json`
- `finjuice template run spending_comparison --param period_days=N --output json`
- For monthly reviews, prefer stable review primitives before writing ad-hoc SQL:
  - `finjuice template run monthly_consumption_summary --param since=YYYY-MM --param until=YYYY-MM --output json`
  - `finjuice template run merchant_top_spend --param month=YYYY-MM --param top_n=10 --output json`
  - `finjuice template run consumption_category_breakdown --param month=YYYY-MM --param top_n=10 --output json`
  - `finjuice template run event_adjusted_spend --param month=YYYY-MM --param event_tags=TAG1,TAG2 --output json` when the user names event-like tags such as travel, medical, lifecycle, or one-off project tags.
  - `finjuice budget status --json --month YYYY-MM` for target, actual, remaining, and at-risk categories.

`consumption_spend` semantics: negative `type_norm=expense` rows, confirmed transfers
excluded, and card-payment, transfer, savings, investment, pension, fund, stock, ISA/IRP,
deposit-like categories/tags excluded. Use the template output as the source of truth
instead of recreating this SQL manually.

**Interpreting weekly_anomalies results:**
Each row has a `change_type` field: `"changed"` (with `change_pct`), `"new"` (category appeared this period), or `"gone"` (category disappeared).

**Graceful fallbacks:**
- If any template returns a non-zero exit code or JSON error, skip it and note "이상 탐지를 건너뜁니다" with the error code from the response.
- If there is less than 2 weeks of data, skip anomaly detection and note "첫 리뷰라 비교 데이터가 없습니다. 다음 주부터 변화를 추적합니다."

## Step 3 — SUMMARIZE

Generate a Korean-language summary combining steps 1-2:
```
📊 [주간/월간] 재정 리뷰

총 지출: ₩XXX,XXX (지난 [주/달] 대비 +XX%)
거래 건수: XX건

주요 변화:
• [카테고리] 지출 증가/감소 (₩XX,XXX → ₩XX,XXX, +XX%)
• [카테고리] 새로 등장 (₩XX,XXX)       ← change_type=new
• [카테고리] 지출 없음 (지난주 ₩XX,XXX) ← change_type=gone
• 새 가맹점 X곳: [가맹점명], [가맹점명]

태깅 커버리지: XX.X%
미분류 거래: XX건
```

## Step 4 — MANUAL CLEANUP QUEUE

Run `finjuice show --json --untagged --limit 50` to inspect the highest-signal untagged transactions.
- If a merchant looks systematically wrong or partially tagged, run `finjuice explain "merchant" --json` to trace the current rule path.
- For each transaction worth fixing, propose the exact edit first; after confirmation, run `finjuice tag --edit <hash> --add-tag TAG --json` or `finjuice tag --edit <hash> --set-category CAT --json`.
- After manual edits, re-run `finjuice show --json --untagged --limit 50` and note whether the queue shrank.

## Step 5 — RULE CURATION

If coverage is below 80% or untagged count is significant, switch to sibling skill
`finjuice-curate` if available; otherwise follow `../finjuice-curate/SKILL.md` inline
for interactive rule improvement.

If the user prefers a lighter touch, run `finjuice rules suggest --json --top 5` and preview each with dry-run:
- `finjuice rules add --dry-run --name NAME --match PATTERN --category CAT --tags TAGS --json`

Present all proposals as a batch:
```
📝 규칙 제안 (X건)

1. [가맹점] → 카테고리: [카테고리], 태그: [태그] (XX건, ₩XX,XXX 영향)
2. ...

위 규칙을 적용할까요? (전체/선택/건너뛰기)
```

If the user confirms, apply with `finjuice rules add` (without `--dry-run`) and re-tag with `finjuice tag --json`.

## Step 6 — VERIFY

Run `finjuice status --json` again and show the coverage improvement:
```
✅ 커버리지: XX.X% → XX.X% (+X.X%)
```

## Step 7 — REPORT

Output a final review summary in the conversation. Do not write saved report artifacts
from this skill. If the user explicitly asks to save or generate a report artifact, route to
the sibling skill `finjuice-report` if available; otherwise follow
`../finjuice-report/SKILL.md` inline.
