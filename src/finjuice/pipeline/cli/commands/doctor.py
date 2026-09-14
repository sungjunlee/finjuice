"""Doctor command: thin Typer wrapper around pipeline doctor checks."""

from __future__ import annotations

import inspect

import typer

from finjuice.pipeline.cli.commands.doctor_rendering import _render_doctor_result
from finjuice.pipeline.cli.output import emit
from finjuice.pipeline.cli.utils import get_activation_evidence_provider
from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor import _build_doctor_result
from finjuice.pipeline.doctor import checks as doctor_checks
from finjuice.pipeline.doctor import skill_runtime as doctor_skill_runtime
from finjuice.pipeline.doctor.repository import collect_repository_doctor


def _probe_cli_capabilities() -> dict[str, bool]:
    """Inspect CLI command signatures without leaking that import into core."""
    try:
        from finjuice.pipeline.cli.commands.tag import tag_command

        return {"tag.edit": "edit" in inspect.signature(tag_command).parameters}
    except (ImportError, AttributeError):
        return {"tag.edit": False}


def doctor(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Diagnose environment and identify issues.

    Performs comprehensive checks on:
    - System (Python version, finjuice version, OS)
    - Data directory (observed access; legacy structure before activation)
    - Configuration (selected repository rules after activation, environment variables)
    - Data (transactions, imports, processing status)
    - Dependencies (required and optional packages)

    Canonical checks identify their dataset revision. Environment and staged-file
    checks are separate observations. Diagnostic failures appear in the summary.
    """
    config: Config = ctx.obj["config"]
    doctor_checks._probe_cli_capabilities = _probe_cli_capabilities
    doctor_skill_runtime._probe_cli_capabilities = _probe_cli_capabilities
    repository = collect_repository_doctor(config, get_activation_evidence_provider(ctx))
    result = (
        _build_doctor_result(config)
        if repository is None
        else _build_doctor_result(config, repository=repository)
    )
    emit(
        result.payload,
        json_output,
        lambda _: _render_doctor_result(result),
        command="doctor",
        meta_extras=result.metadata,
    )


def register_doctor_command(app: typer.Typer) -> None:
    """Register the doctor command with the main app."""
    app.command(name="doctor", rich_help_panel="Admin")(doctor)
