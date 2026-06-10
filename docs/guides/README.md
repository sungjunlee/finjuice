# Guides

Step-by-step instructions for setup, configuration, and common tasks.

## Available Guides

### Setup & Configuration

#### [Data Repository Setup](setup/data-repository.md)
Complete guide for setting up a separate data repository for your personal financial data.

**Topics**:
- Why separate data from code
- Quick start (automatic vs manual setup)
- Directory structure
- Git workflow
- Migration from old setup

#### [DuckDB Analytics Layer](setup/duckdb-setup.md)
Setup guide for the DuckDB analytics extra that powers analytics commands.

**Topics**:
- When to use DuckDB (vs Polars)
- Installation and verification
- Usage examples and API reference
- Performance tuning
- Benchmarking

#### [AI CLI Integration](setup/ai-cli-setup.md)
Setup guide for AI-powered natural language queries in the dashboard.

**Topics**:
- Claude Code CLI setup
- Authentication (OAuth, no API keys)
- Dashboard integration
- Usage examples
- Troubleshooting

#### [GitHub Actions Setup](setup/github-actions.md)
Public repository CI and workflow security setup.

**Topics**:
- GitHub-hosted runner defaults
- Fork-safe pull request checks
- Workflow permissions
- Queue triage

### User Guide

#### [User Guide](user_guide.md)
General user guide for the finance pipeline.

### Workflows

_Coming soon: Development workflows and best practices_

## Quick Start

1. **Install**: Follow [installation instructions](../../README.md#installation)
2. **Set up data repo**: [Data Repository Setup](setup/data-repository.md)
3. **Run pipeline**: See [CLI Reference](../reference/cli.md#finjuice-refresh)
4. **If needed**: Install [DuckDB for analytics commands](setup/duckdb-setup.md) or [AI CLI](setup/ai-cli-setup.md)

## See Also

- [Architecture Documentation](../architecture/) - Design decisions
- [Reference Documentation](../reference/) - API/CLI/Schema reference
- [Project Guide](../../CLAUDE.md) - Development workflow

---

**Last Updated**: 2025-11-16
**Related Issues**: #109
