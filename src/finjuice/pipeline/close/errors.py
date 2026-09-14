"""Privacy-safe errors for month close and reopen."""

from __future__ import annotations


class CloseError(Exception):
    """Base error for month-close operations."""


class CloseLockedError(CloseError):
    """Raised when a closed month would be overwritten in place."""


class CloseNotFoundError(CloseError):
    """Raised when a close period or revision does not exist."""


class CloseStateError(CloseError):
    """Raised when a close action is invalid for the current period state."""


class ClosePathError(CloseError):
    """Raised when a close store path or period name is invalid."""
