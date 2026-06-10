---
name: finjuice-diagnose
description: |
  Full financial diagnosis session for finjuice. Starts from index/checkup discovery,
  deepens into context, status, monthly spending, and tagging gap analysis, then turns the evidence
  into concrete risks, opportunities, and follow-up actions. Journal writes require an explicit
  user request or confirmation.
  Trigger when user says 재정 진단, 종합 진단, 소비 건강검진, financial diagnosis,
  spending diagnosis, or money health check.
argument-hint: "[focus area, month range, or concern]"
compatibility: "Requires finjuice CLI runtime; resolve and run the shared runtime ensure helper before running `finjuice`."
---

# Finjuice Diagnose

## Side Effects

- Modes: `read-only`, `journal-writing`, `artifact-writing`, `runtime-install/update`
- Reads context, status, templates, gaps, transactions, rules, and explain traces.
- Default output is chat-only. Write a diagnosis journal only when the user asks to save,
  record, or confirms journal persistence; saved report artifacts are written only when explicitly requested and must follow the report contract.
- Runtime ensure may install a missing runtime or update runtime state only under the shared runtime policy.

## Runtime Requirements

- Minimum finjuice: `0.6.2`
- Capabilities: `index`, `checkup`, `context`, `status`, `template run`, `rules gaps`, `show`, `explain`
- Extras: `analytics` (`duckdb`)
- Unsupported fallback: Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because the local finjuice runtime lacks required capability `<capability>`. Do not recommend or run the failed command after preflight failure.

Run a full diagnosis session. Default to Korean narrative output unless the user asks for English. Keep the structure concrete and evidence-first.

## Runtime Preflight

Before running any `finjuice ...` command, load the shared procedure in
`skills/finjuice/references/runtime-preflight.md` to resolve `FINJUICE_ENSURE`, then
run this skill-local gate:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.6.2 \
  --require-command "index" \
  --require-command "checkup" \
  --require-command "context" \
  --require-command "status" \
  --require-command "template run" \
  --require-command "rules gaps" \
  --require-command "show" \
  --require-command "explain" \
  --require-extra analytics
```

If the JSON response has `status: "blocked"`, stop and report its `message`; do not
install `uv` automatically or continue to finjuice commands.

Default side-effect mode is read-only. Ask before Phase 4 journal-writing unless the user
already asked to save, record, or create a journal. If the user asks for a separate saved report artifact,
follow `skills/finjuice/references/report-contract.md`: write `evidence.json`,
`commands.txt`, and `report.md` or `index.html`, and make all numbers and period claims
trace to finjuice command output or clearly labeled user-provided values.

## Final Response Contract

Follow [../finjuice/references/final-response-contract.md](../finjuice/references/final-response-contract.md)
and finish Korean-first. Include these fields in the final answer:

- `evidence_commands`: list `context`, `status`, `template run`, `rules gaps`, `show`,
  `explain`, or `query` commands that support the diagnosis.
- `mutations_applied`: usually `없음`; mention journal writes separately and include any
  user-confirmed mutation if the workflow routed into another skill.
- `files_written`: diagnosis journal path, report artifact path if explicitly requested,
  or `없음` for chat-only output.
- `skipped_steps`: skipped deeper reads, skipped report artifact creation, or skipped
  journal persistence with the reason.
- `residual_risk`: data gaps, stale imports, low tagging coverage, ambiguous categories,
  or assumptions that limit confidence.
- `next_suggested_action`: one concrete next action such as rule cleanup, review, import,
  or budget follow-up.

## Phase 0 — LOAD CONTEXT

Load [../finjuice/references/discovery-guide.md](../finjuice/references/discovery-guide.md).
Run `finjuice index --json --privacy compact`, then
`finjuice checkup --json --privacy compact` before deeper diagnosis reads.

Run `finjuice context --journal 3 --json`.
- Parse recent journals, snapshot, active goals, top patterns, and `_meta`.
- Extract the current baseline: recent concerns, month-level cashflow shape, active goals, and whether the context was truncated.
- If `_meta.truncated` is `true` and the user wants a deeper read, re-run with a larger budget before moving on: `finjuice context --journal 5 --budget 7000 --json`.

## Phase 1 — DEEPER READ

Run these in parallel:
- `finjuice status --json --detailed`
- `finjuice template run monthly_consumption_summary --output json`
- `finjuice template run monthly_spend --output json` only when you need legacy all-expense comparison.
- `finjuice rules gaps --json`

Pull out:
- Current date range, total transactions, tagging coverage, untagged count, and top merchants from `status`.
- Month-by-month canonical consumption totals, recent slope, and volatility from `monthly_consumption_summary`.
- Untagged spend concentration, mismatch hotspots, and likely high-impact merchants from `rules gaps`.

`consumption_spend` means expense rows after excluding confirmed transfers plus obvious
card-payment, transfer, savings, investment, pension, fund, stock, ISA/IRP, deposit-like
categories/tags. Do not rebuild this filter with ad-hoc SQL; use
`monthly_consumption_summary` and related templates unless a command fails.

## Phase 2 — STRUCTURED FINDINGS

Generate a diagnosis with exactly these sections:

```text
🩺 재정 진단

1. 현재 상태
- 월 평균 지출 / 최근 월 지출 추세 / 태깅 커버리지

2. 주요 리스크
- 리스크 1: [증거]
- 리스크 2: [증거]
- 리스크 3: [증거]

3. 주요 기회
- 기회 1: [증거]
- 기회 2: [증거]
- 기회 3: [증거]

4. 태깅 커버리지 관찰
- 미분류 집중 영역
- 잘못 묶인 카테고리 또는 규칙 공백
```

Rules:
- Every finding must cite which command produced the evidence.
- Separate spending risks from data-quality risks.
- Do not pad with generic advice. Only surface issues that the CLI evidence supports.

## Phase 3 — ACTION LIST

Produce a prioritized action list. Each item must map to a specific finjuice command or
sibling skill workflow.

Good examples:
- `finjuice template run recurring_candidates --output json` to isolate fixed-cost candidates before budget cuts.
- sibling skill `finjuice-rule-cleanup` to repair duplicate or overly broad rules causing
  false category rollups; if sibling switching is unavailable, follow
  `../finjuice-rule-cleanup/SKILL.md` inline.
- `finjuice show --json --untagged --limit 50` followed by `finjuice explain "merchant" --json` for the largest remaining unclassified merchants.
- `finjuice journal list` to compare this diagnosis against prior concerns before setting new goals.

Format:

```text
우선순위 액션

1. [action]
   명령: [exact command]
   이유: [why now]
   기대효과: [expected impact]
```

## Phase 4 — PERSIST THE DIAGNOSIS

Persist the session outcome only after explicit consent:
- If the user did not ask to save, record, or create a journal, ask once whether to save the
  diagnosis journal. If the user declines or does not answer, skip this phase and say no
  journal was written.
- Before writing, verify `journal new` is available with the shared runtime preflight helper.
  If it is blocked, keep the diagnosis chat-only and report the blocker.
- Run `finjuice journal new --topic <slug> --template diagnosis`.
- Run `finjuice journal resume <slug>` to resolve the created file path.
- Append or replace the body so the journal contains:
  - `# 진단 요약`
  - `## 현재 상태`
  - `## 주요 리스크`
  - `## 주요 기회`
  - `## 우선순위 액션`
- Report the saved journal path in the final response.

Pick `<slug>` from the dominant theme, for example `fixed-cost-diagnosis`, `q2-spend-diagnosis`, or `coverage-diagnosis`.
