# Architecture Decision Records

This directory contains records of significant architectural decisions made during the finjuice project.

## About ADRs

An Architecture Decision Record (ADR) captures an important architectural decision made along with its context and consequences. This project uses the **MADR 3.0.0** format (Markdown Any Decision Records).

For new ADRs, please use [template.md](template.md) as basis.

**More information**: https://adr.github.io/madr/

## Decision Log

| ADR | Title | Status | Date | Issue |
|-----|-------|--------|------|-------|
| [0001](0001-use-madr-for-architecture-decisions.md) | Use MADR for Architecture Decisions | ✅ accepted | 2025-11-16 | #110 |
| [0002](0002-csv-partition-storage.md) | CSV Partition Storage | ✅ accepted | 2025-11-03 | #59 |
| [0003](0003-polars-migration-strategy.md) | Polars Migration Strategy | ✅ accepted | 2025-11-05 | #68 |
| [0004](0004-duckdb-analytics-layer.md) | DuckDB Analytics Layer | ✅ accepted | 2025-11-16 | #90 |
| [0005](0005-issue-based-development-workflow.md) | Issue-Based Development Workflow | ✅ accepted | 2025-10-28 | #47 |
| [0006](0006-polars-vs-duckdb-roles.md) | Polars vs DuckDB Role Separation | ✅ accepted | 2026-01-11 | #183 |
| [0007](0007-cli-as-data-api-for-ai-agents.md) | CLI as Data API for AI Agents | ✅ accepted | 2026-04-05 | #463 |
| [0008](0008-financial-metadata-notes-path.md) | Financial Metadata Notes Path | ✅ accepted | 2026-05-05 | #553 |
| [0009](0009-no-cli-command-spec-registry.md) | No CLI Command Spec Registry | ✅ accepted | 2026-05-12 | #601 |
| [0010](0010-ai-enrichment-proposal-log.md) | AI Enrichment Proposal Log | ✅ accepted | 2026-05-12 | #602 |
| [0011](0011-defer-mcp-and-vector-search-for-index.md) | Defer MCP and Vector Search for Index | ✅ accepted | 2026-05-24 | #774 |
| [0012](0012-agent-package-layout-for-finjuice-workflows.md) | Agent Package Layout for Finjuice Workflows | ✅ accepted | 2026-05-24 | #779 |
| [0013](0013-banksalad-overview-workbook-ingest.md) | Banksalad Overview Workbook Ingest | ✅ accepted | 2026-06-15 | N/A |

## Index by Category

### Meta & Process
- [ADR-0001: Use MADR for Architecture Decisions](0001-use-madr-for-architecture-decisions.md) ✅
- [ADR-0005: Issue-Based Development Workflow](0005-issue-based-development-workflow.md) ✅

### CLI & Agent Surfaces
- [ADR-0007: CLI as Data API for AI Agents](0007-cli-as-data-api-for-ai-agents.md) ✅
- [ADR-0009: No CLI Command Spec Registry](0009-no-cli-command-spec-registry.md) ✅
  - Keep Typer registration as executable source of truth; use runtime introspection guards.
- [ADR-0010: AI Enrichment Proposal Log](0010-ai-enrichment-proposal-log.md) ✅
  - Store append-only `metadata/enrichments/` proposals before any explicit `tags_ai` apply.
- [ADR-0011: Defer MCP and Vector Search for Index](0011-defer-mcp-and-vector-search-for-index.md) ✅
  - Keep `index --json` as a boring catalog; revisit retrieval/MCP only after concrete triggers.
- [ADR-0012: Agent Package Layout for Finjuice Workflows](0012-agent-package-layout-for-finjuice-workflows.md) ✅
  - Keep `skills/finjuice*` canonical; defer named packages until public-preview evidence.

### Data Storage & Schema
- [ADR-0002: CSV Partition Storage](0002-csv-partition-storage.md) ✅
  - 89% metadata reduction, git-friendly diffs, 56% token efficiency
- [ADR-0008: Financial Metadata Notes Path](0008-financial-metadata-notes-path.md) ✅
  - Use goals.yaml for stable context and rules.yaml notes for rule rationale
- [ADR-0013: Banksalad Overview Workbook Ingest](0013-banksalad-overview-workbook-ingest.md) ✅
  - Capture `뱅샐현황` as workbook facts, then derive typed balance/cashflow projections.

### Performance & Analytics
- [ADR-0003: Polars Migration Strategy](0003-polars-migration-strategy.md) ✅
  - 15.87x speedup in dashboard, gradual migration with feature flags
- [ADR-0004: DuckDB Analytics Layer](0004-duckdb-analytics-layer.md) ✅
  - SQL expressiveness plus a checked-in benchmark artifact for current performance
- [ADR-0006: Polars vs DuckDB Role Separation](0006-polars-vs-duckdb-roles.md) ✅
  - Strict separation: DuckDB for analytics/views, Polars for ETL/ingest

## Decision Relationships

```
ADR-0001 (Use MADR)
    ├─ Establishes process for all future ADRs
    └─ Meta-decision enabling this directory

ADR-0002 (CSV Partitions)
    ├─ Supersedes: JSON-based storage
    ├─ Enables: ADR-0003 (Polars), ADR-0004 (DuckDB)
    └─ Foundation for token-efficient AI development

ADR-0003 (Polars Migration)
    ├─ Depends on: ADR-0002 (CSV format)
    └─ Complements: ADR-0004 (Polars for transforms, DuckDB for aggregations)

ADR-0004 (DuckDB Analytics)
    ├─ Depends on: ADR-0002 (CSV partitions)
    ├─ Complements: ADR-0003 (DuckDB for aggregations, Polars for transforms)
    └─ Clarified by: ADR-0006 (Role Separation)

ADR-0005 (Issue Workflow)
    ├─ Process decision (independent of storage/performance)
    └─ Defines how ADRs are created (/issue:* workflow)

ADR-0006 (Role Separation)
    ├─ Clarifies: ADR-0003 (Polars scope) and ADR-0004 (DuckDB scope)
    └─ Enforces: Centralized view usage for analytics
```

## Active ADRs

All 13 current ADRs are **accepted** and active:

1. **MADR Format** - Using MADR 3.0.0 template
2. **CSV Partitions** - Monthly partitioned CSV storage
3. **Polars Migration** - Gradual migration from pandas
4. **DuckDB Analytics** - Optional layer for aggregations
5. **Issue Workflow** - Slash command development process
6. **Role Separation** - Strict DuckDB (Analytics) vs Polars (ETL) split
7. **CLI as Data API** - AI-agent-oriented read surfaces
8. **Financial Metadata Notes Path** - Stable goals.yaml context and rule notes
9. **No CLI Command Spec Registry** - Shared runtime introspection is sufficient for CLI manifests and tool schemas
10. **AI Enrichment Proposal Log** - Append-only proposal records before any explicit AI tag apply
11. **Defer MCP and Vector Search for Index** - Catalog first, retrieval later, MCP last
12. **Agent Package Layout** - Keep the current skill suite canonical; defer named bundles
13. **Banksalad Overview Workbook Ingest** - Capture `뱅샐현황` facts and derive typed projections

## Superseded ADRs

_None yet_

## Writing a New ADR

### Quick Start

1. **Copy template**:
   ```bash
   cp docs/architecture/decisions/template.md docs/architecture/decisions/0006-short-title.md
   ```

2. **Fill in sections**:
   - **Context**: What problem are we solving?
   - **Decision Drivers**: What constraints/priorities matter?
   - **Considered Options**: What alternatives did we evaluate?
   - **Decision Outcome**: What did we choose and why?
   - **Consequences**: Pros, cons, and mitigations

3. **Update this index**:
   - Add row to Decision Log table
   - Add to appropriate category section

4. **Commit**:
   ```bash
   git add docs/architecture/decisions/
   git commit -m "docs: add ADR-0006 [short title]"
   ```

### When to Write an ADR

Write an ADR for **significant** architectural decisions:

✅ **Do write ADR**:
- Storage format changes (CSV → Parquet, etc.)
- Major dependency additions (DuckDB, new frameworks)
- Workflow process changes (CI/CD, testing strategy)
- Performance architecture (caching, optimization approaches)
- Security architecture (authentication, encryption)

❌ **Don't write ADR**:
- Small bug fixes
- Refactoring within existing patterns
- Dependency version updates
- Documentation improvements (unless meta-decision)

### Numbering

- Use **4-digit sequential numbering**: 0001, 0002, ..., 9999
- Numbers are **never reused** (even if ADR deleted)
- No gaps required (but consecutive preferred)

### Status Lifecycle

```
proposed → accepted → [deprecated | superseded]
    ↓
  rejected
```

- **proposed**: Under review, not yet approved
- **accepted**: Approved and implemented
- **deprecated**: No longer recommended (but not replaced)
- **superseded**: Replaced by newer ADR (link to new one)
- **rejected**: Proposed but not accepted

## References

### MADR Resources
- **MADR Homepage**: https://adr.github.io/madr/
- **MADR Template**: https://github.com/adr/madr/blob/main/template/adr-template.md
- **MADR Examples**: https://github.com/adr/madr/tree/main/docs/decisions

### ADR Background
- **Original Nygard Post (2011)**: https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions
- **ADR GitHub Organization**: https://adr.github.io/

### Related Documentation
- [Architecture Overview](../README.md)
- [Project Guide](../../../CLAUDE.md)
- [Development Workflow](../../../CLAUDE.md#development-workflow)

---

**Last Updated**: 2026-06-15
**Related Issues**: #110 (ADR Introduction), #602 (AI Enrichment Proposal Log)
**Format**: MADR 3.0.0
