# AI Agent Setup Guide

**Status**: Skill-first setup
**Last Updated**: 2026-05-05

---

## Overview

This guide explains how to integrate AI coding assistants with your finance data repository.
The recommended path is skill-first: install the finjuice skills into your agent, then
install the local `finjuice` CLI runtime that those skills call.

Two layers are supported:

1. **Agent Skills** - Installed via `npx skills` for Claude Code, Codex, and other agents
2. **AGENTS.md** - Data-repository guardrails for agents working inside your finance data directory

### Key Features

- Tagging rule suggestions based on untagged merchants
- Safe transaction data analysis (read-only by default)
- Guided rules.yaml editing workflow
- Integration with finjuice commands

---

## Quick Start

### 1. Install the finjuice skills

`npx` requires Node.js/npm.

```bash
npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'
```

Remove one `-a` flag if you only use one agent.

Update installed skills:

```bash
npx skills update -g
```

List skills available from this repository:

```bash
npx skills add sungjunlee/finjuice --list
```

### 2. Install the finjuice CLI runtime

Skills orchestrate the workflow; the local CLI runtime processes private data and emits JSON.
Each finjuice skill resolves and runs the shared runtime ensure helper before calling
`finjuice`. The helper may live under a repo checkout
(`skills/finjuice/scripts/ensure_finjuice_cli.sh`), Codex global skills
(`~/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh`), or Claude Code global skills
(`~/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh`). If the runtime is missing
and `uv` is available, that helper uses the same install command shown below. Normal
preflight is availability-first: when a local runtime already exists, it checks GitHub
tag metadata at most once per 24-hour TTL window and stores state in
`~/.finjuice/agent-runtime-state.json`. Network failures or malformed remote metadata do
not block skill execution while the local CLI works.
If a newer runtime exists, the helper reports `update_available` and `remote_version`
without updating by default. It updates only when the user explicitly requests
`--update` or sets `FINJUICE_AUTO_UPDATE=1`. To suppress repeated suggestions
temporarily, use `--snooze-update-check DAYS` capped at 30 days; set
`FINJUICE_RUNTIME_UPDATE_CHECK=0` to skip the remote check for the current run.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install git+https://github.com/sungjunlee/finjuice
uv tool update-shell
finjuice doctor --json
```

Update the runtime:

```bash
# repo checkout
skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json

# Codex global skill
~/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json

# Claude Code global skill
~/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json
```

Snooze runtime update suggestions:

```bash
# repo checkout
skills/finjuice/scripts/ensure_finjuice_cli.sh --snooze-update-check 7 --json

# Codex global skill
~/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh --snooze-update-check 7 --json

# Claude Code global skill
~/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh --snooze-update-check 7 --json
```

Homebrew is not the recommended setup path for normal users.

Use `uvx` only as a one-shot/fallback path when you do not want a persistent tool install.

### 3. Add data-repository agent guardrails

For a new data directory:

```bash
finjuice --data-dir ~/my-finance-data init --with-agents
```

For an existing data directory:

```bash
finjuice --data-dir ~/my-finance-data update-agents
```

---

## AGENTS.md (Cross-Platform)

### What is AGENTS.md?

AGENTS.md is an open standard for guiding AI coding agents, developed collaboratively by OpenAI, Google, and others. Over 20,000 GitHub repositories use this format.

### Supported Tools

| Tool | Support Level |
|------|---------------|
| OpenAI Codex | Native (auto-loads) |
| Google Gemini CLI | Native |
| Cursor | Native |
| Devin | Native |
| Claude Code | Via AGENTS.md |

### Location

```
~/my-finance-data/
├── AGENTS.md          # AI agent instructions
├── rules.yaml         # Tagging rules
├── transactions/      # Monthly data
└── ...
```

### Contents

The AGENTS.md template includes:

1. **Commands** - Available finjuice commands
2. **Project Structure** - Directory layout with editable/read-only markers
3. **Tagging Workflow** - Step-by-step guide
4. **rules.yaml Format** - Rule structure reference
5. **Boundaries** - What AI should/shouldn't do

### Updating

```bash
# Update to latest template version
finjuice update-agents

# Backup is automatically created as AGENTS.md.bak
```

---

## Agent Skills

### What is a Skill?

Agent skills are enhanced instruction sets that agents load dynamically based on context.
They support:

- **Activation Triggers** - Automatic invocation based on keywords
- **Tool Restrictions** - Limit available tools for safety
- **Structured Workflows** - Step-by-step guidance

### Installation

```bash
npx skills add sungjunlee/finjuice -g -a codex -a claude-code --skill '*'
```

### Skill Locations

```
~/.claude/skills/      # Claude Code global skills
~/.codex/skills/       # Codex global skills
.claude/skills/        # Claude Code project skills
```

### Activation Triggers

The skill activates when you mention:
- Tagging rules or rule editing
- Untagged/unclassified merchants
- Transaction analysis or patterns
- rules.yaml modification
- finjuice commands

### Tool Restrictions

For safety, the skill only allows:
- `Read` - View files
- `Grep` - Search patterns
- `Glob` - Find files
- `Bash` - Run finjuice commands

Edit and Write tools are disabled, requiring manual approval for rule changes.

### Management Commands

```bash
# List installed skills
npx skills list

# Update global skills
npx skills update -g

# Remove a skill
npx skills remove finjuice --global
```

---

## Usage Examples

### Analyze Untagged Merchants

```
User: 미분류 가맹점 분석해줘

AI: finjuice rules suggest --json 실행해서 분석할게요...
    → 상위 5개 미분류 가맹점과 추천 규칙 패턴 제시
```

### Add Tagging Rule

```
User: 스타벅스 거래를 카페 태그로 분류하는 규칙 추가해줘

AI: rules.yaml에 다음 규칙을 추가할게요:
    - name: cafe_starbucks
      match: "스타벅스|STARBUCKS"
      fields: [merchant_raw]
      tags: ["카페", "커피"]
      priority: 80

    이 규칙을 추가할까요? (diff 먼저 보여드림)
```

### Full Workflow

```
User: 태깅 안 된 거래들 정리해줘

AI: 1. finjuice rules suggest --json 실행
    2. 상위 미분류 가맹점 패턴 분석
    3. rules.yaml 수정안 제시
    4. 승인 후 finjuice tag 실행
    5. finjuice export로 결과 확인
```

---

## Comparison

| Feature | Agent Skills | AGENTS.md |
|---------|--------------|-----------|
| Primary role | Workflow orchestration | Data-repo guardrails |
| Platform | Claude Code, Codex, and other skill-aware agents | Multi-tool project instructions |
| Location | Agent skill directory, usually global | Finance data directory |
| Auto-activation | Yes, based on skill description | No, loaded as background instructions |
| Update method | `npx skills update -g` | `finjuice update-agents` |
| Best for | Natural-language finance workflows | Safe boundaries for local data edits |

### When to Use Which?

- **Agent Skills**: Default path for Claude Code/Codex users.
- **AGENTS.md**: Add this to the finance data directory so any agent sees the same safety boundaries.
- **Both**: Recommended for normal use.

### Repository Maintenance Policy (Single Source)

To prevent drift between duplicated instruction files:

- **Authoritative files** (edit only here):
  - `src/finjuice/templates/AGENTS.md`
  - `skills/finjuice/SKILL.md`
- **Generated files** (do not edit manually):
  - `templates/AGENTS.md`

Run the sync tool after updating AGENTS.md:

```bash
python scripts/sync_agent_assets.py
```

## AGENTS/Skill Drift Checklist (Mandatory after agent instruction changes)

When updating files that affect AI agent behavior:

1. Update authoritative templates only:
   - `src/finjuice/templates/AGENTS.md`
   - `skills/finjuice/SKILL.md`
2. Run sync to refresh generated AGENTS targets:
   - `python scripts/sync_agent_assets.py`
3. Update public-facing docs that reference capabilities/commands:
   - `README.md`
   - `docs/guides/setup/ai-agent-setup.md`
4. Run doc consistency check:
   - `python -m pytest tests/test_doc_consistency.py -q`
5. Add a note to `docs/plans/execution/drift-register.md` only when a mismatch was fixed.

---

## Troubleshooting

### AGENTS.md Not Found

```
⚠️  AGENTS.md not found in data directory.
```

**Solution**: Initialize with agents or copy template:
```bash
finjuice --data-dir ~/my-finance-data init --with-agents
```

### Skill Not Activating

**Symptoms**: The agent does not use finjuice skill instructions.

**Solutions**:
1. Check installation: `npx skills list`
2. Confirm the target agent was selected during install, or reinstall with `--agent claude-code` or `--agent codex`
3. Restart the agent if its skill directory was created after the session started
4. Mention trigger keywords explicitly, such as `finjuice 온보딩 시작해줘`

### Template Not Found Error

```
❌ Template not found: AGENTS.md
```

**Cause**: Running from wrong directory

**Solution**: Run from project root or reinstall finjuice

---

## Security Considerations

### Data Safety

- Transaction CSVs are marked as **READ-ONLY**
- AI tools can only read data, not modify
- Rule changes require explicit approval

### Best Practices

1. Keep data repository **private** on GitHub/GitLab
2. Review AI-suggested rule changes before applying
3. Use agent skills for guided workflows and AGENTS.md for data-repo safety boundaries
4. Don't store API keys in data repository

---

## References

- [AGENTS.md Specification](https://agents.md/)
- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills)
- [Open Agent Skills CLI](https://github.com/vercel-labs/skills)
- [OpenAI Codex AGENTS.md Guide](https://developers.openai.com/codex/guides/agents-md/)
- [finjuice CLI Reference](../reference/cli.md)

---

## Changelog

### v1.1.0 (2026-05-05)

**Changed**:
- Made `npx skills add` the recommended first install step.
- Reframed the CLI as the local runtime used by finjuice skills.
- Added Codex skill install examples alongside Claude Code.

### v1.0.0 (2025-11-29) - Issue #44

**Added**:
- `finjuice init --with-agents` flag
- `finjuice update-agents` command
- Published Claude skill distribution via `npx skills add sungjunlee/finjuice`
- `templates/AGENTS.md` for cross-platform support
- `skills/finjuice/SKILL.md` for Claude Code

**Supported Platforms**:
- OpenAI Codex CLI
- Google Gemini CLI
- Cursor
- Claude Code (via Skill)

---

**Last Updated**: 2026-05-05
**Version**: v1.1.0
**Status**: Skill-first setup
