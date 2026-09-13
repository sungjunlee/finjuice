"""Privacy-safe errors for frozen-source preservation migration."""

from __future__ import annotations


class MigrationError(Exception):
    """Structured migration failure without financial or host-path payload."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "VALIDATION_FAILED",
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.suggestion = suggestion


def invalid(message: str, *, suggestion: str | None = None) -> MigrationError:
    """Return a validation failure."""
    return MigrationError(message, code="VALIDATION_FAILED", suggestion=suggestion)
