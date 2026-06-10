# Reference Documentation

Technical reference for schemas, CLI commands, JSON outputs, and query snippets.

These files are intentionally not startup instructions for coding agents. Some
of them are large generated artifacts, so agents should open only the targeted
section they need or prefer live CLI help.

## Contents

### [Schema Reference](schema.md)
Complete data schema documentation auto-generated from `templates/schema.yaml`.

**Includes**:
- Current schema version
- Column definitions
- Migration history
- Validation rules
- Performance metrics

**Auto-generated**: Run `just docs-schema` to regenerate.

### [CLI Reference](cli.md)
Complete CLI command reference auto-generated from `finjuice --help`.

**Includes**:
- All CLI commands
- Command options and parameters
- Common workflows
- Troubleshooting

**Auto-generated**: Run `just docs-cli` to regenerate.

### [JSON Output Schemas](json-schemas.md)
Long-form schema reference for command outputs that support `--json`.

Use this only when changing or validating machine-readable CLI contracts.

### [Rule Conditions](rules-conditions.md)
Reference for the conditional rule engine operators, precedence, and examples.

Use this when changing tagging rule semantics or writing complex `rules.yaml`
conditions.

### [DuckDB Snippets](duckdb-snippets.md)
Canonical SQL snippets for ad-hoc analysis on CSV partitions.

Use this when changing analytics examples or validating query templates.

## Usage

These reference documents are **auto-generated** from source of truth:
- Schema: `templates/schema.yaml`
- CLI: `finjuice --help` output

**Do not edit manually** - changes will be overwritten on next generation.

## Agent Usage

- Do not import this directory from `AGENTS.md` or `CLAUDE.md`.
- Prefer `uv run finjuice <command> --help` for command syntax.
- Prefer `uv run finjuice status --json` and focused command output when checking
  current JSON shapes.
- If a generated reference is needed, read the smallest relevant range instead
  of loading the whole file.

## Generation Commands

```bash
# Regenerate schema reference
just docs-schema

# Regenerate CLI reference
just docs-cli

# Regenerate both
just docs
```

## See Also

- [Schema Source](../../templates/schema.yaml) - Schema definition (source of truth)
- [CLI Source](../../src/finjuice/pipeline/cli/) - CLI implementation
- [Architecture](../architecture/) - Design decisions
- [Guides](../guides/) - Setup and usage guides

---

**Last Updated**: 2026-05-03
**Note**: This file is manually maintained. Schema and CLI docs are auto-generated.
