# Troubleshooting Guide

**Last Updated**: 2026-06-16
**Status**: Current for finjuice v0.7.0

This guide covers hand-written troubleshooting advice for the current CLI. For exact
syntax, run `finjuice --help` or `finjuice <command> --help`.

---

## Quick Index

- [Installation Issues](#installation-issues)
- [Data Directory Issues](#data-directory-issues)
- [Import Problems](#import-problems)
- [Tagging Issues](#tagging-issues)
- [Query And Analysis Issues](#query-and-analysis-issues)
- [Export Errors](#export-errors)
- [Performance Issues](#performance-issues)
- [Advanced Debugging](#advanced-debugging)
- [Useful Commands](#useful-commands)

---

## Installation Issues

### "finjuice: command not found"

**Symptom**: Running `finjuice` returns "command not found".

**Solution from a source checkout**:

```bash
cd /path/to/finjuice
uv sync
uv run finjuice --version
# Expected: finjuice 0.7.0
```

If you installed a standalone executable, check that the install location is on PATH:

```bash
which finjuice
finjuice --version
```

### "No module named 'finjuice'"

**Symptom**: Python cannot import the package.

**Solution**:

```bash
cd /path/to/finjuice
uv sync
uv run python -c "import finjuice; print(finjuice.__file__)"
```

This should print a path under `src/finjuice/`.

### "uv: command not found"

Install uv first:

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows PowerShell
powershell -c "irm https://astral.sh/uv/install.ps1 | iex"

uv --version
```

---

## Data Directory Issues

### "Where is my data?"

The default data directory is `~/.finjuice`.

Resolution order:

1. `--data-dir PATH`
2. `FINJUICE_DATA_DIR`
3. `~/.finjuice/config.toml`
4. `~/.finjuice`

Inspect the active location:

```bash
finjuice status --json
finjuice doctor
```

Use a custom location explicitly:

```bash
finjuice --data-dir ~/Documents/my-finance-data status
finjuice --data-dir ~/Documents/my-finance-data refresh
```

### Existing `./data` no longer seems active

v0.6.x uses `~/.finjuice` by default. If you have a legacy `./data` directory, either
migrate it or pass it explicitly.

```bash
finjuice migrate --dry-run
finjuice migrate

finjuice --data-dir ~/Documents/my-finance-data status
```

### "Directory already exists and is not empty"

`finjuice init` is for advanced setup. Most users can start with `finjuice import`,
which initializes the data directory on first run.

If you intentionally want custom setup:

```bash
finjuice init
finjuice init --no-git
finjuice --data-dir ~/Documents/my-finance-data init --save-config
```

If initialization fails because the target contains unrelated files, choose a clean
directory or move the old files aside after backing them up.

---

## Import Problems

### "No XLSX files found in imports/"

**Symptom**: `finjuice ingest` or `finjuice refresh` cannot find input files.

For new files, prefer `import`:

```bash
finjuice import ~/Downloads/export.xlsx
finjuice import ~/Downloads/export.zip
finjuice import ~/Downloads/*.xlsx
```

If you intentionally use `ingest`/`refresh`, put XLSX files under the active data
directory:

```bash
ls -la ~/.finjuice/imports/
cp ~/Downloads/*.xlsx ~/.finjuice/imports/
finjuice refresh
```

For a custom data directory:

```bash
finjuice --data-dir ~/Documents/my-finance-data import ~/Downloads/export.xlsx
```

### Password-protected ZIP import fails

Banksalad ZIP exports can require a password. Pass it explicitly or use the environment
variable.

```bash
finjuice import ~/Downloads/export.zip --password 1234
FINJUICE_ZIP_PASSWORD=1234 finjuice import ~/Downloads/export.zip
```

### "Schema mismatch" or missing required fields

**Likely causes**:

- The file is not a Banksalad account-book export.
- The XLSX was edited manually and the header row changed.
- Banksalad changed the export format.

Check the current schema version:

```bash
rg -n "current_version" templates/schema.yaml
# Expected: current_version: 3
```

Then re-download the export from Banksalad and retry:

```bash
finjuice import --dry-run ~/Downloads/export.xlsx
finjuice import ~/Downloads/export.xlsx
```

### Duplicate row_hash warnings

This is normally safe. `row_hash` is the deduplication key, so importing the same file
again should not duplicate transactions.

To confirm the current data state:

```bash
finjuice status --detailed
finjuice history
```

---

## Tagging Issues

### No rules are applied

Check that `rules.yaml` exists and validates:

```bash
ls -la ~/.finjuice/rules.yaml
finjuice rules validate
finjuice rules list
```

If rules exist, inspect untagged rows and suggestions:

```bash
finjuice review --untagged --all-history
finjuice rules suggest
```

### Tags do not update after editing rules.yaml

Re-apply rules and regenerate reports:

```bash
finjuice rules validate
finjuice tag
finjuice export
```

For a safe preview:

```bash
finjuice tag --dry-run
```

### A transaction has an unexpected tag or category

Use `explain` and `rules test` instead of inspecting the XLSX manually.

```bash
finjuice explain "스타벅스"
finjuice explain "스타벅스" --date 2024-10-25
finjuice rules test cafe_starbucks --limit 10
```

Important v0.7.0 behavior:

- All matching enabled rules contribute deduplicated tags.
- The highest-priority matching rule with a non-empty `category` sets `category_rule`.
- `category_final` can also come from a manual category override, then falls back to
  `category_rule`, `minor_raw`, `major_raw`, and `미분류`.

### Need to manually correct one transaction

Find the row hash, then edit manual tags or category:

```bash
finjuice show --merchant 스타벅스 --limit 10
finjuice tag --edit ac875c7391d4e2f8 --add-tag 업무식대
finjuice tag --edit ac875c7391d4e2f8 --set-category 식비
```

---

## Query And Analysis Issues

### SQL query is rejected

`finjuice query` only allows `SELECT` and `WITH` statements. It blocks write keywords
and file/system access for safety.

Valid examples:

```bash
finjuice query "SELECT * FROM transactions LIMIT 5"
finjuice query "SELECT category_final, SUM(amount) FROM transactions GROUP BY category_final"
```

If you need a reusable query, check templates:

```bash
finjuice template list
finjuice template show monthly_spend
finjuice template run monthly_spend --output markdown
```

### Query results look filtered

`report_filters` from `rules.yaml` are applied by default to user-facing analysis
commands. Use root `--no-filter` for an audit view:

```bash
finjuice --no-filter query "SELECT COUNT(*) FROM transactions"
finjuice --no-filter status --json
```

### AI context is too large or too small

`context` emits local structured data only; it does not call an external model.

```bash
finjuice context --json --budget 3000
finjuice context --json --journal 5 --verbose
finjuice checkup --json --privacy redacted
```

---

## Export Errors

### "No data to export"

Check that transaction partitions exist:

```bash
find ~/.finjuice/transactions -name transactions.csv
finjuice status
```

If there are no partitions, import data first:

```bash
finjuice import ~/Downloads/export.xlsx
```

### Export reports are empty

Common causes:

- No non-transfer expense rows after filters.
- `report_filters` exclude the rows you expected to see.
- Tags were edited but reports were not regenerated.

Diagnostics:

```bash
finjuice status --detailed
finjuice show --limit 20
finjuice --no-filter status --detailed
finjuice query "SELECT type_norm, COUNT(*) FROM transactions GROUP BY type_norm"
```

Then regenerate:

```bash
finjuice tag
finjuice export
```

### Excel cannot open `master_YYYYMMDD.xlsx`

Regenerate the export. Move the old file aside first if you want to keep it for
debugging.

```bash
mkdir -p ~/Desktop/finjuice-debug
mv ~/.finjuice/exports/master_*.xlsx ~/Desktop/finjuice-debug/
finjuice export
```

You can also generate HTML or Markdown:

```bash
finjuice export --format html
finjuice export --format md
```

---

## Performance Issues

### `finjuice refresh` takes a long time

Expected rough ranges depend on hardware and XLSX size:

- Small dataset under 1,000 rows: seconds to under 30 seconds
- Medium dataset 1,000-10,000 rows: under a few minutes
- Large multi-year dataset: several minutes can be normal

Diagnostics:

```bash
finjuice status --detailed
find ~/.finjuice/transactions -name transactions.csv -print
finjuice --verbose refresh
```

If only rules changed, avoid full import work:

```bash
finjuice tag
finjuice export
```

### Out of memory during export

Try a narrower report or non-XLSX format:

```bash
finjuice export --format html --period 2024-10
finjuice export --format md --period 2024-10
```

Close memory-heavy applications and retry. If the issue persists, include dataset size,
format, period, OS, and `finjuice --version` in the bug report.

---

## Advanced Debugging

### Run the standard health checks

```bash
finjuice doctor
finjuice status --json
finjuice manifest --commands-only --json
```

### Inspect command-specific help

```bash
finjuice --help
finjuice import --help
finjuice refresh --help
finjuice query --help
finjuice context --help
finjuice rules --help
```

### Inspect partitions safely

Do not edit transaction partitions directly unless you are intentionally doing manual data
repair. For read-only inspection:

```bash
head -20 ~/.finjuice/transactions/2024/10/transactions.csv
wc -l ~/.finjuice/transactions/2024/10/transactions.csv
```

Prefer CLI read interfaces:

```bash
finjuice show --month 2024-10 --limit 20
finjuice query "SELECT COUNT(*) FROM transactions WHERE strftime(CAST(date AS DATE), '%Y-%m') = '2024-10'"
```

### Reset processed output while keeping imports

Back up before removing or moving processed data:

```bash
mkdir -p ~/Desktop/finjuice-backup
mv ~/.finjuice/transactions ~/Desktop/finjuice-backup/transactions
mv ~/.finjuice/exports ~/Desktop/finjuice-backup/exports
finjuice refresh
```

---

## Useful Commands

```bash
# Version and health
finjuice --version
finjuice doctor
finjuice status --detailed

# Import and reprocess
finjuice import ~/Downloads/export.xlsx
finjuice import ~/Downloads/export.zip --password 1234
finjuice refresh

# Read data
finjuice show --limit 10
finjuice review --untagged --all-history
finjuice query "SELECT * FROM transactions LIMIT 5"
finjuice template list

# Rules
finjuice rules validate
finjuice rules suggest
finjuice tag --dry-run

# AI-agent context
finjuice context --json
finjuice checkup --json --privacy redacted

# Reports
finjuice export
finjuice export --format html --period 2024-10
finjuice open reports
```

---

## Getting Help

If your issue is not covered here:

1. Run `finjuice doctor` and capture the non-sensitive output.
2. Include the exact command, OS, Python version, and `finjuice --version`.
3. Redact transaction rows, account names, and raw financial data before sharing logs.
4. Open an issue at <https://github.com/sungjunlee/finjuice/issues>.

---

**Last Updated**: 2026-06-16
**Version**: v0.7.0
**Related**: [Guides README](README.md), [User Guide](user_guide.md), [CLI Reference](../reference/cli.md)
