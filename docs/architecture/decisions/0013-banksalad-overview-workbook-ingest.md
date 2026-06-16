# Banksalad Overview Workbook Ingest

**Status**: accepted
**Date**: 2026-06-15
**Issue**: N/A
**Supersedes**: N/A

## Context and Problem Statement

finjuice originally focused on the Banksalad `가계부 내역` worksheet. A later asset
snapshot path assumed that asset exports would appear as a separate holdings-like sheet
such as `자산`, `보유종목`, `assets`, or `holdings`, with columns like account,
instrument, quantity, and market value.

Inspection of local real Banksalad exports, including recent 2025-05-05 to 2026-05-05
and 2025-06-07 to 2026-06-07 workbooks, showed a different stable shape:

* The workbook contains `뱅샐현황` and `가계부 내역`.
* `가계부 내역` remains the transaction table with the expected 10 columns.
* `뱅샐현황` is a formatted overview worksheet, not a header-row table.
* Asset and liability information is embedded in a `재무현황` block with side-by-side
  `자산` and `부채` regions.
* `보험현황`, `투자현황`, and `대출현황` appear as structured overview tables with
  institution/product rows and snapshot amounts, but not transaction-level trade history
  or quantity-level holdings.
* Row numbers drift across exports, so fixed row offsets are not a reliable parser
  contract.
* Recent exports still do not contain a separate holdings sheet with `수량`.

The question: should finjuice continue treating assets as an optional holdings sheet,
parse only the net-worth block from `뱅샐현황`, or promote `뱅샐현황` to a first-class
workbook overview source and collect every structured block that can be detected?

## Decision Drivers

* Real export compatibility: the parser must match current Banksalad workbook shape.
* Local-first privacy: raw financial data may be stored locally, but diagnostics and logs
  must not leak amounts, account names, product names, email addresses, or other private
  labels.
* Source fidelity: the overview worksheet contains useful information beyond net worth,
  including cashflow and summary tables.
* Robustness: parsers must detect worksheet roles and table anchors instead of depending
  on fixed row numbers.
* Incremental product value: net worth should work soon, but the design should not discard
  other `뱅샐현황` data that is cheap to preserve.
* Idempotency: re-importing the same workbook must not duplicate overview facts or typed
  balance rows.

## Considered Options

* Keep the existing optional holdings-sheet parser.
* Parse only the `자산`/`부채` block from `뱅샐현황`.
* Ingest the whole `뱅샐현황` worksheet as normalized workbook facts, then derive typed
  projections for balance, cashflow, insurance, investments, and loans.

## Decision Outcome

Chosen option: **ingest the whole `뱅샐현황` worksheet as normalized workbook facts and
derive typed projections**, because it preserves all currently available structured data
while still allowing `networth` to consume a narrow, well-typed balance view.

The existing holdings-sheet parser remains valid only for future or synthetic workbooks
that actually provide quantity-level holdings. It must not be treated as the primary
Banksalad asset source.

### Core Model

Introduce two layers:

* **Workbook facts**: a source-fidelity table for every detected structured cell or table
  fact in `뱅샐현황`. This captures block identity, row/column labels, numeric/text value
  type, source row/column, and source file id.
* **Typed projections**: stable, purpose-built tables derived from facts. Initial
  projections include balance items, monthly cashflow, insurance policies, investment
  positions, and loan positions. Later projections can cover card summaries or other
  detected overview sections without changing the raw-fact capture layer.

### Detection Policy

Do not parse `뱅샐현황` by fixed row numbers. Detect worksheet roles and blocks by anchors:

* Transaction worksheet: `가계부 내역` name or transaction required columns.
* Overview worksheet: `뱅샐현황` name or recognizable overview anchors.
* Balance block: side-by-side `자산` and `부채` anchors with nearby `금액` columns.
* Cashflow block: `현금흐름현황` anchor with month columns and income/expense/net rows.
* Numbered overview sections: `고객정보`, `현금흐름현황`, `재무현황`, `보험현황`,
  `투자현황`, and `대출현황` anchors define source-fidelity fact ranges.
* Typed insurance/investment/loan projections: section-local header rows with allowlisted
  Korean headers such as `금융사`, `보험명`, `상품명`, `대출잔액`, and `평가금액`.
* Unknown overview tables: preserve as generic workbook facts when row/column labels and
  values can be detected, even if no typed projection exists yet.

### Privacy Policy

The inspect/debug surface may print only metadata:

* file basename,
* worksheet names,
* row/column counts,
* detected roles and blocks,
* header/anchor labels from an allowlist.

It must not print private labels, email addresses, product names, account names, raw
amounts, or raw table row contents. Full values may be stored only in the local data
repository, following existing finjuice data privacy rules.

### CLI Surface

Initial user-facing surfaces should be:

* `ingest --dry-run --json`: include overview workbook counts and warnings.
* `ingest` and `refresh --json`: include inserted/skipped counts for workbook facts and
  typed projections.
* `assets balance`: show latest asset/liability balance rows from `뱅샐현황`.
* `networth`: use typed balance projections as the primary Banksalad overview source
  when available. Holdings snapshots remain a quantity-level source only when a workbook
  provides them. Manual `assets.yaml` entries should supplement or override exact-name
  matches, so imported balances and manual rows are not double-counted.
* `inspect xlsx --json` or equivalent: privacy-safe workbook structure diagnostics.

### Consequences

**Positive**:

* Current and recent real Banksalad exports become useful beyond transaction ingest.
* `networth` can be backed by actual Banksalad balance data instead of manual-only or
  synthetic holdings data.
* Future overview sections can be surfaced without reparsing archived XLSX files if raw
  facts are already captured.
* Parser resilience improves because anchor detection tolerates row drift.

**Negative**:

* The raw-fact layer is more abstract than the current transaction and holdings CSVs.
* It adds a second kind of source data: formatted workbook facts rather than simple
  row-table ingest.
* More private data may be stored locally if the whole overview worksheet is captured.

**Mitigations**:

* Keep the fact schema narrow and traceable with source row/column and file id.
* Add a privacy-safe inspect command before or alongside write-mode ingest.
* Add explicit tests that logs and inspect output do not contain amounts, account labels,
  product names, or emails.
* Keep typed projections small and stable; use raw facts only as the preservation layer.
* Add net-worth merge tests that cover overview balance rows, holdings snapshots, manual
  supplement rows, and manual exact-name overrides.

### Confirmation

This decision is working when:

* Recent Banksalad workbooks with only `뱅샐현황` and `가계부 내역` produce non-zero
  workbook facts plus balance, cashflow, insurance, investment, and loan rows when those
  sections are populated.
* The current transaction ingest count remains unchanged for the same files.
* The existing holdings-sheet tests still pass for synthetic/future holdings sheets.
* `ingest --dry-run --json` reports all overview table counts without writing files.
* Re-running ingest is idempotent for facts and all typed projections.
* Privacy tests prove that diagnostics redact private labels and amounts.

## Pros and Cons of the Options

### Keep Existing Holdings-sheet Parser

* Good, because it already exists and has tests.
* Good, because quantity-level holdings are useful if a workbook provides them.
* Bad, because current real Banksalad exports do not provide the expected sheet.
* Bad, because `networth` remains disconnected from actual `뱅샐현황` balance data.

### Parse Only the Balance Block

* Good, because it quickly makes `networth` useful.
* Good, because the first typed schema is straightforward: asset/liability rows.
* Bad, because it throws away other structured overview data available in the workbook.
* Bad, because later features would need to re-open archived XLSX files or add another
  preservation path.

### Whole Overview Facts plus Typed Projections

* Good, because it preserves all detectable overview data while exposing stable typed
  views for product workflows.
* Good, because it separates source fidelity from domain-specific analysis.
* Good, because it can tolerate unknown table sections.
* Bad, because it introduces a more general fact schema that needs careful documentation
  and tests.

## More Information

Related artifacts:

* `templates/schema.yaml`
* `src/finjuice/pipeline/ingest/_asset_processor.py`
* `src/finjuice/pipeline/cli/commands/assets.py`
* `src/finjuice/pipeline/networth.py`

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | clean | mode: HOLD_SCOPE, 0 critical gaps |
| Codex Review | `/codex review` | Independent 2nd opinion | 1 | issues_found | source: codex |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 3 | clean | 4 issues, 0 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | not run | no UI scope |

**UNRESOLVED:** 0

**VERDICT:** ENG CLEARED — ready to implement.
