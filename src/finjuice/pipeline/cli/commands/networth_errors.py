"""Validation and runtime error envelopes for ``finjuice networth``.

Owns assets.yaml issue conversion, goals.yaml validation errors, and
runtime exception mapping. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.networth`, which re-exports the
names used by existing callers.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.asset_config import AssetsConfigValidationError
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.forecast import ScenariosConfigValidationError
from finjuice.pipeline.goals import GoalsValidationProblem


def _validation_issue_to_problem(issue: Any) -> dict[str, Any]:
    """Convert an assets.yaml validation issue to the shared validation envelope."""
    return {
        "severity": "error",
        "type": "invalid_assets_config",
        "path": issue.path,
        "message": issue.message,
        "line": issue.line,
        "column": issue.column,
        "formatted": issue.format(),
    }


def _raise_goals_validation_error(
    *,
    command: str,
    problems: list[GoalsValidationProblem],
    json_output: bool,
) -> None:
    """Raise a structured validation error for goals.yaml issues."""
    message = "goals.yaml is invalid"
    if problems:
        message = message + ":\n" + "\n".join(problem.format() for problem in problems)
    emit_error(
        message,
        error_code=ErrorCode.VALIDATION_FAILED,
        exit_code=ExitCode.VALIDATION_ERROR,
        json_output=json_output,
        command=command,
    )


def _handle_networth_exception(
    exc: Exception,
    *,
    json_output: bool,
    command: str,
) -> None:
    """Convert runtime networth errors into CLI envelopes."""
    if isinstance(exc, AssetsConfigValidationError):
        emit_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    if isinstance(exc, ScenariosConfigValidationError):
        emit_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    if isinstance(exc, ValueError):
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command=command,
        )

    emit_error(
        f"Failed to compute net worth: {exc}",
        error_code=ErrorCode.GENERAL_ERROR,
        json_output=json_output,
        command=command,
    )
