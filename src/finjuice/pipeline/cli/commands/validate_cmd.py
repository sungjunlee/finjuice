"""Validate command for finjuice CLI.

Checks CSV partition integrity against the schema registry.
"""

import json
import logging
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.storage.schema_registry import validate_column_names

logger = logging.getLogger(__name__)


def _validate_partition(csv_path: Path, *, fix: bool) -> dict[str, Any]:
    """Validate a single partition file, returning the result dict."""
    try:
        result = validate_column_names(csv_path)
        result["path"] = str(csv_path)
        if fix and not result["valid"]:
            _try_fix_partition(csv_path, result)
        return result
    except Exception as e:
        return {
            "path": str(csv_path),
            "valid": False,
            "errors": [f"Unexpected error: {e}"],
            "detected_version": None,
            "compatibility_state": "unsupported",
        }


def _try_fix_partition(csv_path: Path, result: dict[str, Any]) -> None:
    """Attempt basic fix for corrupted partition files."""
    if not result.get("errors"):
        return
    logger.info("Attempting fix for: %s", csv_path.name)
    fixed_count = 0
    try:
        lines = csv_path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return
        header = lines[0]
        expected_count = len(header.split(","))
        good_lines = [header]
        for line in lines[1:]:
            if line.count(",") + 1 == expected_count:
                good_lines.append(line)
            else:
                fixed_count += 1
        if fixed_count > 0:
            csv_path.write_text("\n".join(good_lines) + "\n", encoding="utf-8")
            result["fix_applied"] = f"Removed {fixed_count} malformed row(s)"
            logger.info("Fixed %s: removed %d malformed row(s)", csv_path.name, fixed_count)
    except OSError as e:
        result["fix_applied"] = f"Fix failed: {e}"
        logger.warning("Could not fix %s: %s", csv_path.name, e)


def validate_partitions_command(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Automatically fix malformed rows"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> dict[str, Any]:
    """Validate CSV partition files against the schema.

    Scans all transaction CSV partitions and checks column names,
    schema version compatibility, and structural integrity.
    """
    config = get_config(ctx)
    transactions_dir = config.csv_base_dir

    if not transactions_dir.exists():
        result = {
            "valid": False,
            "error": f"Transactions directory not found: {transactions_dir}",
            "partitions_checked": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "results": [],
        }
        if json_output:
            typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            typer.echo(f"❌ Transactions directory not found: {transactions_dir}")
        return result

    csv_files = sorted(transactions_dir.rglob("transactions.csv"))

    if not csv_files:
        result = {
            "valid": True,
            "partitions_checked": 0,
            "valid_count": 0,
            "invalid_count": 0,
            "results": [],
        }
        if json_output:
            typer.echo(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            typer.echo("No transaction CSV files found.")
        return result

    results: list[dict[str, Any]] = []
    valid_count = 0
    invalid_count = 0

    for csv_path in csv_files:
        r = _validate_partition(csv_path, fix=fix)
        results.append(r)
        if r["valid"]:
            valid_count += 1
        else:
            invalid_count += 1

    all_valid = invalid_count == 0

    summary = {
        "valid": all_valid,
        "partitions_checked": len(csv_files),
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "results": results,
    }

    if json_output:
        typer.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        typer.echo("\n📋 Partition Validation Report")
        typer.echo(f"{'─' * 40}")
        typer.echo(f"Partitions checked: {len(csv_files)}")
        typer.echo(f"Valid: {valid_count}")
        typer.echo(f"Invalid: {invalid_count}")
        if fix:
            for r in results:
                fix_msg = r.get("fix_applied")
                if fix_msg:
                    typer.echo(f"  🔧 {Path(r['path']).name}: {fix_msg}")
        if not all_valid:
            typer.echo("\n❌ Issues found:")
            for r in results:
                if not r["valid"]:
                    path_rel = Path(r["path"]).relative_to(transactions_dir.parent)
                    errors = "; ".join(r.get("errors", []))
                    typer.echo(f"  • {path_rel}: {errors}")
        status = "✅ All partitions valid" if all_valid else "❌ Some partitions have issues"
        typer.echo(f"\n{status}")

    return summary
