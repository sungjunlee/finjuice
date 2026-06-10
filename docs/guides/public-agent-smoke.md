# Public Agent Smoke Workflow

Use this workflow to verify finjuice as an agent-first runtime without touching
private finance data or the real `~/.finjuice` workspace.

The public sample input is:

```text
tests/fixtures/sample_banksalad.xlsx
```

It is a synthetic Banksalad-shaped XLSX fixture. Do not use a real export in
public bug reports, CI logs, or screenshots.

## One Command

From a repository checkout:

```bash
uv run python scripts/smoke_agent_workflow.py
```

The script creates an isolated temp `HOME`, XDG config/cache/data roots, and a
temp `--data-dir`, then runs the workflow below. It sets
`FINJUICE_RUNTIME_UPDATE_CHECK=0` so the smoke never needs a remote update check.

Keep the temp workspace for debugging:

```bash
uv run python scripts/smoke_agent_workflow.py --keep-temp
```

## Manual Commands

Use a temp directory so the smoke cannot mutate real user data:

```bash
SMOKE_ROOT="$(mktemp -d)"
export HOME="$SMOKE_ROOT/home"
export XDG_CONFIG_HOME="$SMOKE_ROOT/xdg-config"
export XDG_CACHE_HOME="$SMOKE_ROOT/xdg-cache"
export XDG_DATA_HOME="$SMOKE_ROOT/xdg-data"
export FINJUICE_RUNTIME_UPDATE_CHECK=0
DATA_DIR="$SMOKE_ROOT/data"
SAMPLE_XLSX="tests/fixtures/sample_banksalad.xlsx"
```

If you are validating an installed skill/runtime pair instead of the checkout
script, run the shared runtime preflight first:

```bash
skills/finjuice/scripts/ensure_finjuice_cli.sh --json \
  --require-version 0.6.2 \
  --require-command "index" \
  --require-command "checkup" \
  --require-command "status" \
  --require-command "template" \
  --require-command "export"
```

The checkout smoke command uses `uv run finjuice ...` directly so it can verify
the current source tree without installing into the user's global tool runtime.

Initialize an agent-ready workspace:

```bash
uv run finjuice --data-dir "$DATA_DIR" init --no-git --with-agents
```

Import the public sample:

```bash
uv run finjuice --data-dir "$DATA_DIR" import --file "$SAMPLE_XLSX" --json
```

Run the agent discovery and health checks:

```bash
uv run finjuice --data-dir "$DATA_DIR" status --json
uv run finjuice --data-dir "$DATA_DIR" index --json --privacy compact
uv run finjuice --data-dir "$DATA_DIR" checkup --json --privacy compact
```

Run a review-style read path and a report artifact path:

```bash
uv run finjuice --data-dir "$DATA_DIR" template run monthly_spend --json
uv run finjuice --data-dir "$DATA_DIR" export --format md --json
```

Clean up when done:

```bash
rm -rf "$SMOKE_ROOT"
```

## Expected Result

- `import --json` reports one processed sample file and inserted synthetic rows.
- `status --json`, `index --json --privacy compact`, and
  `checkup --json --privacy compact` return JSON objects.
- `template run monthly_spend --json` returns a review-ready JSON payload.
- `export --format md --json` writes only under the temp data directory.
