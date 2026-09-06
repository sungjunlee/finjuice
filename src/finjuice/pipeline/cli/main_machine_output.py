"""Machine-output and logger helpers for the finjuice CLI root command.

Owns JSON-mode detection, callback-level JSON error command names, and
logger suppression/restore around machine-readable responses. The Typer
app, global callback, and command registration stay in
:mod:`finjuice.pipeline.cli.main`.
"""

from __future__ import annotations

import logging
import sys

import typer

_SUPPRESSED_JSON_LOGGERS = ("finjuice", "duckdb")


def _machine_output_requested(raw_args: list[str] | None = None) -> bool:
    """Return True when the invocation requests machine-readable JSON output."""
    args = raw_args or sys.argv[1:]
    output_json_requested = any(
        (arg in ("--output", "-o") and i + 1 < len(args) and args[i + 1] == "json")
        or arg in ("--output=json", "-o=json")
        for i, arg in enumerate(args)
    )
    return "--json" in args or output_json_requested


def _json_error_command_name(ctx: typer.Context) -> str:
    """Return the best command name for callback-level JSON errors."""
    if ctx.invoked_subcommand:
        return ctx.invoked_subcommand
    if isinstance(ctx.obj, dict):
        raw_args = list(ctx.obj.get("_raw_args", []))
        for arg in raw_args:
            if arg.startswith("-"):
                continue
            return str(arg)
    return "unknown"


def _restore_logger_levels(previous_levels: dict[str, int]) -> None:
    """Restore logger levels captured before machine-output suppression."""
    for logger_name, previous_level in previous_levels.items():
        logging.getLogger(logger_name).setLevel(previous_level)


def _suppress_logs_for_machine_output(ctx: typer.Context, enabled: bool) -> None:
    """Silence logger noise for machine-readable JSON responses."""
    if not enabled:
        return

    previous_levels = {
        logger_name: logging.getLogger(logger_name).level
        for logger_name in _SUPPRESSED_JSON_LOGGERS
    }

    for logger_name in _SUPPRESSED_JSON_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.CRITICAL + 1)

    ctx.call_on_close(lambda: _restore_logger_levels(previous_levels))
