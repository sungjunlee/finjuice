#!/usr/bin/env python3
"""Generate CLI documentation from finjuice --help.

This script runs the Typer app in-process so documentation generation does not
depend on subprocess environment propagation between uv, Rich, and Click/Typer.
"""

import os
import re
import sys
import traceback
from pathlib import Path
from typing import Any

import yaml

# Pin terminal-related env vars before importing Typer/Rich/finjuice.
os.environ["COLUMNS"] = "120"
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"
os.environ.pop("FORCE_COLOR", None)

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

import typer.rich_utils  # noqa: E402
from rich.console import Console  # noqa: E402
from typer.testing import CliRunner  # noqa: E402

_ANSI = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")
_TERMINAL_ENV = {
    "COLUMNS": "120",
    "NO_COLOR": "1",
    "TERM": "dumb",
}
_TERMINAL_WIDTH = 120


def strip_ansi_codes(text: str) -> str:
    """Remove ANSI escape codes from text."""
    stripped = _ANSI.sub("", text)
    return "\n".join(line.rstrip() for line in stripped.splitlines())


def _configure_help_rendering() -> None:
    """Pin Typer/Rich rendering state for deterministic help output."""
    typer.rich_utils.COLOR_SYSTEM = None
    typer.rich_utils.FORCE_TERMINAL = False
    typer.rich_utils.MAX_WIDTH = _TERMINAL_WIDTH


def _capture(
    runner: CliRunner,
    app: Any,
    args: list[str],
    *,
    label: str,
    main_command: bool = False,
) -> str:
    """Return a markdown block for the given CLI args."""
    result = runner.invoke(
        app,
        args,
        env=_TERMINAL_ENV,
        terminal_width=_TERMINAL_WIDTH,
        color=False,
    )

    if result.exit_code == 0 and result.exception is None:
        return f"```\n{strip_ansi_codes(result.output)}\n```"

    if result.output:
        detail = strip_ansi_codes(result.output)
    elif result.exception is not None:
        detail = "".join(
            traceback.format_exception(
                result.exception.__class__,
                result.exception,
                result.exception.__traceback__,
            )
        ).rstrip()
    else:
        detail = f"Command exited with status {result.exit_code}"

    if main_command:
        return f"⚠️ Error getting main help: {result.exception or detail}\n\n```\n{detail}\n```"

    return f"⚠️ Error getting help for '{label}': {result.exception or detail}\n\n```\n{detail}\n```"


def _markdown_cell(value: Any) -> str:
    """Render a safe single-line markdown table cell."""
    text = str(value).replace("\n", " ").replace("|", "\\|").strip()
    return text or "-"


def _format_template_params(params: Any) -> str:
    """Render template registry params in a compact, deterministic form."""
    if not isinstance(params, dict) or not params:
        return "-"

    rendered: list[str] = []
    for name, spec in params.items():
        if not isinstance(spec, dict):
            rendered.append(str(name))
            continue

        param_type = spec.get("type", "str")
        required = "required" if spec.get("required") else "optional"
        constraints: list[str] = []
        if "default" in spec:
            constraints.append(f"default={spec['default']}")
        if "min" in spec:
            constraints.append(f"min={spec['min']}")
        if "max" in spec:
            constraints.append(f"max={spec['max']}")
        suffix = f" ({', '.join(constraints)})" if constraints else ""
        rendered.append(f"`{name}:{param_type}` {required}{suffix}")

    return "<br>".join(rendered)


def _render_template_registry_reference() -> str:
    """Render registered SQL templates from registry.yaml."""
    registry_path = SRC_DIR / "finjuice" / "templates" / "sql" / "registry.yaml"
    payload = yaml.safe_load(registry_path.read_text(encoding="utf-8")) or {}
    templates = payload.get("templates", {})
    if not isinstance(templates, dict) or not templates:
        return ""

    lines = [
        "### Registered SQL Templates",
        "",
        "| Name | Description | Params |",
        "| --- | --- | --- |",
    ]
    for name, spec in templates.items():
        if not isinstance(spec, dict):
            continue
        description = _markdown_cell(spec.get("description", ""))
        params = _markdown_cell(_format_template_params(spec.get("params")))
        lines.append(f"| `{_markdown_cell(name)}` | {description} | {params} |")

    return "\n".join(lines) + "\n\n"


def generate_cli_docs() -> None:
    """Generate CLI reference documentation from finjuice --help."""
    from finjuice.pipeline.cli import output as cli_output
    from finjuice.pipeline.cli.main import app

    _configure_help_rendering()
    cli_output.console = Console(
        stderr=True,
        no_color=True,
        color_system=None,
        force_terminal=False,
        width=_TERMINAL_WIDTH,
    )

    commands = [
        "refresh",
        "status",
        "automation",
        "checkup",
        "context",
        "import",
        "budget",
        "tag",
        "export",
        "show",
        "review",
        "rules",
        "assets",
        "networth",
        "init",
        "query",
        "template",
    ]
    group_subcommands: dict[str, list[str]] = {
        "automation": ["run"],
        "budget": ["status", "edit", "validate"],
        "rules": ["suggest", "validate", "test"],
        "assets": ["status", "show"],
        "networth": ["breakdown", "history", "forecast", "validate"],
        "template": ["run"],
    }

    output_path = ROOT / "docs/reference/cli.md"
    runner = CliRunner()

    md = """# CLI Reference

> **Auto-generated from** `finjuice --help`
> **Do not edit manually** - Run `just docs-cli` to regenerate

---

## Installation

```bash
# Install package with uv
uv pip install -e .

# Verify installation
finjuice --version
```

---

## Main Command

"""

    md += f"{_capture(runner, app, ['--help'], label='main', main_command=True)}\n\n"
    md += "---\n\n"
    md += (
        "`finjuice assets` shows raw imported snapshot rows; "
        "`finjuice networth` shows the aggregated position view "
        "from snapshots plus `assets.yaml`.\n\n"
    )

    for cmd in commands:
        md += f"## `finjuice {cmd}`\n\n"
        md += f"{_capture(runner, app, [cmd, '--help'], label=cmd)}\n\n"

        for sub in group_subcommands.get(cmd, []):
            md += f"### `finjuice {cmd} {sub}`\n\n"
            md += f"{_capture(runner, app, [cmd, sub, '--help'], label=f'{cmd} {sub}')}\n\n"

        if cmd == "template":
            md += _render_template_registry_reference()

        md += "---\n\n"

    md += """## Quick Start (Status-First CLI)

**For new users** - Start with the default status view, then run direct commands:

```bash
# Show current state and suggested commands
finjuice

# Import an XLSX export (auto-initializes the data directory if needed)
finjuice import

# Process pending imports through the full pipeline
finjuice refresh
```

`finjuice interactive` and `finjuice -i` remain for backward compatibility, but they are deprecated.

---

## Common Workflows

### First-time setup (Advanced manual setup)

**For advanced users** who want a custom data directory instead of the default `~/.finjuice`:

```bash
# Advanced: Initialize with custom location
finjuice --data-dir ~/Documents/my-finance-data init

# Place XLSX files in imports/ directory
cp ~/Downloads/banksalad_export.xlsx ~/Documents/my-finance-data/imports/

# Edit tagging rules
vim ~/Documents/my-finance-data/rules.yaml

# Run full pipeline
finjuice --data-dir ~/Documents/my-finance-data refresh
```

### Regular usage

```bash
# Add new XLSX file
cp ~/Downloads/banksalad_202411.xlsx ~/.finjuice/imports/

# Run full pipeline (ingest + tag + export)
finjuice refresh

# Check generated reports
ls ~/.finjuice/exports/reports/
```

### Re-tagging after rule changes

```bash
# Edit tagging rules
vim ~/.finjuice/rules.yaml

# Re-run tagging only
finjuice tag

# Re-generate exports with new tags
finjuice export
```

### Using custom data directory

```bash
# Option 1: Set environment variable
export FINJUICE_DATA_DIR=~/Documents/my-finance-data
finjuice refresh

# Option 2: Use --data-dir flag
finjuice --data-dir ~/Documents/my-finance-data refresh

# Option 3: Use config file
# ~/.finjuice/config.toml
# [data]
# directory = "~/Documents/my-finance-data"
```

---

## CLI Options Reference

### Global Options

- `--data-dir PATH`: Override the configured data directory
- `--verbose, -v`: Enable verbose logging
- `--interactive, -i`: Deprecated compatibility flag for the legacy interactive menu

### Common Patterns

**Verbose output** (for debugging):
```bash
finjuice --verbose refresh
finjuice --verbose tag
```

**Custom data directory**:
```bash
finjuice --data-dir ~/my-data refresh
```

---

## Output Files

After running `finjuice refresh`, you'll find:

### Master File
- `~/.finjuice/exports/master_YYYYMMDD.xlsx` - All transactions with tags

### Reports (CSV)
- `~/.finjuice/exports/reports/monthly_spend.csv` - Monthly spending totals
- `~/.finjuice/exports/reports/by_tag.csv` - Spending breakdown by tag
- `~/.finjuice/exports/reports/by_account.csv` - Spending by account/card
- `~/.finjuice/exports/reports/transfers.csv` - Internal transfer audit log

### Data Partitions
- `~/.finjuice/transactions/YYYY/MM/transactions.csv` - Monthly CSV partitions (git-tracked)

---

## Troubleshooting

### `finjuice: command not found`

**Solution**: Install the package
```bash
uv pip install -e .
```

### `No XLSX files found in imports/`

**Solution**: Check import directory
```bash
ls ~/.finjuice/imports/
# Add XLSX files if empty
```

---

## `finjuice all` (Deprecated alias for `finjuice refresh`)

Compatibility alias for `finjuice refresh`. Prefer `finjuice refresh` for all new usage.

### `Schema mismatch` errors

**Solution**: Check schema version
```bash
# Verify schema.yaml matches code
cat templates/schema.yaml | grep current_version
```

### Import errors during execution

**Solution**: Install all dependencies
```bash
uv sync --all-extras
```

---

## See Also

- [templates/schema.yaml](../../templates/schema.yaml) - Data schema reference
- [templates/rules.yaml.example](../../templates/rules.yaml.example) - Tagging rules template
- [CLAUDE.md](../../CLAUDE.md) - Project guide
- [Data Repository Setup](../setup/data-repository.md) - User data configuration

**Note**: This file is auto-generated. Do not edit manually. Run `just docs-cli` to regenerate.
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(md, encoding="utf-8")

    print(f"✅ Generated {output_path}")
    print(f"📋 Commands documented: main + {len(commands)} subcommands")


if __name__ == "__main__":
    generate_cli_docs()
