# CLAUDE.md

@AGENTS.md

## Claude Code Notes

- This file intentionally imports only `AGENTS.md`.
- Do not add import links for large generated docs such as
  `docs/reference/cli.md`, `docs/reference/json-schemas.md`, or
  `templates/schema.yaml`.
- Use ordinary Markdown links or plain paths for files that should be read only
  when a task needs them.
- Put reusable multi-step procedures in `.claude/skills/` or path-scoped
  `.claude/rules/` files instead of growing startup memory.
- When compacting context, preserve modified file paths, verification commands,
  unresolved failures, and user decisions.

## Privacy Guardrails

- Treat every transaction, asset, export, report, and XLSX/ZIP import as private
  financial data.
- Do not create or move real user data under this program repository. Use
  `~/.finjuice` or an explicit private data directory outside the repo.
- Before committing, check that `data/`, `imports/`, `exports/`, `transactions/`,
  `*.xlsx`, `*.csv`, `*.db`, `.env`, and local agent state files are not being
  added unless they are intentional synthetic fixtures.
