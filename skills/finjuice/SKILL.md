---
name: finjuice
description: |
  Beginner-first personal finance router for Korean finance data. Use when user asks
  about spending, transactions, categories, tags, reports, assets, budgets, trends,
  or says 가계부, 지출, 소비, 거래내역, 얼마 썼어, 이번 달, 카드 사용, 자산, 예산, or 절약.
  Trigger on finjuice, Banksalad, "spending report", or "where did my money go?"
  For first-run setup, switch to sibling skill finjuice-onboard if available.
  For tagging and category cleanup, switch to sibling skill finjuice-curate or finjuice-rule-cleanup if available.
  For weekly/monthly reviews, switch to sibling skill finjuice-review if available.
  For saved report artifacts, HTML reports, yearly recaps, or spending report files, switch to sibling skill finjuice-report if available.
  For advanced explicit workflows only, switch to sibling skill finjuice-diagnose
  when the user clearly asks for full diagnosis.
  If sibling switching is unavailable, follow the referenced sibling SKILL.md inline.
argument-hint: "[question or command]"
compatibility: "Requires finjuice CLI runtime; resolve and run the shared runtime ensure helper before running `finjuice`."
---

# Finjuice

## Side Effects

- Modes: `read-only`, `mutating-with-confirmation`, `artifact-writing`, `runtime-install/update`
- Default analysis reads status, doctor, templates, rules, transactions, assets, and generated summaries.
- `refresh`, `tag`, `rules add/remove`, imports, and exported deliverables mutate runtime data or write artifacts; route to the owning skill and ask before acting unless the user directly requested that operation.
- Runtime ensure may install a missing runtime or update runtime state only under the shared runtime policy.

## Runtime Requirements

- Minimum finjuice: `0.6.2`
- Capabilities: `index`, `checkup`, `status`, `doctor`, `manifest`
- Unsupported fallback: Unsupported CLI path: `<cli path>`. Confidence lost for this workflow because the local finjuice runtime lacks required capability `<capability>`. Do not recommend or run the failed command after preflight failure.

## Runtime Preflight

Before running any `finjuice ...` command, load the shared procedure in
`skills/finjuice/references/runtime-preflight.md` to resolve `FINJUICE_ENSURE`, then
run this skill-local gate:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.6.2 \
  --require-command "index" \
  --require-command "checkup" \
  --require-command "status" \
  --require-command "doctor" \
  --require-command "manifest"
```

If the JSON response has `status: "blocked"`, stop and report its `message`; do not
install `uv` automatically or continue to finjuice commands.

## Data Setup

- Use the Runtime Preflight before CLI calls. If it reports `status: "ready"`, continue
  with the requested command. If it is blocked, report the blocker instead of guessing.
- Resolve the data directory in this order: CLI `--data-dir`, `FINJUICE_DATA_DIR`, saved config, OS default.
- For workspace discovery, load [references/discovery-guide.md](references/discovery-guide.md).
- Start with `finjuice index --json --privacy compact` to identify available collections
  and safe next commands without exposing local paths.
- Run `finjuice checkup --json --privacy compact` when the user needs a general health
  snapshot or the next action is unclear.
- Run `finjuice status --json` after index/checkup when you need `data_directory.path`,
  transaction date ranges, tagging coverage, or `rules_file` details.
- Run `finjuice doctor --json` only when setup looks broken, paths are missing, or
  index/checkup/status returns a runtime health problem.
- Run `finjuice manifest --json` when you need CLI/API discovery such as command syntax,
  safety metadata, schema refs, global options, or privacy profile support.
- If the user has raw exports but no processed data, switch to sibling skill
  `finjuice-onboard` if available; otherwise follow `../finjuice-onboard/SKILL.md`
  inline or import before analysis.
- Use `finjuice ingest --dry-run --json` to preview partition writes without changing data.
- Asset questions require snapshot files under `assets/snapshots/YYYY/MM/snapshots.csv`; if absent, ingest first.
- For dict-shaped JSON responses, parse `_meta` when present for `schema_version`, `command`, and timestamp.
- For exact command syntax, prefer live `finjuice <command> --help` or [references/cli-quick-ref.md](references/cli-quick-ref.md).

## Routing

Routing action: switch to the named sibling skill if the host exposes sibling skills.
If it does not, follow the referenced `SKILL.md` inline. Do not make the workflow depend
on slash commands existing.

### Beginner Core

- User is new or data directory is uninitialized (`DATA_DIR_NOT_INITIALIZED`, `처음 써봐`, `나 처음 쓰는데`, `가계부 시작하고 싶어`, `뱅크샐러드 데이터 분석하고 싶어`) -> `finjuice-onboard` (`../finjuice-onboard/SKILL.md`).
- User asks a practical spending question (`지난달 지출`, `소비 패턴`, `구독 요금`, `매달 새는 돈`, `어디에 많이 썼어`, `카드 사용이 늘었어`, `카드 결제나 계좌 이체`, `중복으로 잡힌`, `돈 흐름 점검`) -> `finjuice-review` (`../finjuice-review/SKILL.md`) unless they explicitly ask to save a file.
- User asks to improve tagging coverage, curate rules, or says `태그 정리`, `커버리지 올려줘`, `카테고리와 태그 규칙`, `규칙 추가해줘`, `rule curation`, `태깅 개선`, `미분류 정리` -> `finjuice-curate` (`../finjuice-curate/SKILL.md`).
- User asks for taxonomy maintenance, duplicate-rule cleanup, or says `규칙 정비`, `룰 정리`, `중복 규칙 정리`, `rule cleanup`, `taxonomy cleanup`, `tagging maintenance` -> `finjuice-rule-cleanup` (`../finjuice-rule-cleanup/SKILL.md`).
- User asks for a saved report artifact (`이번 달 리포트 HTML로 만들어줘`, `리포트 파일로 만들어줘`, `HTML 리포트`, `저장해줘`, `연간 recap`, `spending recap`, `report artifact`) -> `finjuice-report` (`../finjuice-report/SKILL.md`).

### Advanced Explicit Workflows

Do not route casual spending-review prompts here. Use these only when the user clearly
asks for the named high-scope workflow.

- User asks for a full diagnosis (`재정 진단`, `종합 진단`, `소비 건강검진`, `financial diagnosis`, `spending diagnosis`, `money health check`) -> `finjuice-diagnose` (`../finjuice-diagnose/SKILL.md`).

## Default Command Choices

- Workspace map -> `finjuice index --json --privacy compact` first.
- General health and next actions -> `finjuice checkup --json --privacy compact`.
- Detailed data health or import coverage -> `finjuice status --json`, then
  `finjuice doctor --json` if something looks broken.
- CLI/API contract lookup -> `finjuice manifest --json`.
- Full processing after new imports -> `finjuice refresh --json`.
- Read-only analysis -> prefer `template run`, `show`, `explain`, or `query --json`.
- Saved report artifacts -> switch to sibling skill `finjuice-report` if available;
  otherwise follow `../finjuice-report/SKILL.md` inline. Shared evidence contract lives
  in [references/report-contract.md](references/report-contract.md).
- Rule coverage growth -> switch to sibling skill `finjuice-curate` if available;
  otherwise follow `../finjuice-curate/SKILL.md` inline. Do not write rules without a
  preview and user confirmation.
- Taxonomy maintenance -> switch to sibling skill `finjuice-rule-cleanup` if available;
  otherwise follow `../finjuice-rule-cleanup/SKILL.md` inline. Validate rules after
  changes.
- Detailed syntax -> use [references/cli-quick-ref.md](references/cli-quick-ref.md) or live CLI help.

## Query Notes

- `date` is a DuckDB `DATE`. For month grouping use `substr(CAST(date AS VARCHAR), 1, 7)`.
- Exclude internal transfers with `is_transfer = 0` unless the user asks to include transfers.
- Use `query --json` for custom aggregation and keep SQL to `SELECT` or `WITH`.
- For reusable analyses, prefer `finjuice template list --json`, `template show`, and `template run`.

## Rules File

- The rules file lives at `<data-dir>/rules.yaml`; confirm the resolved path with `finjuice status --json`.
- Rules are YAML objects with `name`, `match`, `fields`, `tags`, optional `category`, and `priority`.
- `match` uses Python-style regex; join alternate merchant spellings with `|`.
- `fields` usually target `merchant_raw`, `memo_raw`, `major_raw`, or `minor_raw`.
- Higher `priority` is checked first; rule evaluation is descending and first match wins.
- Use `finjuice rules validate --json` after edits to catch duplicate names, overlaps, regex errors, and priority inversions.
- For gap analysis and rule suggestions, switch to sibling skill `finjuice-curate` if
  available; otherwise follow `../finjuice-curate/SKILL.md` inline or run
  `finjuice rules suggest --json` directly.
- Preview rule writes with `--dry-run` and ask before applying unless the user explicitly requested automation.
- `category` is the single aggregation bucket; `tags` are multi-value attributes for filtering and analysis.
- `category_final` falls back to Banksalad categories when a rule does not set `category`.
- `tags_final` is for filtering only, not spend aggregation.
- The full format guide and examples live in [references/rules-format.md](references/rules-format.md).

## Error Handling

- If JSON output contains `error.code: DATA_DIR_NOT_INITIALIZED`, switch to sibling skill
  `finjuice-onboard` if available; otherwise follow `../finjuice-onboard/SKILL.md`
  inline.
- If `error.code: NO_DATA`, import or ingest data before answering analytical questions.
- If `error.code: RULES_FILE_NOT_FOUND`, create or restore `rules.yaml` in the resolved data directory.
- If asset reports say snapshots are missing, run ingest and confirm `assets/snapshots/YYYY/MM/snapshots.csv` exists.
- If a command has no JSON mode, use its plain-text output only after confirming it is the correct command for the task.

## Related Files

- `<data-dir>/transactions/YYYY/MM/transactions.csv`: partitioned transaction rows.
- `<data-dir>/assets/snapshots/YYYY/MM/snapshots.csv`: monthly asset snapshots.
- `<data-dir>/rules.yaml`: tagging rules.
- `templates/schema.yaml`: transaction and asset schema definitions.
- `<data-dir>/exports/` and `<data-dir>/exports/reports/`: generated workbooks and report files.
