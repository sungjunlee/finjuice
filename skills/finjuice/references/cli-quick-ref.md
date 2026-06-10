# CLI Quick Reference

Use `--data-dir PATH` or `FINJUICE_DATA_DIR` when the data repository is not in the default location. Prefer JSON output when the command supports it.

## Pipeline

### `finjuice refresh`
- Description: Run the full pipeline in order: ingest, tag, transfer, export.
- Key flags: `--json`
- Example: `finjuice refresh --json`

### `finjuice ingest`
- Description: Read `imports/*.xlsx` and write transaction and asset partitions.
- Key flags: `--from-archive FILE_ID`, `--archive`, `--dry-run`, `--json`
- Example: `finjuice ingest --dry-run --json`

### `finjuice tag`
- Description: Apply `rules.yaml` to all transaction partitions and report coverage.
- Key flags: `--edit HASH`, `--add-tag TAG`, `--remove-tag TAG`, `--set-category CAT`, `--dry-run`, `--json`
- Example: `finjuice tag --json`
- Manual edit example: `finjuice tag --edit <hash> --add-tag 정기지출 --json`
- Category override example: `finjuice tag --edit <hash> --set-category 식비 --json`

### `finjuice transfer`
- Description: Pair internal transfers using amount and time-window matching.
- Key flags: `--json`
- Example: `finjuice transfer --json`

### `finjuice export`
- Description: Generate workbook and report artifacts, or preview them first.
- Key flags: `--format {xlsx|html|md|all}`, `--period YYYY-MM`, `--auto-open/--no-auto-open`, `--dry-run`, `--json`
- Example: `finjuice export --dry-run --json`

## Analysis

### `finjuice status`
- Description: Show resolved data directory, transaction coverage, last import, and rules status.
- Key flags: `--detailed`, `--top N`, `--json`
- Example: `finjuice status --json --detailed`

### `finjuice query`
- Description: Run `SELECT` or `WITH` SQL against the `transactions` view.
- Key flags: `--output {table|csv|json|markdown}`, `--json`
- Example: `finjuice query --json "SELECT date, merchant_raw, amount FROM transactions LIMIT 10"`
- DuckDB note: `date` is a `DATE`, not a string. For month grouping, use `substr(CAST(date AS VARCHAR), 1, 7)` instead of `substr(date, 1, 7)`.
- Transfer filter: use `is_transfer = 0` to exclude transfers.

### `finjuice show`
- Description: Return raw transaction rows with month, tag, merchant, or untagged filters.
- Key flags: `--month YYYY-MM`, `--untagged`, `--tag`, `--merchant`, `--limit N`, `--json`
- Example: `finjuice show --json --untagged --limit 50`

### `finjuice explain`
- Description: Find a transaction and show which rules matched, in what order, and how the final classification was chosen.
- Key flags: `QUERY`, `--date YYYY-MM-DD`, `--json`
- Example: `finjuice explain "스타벅스" --json`

### `finjuice template list`
- Description: List curated SQL templates that can be run without hand-writing SQL.
- Key flags: `--json`
- Example: `finjuice template list --json`

### `finjuice template show`
- Description: Show template metadata and the SQL definition for a named template.
- Key flags: `NAME`, `--json`
- Example: `finjuice template show monthly_spend --json`

### `finjuice template run`
- Description: Execute a template with validated parameters and optional JSON output.
- Key flags: `--param key=value`, `--output {table|csv|json|markdown|xlsx}`, `--file PATH`
- Example: `finjuice template run monthly_spend --output json`

## Rules

### `finjuice rules validate`
- Description: Validate `rules.yaml` for duplicates, overlaps, priority inversions, and bad regex.
- Key flags: `--json`
- Example: `finjuice rules validate --json`

### `finjuice rules suggest`
- Description: Suggest rule candidates for untagged merchants and optionally apply them.
- Key flags: `--top N`, `--min-count N`, `--output PATH`, `--apply`, `--yes`, `--tag-after/--no-tag-after`, `--json`
- Example: `finjuice rules suggest --json`

### `finjuice rules add`
- Description: Add or update a tagging rule, optionally with a dry-run impact preview.
- Key flags: `--name NAME`, `--match PATTERN`, `--tags TAGS`, `--category CAT`, `--fields FIELDS`, `--dry-run`, `--json`
- Example: `finjuice rules add --name netflix --match Netflix --category 구독 --tags 구독,정기지출 --json`

### `finjuice rules gaps`
- Description: Compare current tags to Banksalad categories and estimate coverage gains from new rules.
- Key flags: `--top N`, `--simulate/--no-simulate`, `--output PATH`, `--json`
- Example: `finjuice rules gaps --json`

## Admin

### `finjuice doctor`
- Description: Run environment, configuration, data, and dependency diagnostics.
- Key flags: `--json`
- Example: `finjuice doctor --json`

### `finjuice history`
- Description: List import history records with file IDs, timestamps, and archived sources.
- Key flags: `--json`
- Example: `finjuice history --json`

### `finjuice open`
- Description: Open the data directory, imports, reports, rules file, or latest master file in the system UI.
- Key flags: `TARGET` where target is `.`, `imports`, `exports`, `reports`, `transactions`/`tx`, `rules`, or `master`
- Example: `finjuice open rules`

### `finjuice audit log`
- Description: Show the audit trail of pipeline operations.
- Key flags: `--json`
- Example: `finjuice audit log --json`

### `finjuice audit stats`
- Description: Show aggregate statistics from the audit log.
- Key flags: `--json`
- Example: `finjuice audit stats --json`

### `finjuice workspace`
- Description: Create, list, remove, verify, or open workspace directories managed through symlinks.
- Key flags: `create`, `list`, `remove`, `verify`, `open`
- Example: `finjuice workspace list`
