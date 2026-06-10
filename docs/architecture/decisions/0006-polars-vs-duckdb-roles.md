# Polars vs DuckDB Role Separation

**Status**: accepted
**Date**: 2026-01-11
**Issue**: #183

## Context and Problem Statement

We introduced DuckDB alongside Polars to handle complex multi-month aggregations (see [ADR-0004](0004-duckdb-analytics-layer.md)). However, the boundary between when to use Polars and when to use DuckDB has been ambiguous, leading to mixed implementations:

* Some commands manually loaded CSVs with Polars
* Others used DuckDB SQL queries
* Type handling was inconsistent (JSON strings vs Lists)
* Performance characteristics were not clearly leveraged

We need a strict policy on which engine to use for what purpose to maintain code consistency and performance.

## Decision Drivers

* **Performance**: DuckDB is faster for OLAP (aggregations), Polars is faster for ETL (row-wise ops)
* **Consistency**: Unified access pattern for analytics
* **Simplicity**: Reduce code duplication (centralized view)
* **Type Safety**: Ensure consistent type handling across the pipeline

## Decision Outcome

Chosen option: **"Strict Separation by Domain with Explicit Command Ownership"**

1. **SQL Query & Template Interfaces → DuckDB**
   * **Scope**: Ad-hoc SQL, SQL templates, explain flows, simulation flows, and other query-first analysis.
   * **Pattern**: MUST use the centralized `transactions` view via `DuckDBAnalytics`.
   * **Why**: Native SQL support, reusable templates, analytical pushdown, and one normalized query surface.

2. **Ingestion & Transformation → Polars**
   * **Scope**: Reading raw XLSX, deduplication, cleaning, writing CSV partitions.
   * **Pattern**: Use `pl.read_excel`, `pl.DataFrame` transformations.
   * **Why**: Strong row-wise manipulation capabilities, precise schema control during ingest.

3. **DataFrame-Native Analytics Exceptions → Polars**
   * **Scope**: Commands whose core work is simple aggregation, list explosion, or pattern detection rather than SQL composition.
   * **Pattern**: Read partitions through the existing Polars storage helpers and stay in Polars through the result.
   * **Why**: These paths are simpler in DataFrame code, avoid engine hops, and the checked-in benchmark already shows Polars ahead for the simple monthly aggregation workload family.

4. **Data Exchange**
   * **Direction**: DuckDB → Polars (for final consumption in Python)
   * **Mechanism**: Zero-copy Apache Arrow conversion (`.pl()` method in DuckDB).
   * **Rule**: Default analytics/query flows go through DuckDB. Polars is allowed for commands explicitly assigned to Polars in the command table below.

### Consequences

**Positive**:
* ✅ **Standardized Access**: SQL/query-driven analytics use the normalized `transactions` view (with boolean flags, list tags).
* ✅ **Explicit Exceptions**: `stats`, `insights`, and export aggregations are documented as intentional Polars paths instead of accidental drift.
* ✅ **Better Workload Fit**: Each command keeps the engine that matches its interface and benchmarked workload.

**Negative**:
* ⚠️ **Split Mental Model**: Contributors must check command ownership before introducing new analytics code.
* ⚠️ **Dependency**: SQL analytics features still hard-depend on DuckDB (already true via ADR-0004).

## Command Engine Assignment

ADR-0006 is a default policy, not a mandate to force every analytics-facing command through DuckDB.
The command boundary is explicit:

| Command | Current Engine | Decision | Rationale |
|---------|---------------|----------|-----------|
| `query` | DuckDB | Keep | SQL interface |
| `template` | DuckDB | Keep | SQL templates |
| `explain` | DuckDB | Keep | SQL-based |
| `simulate` | DuckDB | Keep | SQL-based |
| `stats` | Polars | Keep as Polars exception | Simple aggregation, no SQL benefit |
| `insights` | Polars | Keep as Polars exception | Pattern detection, DataFrame-native |
| `export aggregations` | Polars | Keep as Polars | Transformation pipeline |

`stats` and `insights` stay on Polars by design. The checked-in benchmark baseline in
[`docs/benchmarks/duckdb-results.json`](../../benchmarks/duckdb-results.json) shows Polars ahead for
the simple monthly aggregation path that best matches the `stats` workload:

* 6,000 rows warm mean: 0.288s (Polars) vs 1.487s (DuckDBAnalytics path)
* 120,000 rows warm mean: 0.887s (Polars) vs 2.766s (DuckDBAnalytics path)

The same benchmark artifact also shows a mixed result for `tag_breakdown`: Polars wins the 6,000-row
warm run (0.477s vs 3.724s), while the 120,000-row warm run favors the current hybrid DuckDB path
(3.699s vs 1.879s). We therefore keep the narrower rule: simple stats/insight commands stay on Polars
because they are simpler in DataFrame code and do not need a SQL surface, while SQL-native commands stay
on DuckDB. This is an inference from the checked-in benchmark artifact plus the current command design,
not a claim that Polars always wins every aggregation.

The `inspect` command follows the DuckDB default as another SQL preset interface, even though it is not
part of the `#249` command table above.

## Implementation Guidelines

### 1. Analytics (DuckDB)

```python
# ✅ GOOD: Use centralized view
with DuckDBAnalytics(data_dir) as analytics:
    df = analytics.conn.execute("SELECT * FROM transactions WHERE is_transfer_bool = false").pl()

# ❌ BAD: Manual file reading for a DuckDB-owned command
pl.read_csv(data_dir / "transactions/*/*.csv")
```

### 2. Ingestion (Polars)

```python
# ✅ GOOD: Use Polars for ETL
df = pl.read_excel(xlsx_path)
df = df.with_columns(...)
df.write_csv(partition_path)
```

### 3. Command-Level Polars Exceptions

```python
# ✅ GOOD: Polars is allowed for commands explicitly assigned in ADR-0006
df = get_all_transactions(config.csv_base_dir)
monthly = df.group_by("month").agg(...)
```

## Related ADRs

* [ADR-0002: CSV Partition Storage](0002-csv-partition-storage.md)
* [ADR-0004: DuckDB Analytics Layer](0004-duckdb-analytics-layer.md)
