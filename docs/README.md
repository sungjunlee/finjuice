# Documentation Guide

Complete documentation for the finjuice project.

## Directory Structure

- **[architecture/](architecture/)** - System design and architecture decisions
  - [specs/](architecture/specs/) - Design specifications
  - [decisions/](architecture/decisions/) - Architecture Decision Records (ADR)
  - [discussions/](architecture/discussions/) - Implementation discussions

- **[reference/](reference/)** - Auto-generated technical reference
  - [schema.md](reference/schema.md) - Data schema (from schema.yaml)
  - [cli.md](reference/cli.md) - CLI commands (from finjuice --help)

- **[guides/](guides/)** - Step-by-step how-to guides
  - [setup/](guides/setup/) - Setup and configuration guides
  - [workflows/](guides/workflows/) - Development workflows
  - [user_guide.md](guides/user_guide.md) - User guide

- **[benchmarks/](benchmarks/)** - Performance benchmarks and results

- **[plans/](plans/)** - Incremental implementation plans and execution roadmaps

- **[archive/](archive/)** - Historical documents (reference only)
  - [tasks/](archive/tasks/) - Completed implementation tasks
  - [improvements/](archive/improvements/) - Documentation improvements
  - [audit/](archive/audit/) - Issue audits and progress tracking

## Quick Links

### Getting Started
- [Project Overview](../README.md)
- [CLI Reference](reference/cli.md)

### Architecture & Design
- [Initial Specification (Korean)](architecture/specs/v0_initial.md)
- [Architecture Decisions](architecture/decisions/README.md)
- [Schema Reference](reference/schema.md)

### Setup Guides
- [Data Repository Setup](guides/setup/data-repository.md)
- [DuckDB Analytics Layer](guides/setup/duckdb-setup.md)
- [AI CLI Integration](guides/setup/ai-cli-setup.md)

### Development
- [User Guide](guides/user_guide.md)
- [Development Workflows](guides/workflows/) (Coming soon)
- [Agentic Direction Roadmap](plans/agentic-direction-roadmap.md)
- [Pilot Execution Logs](plans/execution/)

## Contributing

See [CONTRIBUTING.md](../CONTRIBUTING.md) for public contribution guidelines.

---

**Last Updated**: 2026-02-15
**Related Issues**: #109, #110
