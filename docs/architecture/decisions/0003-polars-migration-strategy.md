# Polars Migration Strategy

**Status**: accepted
**Date**: 2025-11-05
**Issue**: #68

## Context and Problem Statement

The dashboard exhibited significant performance issues due to pandas-based data loading:

* Loading 12 months of data took 15.87x longer than Polars equivalent
* CSV reading was the bottleneck (pandas: 5.2s vs Polars: 0.33s for 6K rows)
* Large codebase already using pandas throughout pipeline
* Full migration to Polars is risky (potential regressions, API differences)

How can we adopt Polars for performance-critical paths while minimizing migration risk?

## Decision Drivers

* **Performance**: Need 10-15x speedup for dashboard responsiveness
* **Risk mitigation**: Avoid breaking existing pipeline functionality
* **Gradual adoption**: Allow incremental migration with validation
* **Compatibility**: Support both pandas and Polars during transition
* **Maintainability**: Minimize code duplication long-term

## Considered Options

1. **Feature-flag gradual migration** (phased rollout)
2. **Big-bang migration** (replace all pandas at once)
3. **Dual implementation** (maintain both permanently)
4. **Dashboard-only Polars** (localize to one component)
5. **Stick with pandas** (optimize instead of replace)

## Decision Outcome

Chosen option: "Feature-flag gradual migration", because:

* Low risk (isolate changes behind feature flag)
* Measurable (compare pandas vs Polars performance directly)
* Incremental (migrate one module at a time)
* Reversible (easy rollback if issues found)
* Clear path to full migration (3-phase plan)

### Consequences

**Positive**:
* ✅ **15.87x speedup** in dashboard (5.2s → 0.33s for 6K rows)
* ✅ **Low migration risk**: Feature flag allows A/B testing
* ✅ **Incremental validation**: Each module tested independently
* ✅ **Future-proof**: Polars is actively developed, pandas stagnating

**Negative**:
* ⚠️ **Code duplication**: Two backends during Phase 1-2 (temporary)
* ⚠️ **Maintenance burden**: Must update both implementations during transition
* ⚠️ **API differences**: Polars uses different syntax (learning curve)

**Mitigations**:
* **Phase 3 cleanup**: Remove pandas code after validation
* **Timeline**: 3-phase plan limits duplication window
* **Documentation**: Clear migration guide for API differences

### Confirmation

Migration success measured by:
* Dashboard load time <1s for 12 months (✅ achieved: 0.33s for 6K rows)
* No regressions in pipeline functionality
* Feature flag defaults to Polars by Phase 3 (pandas deprecated)

## Pros and Cons of the Options

### Feature-Flag Gradual Migration

**Approach**: Use `use_polars()` context manager, migrate module-by-module over 3 phases.

* ✅ Good, because low risk (isolated changes)
* ✅ Good, because measurable (A/B performance comparison)
* ✅ Good, because incremental (one module at a time)
* ✅ Good, because reversible (flag rollback)
* 🔵 Neutral, because temporary code duplication
* ❌ Bad, because maintenance burden during transition

### Big-Bang Migration

**Approach**: Replace all pandas code with Polars in one PR.

* ✅ Good, because no code duplication
* ✅ Good, because fast (one migration effort)
* ❌ Bad, because high risk (potential widespread breakage)
* ❌ Bad, because hard to validate (too many changes at once)
* ❌ Bad, because difficult rollback (all-or-nothing)

### Dual Implementation (Permanent)

**Approach**: Maintain both pandas and Polars backends indefinitely.

* ✅ Good, because maximum compatibility
* ✅ Good, because users can choose
* ❌ Bad, because permanent maintenance burden
* ❌ Bad, because code duplication forever
* ❌ Bad, because confusing for new contributors

### Dashboard-Only Polars

**Approach**: Use Polars only in dashboard, keep pandas for pipeline.

* ✅ Good, because localized changes
* ✅ Good, because immediate dashboard benefit
* 🔵 Neutral, because two backends in codebase
* ❌ Bad, because misses opportunity to improve pipeline performance
* ❌ Bad, because duplication persists

### Stick with Pandas

**Approach**: Optimize pandas code instead of migrating.

* ✅ Good, because no migration effort
* ✅ Good, because no API changes
* ❌ Bad, because pandas fundamentally slower (C vs Rust)
* ❌ Bad, because limited optimization headroom
* ❌ Bad, because pandas development slowing down

## Implementation Phases

### Phase 1: Dashboard Prototype (✅ Complete)
**Status**: Implemented and validated
* Dashboard uses `use_polars()` flag
* Performance: 15.87x speedup confirmed
* Fallback to pandas if Polars unavailable

### Phase 2: Pipeline Migration (Pending)
**Target**: Q1 2026
* Migrate `csv_partition.py` to Polars
* Migrate ingest/tag/export modules
* Maintain pandas fallback

### Phase 3: Deprecate Pandas (Future)
**Target**: Q2 2026
* Remove pandas code paths
* Polars becomes default (required dependency)
* Update documentation

## More Information

**Performance Benchmarks** (Issue #68):
* **Dataset**: 6,000 rows (12 months)
* **Pandas**: 5.2s total (CSV read: 4.8s, transform: 0.4s)
* **Polars**: 0.33s total (CSV read: 0.28s, transform: 0.05s)
* **Speedup**: 15.87x overall, 17.14x for CSV reading

**Implementation**:
* Feature flag: `src/finjuice/pipeline/config.py::use_polars()`
* Dashboard: `dashboards/data_loader.py`
* Storage layer: `src/finjuice/pipeline/storage/csv_partition_polars.py`

**Related ADRs**:
* [ADR-0002: CSV Partition Storage](0002-csv-partition-storage.md) - CSV format enables Polars performance
* [ADR-0004: DuckDB Analytics Layer](0004-duckdb-analytics-layer.md) - Complements Polars for aggregations

**References**:
* Issue #68: Polars Migration Strategy
* Benchmark results: `docs/benchmarks/polars-performance.md`
* Polars documentation: https://pola-rs.github.io/polars/
