# AI CLI Integration Setup Guide

**Status**: Structured Data API
**Last Updated**: 2026-05-05

---

## Overview

`finjuice` does **not** call Claude, OpenAI, or any other LLM provider directly.
Per ADR-0007, the CLI emits structured local data, and external agents decide how
to compose prompts and which model to call.

### Core Pattern

```text
agent CLI -> finjuice context --json -> compose prompt -> call the agent's own LLM
```

### What `finjuice context` emits

- Recent journals (newest first)
- Current status snapshot
- Active goals from `goals.yaml` when present
- Top 30-day spending movers
- Token estimate metadata for prompt-budget control

### Savings fields in status snapshots

`savings_rate_3mo` is kept for compatibility and still means the legacy residual
cashflow formula: recent income minus all non-transfer expenses, divided by
recent income. Detailed status JSON also emits `residual_savings_rate_3mo` with
the same value, plus consumption-oriented fields that subtract tag-inferred
structural savings from expenses before calculating the rate.

Structural savings sources come from two places:

- confirmed `goals.yaml` `recurring_savings` entries
- non-transfer expense rows tagged with the built-in aliases `정기저축`, `IRP`,
  `연금`, or `투자입금`

Tags listed on `recurring_savings` entries also act as explicit aliases for
inference. A broader configurable alias surface can be added later if needed.

---

## Prerequisites

You need two separate pieces:

1. Installed finjuice skills for your agent
2. `finjuice` installed locally with access to your data directory
3. An external AI agent CLI such as:
   - Claude Code
   - OpenAI Codex CLI
   - Cursor agent flows
   - Any custom script that can read JSON and call an LLM

`finjuice` itself does not require AI API keys for this feature.

---

## Recommended Skill Install

Install the finjuice skills first so the agent knows how to call the local runtime safely.
`npx` requires Node.js/npm.

```bash
npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'
```

Then let the skill runtime preflight check the local CLI before it calls `finjuice`.
For manual recovery or debugging, the preflight uses this persistent runtime install command
only when `finjuice` is missing. The helper may live under a repo checkout
(`skills/finjuice/scripts/ensure_finjuice_cli.sh`), Codex global skills
(`~/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh`), or Claude Code global skills
(`~/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh`). When `finjuice` already
exists, it checks GitHub tag metadata at most once per 24-hour TTL window and stores
lightweight state in `~/.finjuice/agent-runtime-state.json`. Network failures or
malformed remote metadata are non-blocking while the local CLI works. Newer versions are
reported through `update_available` and `remote_version`, but the helper does not update
unless the user explicitly requests `--update` or sets `FINJUICE_AUTO_UPDATE=1`. Use
`--snooze-update-check DAYS` to suppress repeated suggestions for up to 30 days, or
`FINJUICE_RUNTIME_UPDATE_CHECK=0` to skip the check for the current run.

```bash
uv tool install git+https://github.com/sungjunlee/finjuice

# repo checkout
skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json
skills/finjuice/scripts/ensure_finjuice_cli.sh --snooze-update-check 7 --json

# Codex global skill
~/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json
~/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh --snooze-update-check 7 --json

# Claude Code global skill
~/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json
~/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh --snooze-update-check 7 --json

finjuice doctor --json
```

Use `uvx` only for one-shot/fallback execution; it is not the default setup path.

---

## Context Injection

### Basic JSON export

```bash
finjuice context --json
```

This prints a structured JSON envelope that agents can inject into prompts or
tool memory.

### Control journal count

```bash
finjuice context --json --journal 5
```

This keeps the newest-first ordering from `finjuice journal list` and clamps the
number of entries included.

### Control prompt budget

```bash
finjuice context --json --budget 4000
```

Budget resolution:

1. `--budget` flag
2. `FINJUICE_CONTEXT_BUDGET`
3. default `5000`

Example:

```bash
export FINJUICE_CONTEXT_BUDGET=3500
finjuice context --json
finjuice context --json --budget 2000
```

### Plain-text mode

```bash
finjuice context
```

Default output is a readable text summary for quick inspection. It stays plain when
stdout is piped, so commands like `finjuice context | cat` remain ANSI-clean.

### Token breakdown on stderr

```bash
finjuice context --json --verbose > /tmp/context.json
```

`--verbose` writes the section token breakdown to stderr so stdout stays usable for
pipes and JSON capture.

---

## Example Agent Workflow

### Claude Code / Codex style

```bash
CONTEXT_JSON="$(finjuice context --json)"
```

Then the agent prompt can include:

```text
Use the following finjuice context JSON as local structured context.
Do not assume the CLI has already called any model.
```

Append the JSON payload, then ask the model for analysis or planning.

### Shell pipeline pattern

```bash
finjuice context --json > /tmp/finjuice-context.json
python scripts/build_prompt.py /tmp/finjuice-context.json > /tmp/prompt.txt
# agent-specific model invocation happens after this step
```

### Combine with other finjuice data APIs

Typical follow-up commands for deeper context:

```bash
finjuice status --json --detailed
finjuice show --json --month 2026-04
finjuice template list
```

Use `context` for recency-oriented prompt bootstrapping, then pull narrower views as
needed.

---

## Truncation Behavior

When the estimated token budget is exceeded, `finjuice context` drops sections in
this order:

1. `top_patterns`
2. Oldest journal entries, one by one
3. Lower-priority `status_snapshot` fields
4. `active_goals` are never dropped

The JSON `_meta` block records:

- `total_tokens_est`
- `budget`
- `truncated`
- `dropped_sections`
- per-section token counts

---

## Security & Privacy

### What finjuice does

- Reads local CSV partitions and journal markdown
- Emits JSON or plain text to stdout
- Keeps agent orchestration outside the CLI

### What finjuice does not do

- No subprocess calls to Claude/OpenAI for `context`
- No `httpx`, `requests`, `anthropic`, or `openai` SDK usage
- No background sync or remote storage

### Data sharing boundary

Anything sent to an external model happens **after** `finjuice` prints the context.
You decide whether to:

- send the full JSON
- redact fields first
- trim with `--journal` / `--budget`
- combine with other local summaries

---

## Troubleshooting

### `top_patterns` is empty

Possible causes:

- No transaction data yet
- DuckDB extra not installed
- Not enough recent expense history to compare the two 30-day windows

Check:

```bash
finjuice doctor
finjuice status --json --detailed
```

### `active_goals` is empty

This is expected when `goals.yaml` does not exist yet. The context command treats
that file as optional.

### My pipe picked up extra output

Use:

```bash
finjuice context --json > /tmp/context.json
```

If you also want token diagnostics, add `--verbose`; its output goes to stderr.

---

## See Also

- [CLAUDE.md](../../../CLAUDE.md) - Project guide
- [CLI Reference](../../reference/cli.md) - Full CLI documentation
- [AI Agent Setup](ai-agent-setup.md) - Broader agent workflow guidance

---

**Last Updated**: 2026-05-05
**Status**: Structured Data API
