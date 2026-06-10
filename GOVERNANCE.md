# Governance

finjuice is currently a solo-maintainer, developer-preview project.

## Decision Making

- The maintainer makes final decisions on scope, releases, and public contract
  changes.
- CLI JSON schemas, storage schemas, privacy boundaries, and security-sensitive
  behavior require explicit review before merging.
- Architecture decisions that affect the agent/runtime contract should be
  recorded under `docs/architecture/decisions/`.

## Public Preview Priorities

1. Protect private financial data.
2. Keep CLI JSON behavior stable for AI-agent skills.
3. Prefer small, reversible changes with focused tests.
4. Avoid hosted, server, MCP, or vector-search complexity until the documented
   triggers for those surfaces are met.

## Maintainer Actions

Maintainers may close issues that require raw private data to proceed, move
open-ended usage questions to discussions, request synthetic reproductions, and
decline changes that expand public support burden without improving the
agent-first workflow.
