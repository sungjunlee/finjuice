# CSV Partition Storage for Transaction Data

**Status**: accepted
**Date**: 2025-11-03
**Issue**: #59
**Supersedes**: JSON-based storage (no formal ADR)

## Context and Problem Statement

The original transaction storage used a single consolidated JSON file. This created several problems:

* **Token inefficiency**: Loading full dataset consumed 170K tokens (expensive for AI analysis)
* **Git unfriendly**: JSON structure changes produced unreadable diffs
* **Monolithic**: No way to selectively load specific time periods
* **Metadata overhead**: Full file paths and mtimes stored per-row consumed significant space

How should we store transaction data to optimize for AI-assisted development, git workflows, and selective data access?

## Decision Drivers

* **Token efficiency**: Minimize tokens needed for AI context (Claude Code, analysis tasks)
* **Git-friendly diffs**: Clear, line-oriented changes for code review
* **Selective loading**: Load only needed months for analysis
* **Unix tool compatibility**: Enable grep, awk, csvkit for quick queries
* **Schema evolution**: Support versioning and migration
* **Traceability**: Track source files without excessive metadata

## Considered Options

1. **CSV partitions** (year/month structure)
2. **Single consolidated CSV** (flat file)
3. **SQLite database** (relational storage)
4. **Parquet files** (columnar storage)
5. **Keep JSON** (status quo)

## Decision Outcome

Chosen option: "CSV partitions (year/month structure)", because:

CSV partitions are the runtime source of truth for transaction data. The
project does not maintain a parallel database file as a secondary runtime
representation.

* 89% token reduction (170K → 8K per month partition)
* Git-friendly line-oriented diffs
* Natural partitioning by time (most common access pattern)
* Direct CLI tool access (grep, awk, head, tail)
* Human-readable for verification

### Consequences

**Positive**:
* ✅ **89% metadata reduction**: Compact file_id (8 chars) replaces path (80 chars) + mtime (26 chars)
* ✅ **56% token efficiency**: Monthly partitions vs full dataset
* ✅ **Clear git diffs**: Line-by-line changes, easy code review
* ✅ **Unix tool compatibility**: Standard CSV tools work directly
* ✅ **Faster selective loading**: Read only needed months (8K tokens vs 170K)
* ✅ **Schema versioning**: Centralized schema.yaml tracks evolution

**Negative**:
* ⚠️ **Multi-file reads**: Complex aggregations require loading multiple partitions
* ⚠️ **No built-in type safety**: CSV is text-based (vs Parquet's schema enforcement)
* ⚠️ **Partition management overhead**: Must handle year/month directory structure

**Mitigations**:
* DuckDB integration for fast multi-partition queries (see [ADR-0003](0003-duckdb-analytics-layer.md))
* Schema validation at ingest time prevents type errors
* `read_month()` helper function abstracts partition management
* Import history CSV (`data/metadata/import_history.csv`) centralizes file_id lookups

### Confirmation

Validated by:
* Migration of 13 partitions (2,269 transactions) completed successfully
* Token count measurements: 8K per month vs 170K for full dataset
* Git diff comparison: CSV diffs are human-readable vs JSON structure noise

## Pros and Cons of the Options

### CSV Partitions (year/month structure)

**Structure**: `data/transactions/YYYY/MM/transactions.csv`

* ✅ Good, because 89% metadata reduction (file_id system)
* ✅ Good, because monthly partitions match common access pattern
* ✅ Good, because line-oriented diffs are git-friendly
* ✅ Good, because standard Unix tools work (grep, awk)
* ✅ Good, because human-readable for debugging
* 🔵 Neutral, because requires partition management code
* ❌ Bad, because aggregations require reading multiple files

### Single Consolidated CSV

**Structure**: One large `transactions.csv` file

* ✅ Good, because simpler (no partition management)
* ✅ Good, because full-table queries are fast
* ❌ Bad, because loading file consumes ~170K tokens (not selective)
* ❌ Bad, because git diffs become large and hard to review
* ❌ Bad, because file size grows unbounded over time

### SQLite Database

**Structure**: one local relational database file

**Current status**: considered but not implemented as a supported storage
layer.

* ✅ Good, because fast queries with SQL
* ✅ Good, because type safety and constraints enforced
* ✅ Good, because ACID transactions
* ❌ Bad, because binary format (not human-readable)
* ❌ Bad, because git diffs are meaningless (binary)
* ❌ Bad, because not accessible to standard text tools
* 🔵 Neutral, because adds runtime dependency

### Parquet Files

**Structure**: `transactions.parquet` columnar storage

* ✅ Good, because excellent compression and performance
* ✅ Good, because schema enforcement built-in
* ✅ Good, because columnar format optimized for analytics
* ❌ Bad, because binary format (not human-readable)
* ❌ Bad, because less git-friendly (binary diffs)
* ❌ Bad, because requires PyArrow/Polars to read

### Keep JSON (status quo)

**Structure**: Single `transactions.json` file

* ✅ Good, because already implemented
* 🔵 Neutral, because human-readable
* ❌ Bad, because 170K token overhead (expensive AI context)
* ❌ Bad, because nested structure creates noisy diffs
* ❌ Bad, because hard to use with standard Unix tools

## More Information

**Implementation Details**:
* Schema defined in `templates/schema.yaml` (current CSV v3 runtime contract, 27 columns)
* Migration script: `scripts/migrate_csv_metadata.py`
* Partition storage module: `src/finjuice/pipeline/storage/csv_partition.py`
* Import history: `data/metadata/import_history.csv`

**Performance Metrics** (Issue #59):
* Rows migrated: 2,269
* Partitions created: 13
* Metadata savings: 152 chars per row = 89% reduction
* Token efficiency: 40-50% overall improvement
* Collision probability: <0.001% for 100K transactions (10-char row_hash)

**Related ADRs**:
* [ADR-0003: DuckDB Analytics Layer](0003-duckdb-analytics-layer.md) - Addresses multi-partition aggregation
* [ADR-0001: Use MADR](0001-use-madr-for-architecture-decisions.md) - Meta-decision process

**References**:
* Issue #59: CSV Metadata Optimization
* Issue #61: Data Schema Registry and Versioning System
* Issue #62: Import History Redesign
* Schema registry: [`templates/schema.yaml`](../../../templates/schema.yaml)
