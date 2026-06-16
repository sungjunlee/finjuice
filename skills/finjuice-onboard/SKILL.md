---
name: finjuice-onboard
description: |
  First-run onboarding for finjuice. Guides user through initial Banksalad XLSX import,
  data directory setup, and initial rule bootstrapping.
  Trigger when user says 처음 써봐, 나 처음 쓰는데, 가계부 시작하고 싶어, 뱅크샐러드 데이터 분석하고 싶어,
  or when finjuice status returns DATA_DIR_NOT_INITIALIZED.
argument-hint: "[file path to Banksalad export]"
compatibility: "Requires finjuice CLI runtime; resolve and run the shared runtime ensure helper before running `finjuice`."
---

# Finjuice Onboarding

## Side Effects

- Modes: `read-only`, `mutating-with-confirmation`, `artifact-writing`, `runtime-install/update`
- Reads setup state, doctor output, import previews, status, rules, and CLI metadata.
- Import/ingest, goal-context saves, rule curation, refresh, tag, transfer, and export steps mutate local finjuice data or write generated outputs only after explicit user confirmation or a direct user request.
- Runtime ensure may install a missing runtime or update runtime state only under the shared runtime policy.

## Runtime Requirements

- Minimum finjuice: `0.7.0`
- Capabilities: `index`, `status`, `import`
- Unsupported fallback: Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because the local finjuice runtime lacks required capability `<capability>`. Do not recommend or run the failed command after preflight failure.

Guide the user through first-time setup. Ask one question at a time, wait for the answer, then proceed.

## Runtime Preflight

Before running any `finjuice ...` command, load the shared procedure in
`skills/finjuice/references/runtime-preflight.md` to resolve `FINJUICE_ENSURE`, then
run this skill-local gate:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.7.0 \
  --require-command "index" \
  --require-command "status" \
  --require-command "import"
```

If the JSON response has `status: "blocked"`, stop and report its `message`; do not
install `uv` automatically or continue to finjuice commands.

## Step 1 — Detect state

Load [../finjuice/references/discovery-guide.md](../finjuice/references/discovery-guide.md),
then run `finjuice index --json --privacy compact`.
- If `workspace.status` is `uninitialized`, continue.
- Find the `collections[]` entry where `name == "transactions"`. If its `status` is
  `populated`, onboarding is not needed. Say so and suggest the base `finjuice` skill
  for analysis.

Run `finjuice status --json` only after the index shows an initialized workspace that
needs transaction/tagging details.
- If `transactions.count` > 0, onboarding is not needed. Say so and suggest the base
  `finjuice` skill for analysis.
- If `error.code` is `DATA_DIR_NOT_INITIALIZED` or `NO_DATA`, continue.

## Step 2 — Ask for the export file

Ask: `뱅크샐러드에서 내보낸 엑셀 파일이 어디에 있나요?`
- Common paths: `~/Downloads/뱅크샐러드_*.xlsx`, `~/Downloads/*님_*.zip`
- If the file is a password-protected ZIP, collect the password before Step 3.

## Step 3 — Import

Run `finjuice import <FILE_PATH> --json` (add `--password <PW>` for ZIP).
- Parse `status`, `pipeline_results`, and `imported_files`.
- First-run: the command auto-creates `~/.finjuice` and runs ingest -> tag -> transfer -> export.

## Step 4 — Verify

Run `finjuice status --json`.
- Parse `transactions.count`, `transactions.date_range`, `tagging.untagged_count`, and `rules_file.path`.
- If `tagging.untagged_count` is 0, skip rule curation but still collect optional context in Step 5.

## Step 5 — Optional essential financial context

Ask 3-5 short questions. The user may answer `skip` for any item:
- 월 실수입 또는 가구 기준 월소득 추정이 있나요?
- 월 지출 예산 상한은 얼마로 둘까요?
- 매달 자동으로 저축/투자하는 금액이 있나요?
- 부양가족, 가구원 수, 가족 지원 같은 예산 맥락이 있나요?
- 월 30만원 이상 반복되는 대출, 월세, 보험료 같은 큰 의무지출이 있나요?

Write only user-confirmed, high-level answers into `goals.yaml`:
- `monthly_budget.total` for the budget cap.
- `recurring_savings` for confirmed savings/investing.
- `financial_context.income`, `financial_context.family`, and `financial_context.housing`
  for stable context.
- `known_obligations` for confirmed large obligations/loans.

Use `source: "onboarding"` and today's `as_of` date when the user provides a value.
After editing, run `finjuice budget validate --json`. If validation fails, fix
`goals.yaml` before continuing.

## Step 6 — Initial rule curation

Switch to sibling skill `finjuice-curate` if available; otherwise follow
`../finjuice-curate/SKILL.md` inline to interactively improve tagging coverage.
- This handles the suggest -> judge -> apply loop with the user.
- If the user explicitly asks for bulk auto-apply, use `finjuice rules suggest --apply --yes --json` as a bootstrap shortcut instead.

## Step 7 — Re-tag

Run `finjuice tag --json` after rules are added.
- Parse `total`, `tagged`, `untagged`, and `coverage_pct`.

## Step 8 — Present results

Run `finjuice status --json --detailed`.
- Show total transactions, date range, tagging coverage, top tags, and top merchants.
- Suggest next steps:
  - `finjuice export --format html` for a visual report
  - `finjuice template run monthly_spend --output json` for monthly spending
  - sibling skill `finjuice-review` for a weekly review if available; otherwise follow
    `../finjuice-review/SKILL.md` inline

Full step-by-step command guidance lives in [../finjuice/references/onboarding-sequence.md](../finjuice/references/onboarding-sequence.md) (requires the base `finjuice` skill to be co-installed).
