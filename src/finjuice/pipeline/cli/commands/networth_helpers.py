"""assets.yaml init/validate helpers for ``finjuice networth``.

Owns starter template creation, validation payload assembly, and the
shared assets-file JSON envelope. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.networth`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.asset_config import (
    AssetsConfigValidationResult,
    validate_assets_config_file,
)
from finjuice.pipeline.cli.commands.networth_errors import _validation_issue_to_problem
from finjuice.pipeline.cli.commands.networth_rendering import _render_validate
from finjuice.pipeline.cli.output import (
    ErrorCode,
    _build_meta,
    emit_error,
    info,
    success,
)
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)


def _emit_assets_file_json(payload: dict[str, Any], *, command: str) -> None:
    """Emit an assets.yaml command payload with the shared ``_meta`` envelope."""
    typer.echo(
        json.dumps(
            {"_meta": _build_meta(command), **payload},
            ensure_ascii=False,
            indent=2,
        )
    )


def _assets_init_payload(dest_path: Path, *, created: bool) -> dict[str, Any]:
    """Build the stable ``networth init`` JSON payload."""
    if created:
        message = f"Created starter assets.yaml at {dest_path}"
    else:
        message = f"assets.yaml already exists at {dest_path}"
    return {
        "path": str(dest_path),
        "created": created,
        "message": message,
    }


def _write_starter_assets_yaml(dest_path: Path) -> None:
    """Copy the bundled assets.yaml example into the data directory."""
    template_files = importlib.resources.files("finjuice.templates")
    template = template_files.joinpath("assets.yaml.example").read_text(encoding="utf-8")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_text(template, encoding="utf-8")


def _build_validate_payload(
    assets_file: Path,
    validation: AssetsConfigValidationResult,
) -> dict[str, Any]:
    """Build the stable ``networth validate`` JSON payload."""
    problems = [_validation_issue_to_problem(issue) for issue in validation.issues]
    return {
        "path": str(assets_file),
        "exists": validation.exists,
        "valid": validation.is_valid,
        "status": "valid" if validation.is_valid else "issues",
        "version": validation.config.version if validation.exists and validation.is_valid else None,
        "manual_assets": len(validation.config.manual_assets) if validation.is_valid else 0,
        "liabilities": len(validation.config.liabilities) if validation.is_valid else 0,
        "errors": len(problems),
        "warnings": 0,
        "problems": problems,
    }


def _run_init_command(ctx: typer.Context, *, json_output: bool) -> None:
    """Create a starter assets.yaml from the built-in template."""
    config = get_config(ctx)
    dest_path = config.assets_file

    if dest_path.exists():
        payload = _assets_init_payload(dest_path, created=False)
        if json_output:
            _emit_assets_file_json(payload, command="networth init")
        else:
            info(f"assets.yaml already exists at {dest_path}")
            info("Run 'finjuice networth validate' to check, or 'finjuice networth' to view.")
        return

    try:
        _write_starter_assets_yaml(dest_path)
    except Exception as exc:
        logger.error("Failed to create assets.yaml: %s", exc, exc_info=True)
        emit_error(
            f"Failed to create assets.yaml: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            json_output=json_output,
            command="networth init",
        )

    payload = _assets_init_payload(dest_path, created=True)
    if json_output:
        _emit_assets_file_json(payload, command="networth init")
    else:
        success(f"Created {dest_path}")
        info("Edit the values and run 'finjuice networth validate' to verify.")
        info("Then run 'finjuice networth' to see your position.")


def _run_validate_command(ctx: typer.Context, *, json_output: bool) -> None:
    """Validate assets.yaml and report line-numbered errors."""
    config = get_config(ctx)
    validation = validate_assets_config_file(config.assets_file, allow_missing_file=True)
    payload = _build_validate_payload(config.assets_file, validation)

    if json_output:
        _emit_assets_file_json(payload, command="networth validate")
    else:
        _render_validate(payload)

    if not validation.is_valid:
        raise typer.Exit(code=1)
