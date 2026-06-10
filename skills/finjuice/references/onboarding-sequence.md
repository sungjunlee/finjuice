# Onboarding Command Sequence

Use this flow when `finjuice status --json` reports `DATA_DIR_NOT_INITIALIZED` or the user is clearly starting from scratch.

## Step 1: Detect current state

`finjuice status --json`

- If `transactions.count` is greater than `0`, onboarding is not needed.
- Parse `data_directory.path`, `transactions.date_range`, `tagging.untagged_count`, and `rules_file.path`.
- If `error.code` is `DATA_DIR_NOT_INITIALIZED`, continue to Step 2.
- If `error.code` is `NO_DATA`, the directory exists but there are no processed transactions yet; continue to Step 2.

## Step 2: Ask for the export file

- Ask: `뱅크샐러드에서 내보낸 엑셀 파일이 어디에 있나요?`
- Common paths: `~/Downloads/뱅크샐러드_*.xlsx`, `~/Downloads/*님_*.zip`
- If the file is a password-protected ZIP, collect the password before running the
  import command in a headless session. Prefer the CLI ZIP path; do not manually unzip
  unless `finjuice import` fails and you report that fallback.

## Step 3: Import data

`finjuice import <FILE_PATH> --json`

- For XLSX: `finjuice import ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx --json`
- For ZIP with an explicit option: `finjuice import ~/Downloads/뱅크샐러드_2024-12-22~2025-12-22.zip --password <PW> --json`
- For headless ZIP import without putting the password in the command history:
  `FINJUICE_ZIP_PASSWORD=<PW> finjuice import ~/Downloads/뱅크샐러드_2024-12-22~2025-12-22.zip --json`
- For preview-first ZIP import:
  `FINJUICE_ZIP_PASSWORD=<PW> finjuice import --dry-run ~/Downloads/뱅크샐러드_2024-12-22~2025-12-22.zip --json`
- Parse the JSON response for `status`, `pipeline_results`, and `imported_files`.
- In JSON mode, password-required ZIP imports must fail fast with a structured error
  instead of prompting. Ask for `FINJUICE_ZIP_PASSWORD` or `--password` and retry.
- First-run expectation: the command may print `Data directory initialized at ...` and a `First Run Setup` panel before running the pipeline.

## Step 4: Verify import

`finjuice status --json`

- Parse `transactions.count`
- Parse `transactions.date_range.start` and `transactions.date_range.end`
- Parse `tagging.tagged_count`, `tagging.untagged_count`, and `tagging.tagging_rate`
- Parse `rules_file.path` and `rules_file.exists`
- If `tagging.untagged_count` is `0`, skip rule curation but still collect optional context in Step 5.

## Step 5: Collect optional essential financial context

Ask up to five short questions. The user can answer `skip` to any of them:

1. 월 실수입 또는 가구 기준 월소득 추정이 있나요?
2. 월 지출 예산 상한은 얼마로 둘까요?
3. 매달 자동으로 저축/투자하는 금액이 있나요?
4. 부양가족, 가구원 수, 가족 지원 같은 예산 맥락이 있나요?
5. 월 30만원 이상 반복되는 대출, 월세, 보험료 같은 큰 의무지출이 있나요?

Persist only user-confirmed, aggregated answers:

- `monthly_budget.total` for the budget cap.
- `recurring_savings` for confirmed savings/investing.
- `financial_context.income`, `financial_context.family`, and `financial_context.housing`
  for stable context.
- `known_obligations` for confirmed large obligations/loans.

Use `source: "onboarding"` and today's `as_of` date for collected values. Then run:

`finjuice budget validate --json`

If validation fails, fix `goals.yaml` before continuing. A fully skipped context step
is valid as long as the base template still validates.

## Step 6: Suggest rules for untagged merchants

`finjuice rules suggest --json`

- Parse `untagged_count`, `total_count`, and `coverage_before_pct`
- Parse each suggestion's `merchant`, `pattern`, `transaction_count`, `banksalad_category.major`, and `banksalad_category.minor`
- Current CLI note: suggestion payloads do not include `confidence`; if you need user approval, show the top merchants before applying automatically.

## Step 7: Apply rules

`finjuice rules suggest --apply --yes --json`

- Parse `applied`, `skipped`, `coverage_before_pct`, and `coverage_after_pct`
- By default this also re-tags transactions because `--tag-after` defaults to `True`

## Step 8: Re-tag or verify coverage explicitly

`finjuice tag --json`

- Parse `total`, `tagged`, `untagged`, and `coverage_pct`
- Use this if Step 7 was skipped, `--no-tag-after` was used, or you want a fresh standalone coverage result

## Step 9: Present results

`finjuice status --json --detailed`

- Parse `transactions.count`, `transactions.date_range`, and `tagging.tagging_rate`
- Parse `detailed_stats.top_tags` and `detailed_stats.top_merchants`
- Suggested next steps:
  - `finjuice export --format html` for a visual report
  - `finjuice template run monthly_spend --output json` for a monthly spending summary
  - `finjuice show --json --untagged --limit 50` if untagged merchants remain
