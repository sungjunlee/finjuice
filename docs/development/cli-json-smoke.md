# Installed CLI JSON Smoke

`scripts/smoke_installed_cli_json.py` validates a small set of public CLI JSON
surfaces after installing the built wheel into a fresh stdlib `venv`.

This complements the broader package artifact checks documented in
[`release-artifacts.md`](release-artifacts.md).

## Command Matrix

The matrix is intentionally small so it can run in the default package CI job.
Commands use a synthetic local data directory and analytics fixture where needed.

| Matrix name | Installed command | Schema | Why |
| --- | --- | --- | --- |
| `status` | `finjuice --data-dir <synthetic> status --json` | `schemas/status.schema.json` | Primary machine-readable health/status envelope. |
| `doctor` | `finjuice --data-dir <synthetic> doctor --json` | `schemas/doctor.schema.json` | Installed runtime and dependency diagnostics. |
| `manifest` | `finjuice manifest --json` | `schemas/manifest.schema.json` | Self-describing CLI command/API discovery. |
| `rules-list` | `finjuice --data-dir <synthetic> rules list --json` | `schemas/rules_list.schema.json` | Read-only tagging rule registry surface. |
| `query` | `finjuice --data-dir <synthetic> query "SELECT date, merchant_raw, amount FROM transactions LIMIT 1" --json` | `schemas/query.schema.json` | Arbitrary read-only SQL analysis surface with pagination metadata. |
| `explain` | `finjuice --data-dir <synthetic> explain "Smoke Merchant" --json` | `schemas/explain.schema.json` | Transaction classification trace surface over synthetic local data. |
| `networth-forecast` | `finjuice --data-dir <synthetic> networth forecast --from 2024-10-01 --years 1 --json` | `schemas/networth_forecast.schema.json` | Forward-looking net worth analysis surface with deterministic assumptions. |
| `checkup-compact` | `finjuice --data-dir <synthetic> checkup --json --privacy compact` | `schemas/checkup.schema.json` | Privacy-profiled sensitive summary surface. |

## Failure Categories

The smoke emits categorized failures with the wheel artifact, command, detail,
and full captured stderr.

| Category | Meaning |
| --- | --- |
| `[install-failed]` | The wheel could not be built, checked, installed, or prepared in the stdlib smoke `venv`. |
| `[command-failed]` | The installed CLI exited non-zero or emitted no stdout. |
| `[json-malformed]` | The command exited successfully, but stdout was not valid JSON. |
| `[schema-drift]` | The command JSON did not validate against its schema, or the schema could not be loaded/compiled. |

## Local Usage

Run the full matrix:

```bash
uv run python scripts/smoke_installed_cli_json.py
```

Run a focused subset:

```bash
uv run python scripts/smoke_installed_cli_json.py --commands status,query
```

Keep temporary build, venv, and synthetic data directories after a failure:

```bash
uv run python scripts/smoke_installed_cli_json.py --keep-temp
```

## Adding A Command

1. Choose a read-only command that exits 0 with synthetic empty/template data.
2. Confirm it emits JSON from the installed console script with `--json` or the
   command's JSON-equivalent option.
3. Add a `JsonCommand` entry to `COMMANDS` in
   `scripts/smoke_installed_cli_json.py`.
4. Map it to the existing `schemas/<name>.schema.json` file. Add or regenerate
   schema artifacts separately if a schema does not already exist.
5. If the command exposes sensitive data and has a privacy option, prefer a
   compact or redacted profile.
6. Update the table above and run:

```bash
uv run python scripts/smoke_installed_cli_json.py --commands <matrix-name>
uv run pytest -q tests/scripts/test_smoke_installed_cli_json.py
```
