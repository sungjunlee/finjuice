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
    ExitCode,
    _build_meta,
    emit_error,
    info,
    success,
)
from finjuice.pipeline.cli.utils import get_activation_evidence_provider, get_config
from finjuice.pipeline.config import Config
from finjuice.pipeline.networth_initialization_repository import initialize_repository_assets
from finjuice.pipeline.networth_validation_repository import (
    NetworthValidationReadError,
    compute_repository_networth_validate,
)
from finjuice.pipeline.storage.authority import legacy_write_lease
from finjuice.pipeline.storage.sqlite.errors import AuthorityError

logger = logging.getLogger(__name__)


def _emit_assets_file_json(
    payload: dict[str, Any], *, command: str, metadata: dict[str, object] | None = None
) -> None:
    """Emit an assets.yaml command payload with the shared ``_meta`` envelope."""
    typer.echo(
        json.dumps(
            {"_meta": _build_meta(command, extras=metadata), **payload},
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


def _ensure_starter_assets_yaml(config: Config) -> bool:
    """Create the starter file under the legacy fence and report whether it was new."""
    with legacy_write_lease(config.data_dir):
        if config.assets_file.exists():
            return False
        _write_starter_assets_yaml(config.assets_file)
        return True


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
    """Initialize the selected authority without overwriting existing settings."""
    config = get_config(ctx)
    dest_path = config.assets_file
    try:
        repository = initialize_repository_assets(
            config.data_dir, get_activation_evidence_provider(ctx)
        )
    except Exception:
        emit_error(
            "Canonical assets initialization could not be completed.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="networth init",
        )
        raise AssertionError("emit_error must exit")
    if repository is not None:
        metadata = repository.pop("_repository_meta")
        if json_output:
            _emit_assets_file_json(repository, command="networth init", metadata=metadata)
        else:
            info(f"Canonical assets · revision {metadata['dataset_revision']}")
            info(repository["message"])
            info("Run 'finjuice networth validate' to inspect the canonical configuration.")
        return

    try:
        created = _ensure_starter_assets_yaml(config)
    except AuthorityError as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="networth init",
        )
    except Exception as exc:
        logger.error("Failed to create assets.yaml: %s", exc, exc_info=True)
        emit_error(
            f"Failed to create assets.yaml: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            json_output=json_output,
            command="networth init",
        )

    if not created:
        payload = _assets_init_payload(dest_path, created=False)
        if json_output:
            _emit_assets_file_json(payload, command="networth init")
        else:
            info(f"assets.yaml already exists at {dest_path}")
            info("Run 'finjuice networth validate' to check, or 'finjuice networth' to view.")
        return

    payload = _assets_init_payload(dest_path, created=True)
    if json_output:
        _emit_assets_file_json(payload, command="networth init")
    else:
        success(f"Created {dest_path}")
        info("Edit the values and run 'finjuice networth validate' to verify.")
        info("Then run 'finjuice networth' to see your position.")


def _run_validate_command(ctx: typer.Context, *, json_output: bool) -> None:
    """Validate the selected authority and preserve legacy file diagnostics."""
    config = get_config(ctx)
    try:
        repository = compute_repository_networth_validate(
            config.data_dir, get_activation_evidence_provider(ctx)
        )
    except NetworthValidationReadError:
        emit_error(
            "Canonical assets validation could not be read.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="networth validate",
        )
    validation = (
        repository.validation
        if repository is not None
        else validate_assets_config_file(config.assets_file, allow_missing_file=True)
    )
    payload = _build_validate_payload(config.assets_file, validation)
    metadata = None
    if repository is not None:
        payload.update(
            path=None,
            authority="repository",
            selection_state=repository.selection_state,
            revision_id=repository.revision_id,
        )
        metadata = repository.metadata

    if json_output:
        _emit_assets_file_json(payload, command="networth validate", metadata=metadata)
    else:
        if metadata is not None:
            info(
                f"Repository revision {metadata['dataset_revision']} "
                f"({metadata['dataset_generation']}); policy canonical_assets_validation.v1; "
                f"assets {metadata['assets_selection_state']}"
            )
        _render_validate(payload)

    if not validation.is_valid:
        raise typer.Exit(code=1)
