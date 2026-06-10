"""Status command stable entrypoint and thin Typer wrapper."""

from __future__ import annotations

import os
from pathlib import Path

import typer

from finjuice.pipeline.cli.output import emit_error
from finjuice.pipeline.cli.report_filters import no_filter_requested
from finjuice.pipeline.config import Config

from .compute import (
    StatusCommandError,
    StatusFacts,
    StatusOptions,
    collect_status_facts,
)
from .detector import StatusDiagnoses, diagnose_status
from .rendering import (
    StatusRenderContext,
    StatusResult,
    build_status_result,
    emit_status_result,
    render_status,
)

__all__ = [
    "StatusCommandError",
    "StatusDiagnoses",
    "StatusFacts",
    "StatusOptions",
    "StatusRenderContext",
    "StatusResult",
    "_build_status_options",
    "_compute_status",
    "_emit_status_result",
    "_get_data_dir_source",
    "_render_status",
    "build_status_result",
    "collect_status_facts",
    "diagnose_status",
    "emit_status_result",
    "render_status",
    "status",
]


def _get_data_dir_source(data_dir: Path, ctx: typer.Context) -> str:
    """
    Determine the source of the data directory setting.

    Returns a user-friendly description of how the data directory was determined:
    - "CLI flag": --data-dir was explicitly specified
    - "env: FINJUICE_DATA_DIR": Environment variable was used
    - "config file": Using config file (~/.finjuice/config.toml)
    - "default: ~/.finjuice": Using the default finjuice data directory
    """
    parent_ctx = ctx.parent
    if parent_ctx and parent_ctx.params.get("data_dir") is not None:
        return "CLI flag"

    if os.getenv("FINJUICE_DATA_DIR"):
        return "env: FINJUICE_DATA_DIR"

    try:
        from finjuice.pipeline.config_file import config_exists, get_config_path, load_config

        if config_exists():
            user_config = load_config()
            if user_config and user_config.data and user_config.data.directory:
                config_path = get_config_path()
                return f"config file ({config_path.name})"
    except (ImportError, OSError, AttributeError):
        pass

    return "default: ~/.finjuice"


def _build_status_options(
    ctx: typer.Context,
    *,
    detailed: bool,
    top_n: int,
) -> StatusOptions:
    """Translate Typer context and flags into the status use-case options."""
    config: Config = ctx.obj["config"]
    return StatusOptions(
        config=config,
        data_dir_source=_get_data_dir_source(config.data_dir, ctx),
        detailed=detailed,
        top_n=top_n,
        no_filter=no_filter_requested(ctx),
        report_filters=None,
    )


def _compute_status(options: StatusOptions) -> StatusResult:
    """Compute status data through collect, detect, and payload assembly stages."""
    facts = collect_status_facts(options)
    diagnoses = diagnose_status(facts)
    return build_status_result(facts, diagnoses)


def _render_status(status_result: StatusResult) -> None:
    render_status(status_result)


def _emit_status_result(result: StatusResult, *, json_output: bool) -> None:
    emit_status_result(result, json_output=json_output)


def status(
    ctx: typer.Context,
    detailed: bool = typer.Option(
        False,
        "--detailed",
        "-d",
        help="상세 통계 포함 (태그별/가맹점별 지출)",
    ),
    top_n: int = typer.Option(
        5,
        "--top",
        "-n",
        help="상세 통계에서 보여줄 상위 항목 수",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Show current data status.

    Displays overview of:
    - Transaction count and date range
    - Last import information
    - Untagged transactions needing review
    - Rules file status

    With --detailed flag, also shows:
    - Monthly average income and expense
    - Residual cashflow and consumption-oriented savings rates
    - Structural savings sources inferred from tags or goals.yaml
    - Top spending categories

    Examples:
        finjuice status             # 기본 상태
        finjuice status --detailed  # 상세 통계 포함
        finjuice status -d -n 10    # 상위 10개 항목
    """
    options = _build_status_options(ctx, detailed=detailed, top_n=top_n)
    try:
        result = _compute_status(options)
    except StatusCommandError as exc:
        emit_error(
            exc.message,
            error_code=exc.error_code,
            exit_code=exc.exit_code,
            suggestion=exc.suggestion,
            json_output=json_output,
            command="status",
        )
        raise  # defensive: emit_error is NoReturn, but guard against future regressions

    _emit_status_result(result, json_output=json_output)
