# AGENTS.md

Repository instructions for AI coding agents working on finjuice.

Keep this file short. It is loaded at session start by Codex and may be
imported by Claude Code. Put large references in `docs/`, path-scoped rules, or
skills instead of adding them here.

## Working Language

- Respond to the user in Korean unless they explicitly ask for another language.
- Keep explanations concise and action-oriented.

## Project Overview

finjuice processes Banksalad XLSX exports into tagged, deduplicated personal
finance data.

- Core principles: local-first, idempotent, privacy-focused, solo-dev friendly.
- Tech stack: Python 3.10+, uv, Polars, Typer CLI, CSV partitions.
- Storage model: user data lives outside the program repo, partitioned by
  `transactions/YYYY/MM/`.
- Main package: `src/finjuice/pipeline/`.
- Schema source of truth: `templates/schema.yaml`.

High-level flow:

```text
imports/ -> ingest -> transactions/YYYY/MM/ -> tag -> transfer -> export
```

## Daily Commands

Run these from the repository root:

```bash
uv run pytest
uv run ruff check .
uv run mypy src/
```

Common CLI checks:

```bash
uv run finjuice --help
uv run finjuice status --json
uv run finjuice template list
uv run finjuice query --help
```

Prefer live CLI help over loading large generated reference files when you only
need command syntax.

## Development Workflow

- Inspect existing code and tests before editing.
- Prefer small, focused changes that match local patterns.
- Add or update tests for behavioral changes.
- Run the narrowest useful test first, then the broader checks above when
  finishing.
- Do not commit, push, or open a PR unless the user asks.
- Preserve unrelated user changes in the worktree.

Issue workflow shortcuts may exist under `.claude/commands/`, but use them only
when the user asks for that workflow.

## Architecture Notes

- Ingest normalizes XLSX rows and deduplicates using `row_hash`.
- Tagging evaluates enabled `rules.yaml` rules by priority: all matches
  contribute deduped tags, while the highest-priority matching rule with a
  non-empty category sets `category_rule`.
- Transfer detection pairs internal transfers by time and amount heuristics.
- Export aggregates CSV partitions into reports and spreadsheet outputs.
- Analysis commands (`show`, `query`, `explain`, `template`) are the preferred
  read interface for agents.

## Python Standards

- Use type hints for new and changed public code.
- Follow the configured ruff style and 100-character line length.
- Use Google-style docstrings for public APIs when a docstring is warranted.
- Use semantic CLI output helpers from `finjuice.pipeline.cli.output` for
  user-facing messages.
- Use `logger` for debug/internal logs and avoid logging financial details.

## Security And Data Rules

- Treat transaction, asset, and export data as private financial data.
- Never log raw financial rows, account numbers, or sensitive file contents.
- Never edit user transaction or asset CSV partitions directly unless the user
  explicitly requests it.
- Validate file paths that come from user input; avoid path traversal.
- Use parameterized SQL placeholders such as `?`; do not format values into SQL
  strings.
- Keep `data/`, `*.db`, `.env`, and private exports out of git.

## Testing Expectations

- Use pytest with Arrange, Act, Assert structure for new tests.
- Include idempotency checks when changing ingest, tagging, transfer detection,
  export, or storage behavior.
- For CLI behavior, test both human output and `--json` output where relevant.
- If a verification command cannot run, state the exact reason and the residual
  risk.

## Documentation Boundaries

- `docs/reference/` contains generated or long-form reference material. Do not
  import those files into startup instructions.
- `docs/reference/cli.md` and `docs/reference/json-schemas.md` are large; prefer
  `finjuice <command> --help`, `finjuice status --json`, or targeted file reads.
- Regenerate generated docs with `just docs`, `just docs-cli`, or
  `just docs-schema` instead of editing generated files manually.
- Move multi-step agent procedures into skills or `.claude/rules/` rather than
  growing this file.

## Ask First

Ask before:

- Changing public CLI semantics or JSON schemas.
- Adding production dependencies.
- Making security-sensitive changes.
- Modifying private user data files.
- Applying a destructive or irreversible operation.
