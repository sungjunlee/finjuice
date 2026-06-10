# Migration Notes

This document tracks externally visible CLI and documentation migrations introduced by the Agentic Pilot.

## 2026-02 Pilot Changes

### Command Example Corrections

- Legacy examples that passed the unsupported full-tag option to `finjuice tag`
  were corrected to plain `finjuice tag`.

Reason:
- `--full` is not a supported option in current CLI.
- Re-running `finjuice tag` applies rules again to transaction data.

### New Template Command Group

Added commands:

- `finjuice template list`
- `finjuice template show <name>`
- `finjuice template run <name> --param key=value --output table|csv|json|markdown|xlsx`

Compatibility note:
- Existing `finjuice query "<SQL>"` remains supported and unchanged.

### Agent Asset Maintenance Policy

Authoritative files:
- `src/finjuice/templates/AGENTS.md`
- `skills/finjuice/SKILL.md`

Generated files (do not edit manually):
- `templates/AGENTS.md`

Sync command for AGENTS.md:

```bash
python scripts/sync_agent_assets.py
```
