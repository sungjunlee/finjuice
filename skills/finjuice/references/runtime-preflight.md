# Runtime Preflight

Shared runtime preflight for every `finjuice*` skill. Use this before any
`finjuice ...` command, then append the skill-local `--require-*` declarations
from that skill's `## Runtime Preflight` section.

## Resolve Helper

Run this resolver from the current workspace or skill directory:

```bash
FINJUICE_ENSURE=""
for candidate in \
  "skills/finjuice/scripts/ensure_finjuice_cli.sh" \
  "$HOME/.codex/skills/finjuice/scripts/ensure_finjuice_cli.sh" \
  "$HOME/.claude/skills/finjuice/scripts/ensure_finjuice_cli.sh" \
  ".claude/skills/finjuice/scripts/ensure_finjuice_cli.sh" \
  "scripts/ensure_finjuice_cli.sh"; do
  if [ -x "$candidate" ]; then
    FINJUICE_ENSURE="$candidate"
    break
  fi
done
if [ -z "$FINJUICE_ENSURE" ]; then
  printf 'finjuice runtime ensure helper not found\n' >&2
  exit 127
fi
```

The resolver works from a repo checkout, Codex global skills, Claude Code global
skills, Claude Code project skills, or the `skills/finjuice/` skill directory.

## Invoke Helper

Each skill owns its local version, command, flag, and capability gates. After
resolving `FINJUICE_ENSURE`, run the command shown in that skill's
`## Runtime Preflight` section. It must start with:

```bash
"$FINJUICE_ENSURE" --json \
  --require-version 0.7.1
```

and then include the skill-specific `--require-command`, `--require-flag`, and
`--require-capability` declarations from the local skill file.

If the JSON response has `status: "blocked"`, stop and report its `message`; do
not install `uv`, do not continue to `finjuice ...` commands, and do not
recommend or run a command whose preflight failed.

## Runtime Update Policy

Default preflight is availability-first. It reports an existing `finjuice`
runtime and only installs when `finjuice` is missing and `uv` is available. With
an existing runtime, it may check GitHub tag metadata once per 24-hour TTL
window and cache state in `~/.finjuice/agent-runtime-state.json`. A remote
metadata failure is non-blocking and must continue with the local runtime.

If JSON includes `update_available: true`, tell the user that the newer
`remote_version` exists, but do not update during normal skill runs. Update an
existing runtime only when the user explicitly requests it, by running:

```bash
skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json
```

or by setting `FINJUICE_AUTO_UPDATE=1`. Explicit updates use
`uv tool install --force git+https://github.com/sungjunlee/finjuice` and report
`update_requested: true` in JSON.

To suppress repeated update suggestions temporarily, run:

```bash
skills/finjuice/scripts/ensure_finjuice_cli.sh --snooze-update-check DAYS --json
```

`DAYS` is capped at 30. To skip the remote update check for the current run
only, set `FINJUICE_RUNTIME_UPDATE_CHECK=0`.
