# CLI Reference

> **Auto-generated from** `finjuice --help`
> **Do not edit manually** - Run `just docs-cli` to regenerate

---

## Installation

```bash
# Install package with uv
uv pip install -e .

# Verify installation
finjuice --version
```

---

## Main Command

```

 Usage: finjuice [OPTIONS] [COMMAND] [ARGS]...

 Local-first personal finance pipeline for Banksalad data

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --version                  Show finjuice version and exit. 'finjuice version --json' for machine-readable.           │
│ --data-dir   -d      PATH  Data directory path. Priority: CLI arg > FINJUICE_DATA_DIR env var > ~/.finjuice default. │
│                            Example: finjuice --data-dir ~/my-finance-data refresh                                    │
│                            [env var: FINJUICE_DATA_DIR]                                                              │
│ --verbose    -v            Enable DEBUG-level logging                                                                │
│ --no-filter                Disable read-time report_filters for this invocation.                                     │
│ --help                     Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ import          Import XLSX files and run full pipeline.                                                             │
│ tag             Apply tagging rules to all transactions in the active storage.                                       │
│ export          Generate master XLSX, HTML, and/or Markdown reports.                                                 │
│ export-verify   Check export revision freshness and modified or missing artifacts without writing.                   │
│ refresh         Re-process all existing data                                                                         │
│ validate        Validate CSV partition files against the schema.                                                     │
│ index           Emit workspace catalog                                                                               │
│ status          Show current data status.                                                                            │
│ automation      Run one-shot workflow automation checks for external schedulers.                                     │
│ rules           Manage tagging rules                                                                                 │
│ journal         Create and revisit markdown journals with financial snapshots.                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Analysis ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ query           Execute a SQL query on your transaction data.                                                        │
│ explain         Explain the classification of a transaction.                                                         │
│ context         Emit a read-only context bundle for external AI agents.                                              │
│ checkup         Emit the recommended read-only runtime snapshot for agent inspect/decide loops.                      │
│ review          Show transactions that need manual review.                                                           │
│ show            Show transactions with optional filters.                                                             │
│ template        Run curated SQL query templates, including dynamic pivot tables                                      │
│ inspect         Privacy-safe source file inspection.                                                                 │
│ assets          View raw asset snapshot rows and per-position holdings                                               │
│ networth        View aggregated net worth from asset snapshots plus assets.yaml. Use `finjuice assets` for raw       │
│                 snapshot rows.                                                                                       │
│ budget          Track declarative monthly budgets from goals.yaml                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Admin ──────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ update-agents   Update AGENTS.md to the latest template version.                                                     │
│ init            Initialize directory structure (advanced setup).                                                     │
│ history         Display import history log.                                                                          │
│ open            Open data directories or files in file manager/editor.                                               │
│ doctor          Diagnose environment and identify issues.                                                            │
│ manifest        Emit CLI manifest                                                                                    │
│ version         Show finjuice CLI version and data schema version.                                                   │
│ workspace       Manage workspace directories (symlink-based)                                                         │
│ backup          Create, verify, and restore a complete legacy data-tree backup.                                      │
│ ssot            Manage inactive SQLite migration candidates.                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Advanced ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ ingest          Import XLSX files from imports/ into the selected storage authority.                                 │
│ transfer        Detect and pair internal transfers.                                                                  │
│ reconcile       Match evidence to ledger payments without writing transactions.                                      │
│ audit           Inspect and manage audit logs                                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

`finjuice assets` shows raw imported snapshot rows; `finjuice networth` shows the aggregated position view from snapshots plus `assets.yaml`.

## `finjuice refresh`

```

 Usage: finjuice refresh [OPTIONS]

 Re-process all existing data (ingest → tag → transfer → export).

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                Output as JSON                                                                 │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice status`

```

 Usage: finjuice status [OPTIONS]

 Show current data status.

 Displays:
 - Transaction count and date range
 - Last import information
 - Untagged transactions needing review
 - Rules file status

 With --detailed flag:
 - Monthly average income and expense
 - Recent savings rate
 - Top spending categories

 Examples:
     finjuice status             # 기본 상태
     finjuice status --detailed  # 상세 통계 포함
     finjuice status -d -n 10    # 상위 10개 항목

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --detailed  -d               상세 통계 포함 (태그별/가맹점별 지출)                                                   │
│ --top       -n      INTEGER  상세 통계에서 보여줄 상위 항목 수 [default: 5]                                          │
│ --json                       Output as JSON                                                                          │
│ --help                       Show this message and exit.                                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice automation`

```

 Usage: finjuice automation [OPTIONS] COMMAND [ARGS]...

 Run one-shot workflow automation checks for external schedulers.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ run   Run one one-shot automation pass using config-backed thresholds.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice automation run`

```

 Usage: finjuice automation run [OPTIONS]

 Run one one-shot automation pass using config-backed thresholds.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                   Output as JSON                                                              │
│ --privacy        [raw|redacted|compact]  Privacy profile for JSON output: raw, redacted, or compact [default: raw]   │
│ --help                                   Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice checkup`

```

 Usage: finjuice checkup [OPTIONS]

 Emit the recommended read-only runtime snapshot for agent inspect/decide loops.

 Pattern:
     agent -> `finjuice checkup --json` -> choose the next explicit finjuice command

 Use --fast for a cheap posture summary that skips full detectors.

 The finjuice CLI only emits structured data. It does not execute side effects here.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                       Output as JSON                                                          │
│ --privacy            [raw|redacted|compact]  Privacy profile for JSON output: raw, redacted, or compact              │
│                                              [default: raw]                                                          │
│ --stale-after        INTEGER                 Days after which data is considered stale (default: 35) [default: 35]   │
│ --fast                                       Cheap posture summary; skip full detectors.                             │
│ --help                                       Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice context`

```

 Usage: finjuice context [OPTIONS]

 Emit a read-only context bundle for external AI agents.

 Pattern:
     agent -> `finjuice context --json` -> compose prompt -> call the agent's own LLM

 The finjuice CLI only emits structured data. It does not call external models.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --journal        INTEGER RANGE [x>=0]  Number of newest journal entries to include (default: 3). [default: 3]        │
│ --budget         INTEGER RANGE [x>=1]  Token budget for the emitted context. Default: FINJUICE_CONTEXT_BUDGET if     │
│                                        set, else 5000. --budget overrides the env var.                               │
│ --verbose                              Write the section-by-section token breakdown to stderr.                       │
│ --json                                 Emit structured JSON instead of the default text summary.                     │
│ --help                                 Show this message and exit.                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice import`

```

 Usage: finjuice import [OPTIONS] [FILES]...

 Import XLSX files and run full pipeline.

 This is the main command for processing new Banksalad exports:
 1. Copy XLSX files to imports/ directory (extracts from ZIP if needed)
 2. Run full pipeline (ingest → tag → transfer → export)

 Supports both XLSX files and password-protected ZIP files from Banksalad.

 Examples:
     # Explicit file option
     finjuice import --file ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx

     # Import and process a single file
     finjuice import ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx

     # Import password-protected ZIP (prompts for password)
     finjuice import ~/Downloads/뱅크샐러드_2024-12-22~2025-12-22.zip

     # Import ZIP with password option
     finjuice import ~/Downloads/*.zip --password 1234

     # Headless ZIP import via environment variable
     FINJUICE_ZIP_PASSWORD=1234 finjuice import ~/Downloads/export.zip --json

     # Preview password-protected ZIP import without processing
     FINJUICE_ZIP_PASSWORD=1234 finjuice import --dry-run ~/Downloads/export.zip --json

     # Import multiple files (XLSX and ZIP mixed)
     finjuice import ~/Downloads/export1.xlsx ~/Downloads/export2.zip

     # Overwrite existing files
     finjuice import --force ~/Downloads/*.xlsx

     # Preview without processing
     finjuice import --dry-run ~/Downloads/*.xlsx

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│   files      [FILES]...  XLSX or ZIP file(s) to import. Pass one or more paths, or use --file for a single XLSX.     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --file                         PATH     XLSX file to import without prompts.                                         │
│ --force                -f               Overwrite existing files in imports/                                         │
│ --dry-run                               Preview what would be imported without processing                            │
│ --no-scan                               Disable auto-scan of ~/Downloads for Banksalad files                         │
│ --password             -p      TEXT     Password for encrypted ZIP files. If not provided, prompts interactively.    │
│                                         [env var: FINJUICE_ZIP_PASSWORD]                                             │
│ --json                                  Output as JSON                                                               │
│ --idempotency-key              TEXT     Stable retry key for an authoritative mutation                               │
│ --expected-generation          TEXT     Expected active dataset generation                                           │
│ --expected-revision            INTEGER  Expected active dataset revision                                             │
│ --help                                  Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice budget`

```

 Usage: finjuice budget [OPTIONS] COMMAND [ARGS]...

 Track declarative monthly budgets from goals.yaml

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ status     Show monthly budget targets vs actual consumption spend.                                                  │
│ edit       Edit monthly budget values in goals.yaml while preserving comments.                                       │
│ validate   Validate goals.yaml against the monthly_budget schema.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice budget status`

```

 Usage: finjuice budget status [OPTIONS]

 Show monthly budget targets vs actual consumption spend.

 Spend excludes savings/transfers/investments matching the shared
 non-consumption pattern used by monthly_consumption_summary.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --month        TEXT  Budget month (YYYY-MM)                                                                          │
│ --json               Output as JSON                                                                                  │
│ --help               Show this message and exit.                                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice budget edit`

```

 Usage: finjuice budget edit [OPTIONS]

 Edit monthly budget values in goals.yaml while preserving comments.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --set                        KEY=VALUE  Update one field in goals.yaml. Use total=..., categories.<name>=...,        │
│                                         monthly_budget.categories.<name>=..., or bare category names such as         │
│                                         식비=700000.                                                                 │
│ --yes                                   Skip the confirmation prompt                                                 │
│ --json                                  Output as JSON                                                               │
│ --idempotency-key            TEXT       Stable retry key for an authoritative mutation                               │
│ --expected-generation        TEXT       Expected active dataset generation                                           │
│ --expected-revision          INTEGER    Expected active dataset revision                                             │
│ --help                                  Show this message and exit.                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice budget validate`

```

 Usage: finjuice budget validate [OPTIONS]

 Validate goals.yaml against the monthly_budget schema.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON                                                                                       │
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice tag`

```

 Usage: finjuice tag [OPTIONS]

 Apply tagging rules to all transactions in the active storage.

 Loads rules from the canonical config or legacy rules.yaml.
 Updates tags_rule and tags_final fields.

 Use --dry-run to preview changes before applying them.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --edit                                   TEXT     Inspect or edit a transaction's manual tags by row_hash            │
│ --add-tag                                TEXT     Add one or more manual tags (repeatable)                           │
│ --remove-tag                             TEXT     Remove one or more manual tags (repeatable)                        │
│ --set-category                           TEXT     Persist a manual category override for category_final              │
│ --set-note                               TEXT     Persist a row-level manual note without changing analysis tags     │
│ --dry-run                --no-dry-run             Preview changes without writing to the active storage              │
│                                                   [default: no-dry-run]                                              │
│ --json                                            Output as JSON                                                     │
│ --idempotency-key                        TEXT     Stable retry key for an authoritative mutation                     │
│ --expected-generation                    TEXT     Expected active dataset generation                                 │
│ --expected-revision                      INTEGER  Expected active dataset revision                                   │
│ --delivery-config                        PATH     Explicit delivery JSON after manual edit.                          │
│ --help                                            Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice export`

```

 Usage: finjuice export [OPTIONS]

 Generate master XLSX, HTML, and/or Markdown reports.

 Exports:
 - xlsx: master_YYYYMMDD.xlsx + CSV reports (default). The master workbook
   stays unfiltered for auditability; report CSVs honor report_filters unless
   the root --no-filter flag is set.
 - html: Interactive HTML report with Plotly charts. Honors report_filters by default.
 - md: GitHub-friendly Markdown report. Honors report_filters by default.
 - all: All formats (xlsx + html + md)

 Examples:
     # Default XLSX export
     finjuice export

     # HTML report with charts (auto-opens in browser)
     finjuice export --format html

     # Markdown for version control
     finjuice export --format md

     # October 2024 only
     finjuice export --format html --period 2024-10

     # All formats
     finjuice export --format all

     # Disable auto-open
     finjuice export --format html --no-auto-open

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --format     -f                    TEXT  Export format: xlsx, html, md, all [default: xlsx]                          │
│ --period     -p                    TEXT  Period filter (YYYY-MM format, e.g., 2024-10)                               │
│ --auto-open      --no-auto-open          Auto-open report in browser/viewer (HTML only) [default: auto-open]         │
│ --dry-run        --no-dry-run            Preview output files without writing [default: no-dry-run]                  │
│ --json                                   Output as JSON                                                              │
│ --online                                 Load Plotly.js from CDN (default: offline/embedded for privacy)             │
│ --help                                   Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice show`

```

 Usage: finjuice show [OPTIONS]

 Show transactions with optional filters.

 Displays transactions in a formatted table with options to filter by:
 - Month (YYYY-MM format)
 - Untagged status
 - Specific tag
 - Merchant name

 Scope:
     - Bare `show` (no filters): latest month only (bounded output).
     - Any of --tag/--untagged/--merchant without --month: scans all partitions.
     - --month X: scoped to that month only, regardless of other filters.

 Examples:
     # Show latest 20 transactions (latest month only)
     finjuice show

     # Show October 2024 transactions
     finjuice show --month 2024-10

     # Show untagged transactions (across all partitions)
     finjuice show --untagged --limit 50

     # Show specific tag (across all partitions)
     finjuice show --tag 카페 --limit 30

     # Quote tags with brackets/spaces
     finjuice show --tag "[테스트]LLM서비스"

     # Combine month + tag to scope to a single month
     finjuice show --month 2025-04 --tag 카페

     # Show specific merchant
     finjuice show --merchant 스타벅스

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --month              TEXT     Filter by month (YYYY-MM)                                                              │
│ --untagged                    Show only untagged transactions                                                        │
│ --tag                TEXT     Filter by tag (exact match; scans all partitions when --month is omitted). Quote tags  │
│                               that contain spaces or brackets, e.g. --tag "[테스트]LLM서비스".                       │
│ --merchant           TEXT     Filter by merchant (case-insensitive)                                                  │
│ --limit      -n      INTEGER  Number of transactions to show [default: 20]                                           │
│ --cursor             TEXT     Opaque pagination cursor [default: 0]                                                  │
│ --max-bytes          INTEGER  Maximum serialized JSON response size before truncating rows [default: 1048576]        │
│ --json                        Output as JSON                                                                         │
│ --help                        Show this message and exit.                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice review`

```

 Usage: finjuice review [OPTIONS]

 Show transactions that need manual review.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --untagged                                        Show only untagged transactions (tags_final=[])                    │
│ --low-confidence          FLOAT                   Filter by confidence below threshold (e.g., 0.7)                   │
│ --month                   TEXT                    Filter by month (YYYY-MM)                                          │
│ --all-history                                     Review matching transactions across all available monthly          │
│                                                   partitions                                                         │
│ --limit           -n      INTEGER                 Number of transactions to show [default: 50]                       │
│ --cursor                  TEXT                    Opaque pagination cursor [default: 0]                              │
│ --max-bytes               INTEGER                 Maximum serialized JSON response size before truncating            │
│                                                   transactions                                                       │
│                                                   [default: 1048576]                                                 │
│ --json                                            Output as JSON                                                     │
│ --privacy                 [raw|redacted|compact]  Privacy profile for JSON output: raw, redacted, or compact         │
│                                                   [default: raw]                                                     │
│ --help                                            Show this message and exit.                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice rules`

```

 Usage: finjuice rules [OPTIONS] COMMAND [ARGS]...

 Manage tagging rules

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ validate   Validate tagging rules for conflicts and issues.                                                          │
│ list       List tagging rules as structured JSON or a compact table.                                                 │
│ add        Add or update a tagging rule programmatically.                                                            │
│ remove     Remove a tagging rule by name.                                                                            │
│ test       Dry-run a single rule against existing transactions without writing changes.                              │
│ suggest    Suggest rule patterns with rich merchant context.                                                         │
│ export     Export tagging rules as Banksalad category mapping guide.                                                 │
│ gaps       Analyze gaps between tags and Banksalad categories.                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice rules suggest`

```

 Usage: finjuice rules suggest [OPTIONS]

 Suggest rule patterns with rich merchant context.

 Analyzes untagged merchants with DuckDB and shows context that helps users
 or AI agents decide how to tag them. `--apply --yes` still creates rules
 from the generated pattern plus Banksalad category context.

 Examples:
     finjuice rules suggest              # Show top 10 suggestions
     finjuice rules suggest --top 20     # Show top 20 suggestions
     finjuice rules suggest -o rules.txt # Save to file
     finjuice rules suggest --apply      # Interactively add rules
     finjuice rules suggest --apply --yes   # Auto-apply all suggestions

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --top        -n                    INTEGER                 Number of suggestions to show (default: 10) [default: 10] │
│ --min-count  -m                    INTEGER                 Minimum transaction count for a merchant (default: 1)     │
│                                                            [default: 1]                                              │
│ --output     -o                    PATH                    Save merchant context report to file                      │
│ --apply      -a                                            Interactively apply suggested rules to rules.yaml         │
│ --yes        -y                                            Apply all suggestions without prompts (use with --apply)  │
│ --preview                                                  Show merchant context table before next steps             │
│ --dry-run                                                  Preview rules that would be added without modifying       │
│                                                            rules.yaml                                                │
│ --file-id                          TEXT                    Limit suggestions to transactions imported from a         │
│                                                            specific file_id                                          │
│ --json                                                     Output as JSON                                            │
│ --privacy                          [raw|redacted|compact]  Privacy profile for JSON output: raw, redacted, or        │
│                                                            compact                                                   │
│                                                            [default: raw]                                            │
│ --tag-after      --no-tag-after                            Re-tag transactions after applying rules (default: True)  │
│                                                            [default: tag-after]                                      │
│ --help                                                     Show this message and exit.                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice rules validate`

```

 Usage: finjuice rules validate [OPTIONS]

 Validate tagging rules for conflicts and issues.

 Checks for:
 - Duplicate rule names
 - Pattern overlaps (rules that match same transactions)
 - Priority inversions (broad patterns blocking specific ones)
 - Invalid regex patterns

 Examples:
     finjuice rules validate

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json            Output as JSON                                                                                     │
│ --strict          Fail fast on the first malformed rule instead of collecting all rule-load errors                   │
│ --help            Show this message and exit.                                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice rules test`

```

 Usage: finjuice rules test [OPTIONS] RULE_NAME

 Dry-run a single rule against existing transactions without writing changes.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    rule_name      TEXT  Exact rule name to test [required]                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --limit        INTEGER RANGE [x>=0]  Sample row count (default: 5) [default: 5]                                      │
│ --month        TEXT                  Restrict to one partition (YYYY-MM)                                             │
│ --json                               Output as JSON                                                                  │
│ --help                               Show this message and exit.                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice assets`

```

 Usage: finjuice assets [OPTIONS] COMMAND [ARGS]...

 View raw asset snapshot rows and per-position holdings

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ status    Show asset portfolio overview.                                                                             │
│ balance   Show latest Banksalad overview balance rows.                                                               │
│ show      Show detailed holdings.                                                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice assets status`

```

 Usage: finjuice assets status [OPTIONS]

 Show asset portfolio overview.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON                                                                                       │
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice assets show`

```

 Usage: finjuice assets show [OPTIONS]

 Show detailed holdings.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --month            TEXT     Snapshot month (YYYY-MM)                                                                 │
│ --account          TEXT     Filter by account ID                                                                     │
│ --limit    -n      INTEGER  Max positions to show [default: 50]                                                      │
│ --json                      Output as JSON                                                                           │
│ --help                      Show this message and exit.                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice networth`

```

 Usage: finjuice networth [OPTIONS] [COMMAND] [ARGS]...

 View aggregated net worth from asset snapshots plus assets.yaml. Use `finjuice assets` for raw snapshot rows.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --date        TEXT  Snapshot date (YYYY-MM-DD)                                                                       │
│ --json              Output as JSON                                                                                   │
│ --help              Show this message and exit.                                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ breakdown   Show aggregated asset breakdown by category or asset.                                                    │
│ history     Show monthly net worth history from available snapshots.                                                 │
│ forecast    Project net worth under deterministic scenario assumptions.                                              │
│ init        Initialize assets settings; repositories receive an empty configuration.                                 │
│ validate    Validate the selected assets configuration and report issues.                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice networth breakdown`

```

 Usage: finjuice networth breakdown [OPTIONS]

 Show aggregated asset breakdown by category or asset.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --by          [category|asset]  Break down by category or asset [required]                                        │
│    --date        TEXT              Snapshot date (YYYY-MM-DD)                                                        │
│    --json                          Output as JSON                                                                    │
│    --help                          Show this message and exit.                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice networth history`

```

 Usage: finjuice networth history [OPTIONS]

 Show monthly net worth history from available snapshots.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --months        INTEGER RANGE [x>=1]  Max monthly points to return [default: 6]                                      │
│ --json                                Output as JSON                                                                 │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice networth forecast`

```

 Usage: finjuice networth forecast [OPTIONS]

 Project net worth under deterministic scenario assumptions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --years           INTEGER RANGE [1<=x<=100]              Forecast horizon in years [default: 5]                      │
│ --scenario        [conservative|neutral|optimistic|all]  Scenario: conservative, neutral, optimistic, all            │
│                                                          [default: neutral]                                          │
│ --from            TEXT                                   Forecast start date (YYYY-MM-DD)                            │
│ --json                                                   Output as JSON                                              │
│ --help                                                   Show this message and exit.                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice networth validate`

```

 Usage: finjuice networth validate [OPTIONS]

 Validate the selected assets configuration and report issues.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON                                                                                       │
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice init`

```

 Usage: finjuice init [OPTIONS]

 Initialize directory structure (advanced setup).

 ⚠️  Most users should use `finjuice import` which handles setup automatically.

 This command is for advanced users who need:
 - Custom data directory location
 - Skip git initialization (--no-git)
 - Include AGENTS.md for AI tools (--with-agents)
 - Save location to config file (--save-config)

 Creates a new data directory with:
 - Directory structure (imports/, transactions/, exports/)
 - Template files (.gitignore, README.md, rules.yaml)
 - Optional git repository initialization
 - Optional AGENTS.md for AI tool integration

 Examples:
     # Recommended: Import auto-creates the data directory on first run
     finjuice import ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx

     # Advanced: Custom location with git and save to config
     finjuice --data-dir ~/my-finance-data init --save-config

     # Advanced: Skip git initialization
     finjuice init --no-git

     # Advanced: Include AI agent configuration
     finjuice init --with-agents

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --with-git       --no-git      Initialize git repository (default: True) [default: with-git]                         │
│ --with-agents                  Include AGENTS.md for AI tool integration (Codex, Gemini, Cursor)                     │
│ --save-config                  Save this location to config file (~/.finjuice/config.toml)                           │
│ --json                         Output as JSON                                                                        │
│ --help                         Show this message and exit.                                                           │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice query`

```

 Usage: finjuice query [OPTIONS] SQL

 Execute a SQL query on your transaction data.

 The 'transactions' view reads the selected authority: legacy CSV or a verified
 SQLite snapshot. Repository results include the generation and revision in JSON metadata.
 Only SELECT and WITH statements are allowed for safety.
 Report filters are applied by default by prepending a CTE that rebinds the
 conventional `transactions` view to filtered rows; use the root `--no-filter`
 flag when you need the unfiltered audit view for this invocation.
 Privacy profiles are intentionally not exposed here because arbitrary SQL
 can rename, compute, or combine sensitive row fields outside a stable
 redaction contract.

 Examples:
     finjuice query "SELECT * FROM transactions LIMIT 5"
     finjuice query "SELECT month, SUM(amount) FROM transactions GROUP BY month"
     finjuice query "SELECT * FROM transactions WHERE amount < -100000" -o markdown

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    sql      TEXT  SQL query to execute (SELECT only) [required]                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --output     -o      TEXT     Output format: table, csv, json, markdown                                              │
│ --json                        Alias for --output json                                                                │
│ --limit              INTEGER  Maximum rows to return (max 10000) [default: 100]                                      │
│ --cursor             TEXT     Opaque pagination cursor [default: 0]                                                  │
│ --max-bytes          INTEGER  Maximum serialized JSON response size before truncating rows [default: 1048576]        │
│ --help                        Show this message and exit.                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## `finjuice template`

```

 Usage: finjuice template [OPTIONS] COMMAND [ARGS]...

 Run curated SQL query templates, including dynamic pivot tables

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ list   List available query templates.                                                                               │
│ show   Show template metadata and SQL definition.                                                                    │
│ run    Run a SQL template with validated parameters.                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice template run`

```

 Usage: finjuice template run [OPTIONS] NAME

 Run a SQL template with validated parameters.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    name      TEXT  Template name [required]                                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --param      -p      TEXT     Template parameter in key=value format. Repeat for multiple parameters.                │
│ --output     -o      TEXT     Output format: table, csv, json, markdown, xlsx                                        │
│ --json                        Output as JSON                                                                         │
│ --file       -f      PATH     Save output to file. Required when --output xlsx.                                      │
│ --limit              INTEGER  Maximum rows to return (max 10000) [default: 100]                                      │
│ --cursor             TEXT     Opaque pagination cursor [default: 0]                                                  │
│ --max-bytes          INTEGER  Maximum serialized JSON response size before truncating rows [default: 1048576]        │
│ --help                        Show this message and exit.                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### Registered SQL Templates

| Name | Description | Params |
| --- | --- | --- |
| `monthly_spend` | Monthly total spending and count (excluding transfers) | `since:month` optional (default=None)<br>`until:month` optional (default=None) |
| `tag_breakdown` | Spending breakdown by tag using tags_final array | `since:month` optional (default=None)<br>`until:month` optional (default=None)<br>`top_n:int` optional (default=10, min=1, max=100) |
| `monthly_consumption_summary` | Canonical monthly consumption spend excluding transfers, savings, investments, and card-payment flows | `since:month` optional (default=None)<br>`until:month` optional (default=None) |
| `consumption_category_breakdown` | Canonical consumption spend by category for one month | `month:month` required<br>`top_n:int` optional (default=10, min=1, max=100) |
| `merchant_top_spend` | Top merchants by canonical consumption spend for one month | `month:month` required<br>`top_n:int` optional (default=20, min=1, max=100) |
| `event_adjusted_spend` | Month consumption spend with selected event tags excluded from the adjusted total | `month:month` required<br>`event_tags:str` optional (default=None) |
| `recurring_candidates` | Potential recurring charges by merchant + amount | `min_occurrences:int` optional (default=3, min=2, max=36)<br>`min_amount:int` optional (default=5000, min=1000, max=5000000)<br>`top_n:int` optional (default=20, min=1, max=100) |
| `anomaly_large_txn` | Large transactions above threshold | `threshold:int` optional (default=300000, min=10000, max=100000000)<br>`since:month` optional (default=None)<br>`until:month` optional (default=None)<br>`top_n:int` optional (default=20, min=1, max=200) |
| `card_spend_summary` | Spending summary by card/account | `since:month` optional (default=None)<br>`until:month` optional (default=None)<br>`top_n:int` optional (default=20, min=1, max=100) |
| `merchant_monthly_trend` | Monthly spending trend for merchant keyword (ILIKE match) | `merchant:str` required<br>`since:month` optional (default=None)<br>`until:month` optional (default=None)<br>`top_n:int` optional (default=12, min=1, max=24) |
| `spend_by_weekday_hour` | Spending pattern aggregated by weekday and hour | `since:month` optional (default=None)<br>`until:month` optional (default=None) |
| `weekly_anomalies` | Category-level spending anomalies: returns change_type (new/gone/changed) and change_pct | `period_days:int` optional (default=7, min=1, max=365)<br>`threshold_pct:int` optional (default=30, min=0, max=1000) |
| `new_merchants` | First-time merchants seen only in the recent period | `days:int` optional (default=7, min=1, max=365) |
| `spending_comparison` | Period-over-period total spending comparison | `period_days:int` optional (default=7, min=1, max=365) |
| `compare` | Baseline-vs-current monthly-average comparison by category, major, or merchant | `baseline_months:month_window` required<br>`current_months:month_window` required<br>`group_by:enum` optional (default=category_final)<br>`type_norm:enum` optional (default=expense) |
| `pivot` | Dynamic pivot by row axis, column axis, and metric | `row:enum` required<br>`col:enum` required<br>`value:enum` optional (default=amount)<br>`agg:enum` optional (default=sum)<br>`months:month_range` optional (default=None)<br>`top_n_cols:int` optional (default=10, min=1, max=100) |

---

## `finjuice ssot`

```

 Usage: finjuice ssot [OPTIONS] COMMAND [ARGS]...

 Manage inactive SQLite migration candidates.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ migrate     Plan, build, and verify preservation migrations.                                                         │
│ backup      Create snapshots, capture a local recovery graph, retain a managed store, and restore inactive           │
│             workspaces.                                                                                              │
│ account     Inspect canonical accounts and explicitly bind source identities.                                        │
│ assets      Confirm source-backed asset meanings and report exact scoped ownership.                                  │
│ intake      Preserve original evidence and review explicitly supplied extraction and proposals.                      │
│ reconcile   Preserve purchase evidence and review exact N:M ledger settlements.                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot reconcile`

```

 Usage: finjuice ssot reconcile [OPTIONS] COMMAND [ARGS]...

 Preserve purchase evidence and review exact N:M ledger settlements.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ submit       Preserve original bytes and explicit purchase/order/line-item/payment evidence.                         │
│ candidates   Explain exact candidates, residuals and immutable decisions; never apply guesses.                       │
│ confirm      Confirm evidence_ids/payment_ids and reviewed expected_residual/currency with reason/time.              │
│ withdraw     Append allocation_id/reason/withdrawn_at; regrouping requires a new explicit confirmation.              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot reconcile submit`

```

 Usage: finjuice ssot reconcile submit [OPTIONS] SOURCE METADATA

 Preserve original bytes and explicit purchase/order/line-item/payment evidence.

 Metadata: source_namespace, received_at, items. Each item explicitly names
 external_key, evidence_kind, occurred_on, amount (decimal string), currency,
 settlement_unit, detail, optional parent_external_key and transaction_id.
 Positive evidence is a purchase; negative evidence is a refund.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    source        PATH  [required]                                                                                  │
│ *    metadata      PATH  [required]                                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot reconcile candidates`

```

 Usage: finjuice ssot reconcile candidates [OPTIONS]

 Explain exact candidates, residuals and immutable decisions; never apply guesses.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --window-days        INTEGER RANGE [x>=0]  [default: 14]                                                             │
│ --json                                                                                                               │
│ --help                                     Show this message and exit.                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot reconcile confirm`

```

 Usage: finjuice ssot reconcile confirm [OPTIONS] REQUEST

 Confirm evidence_ids/payment_ids and reviewed expected_residual/currency with reason/time.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    request      PATH  [required]                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot reconcile withdraw`

```

 Usage: finjuice ssot reconcile withdraw [OPTIONS] REQUEST

 Append allocation_id/reason/withdrawn_at; regrouping requires a new explicit confirmation.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    request      PATH  [required]                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot intake`

```

 Usage: finjuice ssot intake [OPTIONS] COMMAND [ARGS]...

 Preserve original evidence and review explicitly supplied extraction and proposals.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ submit     Preserve source bytes and supplied metadata; never infer OCR or account meaning.                          │
│ list       Read one authority-bound snapshot including pending, stale and uncertain decisions.                       │
│ confirm    Apply exactly the stored proposal with its explicit application identity.                                 │
│ revise     Atomically preserve a typed successor over verified source bytes; never erase its parent.                 │
│ withdraw   Reject an unapplied proposal; applied domain changes require a typed correction proposal.                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot intake submit`

```

 Usage: finjuice ssot intake submit [OPTIONS] SOURCE METADATA

 Preserve source bytes and supplied metadata; never infer OCR or account meaning.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    source        PATH  Original description/image/workbook file [required]                                         │
│ *    metadata      PATH  Explicit extraction and proposal JSON document [required]                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot intake revise`

```

 Usage: finjuice ssot intake revise [OPTIONS] PROPOSAL_ID REQUEST

 Atomically preserve a typed successor over verified source bytes; never erase its parent.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  [required]                                                                               │
│ *    request          PATH  Parent digest, new proposal and explicit revision evidence [required]                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot intake withdraw`

```

 Usage: finjuice ssot intake withdraw [OPTIONS] PROPOSAL_ID REQUEST

 Reject an unapplied proposal; applied domain changes require a typed correction proposal.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  [required]                                                                               │
│ *    request          PATH  Exact proposal digest, withdrawal evidence and timestamp [required]                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot intake list`

```

 Usage: finjuice ssot intake list [OPTIONS]

 Read one authority-bound snapshot including pending, stale and uncertain decisions.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot intake confirm`

```

 Usage: finjuice ssot intake confirm [OPTIONS] PROPOSAL_ID

 Apply exactly the stored proposal with its explicit application identity.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    proposal_id      TEXT  [required]                                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --confirmed-at               TEXT     Explicit confirmation timestamp [required]                                  │
│    --json                                                                                                            │
│    --idempotency-key            TEXT     Stable retry key for an authoritative mutation                              │
│    --expected-generation        TEXT     Expected active dataset generation                                          │
│    --expected-revision          INTEGER  Expected active dataset revision                                            │
│    --help                                Show this message and exit.                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot assets`

```

 Usage: finjuice ssot assets [OPTIONS] COMMAND [ARGS]...

 Confirm source-backed asset meanings and report exact scoped ownership.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ list               List original source identities, pending meanings and immutable decision history.                 │
│ confirm            Record explicit meaning/scope/date/evidence for one existing source value.                        │
│ correct            Append a source meaning correction; retain its earlier assertion and raw source.                  │
│ relation-confirm   Explicitly include/overlap two existing source entities with review evidence.                     │
│ relation-correct   Correct an inclusion/overlap decision without deleting its previous evidence.                     │
│ report             Report exact owned values in an explicit party/source scope; surface unknowns.                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot assets list`

```

 Usage: finjuice ssot assets list [OPTIONS]

 List original source identities, pending meanings and immutable decision history.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot assets confirm`

```

 Usage: finjuice ssot assets confirm [OPTIONS] REQUEST

 Record explicit meaning/scope/date/evidence for one existing source value.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    request      PATH  [required]                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot assets correct`

```

 Usage: finjuice ssot assets correct [OPTIONS] ASSERTION_ID REQUEST

 Append a source meaning correction; retain its earlier assertion and raw source.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    assertion_id      TEXT  [required]                                                                              │
│ *    request           PATH  [required]                                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot assets relation-confirm`

```

 Usage: finjuice ssot assets relation-confirm [OPTIONS] REQUEST

 Explicitly include/overlap two existing source entities with review evidence.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    request      PATH  [required]                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot assets relation-correct`

```

 Usage: finjuice ssot assets relation-correct [OPTIONS] ASSERTION_ID REQUEST

 Correct an inclusion/overlap decision without deleting its previous evidence.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    assertion_id      TEXT  [required]                                                                              │
│ *    request           PATH  [required]                                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot assets report`

```

 Usage: finjuice ssot assets report [OPTIONS]

 Report exact owned values in an explicit party/source scope; surface unknowns.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --as-of             TEXT                  [required]                                                              │
│ *  --currency          TEXT                  [required]                                                              │
│ *  --party             TEXT                  [required]                                                              │
│    --source            TEXT                                                                                          │
│    --stale-days        INTEGER RANGE [x>=0]  [default: 30]                                                           │
│    --json                                                                                                            │
│    --help                                    Show this message and exit.                                             │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account`

```

 Usage: finjuice ssot account [OPTIONS] COMMAND [ARGS]...

 Inspect canonical accounts and explicitly bind source identities.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ list                List accounts, exact source candidates and immutable confirmation history.                       │
│ confirm             Confirm an exact source binding from an explicit JSON request file.                              │
│ correct             Append a correction of the named current binding; retain the original evidence.                  │
│ ownership           Read exact confirmed ownership as of a date without household aggregation.                       │
│ preview             Preview binding impact; pass its generation/revision to confirm or correct.                      │
│ ownership-confirm   Confirm exact party shares, effective dates and explicit evidence from JSON.                     │
│ ownership-correct   Correct ownership by appending a confirmed successor; retain prior evidence.                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account list`

```

 Usage: finjuice ssot account list [OPTIONS]

 List accounts, exact source candidates and immutable confirmation history.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account confirm`

```

 Usage: finjuice ssot account confirm [OPTIONS] REQUEST

 Confirm an exact source binding from an explicit JSON request file.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    request      PATH  [required]                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account correct`

```

 Usage: finjuice ssot account correct [OPTIONS] BINDING_ID REQUEST

 Append a correction of the named current binding; retain the original evidence.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    binding_id      TEXT  [required]                                                                                │
│ *    request         PATH  [required]                                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account ownership`

```

 Usage: finjuice ssot account ownership [OPTIONS] ACCOUNT_ID

 Read exact confirmed ownership as of a date without household aggregation.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    account_id      TEXT  [required]                                                                                │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --as-of        TEXT  [required]                                                                                   │
│    --json                                                                                                            │
│    --help               Show this message and exit.                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account preview`

```

 Usage: finjuice ssot account preview [OPTIONS] REQUEST

 Preview binding impact; pass its generation/revision to confirm or correct.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    request      PATH  [required]                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --corrects        TEXT                                                                                               │
│ --json                                                                                                               │
│ --help                  Show this message and exit.                                                                  │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account ownership-confirm`

```

 Usage: finjuice ssot account ownership-confirm [OPTIONS] REQUEST

 Confirm exact party shares, effective dates and explicit evidence from JSON.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    request      PATH  [required]                                                                                   │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot account ownership-correct`

```

 Usage: finjuice ssot account ownership-correct [OPTIONS] ASSERTION_ID REQUEST

 Correct ownership by appending a confirmed successor; retain prior evidence.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    assertion_id      TEXT  [required]                                                                              │
│ *    request           PATH  [required]                                                                              │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json                                                                                                               │
│ --idempotency-key            TEXT     Stable retry key for an authoritative mutation                                 │
│ --expected-generation        TEXT     Expected active dataset generation                                             │
│ --expected-revision          INTEGER  Expected active dataset revision                                               │
│ --help                                Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup`

```

 Usage: finjuice ssot backup [OPTIONS] COMMAND [ARGS]...

 Create snapshots, capture a local recovery graph, retain a managed store, and restore inactive workspaces.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ create           Capture one SQLite generation snapshot and its referenced artifacts.                                │
│ restore          Restore a verified SQLite backup into an inactive isolated directory.                               │
│ status           Report whether one SQLite backup directory is an intact local snapshot.                             │
│ capture-bundle   Capture one local recovery graph from explicit operator paths.                                      │
│ verify-bundle    Verify one published recovery graph against independently enrolled evidence.                        │
│ restore-bundle   Verify the graph, then restore its snapshot into an inactive workspace.                             │
│ store            Initialize and retain complete local recovery graphs in one managed store.                          │
│ deliver          Run one filesystem backup delivery or report committed vs pending coverage.                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup create`

```

 Usage: finjuice ssot backup create [OPTIONS]

 Capture one SQLite generation snapshot and its referenced artifacts.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --source        PATH  Published generation root or database. [required]                                           │
│ *  --output        PATH  Backup directory to publish. [required]                                                     │
│    --json                Output as JSON                                                                              │
│    --help                Show this message and exit.                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup restore`

```

 Usage: finjuice ssot backup restore [OPTIONS] BACKUP

 Restore a verified SQLite backup into an inactive isolated directory.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    backup      PATH  Backup directory or current attempt. [required]                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --target        PATH  Fresh isolated workspace directory; parent must exist. [required]                           │
│    --json                Output as JSON                                                                              │
│    --help                Show this message and exit.                                                                 │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup status`

```

 Usage: finjuice ssot backup status [OPTIONS] BACKUP

 Report whether one SQLite backup directory is an intact local snapshot.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    backup      PATH  Backup directory to inspect. [required]                                                       │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --json          Output as JSON                                                                                       │
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup capture-bundle`

```

 Usage: finjuice ssot backup capture-bundle [OPTIONS]

 Capture one local recovery graph from explicit operator paths.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --source-data-dir            PATH  Explicit live data directory to snapshot; not read from the host pointer.      │
│                                       [required]                                                                     │
│ *  --output                     PATH  Fresh directory for the published graph. [required]                            │
│ *  --expected                   PATH  Independently retained expectation JSON; never derived from the live tree.     │
│                                       [required]                                                                     │
│ *  --wheel                      PATH  Operator-selected release wheel. [required]                                    │
│ *  --dependency-lock            PATH  Operator-selected dependency lock file. [required]                             │
│ *  --binding                    PATH  Operator-selected trusted binding file. [required]                             │
│ *  --migration-candidate        PATH  Immutable migration candidate directory. [required]                            │
│    --json                             Output as JSON                                                                 │
│    --help                             Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup verify-bundle`

```

 Usage: finjuice ssot backup verify-bundle [OPTIONS] BUNDLE

 Verify one published recovery graph against independently enrolled evidence.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    bundle      PATH  Published local recovery graph directory. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --expected        PATH  Independently retained expectation JSON; never derived from the bundle. [required]        │
│    --json                  Output as JSON                                                                            │
│    --help                  Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup restore-bundle`

```

 Usage: finjuice ssot backup restore-bundle [OPTIONS] BUNDLE

 Verify the graph, then restore its snapshot into an inactive workspace.

╭─ Arguments ──────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *    bundle      PATH  Published local recovery graph directory. [required]                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --target          PATH  Fresh isolated workspace directory; parent must exist. [required]                         │
│ *  --expected        PATH  Independently retained expectation JSON; never derived from the bundle. [required]        │
│    --json                  Output as JSON                                                                            │
│    --help                  Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup deliver`

```

 Usage: finjuice ssot backup deliver [OPTIONS] COMMAND [ARGS]...

 Run one filesystem backup delivery or report committed vs pending coverage.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ status   Report committed-record coverage and delivery history without transferring.                                 │
│ run      Run one filesystem delivery. Nonzero exit is backup failure, not a domain rollback.                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup deliver status`

```

 Usage: finjuice ssot backup deliver status [OPTIONS]

 Report committed-record coverage and delivery history without transferring.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --source-data-dir          PATH  [required]                                                                       │
│ *  --expected                 PATH  Independently retained expectation JSON; never derived from the store.           │
│                                     [required]                                                                       │
│ *  --sender-store             PATH  [required]                                                                       │
│ *  --destination-store        PATH  [required]                                                                       │
│ *  --control-dir              PATH  [required]                                                                       │
│    --json                                                                                                            │
│    --help                           Show this message and exit.                                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup deliver run`

```

 Usage: finjuice ssot backup deliver run [OPTIONS]

 Run one filesystem delivery. Nonzero exit is backup failure, not a domain rollback.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --source-data-dir            PATH  [required]                                                                     │
│ *  --expected                   PATH  Independently retained expectation JSON; never derived from the store.         │
│                                       [required]                                                                     │
│ *  --sender-store               PATH  [required]                                                                     │
│ *  --destination-store          PATH  [required]                                                                     │
│ *  --control-dir                PATH  [required]                                                                     │
│    --wheel                      PATH                                                                                 │
│    --dependency-lock            PATH                                                                                 │
│    --binding                    PATH                                                                                 │
│    --migration-candidate        PATH                                                                                 │
│    --json                                                                                                            │
│    --help                             Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store`

```

 Usage: finjuice ssot backup store [OPTIONS] COMMAND [ARGS]...

 Initialize and retain complete local recovery graphs in one managed store.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ --help          Show this message and exit.                                                                          │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ init      Create one empty local store bound to independently enrolled expectations.                                 │
│ capture   Capture one verified recovery graph into the initialized store.                                            │
│ list      Verify and list complete graphs in one initialized local store.                                            │
│ verify    Verify one managed recovery graph against independently enrolled evidence.                                 │
│ restore   Verify one managed graph, then restore its snapshot into an inactive workspace.                            │
│ protect   Verify one graph and durably register it as an additional baseline.                                        │
│ plan      Recompute a GFS retention plan from verified local inventory.                                              │
│ prune     Recompute under an exclusive lease and delete only unprotected local graphs.                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store init`

```

 Usage: finjuice ssot backup store init [OPTIONS]

 Create one empty local store bound to independently enrolled expectations.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store           PATH  Fresh directory for the initialized store. [required]                                     │
│ *  --expected        PATH  Independently retained JSON for this activation. [required]                               │
│    --json                  Output as JSON                                                                            │
│    --help                  Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store capture`

```

 Usage: finjuice ssot backup store capture [OPTIONS]

 Capture one verified recovery graph into the initialized store.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store                      PATH  Initialized local recovery-graph store. [required]                             │
│ *  --source-data-dir            PATH  Explicit live data directory to snapshot; not read from the host pointer.      │
│                                       [required]                                                                     │
│ *  --expected                   PATH  Independently retained expectation JSON; never derived from the store.         │
│                                       [required]                                                                     │
│ *  --wheel                      PATH  Operator-selected release wheel. [required]                                    │
│ *  --dependency-lock            PATH  Operator-selected dependency lock file. [required]                             │
│ *  --binding                    PATH  Operator-selected trusted binding file. [required]                             │
│ *  --migration-candidate        PATH  Immutable migration candidate directory. [required]                            │
│    --json                             Output as JSON                                                                 │
│    --help                             Show this message and exit.                                                    │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store list`

```

 Usage: finjuice ssot backup store list [OPTIONS]

 Verify and list complete graphs in one initialized local store.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store           PATH  Initialized local recovery-graph store. [required]                                        │
│ *  --expected        PATH  Independently retained expectation JSON; never derived from the store. [required]         │
│    --json                  Output as JSON                                                                            │
│    --help                  Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store verify`

```

 Usage: finjuice ssot backup store verify [OPTIONS]

 Verify one managed recovery graph against independently enrolled evidence.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store           PATH  Initialized local recovery-graph store. [required]                                        │
│ *  --copy-id         TEXT  UUID identity of one published graph. [required]                                          │
│ *  --expected        PATH  Independently retained expectation JSON; never derived from the store. [required]         │
│    --json                  Output as JSON                                                                            │
│    --help                  Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store restore`

```

 Usage: finjuice ssot backup store restore [OPTIONS]

 Verify one managed graph, then restore its snapshot into an inactive workspace.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store           PATH  Initialized local recovery-graph store. [required]                                        │
│ *  --copy-id         TEXT  UUID identity of one published graph. [required]                                          │
│ *  --target          PATH  Fresh isolated workspace directory; parent must exist. [required]                         │
│ *  --expected        PATH  Independently retained expectation JSON; never derived from the store. [required]         │
│    --json                  Output as JSON                                                                            │
│    --help                  Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store protect`

```

 Usage: finjuice ssot backup store protect [OPTIONS]

 Verify one graph and durably register it as an additional baseline.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store           PATH  Initialized local recovery-graph store. [required]                                        │
│ *  --copy-id         TEXT  UUID identity of one published graph. [required]                                          │
│ *  --expected        PATH  Independently retained expectation JSON; never derived from the store. [required]         │
│    --json                  Output as JSON                                                                            │
│    --help                  Show this message and exit.                                                               │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store plan`

```

 Usage: finjuice ssot backup store plan [OPTIONS]

 Recompute a GFS retention plan from verified local inventory.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store           PATH     Initialized local recovery-graph store. [required]                                     │
│ *  --expected        PATH     Independently retained expectation JSON; never derived from the store. [required]      │
│    --daily           INTEGER  GFS window; omit unused fields to keep the default policy.                             │
│    --weekly          INTEGER  GFS window; omit unused fields to keep the default policy.                             │
│    --monthly         INTEGER  GFS window; omit unused fields to keep the default policy.                             │
│    --json                     Output as JSON                                                                         │
│    --help                     Show this message and exit.                                                            │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

### `finjuice ssot backup store prune`

```

 Usage: finjuice ssot backup store prune [OPTIONS]

 Recompute under an exclusive lease and delete only unprotected local graphs.

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ *  --store              PATH     Initialized local recovery-graph store. [required]                                  │
│ *  --expected           PATH     Independently retained expectation JSON; never derived from the store. [required]   │
│    --plan-digest        TEXT     Optional reviewed plan digest; stale values are rejected.                           │
│    --daily              INTEGER  GFS window; omit unused fields to keep the default policy.                          │
│    --weekly             INTEGER  GFS window; omit unused fields to keep the default policy.                          │
│    --monthly            INTEGER  GFS window; omit unused fields to keep the default policy.                          │
│    --json                        Output as JSON                                                                      │
│    --help                        Show this message and exit.                                                         │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

```

---

## Quick Start (Status-First CLI)

**For new users** - Start with the default status view, then run direct commands:

```bash
# Show current state and suggested commands
finjuice

# Import an XLSX export (auto-initializes the data directory if needed)
finjuice import

# Process pending imports through the full pipeline
finjuice refresh
```

`finjuice interactive` and `finjuice -i` remain for backward compatibility, but they are deprecated.

---

## Common Workflows

### First-time setup (Advanced manual setup)

**For advanced users** who want a custom data directory instead of the default `~/.finjuice`:

```bash
# Advanced: Initialize with custom location
finjuice --data-dir ~/Documents/my-finance-data init

# Place XLSX files in imports/ directory
cp ~/Downloads/banksalad_export.xlsx ~/Documents/my-finance-data/imports/

# Edit tagging rules
vim ~/Documents/my-finance-data/rules.yaml

# Run full pipeline
finjuice --data-dir ~/Documents/my-finance-data refresh
```

### Regular usage

```bash
# Add new XLSX file
cp ~/Downloads/banksalad_202411.xlsx ~/.finjuice/imports/

# Run full pipeline (ingest + tag + export)
finjuice refresh

# Check generated reports
ls ~/.finjuice/exports/reports/
```

### Re-tagging after rule changes

```bash
# Edit tagging rules
vim ~/.finjuice/rules.yaml

# Re-run tagging only
finjuice tag

# Re-generate exports with new tags
finjuice export
```

### Using custom data directory

```bash
# Option 1: Set environment variable
export FINJUICE_DATA_DIR=~/Documents/my-finance-data
finjuice refresh

# Option 2: Use --data-dir flag
finjuice --data-dir ~/Documents/my-finance-data refresh

# Option 3: Use config file
# ~/.finjuice/config.toml
# [data]
# directory = "~/Documents/my-finance-data"
```

---

## CLI Options Reference

### Global Options

- `--data-dir PATH`: Override the configured data directory
- `--verbose, -v`: Enable verbose logging
- `--interactive, -i`: Deprecated compatibility flag for the legacy interactive menu

### Common Patterns

**Verbose output** (for debugging):
```bash
finjuice --verbose refresh
finjuice --verbose tag
```

**Custom data directory**:
```bash
finjuice --data-dir ~/my-data refresh
```

---

## Output Files

After running `finjuice refresh`, you'll find:

### Master File
- `~/.finjuice/exports/master_YYYYMMDD.xlsx` - All transactions with tags

### Reports (CSV)
- `~/.finjuice/exports/reports/monthly_spend.csv` - Monthly spending totals
- `~/.finjuice/exports/reports/by_tag.csv` - Spending breakdown by tag
- `~/.finjuice/exports/reports/by_account.csv` - Spending by account/card
- `~/.finjuice/exports/reports/transfers.csv` - Internal transfer audit log

### Data Partitions
- `~/.finjuice/transactions/YYYY/MM/transactions.csv` - Monthly CSV partitions (git-tracked)

---

## Troubleshooting

### `finjuice: command not found`

**Solution**: Install the package
```bash
uv pip install -e .
```

### `No XLSX files found in imports/`

**Solution**: Check import directory
```bash
ls ~/.finjuice/imports/
# Add XLSX files if empty
```

---

## `finjuice all` (Deprecated alias for `finjuice refresh`)

Compatibility alias for `finjuice refresh`. Prefer `finjuice refresh` for all new usage.

### `Schema mismatch` errors

**Solution**: Check schema version
```bash
# Verify schema.yaml matches code
cat templates/schema.yaml | grep current_version
```

### Import errors during execution

**Solution**: Install all dependencies
```bash
uv sync --all-extras
```

---

## See Also

- [templates/schema.yaml](../../templates/schema.yaml) - Data schema reference
- [templates/rules.yaml.example](../../templates/rules.yaml.example) - Tagging rules template
- [CLAUDE.md](../../CLAUDE.md) - Project guide
- [Data Repository Setup](../setup/data-repository.md) - User data configuration

**Note**: This file is auto-generated. Do not edit manually. Run `just docs-cli` to regenerate.
