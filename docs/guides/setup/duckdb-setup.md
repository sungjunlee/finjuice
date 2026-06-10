# DuckDB Analytics Layer Setup Guide

**Status**: Analytics extra (required for analytics commands)
**Performance**: Workload-dependent; see `docs/benchmarks/duckdb-results.json`
**Since**: v0.2.0 (2025-11-16)

---

## Overview

The DuckDB analytics layer is finjuice's SQL-oriented analytics/query engine on top of the
existing Polars-based CSV partition storage. It integrates with the current partition layout
through zero-copy Apache Arrow conversion.

DuckDB is packaged as the optional `analytics` install extra so core ingest/tag/export setups
can stay lean. Once you use analytics commands, DuckDB is the only supported engine behind
`query`, `template`, `inspect`, `explain`, and `simulate`.

The checked-in benchmark baseline was refreshed on 2026-03-26 with Python 3.13.11,
Polars 1.35.2, and DuckDB 1.4.2. That run showed workload-dependent results rather than a
general DuckDB speedup, so benchmark your own path before treating DuckDB as a performance upgrade.
The current checked-in artifact uses the live v3 26-column partition shape. In that artifact,
Polars is ahead on all cold runs and on both `monthly_spend` warm runs, while the
120,000-row warm `tag_breakdown` benchmark favors the current hybrid `DuckDBAnalytics` path.

### When to Use DuckDB

✅ **Use DuckDB for**:
- SQL-oriented analytics and ad-hoc exploration
- Multi-partition reads where the centralized `transactions` view simplifies logic
- Analytics commands backed by DuckDB (`query`, `template`, `inspect`, `explain`, `simulate`)
- Representative workloads you have benchmarked locally and confirmed
- **See [ADR-0006](../../architecture/decisions/0006-polars-vs-duckdb-roles.md) for strict separation rules.**

❌ **Use Polars for**:
- Single-record operations (ingest, tagging)
- Data transformations and ETL
- Operations requiring high-level DataFrame API
- Simple aggregations where Polars is already faster on the checked-in benchmark

### Performance Characteristics

| Operation | Dataset Size | Polars cold | DuckDBAnalytics path cold | Polars warm mean | DuckDBAnalytics path warm mean | Warm speedup |
|-----------|--------------|-------------|---------------------------|------------------|-------------------------------|--------------|
| Monthly aggregation | 6,000 rows | 1.560s | 4.735s | 0.288s | 1.487s | **0.19x** |
| Tag breakdown | 6,000 rows | 0.905s | 2.258s | 0.477s | 3.724s | **0.13x** |
| Monthly aggregation | 120,000 rows | 2.897s | 4.969s | 0.887s | 2.766s | **0.32x** |
| Tag breakdown | 120,000 rows | 4.836s | 24.236s | 3.699s | 1.879s | **1.97x** |

**Cold** means the first execution on a fresh engine state. **Warm** means repeated runs in the
same Python process; DuckDBAnalytics warm runs reuse a single `DuckDBAnalytics` connection and view. Treat
this artifact as a reproducible host-local baseline, not a universal threshold.
For `tag_breakdown`, the DuckDBAnalytics path is still hybrid: DuckDB reads via the
`transactions` view, then Polars performs the JSON explode and final aggregation fallback.

---

## Installation

### 1. End-user installation

DuckDB is distributed via the optional `analytics` extra. Pick the one command that matches how
you installed `finjuice`:

```bash
# Installed finjuice with uv tool install
uv tool install --force --with duckdb git+https://github.com/sungjunlee/finjuice

# Working from a local checkout with uv sync
uv sync --extra analytics

# Installed finjuice with pip
pip install 'finjuice[analytics]'
```

Use `finjuice doctor` if you are unsure which install mode applies. It detects the environment
and prints the exact command again.

### 2. Verify Installation

```python
import duckdb
print(duckdb.__version__)  # Should print 0.9.0+
```

---

## Usage

### Basic Usage

```python
from pathlib import Path
from finjuice.pipeline.analytics import DuckDBAnalytics

# Initialize analytics layer
data_dir = Path("~/.finjuice").expanduser()  # Contains transactions/ directory
analytics = DuckDBAnalytics(data_dir)

try:
    # Monthly spending (excludes transfers & income)
    monthly = analytics.monthly_spend()
    print(monthly.head())
    # shape: (12, 3)
    # ┌─────────┬───────────────────┬──────────────┐
    # │ month   ┆ transaction_count ┆ total_amount │
    # │ ---     ┆ ---               ┆ ---          │
    # │ str     ┆ u32               ┆ f64          │
    # ╞═════════╪═══════════════════╪══════════════╡
    # │ 2024-11 ┆ 156               ┆ -1234567.89  │
    # └─────────┴───────────────────┴──────────────┘

    # Top spending tags
    tags = analytics.tag_breakdown(top_n=10)
    print(tags.head())

    # Read specific partitions
    oct_data = analytics.read_partitions(pattern="2024/10/*.csv")
    print(f"October: {len(oct_data)} transactions")

finally:
    analytics.close()
```

### Context Manager Pattern (Recommended)

```python
with DuckDBAnalytics(data_dir) as analytics:
    monthly = analytics.monthly_spend()
    tags = analytics.tag_breakdown(top_n=5)
    # Connection auto-closed on exit
```

### Advanced Usage

#### 1. Memory Limit Configuration

```python
# Limit DuckDB memory usage (useful for large datasets)
analytics = DuckDBAnalytics(data_dir, memory_limit="1GB")
```

#### 2. Column Selection (Faster Reads)

```python
# Only read needed columns
df = analytics.read_partitions(
    pattern="2024/11/*.csv",
    columns=["date", "amount", "merchant_raw", "tags_final"]
)
```

#### 3. Custom SQL Queries

```python
# Direct SQL access for advanced analytics
analytics = DuckDBAnalytics(data_dir)
try:
    sql = """
        SELECT
            account,
            strftime(date, '%Y-%m') AS month,
            COUNT(*) AS txn_count,
            ROUND(SUM(-amount), 0) AS spend_krw
        FROM transactions
        WHERE amount < 0
          AND (is_transfer = 0 OR is_transfer IS NULL)
        GROUP BY account, month
        ORDER BY account, month DESC
    """
    result_df = analytics.conn.execute(sql).pl()  # Returns Polars DataFrame
    print(result_df)
finally:
    analytics.close()
```

For more pasteable query patterns, see the
[DuckDB SQL snippets reference](../../reference/duckdb-snippets.md).

---

## API Reference

### DuckDBAnalytics Class

```python
class DuckDBAnalytics:
    """High-performance analytics layer using DuckDB."""

    def __init__(
        self,
        data_dir: Path,
        memory_limit: Optional[str] = None
    ):
        """Initialize DuckDB connection.

        Args:
            data_dir: Path to data directory containing transactions/
            memory_limit: Optional memory limit (e.g., "1GB", "500MB")

        Raises:
            ImportError: If duckdb not installed
        """

    def read_partitions(
        self,
        pattern: str = "*/*/*.csv",
        columns: Optional[list[str]] = None
    ) -> pl.DataFrame:
        """Read CSV partitions into Polars DataFrame.

        Args:
            pattern: Glob pattern for CSV files (default: all partitions)
            columns: Optional list of columns to select

        Returns:
            Polars DataFrame with transaction data
        """

    def monthly_spend(
        self,
        exclude_transfers: bool = True,
        exclude_income: bool = True
    ) -> pl.DataFrame:
        """Calculate monthly spending totals.

        Args:
            exclude_transfers: Exclude internal transfers (default: True)
            exclude_income: Exclude income transactions (default: True)

        Returns:
            Polars DataFrame with columns: [month, transaction_count, total_amount]
        """

    def tag_breakdown(
        self,
        top_n: int = 10,
        exclude_transfers: bool = True
    ) -> pl.DataFrame:
        """Calculate spending breakdown by tag.

        NOTE: Currently uses Polars fallback for JSON unnesting.

        Args:
            top_n: Number of top tags to return (default: 10)
            exclude_transfers: Exclude transfers (default: True)

        Returns:
            Polars DataFrame with columns: [tag, transaction_count, total_amount]
        """

    def close(self):
        """Close DuckDB connection and free resources."""
```

### Query Builder Functions

```python
from finjuice.pipeline.analytics.query_builder import (
    build_monthly_spend_query,
    build_tag_breakdown_query,
    build_top_merchants_query,
    build_account_summary_query,
    build_date_range_filter_query,
)

# Example: Build custom monthly spend query
sql = build_monthly_spend_query(
    partitions_path=str(Path("~/.finjuice/transactions/*/*/*.csv").expanduser()),
    exclude_transfers=True,
    exclude_income=True
)
```

---

## Performance Tuning

### 1. Connection Reuse

For multiple queries, reuse the DuckDB connection:

```python
# ✅ Good: Reuse connection
with DuckDBAnalytics(data_dir) as analytics:
    monthly = analytics.monthly_spend()
    tags = analytics.tag_breakdown()
    merchants = analytics.read_partitions(pattern="2024/11/*.csv")

# ❌ Bad: Create new connection each time
monthly = DuckDBAnalytics(data_dir).monthly_spend()  # Slow!
tags = DuckDBAnalytics(data_dir).tag_breakdown()     # Slow!
```

### 2. Partition Pruning

Use specific glob patterns to read only needed partitions:

```python
# Read only Q4 2024
q4_data = analytics.read_partitions(pattern="2024/{10,11,12}/*.csv")

# Read only October
oct_data = analytics.read_partitions(pattern="2024/10/*.csv")
```

### 3. Memory Management

For large datasets, set a memory limit:

```python
# Prevent OOM on large aggregations
analytics = DuckDBAnalytics(data_dir, memory_limit="2GB")
```

---

## Integration Examples

### Application Integration

```python
from finjuice.pipeline.analytics import DuckDBAnalytics

def load_monthly_spend():
    with DuckDBAnalytics(DATA_DIR) as analytics:
        return analytics.monthly_spend()
```

### CLI Commands

```bash
# Install the analytics extra once
uv sync --extra analytics

# Run analytics commands
finjuice query "SELECT * FROM transactions LIMIT 5"
finjuice template run monthly_spend --output json
finjuice explain "Starbucks"
finjuice simulate "Netflix" --tags streaming
```

---

## Benchmarking

### Run Benchmark Script

```bash
# Recommended re-baseline command (checked-in artifact shape)
uv run --extra analytics python scripts/benchmark_duckdb.py \
  --scenario 6k_rows:24:250 \
  --scenario 120k_rows:24:5000 \
  --iterations 3 \
  --output docs/benchmarks/duckdb-results.json

# Single scenario fallback
uv run --extra analytics python scripts/benchmark_duckdb.py \
  --partitions 24 \
  --rows-per-partition 5000 \
  --iterations 3
```

The script now generates exact distinct `YYYY/MM` partitions. For example, `24` partitions span
`2024-01` through `2025-12` instead of relying on 30-day offsets.

### Interpreting Results

- **Speedup < 1.0**: DuckDB slower (small dataset or init overhead)
- **Speedup > 1.0**: DuckDB faster on that measured path
- Compare **cold** and **warm** separately before deciding whether the engine helps your workflow
- The checked-in 2026-03-26 baseline shows Polars ahead on all cold runs and on both
  `monthly_spend` warm runs
- The 120,000-row warm `tag_breakdown` case favors the current hybrid `DuckDBAnalytics` path
- `tag_breakdown` is not a pure DuckDB aggregation benchmark yet; it measures the current
  `DuckDBAnalytics.tag_breakdown()` path, including the Polars fallback

---

## Troubleshooting

### ImportError: DuckDB not installed

**Error**:
```
DuckDB is required for analytics commands. Run 'finjuice doctor' to see the exact analytics install command.
```

**Solution**:
```bash
# Installed finjuice with uv tool install
uv tool install --force --with duckdb git+https://github.com/sungjunlee/finjuice

# Working from a local checkout with uv sync
uv sync --extra analytics

# Installed finjuice with pip
pip install 'finjuice[analytics]'
```

### Slow Performance on Small Datasets

**Symptom**: DuckDB slower than Polars on your benchmark

**Explanation**: DuckDB connection setup and view registration add cold-start cost, and the current
CSV-partition benchmark still shows Polars ahead for `monthly_spend` even at 120K rows.

### JSON Unnesting Error (tag_breakdown)

**Symptom**: `tag_breakdown()` returns unexpected results or errors

**Explanation**: Currently using Polars fallback for JSON unnesting. Pure DuckDB optimization is TODO (follow-up issue).

**Workaround**: Polars fallback is fast and reliable. No action needed unless performance critical.
For ad-hoc SQL, use the DuckDB-safe `from_json(...)` + `UNNEST(...)` examples in the
[DuckDB SQL snippets reference](../../reference/duckdb-snippets.md).

### Memory Errors on Large Aggregations

**Error**:
```
Out of Memory Error: failed to allocate data of size ...
```

**Solution**:
```python
# Set memory limit
analytics = DuckDBAnalytics(data_dir, memory_limit="2GB")

# Or process in chunks
for year in range(2022, 2025):
    df = analytics.read_partitions(pattern=f"{year}/*/*.csv")
    # Process year-by-year
```

---

## Limitations & Future Work

### Current Limitations

1. **tag_breakdown JSON Unnesting**: Uses Polars fallback instead of pure DuckDB
   - Reason: DuckDB JSON→LIST conversion issues with CSV-stored JSON strings
   - Impact: Polars handles this reliably and is still 3-5x faster than pandas
   - Status: Acceptable for current use case; consider DuckDB 1.0+ JSON functions when stable

2. **No Persistent Database**: In-memory only
   - Reason: Design decision for simplicity
   - Impact: No query caching across sessions
   - Future: Consider persistent mode for very large datasets (100GB+)

3. **Limited SQL Builder Coverage**: Only common queries have builders
   - Solution: Use `analytics.conn.execute(sql)` for custom SQL

### Future Enhancements (Post-MVP)

- [ ] Dashboard integration (Phase 3)
- [ ] CLI commands (`finjuice analytics ...`)
- [ ] Add more query builders (account summary, merchant analysis)
- [ ] Persistent database mode for massive datasets
- [ ] Multi-file aggregation optimizations
- [ ] Integration with export pipeline

---

## See Also

- [Issue #90: DuckDB Analytics Layer](https://github.com/sungjunlee/finjuice/issues/90)
- [DuckDB Python Documentation](https://duckdb.org/docs/guides/python/polars)
- [Polars ↔ DuckDB Integration Guide](https://duckdb.org/docs/guides/python/polars#apache-arrow)
- [DuckDB SQL snippets reference](../../reference/duckdb-snippets.md)
- [Benchmark Results](../../benchmarks/duckdb-results.json)
- [CSV Partition Storage](../specs/v0_initial.md#file-storage)

---

**Last Updated**: 2026-03-26
**Version**: v0.2.0
**Status**: Stable (Phase 1-2 Complete)
