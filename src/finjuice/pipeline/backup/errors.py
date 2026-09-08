"""Backup operation errors without path or financial payload."""

from __future__ import annotations


class BackupError(Exception):
    """Structured backup failure with a privacy-safe message."""

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


def invalid(message: str, *, suggestion: str | None = None) -> BackupError:
    """Return a validation failure without leaking private details."""
    return BackupError(message, code="VALIDATION_FAILED", suggestion=suggestion)
