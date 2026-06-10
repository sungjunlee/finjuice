# Architecture Documentation

High-level architecture and design decisions for finjuice.

## Overview

This directory contains documentation about the system's architecture, design decisions, and technical specifications.

## Contents

### [specs/](specs/)
Original design specifications and requirements.

- [v0_initial.md](specs/v0_initial.md) - Initial specification (Korean, comprehensive)

### [decisions/](decisions/)
Architecture Decision Records (ADR) documenting significant architectural choices.

**Format**: MADR 3.0.0 (Markdown Any Decision Records)

**Active ADRs**:
- [ADR-0001: Use MADR](decisions/0001-use-madr-for-architecture-decisions.md) - Meta-decision for ADR process
- [ADR-0002: CSV Partition Storage](decisions/0002-csv-partition-storage.md) - 89% token reduction
- [ADR-0003: Polars Migration](decisions/0003-polars-migration-strategy.md) - 15x speedup
- [ADR-0004: DuckDB Analytics](decisions/0004-duckdb-analytics-layer.md) - Fast aggregations
- [ADR-0005: Issue Workflow](decisions/0005-issue-based-development-workflow.md) - Development process
- [ADR-0012: Agent Package Layout](decisions/0012-agent-package-layout-for-finjuice-workflows.md) - Skill suite stays canonical

**See**: [Full ADR Index](decisions/README.md)

### [discussions/](discussions/)
Implementation discussions and technical analysis.

- [implementation_details.md](discussions/implementation_details.md)

## Key Architectural Decisions

### Storage Architecture
- **CSV Partition Storage**: Monthly partitioned CSV files for 89% token reduction
- **Schema Versioning**: Centralized schema registry in `templates/schema.yaml`
- **Import History**: Centralized metadata tracking with optional archiving

### Analytics Architecture
- **Polars**: High-performance DataFrame operations (15x faster than pandas)
- **DuckDB**: Optional SQL-oriented analytics layer; benchmark current workloads before assuming a speed win
- **Partition-based Loading**: Load only needed months for efficiency

### Development Workflow
- **Issue-based**: Slash commands (`/issue:*`) for structured workflow
- **TDD Cycle**: Red-Green-Refactor pattern with automated checks
- **Quality Gates**: Automated pytest, ruff, mypy on every PR

## Core Principles

1. **Local-first**: Offline-capable, no forced cloud dependencies
2. **Privacy-focused**: Personal financial data stays local
3. **Idempotent**: Rerunnable pipeline with consistent results
4. **Token-efficient**: Optimized for AI-assisted development
5. **Git-friendly**: Clear diffs, trackable changes

## Related Documentation

- [Full Specification](specs/v0_initial.md) - Complete design doc (Korean)
- [Schema Reference](../reference/schema.md) - Data schema details
- [CLI Reference](../reference/cli.md) - Command reference
- [Project Guide](../../CLAUDE.md) - Development workflow

---

**Last Updated**: 2025-11-16
**Related Issues**: #109, #110
