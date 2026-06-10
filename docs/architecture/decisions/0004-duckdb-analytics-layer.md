# DuckDB Analytics Layer

**Status**: accepted
**Date**: 2025-11-16
**Issue**: #90
**Last Reviewed**: 2026-03-26 (#247)

## Context and Problem Statement

CSV partition storage (see [ADR-0002](0002-csv-partition-storage.md)) optimized for selective monthly loading, but created challenges for multi-month aggregations:

* Complex aggregations require reading multiple CSV files
* Pandas/Polars concat operations add overhead
* SQL queries are more natural for some analytics (GROUP BY, JOIN)
* Dashboard queries need to aggregate across 12+ months

DuckDB was introduced as a SQL-oriented analytics layer on top of those CSV partitions. The original
ADR assumed broad speedups over Polars, but the 2026-03-26 benchmark re-baseline on the current
codebase does not support a blanket "DuckDB is faster" claim.

How can we keep the analytics boundary while documenting the measured behavior honestly?

## Decision Drivers

* **Measured behavior**: Keep performance claims aligned with the checked-in benchmark artifact
* **SQL expressiveness**: Natural query language for analytics
* **Optional dependency**: Don't force on all users
* **Zero-copy integration**: Leverage existing CSV partitions
* **Maintain simplicity**: Keep CSV partitions as source of truth

## Considered Options

1. **DuckDB analytics layer** (optional, opt-in)
2. **Materialize views in SQLite** (pre-computed aggregations)
3. **In-memory aggregation cache** (computed on first access)
4. **Switch to Parquet** (columnar storage)
5. **Stick with Polars concat** (status quo)

## Decision Outcome

Chosen option: "DuckDB analytics layer (optional, opt-in)", because:

* SQL expressiveness for complex queries
* Centralized analytics/view contract on top of CSV partitions
* Zero-copy read from CSV files (Apache Arrow)
* Optional install (doesn't force dependency)
* Works alongside existing Polars pipeline
* Performance remains workload-dependent and must be benchmarked, not assumed

### Consequences

**Positive**:
* ✅ **SQL expressiveness**: Natural language for GROUP BY, JOIN, window functions
* ✅ **Centralized analytics view**: One `transactions` surface for DuckDB-backed query commands
* ✅ **Zero-copy**: Direct CSV read via Apache Arrow (no intermediate files)
* ✅ **Optional**: Users without `[analytics]` extra unaffected
* ✅ **Complements Polars**: Use DuckDB for aggregations, Polars for transforms

**Negative**:
* ⚠️ **Extra dependency**: Adds duckdb to `[analytics]` extra (~50MB)
* ⚠️ **Learning curve**: Developers need to know when to use DuckDB vs Polars
* ⚠️ **Cold-start overhead**: Connection setup and view registration are materially slower than Polars in the current CSV benchmark
* ⚠️ **No guaranteed speed win**: Current synthetic CSV benchmark does not show DuckDB ahead on the measured paths

**Mitigations**:
* **Opt-in installation**: `uv sync --extra analytics` (not required)
* **Checked-in benchmark artifact**: Keep `docs/benchmarks/duckdb-results.json` current
* **Polars fallback**: Dashboard works without DuckDB (auto-detects)
* **Helper functions**: Wrap SQL queries to reduce complexity

### Confirmation

Success measured by:
* Benchmark artifact exists and records current versions plus cold/warm methodology
* ADR and setup guide cite measured results instead of placeholder speedup claims
* No impact on users without `[analytics]` extra

## Pros and Cons of the Options

### DuckDB Analytics Layer (Chosen)

**Approach**: Optional analytics layer, CSV partitions remain source of truth.

* ✅ Good, because SQL expressiveness (natural for analytics)
* ✅ Good, because centralized analytics/view contract reduces ad-hoc CSV query logic
* ✅ Good, because zero-copy CSV reads (Apache Arrow)
* ✅ Good, because optional (no forced dependency)
* ✅ Good, because complements Polars (use best tool for job)
* 🔵 Neutral, because adds ~50MB dependency
* ❌ Bad, because cold runs are slower in the current benchmark
* ❌ Bad, because monthly spend remains slower than Polars even in the 120K synthetic case
* ❌ Bad, because developers need to choose between DuckDB/Polars

### Materialize Views in SQLite

**Approach**: Pre-compute aggregations, store in SQLite, refresh periodically.

* ✅ Good, because fast queries (pre-computed)
* ✅ Good, because lightweight (SQLite built-in)
* ❌ Bad, because stale data (requires refresh logic)
* ❌ Bad, because storage duplication (CSV + SQLite)
* ❌ Bad, because maintenance burden (view definitions)

### In-Memory Aggregation Cache

**Approach**: Compute aggregations on first access, cache in memory.

* ✅ Good, because no external dependency
* ✅ Good, because automatic (transparent to user)
* ❌ Bad, because cache invalidation complexity
* ❌ Bad, because memory overhead (large datasets)
* ❌ Bad, because doesn't help with ad-hoc queries (cold cache)

### Switch to Parquet

**Approach**: Replace CSV partitions with Parquet files.

* ✅ Good, because columnar storage (fast aggregations)
* ✅ Good, because schema enforcement built-in
* ✅ Good, because compression (smaller files)
* ❌ Bad, because binary format (not human-readable)
* ❌ Bad, because git-unfriendly (binary diffs)
* ❌ Bad, because breaks existing CSV workflows (see [ADR-0002](0002-csv-partition-storage.md))

### Stick with Polars Concat (Status Quo)

**Approach**: Keep using Polars `read_csv()` + `concat()` for multi-month queries.

* ✅ Good, because no new dependency
* ✅ Good, because already implemented
* ✅ Good, because it is currently faster for the benchmarked monthly spend workload
* ❌ Bad, because less expressive than SQL for complex queries

## Implementation Details

### API Design

```python
from finjuice.pipeline.analytics import DuckDBAnalytics

# Context manager (recommended)
with DuckDBAnalytics(data_dir) as analytics:
    monthly = analytics.monthly_spend()
    tags = analytics.tag_breakdown(top_n=10)

# Manual lifecycle
analytics = DuckDBAnalytics(data_dir)
try:
    result = analytics.read_partitions(pattern="2024/*/transactions.csv")
finally:
    analytics.close()
```

### Performance Characteristics

Benchmark baseline from `docs/benchmarks/duckdb-results.json` on 2026-03-26:
Python 3.13.11, Polars 1.35.2, DuckDB 1.4.2, current v3 27-column partition shape,
and 24 distinct month partitions.

| Operation | Dataset | Polars cold | DuckDBAnalytics path cold | Polars warm mean | DuckDBAnalytics path warm mean | Warm speedup |
|-----------|---------|-------------|---------------------------|------------------|-------------------------------|--------------|
| Monthly aggregation | 6,000 rows | 1.560s | 4.735s | 0.288s | 1.487s | **0.19x** |
| Tag breakdown | 6,000 rows | 0.905s | 2.258s | 0.477s | 3.724s | **0.13x** |
| Monthly aggregation | 120,000 rows | 2.897s | 4.969s | 0.887s | 2.766s | **0.32x** |
| Tag breakdown | 120,000 rows | 4.836s | 24.236s | 3.699s | 1.879s | **1.97x** |

**Cold** means the first execution on fresh engine state. **Warm** means repeated runs in the same
Python process; DuckDBAnalytics warm runs reuse a single `DuckDBAnalytics` connection and view. Treat this
artifact as a reproducible host-local baseline, not a universal threshold.
For `tag_breakdown`, the DuckDBAnalytics path is still hybrid: DuckDB reads through the
`transactions` view, then Polars performs the JSON explode and final aggregation fallback.
In this checked-in run, Polars is ahead on all cold runs and on both `monthly_spend` warm runs,
while the 120,000-row warm `tag_breakdown` case favors the current hybrid path.

### Polars vs DuckDB Guidelines

**Use Polars for**:
- Single-record operations (ingest, tagging)
- Data transformations and ETL
- High-level DataFrame API
- Simple aggregations where the checked-in benchmark already shows Polars ahead

**Use DuckDB for**:
- SQL-native operations
- Current DuckDB-backed query/inspection flows
- Representative workloads that you have benchmarked and verified locally

## More Information

**Implementation**:
* Analytics layer: `src/finjuice/pipeline/analytics/duckdb_layer.py`
* Query builders: `src/finjuice/pipeline/analytics/query_builder.py`
* Installation: `uv sync --extra analytics`
* Documentation: `docs/guides/setup/duckdb-setup.md`

**Performance Benchmarks**:
* Benchmark script: `scripts/benchmark_duckdb.py`
* Results: `docs/benchmarks/duckdb-results.json`

**Related ADRs**:
* [ADR-0002: CSV Partition Storage](0002-csv-partition-storage.md) - CSV partitions enable DuckDB
* [ADR-0003: Polars Migration](0003-polars-migration-strategy.md) - Polars for transforms, DuckDB for aggregations

**References**:
* Issue #90: DuckDB Analytics Layer
* DuckDB documentation: https://duckdb.org/docs/guides/python/polars
* Setup guide: `docs/guides/setup/duckdb-setup.md`
