"""Validation error envelopes for ``finjuice budget``.

Owns goals.yaml validation error reporting. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.budget`, which re-exports the
names used by existing callers.
"""

from __future__ import annotations

from typing import NoReturn

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.goals import GoalsValidationProblem


def _raise_goals_validation_error(
    *,
    command: str,
    problems: list[GoalsValidationProblem],
    json_output: bool,
) -> NoReturn:
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
