# Contributing to finjuice

Thanks for helping improve finjuice. This project handles personal finance data,
so contributions should stay small, reproducible, and privacy-conscious.

## Setup

```bash
git clone https://github.com/sungjunlee/finjuice.git
cd finjuice
uv sync
uv run finjuice --help
```

For manual CLI checks, prefer a scratch data directory:

```bash
FINJUICE_DATA_DIR="$(mktemp -d)" uv run finjuice status --json
```

## Daily Commands

Run the narrowest useful command first, then the broader checks before opening a
pull request:

```bash
uv run pytest
uv run ruff check .
uv run mypy src/
```

Pull requests also run a public GitHub-hosted CI gate on `ubuntu-latest` for
fork-safe feedback. That gate installs dependencies, runs Ruff lint/format
checks, and executes a focused pytest selection. Heavier coverage, package,
documentation, matrix, type, and security checks remain in the self-hosted
workflows. See [docs/development/ci.md](docs/development/ci.md).

Useful CLI smoke checks:

```bash
uv run finjuice --help
uv run finjuice status --json
uv run finjuice template list
uv run finjuice query --help
```

## Test Expectations

- Add or update pytest coverage for behavior changes.
- Include idempotency checks when changing ingest, tagging, transfer detection,
  export, or storage behavior.
- For CLI behavior, cover both human output and `--json` output when relevant.
- For documentation-only changes, tests may be unnecessary; state that clearly in
  the PR verification section.

## Privacy Rules

- Do not commit raw Banksalad exports, private transaction rows, account numbers,
  real asset data, `.env` files, local databases, or private exports.
- Use synthetic or heavily redacted examples in issues, tests, fixtures, logs,
  screenshots, and PR descriptions.
- Do not ask other contributors to paste private financial data. Request minimal,
  redacted structure instead.
- Keep `data/`, `*.db`, `.env`, and private export files out of git.

## Contribution Scope

Good contribution areas include:

- documentation improvements
- tests and synthetic fixtures
- parsing or import fixes based on redacted examples
- tagging, transfer, export, and reporting correctness fixes
- CLI usability improvements that preserve existing contracts

Please open or reference an issue before changing public CLI semantics, JSON
contracts, storage schemas, dependencies, security-sensitive behavior, or private
data handling.

## CLI JSON And Schema Boundaries

finjuice treats CLI JSON output and data schemas as public contracts.

- `templates/schema.yaml` is the source of truth for transaction storage schema.
- `schemas/*.schema.json` describe CLI JSON output contracts.
- `docs/reference/` contains generated reference material; regenerate it with
  `just docs`, `just docs-cli`, or `just docs-schema` instead of editing it by
  hand.
- Any contract change should include compatibility notes, focused tests, and
  documentation updates.

## Safe Pull Request Workflow

1. Create a focused branch and keep unrelated edits out of the PR.
2. Stage files intentionally; avoid broad `git add -A` when your worktree has
   unrelated changes.
3. Run the relevant verification commands and record the results in the PR.
4. Explain privacy impact and whether CLI JSON/schema contracts changed.
5. Link the issue with `Closes #...` when the PR fully resolves it.
