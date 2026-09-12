"""Preserve completed step results when a composed pipeline fails."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError


class FullPipelineError(RuntimeError):
    """A failed step with the receipts and summaries produced before failure."""

    def __init__(
        self,
        failed_step: str,
        steps: dict[str, dict[str, Any]],
        *,
        error_type: str,
    ) -> None:
        completed = ", ".join(name for name in steps if name != failed_step) or "none"
        message = f"Pipeline step '{failed_step}' failed. Completed steps: {completed}."
        if failed_step in steps:
            message += " Partial results from the failed step were preserved."
        super().__init__(message)
        self.failed_step = failed_step
        self.steps = dict(steps)
        self.error_type = error_type
        self.error_code = ErrorCode.GENERAL_ERROR
        self.exit_code = ExitCode.GENERAL_ERROR

    @classmethod
    def from_exception(
        cls, failed_step: str, steps: dict[str, dict[str, Any]], cause: Exception
    ) -> "FullPipelineError":
        """Retain typed failure status and receipts without exposing raw cause text."""
        failure = cls(failed_step, steps, error_type=type(cause).__name__)
        if isinstance(cause, MutationValidationError):
            failure.error_code = ErrorCode.INVALID_ARGS
            failure.exit_code = ExitCode.USAGE_ERROR
        elif isinstance(cause, MutationConflictError):
            failure.error_code = ErrorCode.VALIDATION_FAILED
            failure.exit_code = ExitCode.VALIDATION_ERROR
        return failure

    def metadata(self) -> dict[str, Any]:
        """Return additive error metadata without copying an exception's raw message."""
        return {
            "pipeline": {
                "failed_step": self.failed_step,
                "completed_steps": [name for name in self.steps if name != self.failed_step],
                "steps": self.steps,
                "error_type": self.error_type,
            }
        }
