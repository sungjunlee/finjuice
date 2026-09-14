"""Privacy-safe errors for family account identity and ownership."""

from __future__ import annotations


class AccountsError(Exception):
    """Domain failure that does not embed names, amounts, or source paths."""

    def __init__(self, message: str, *, code: str = "ACCOUNTS_INVALID") -> None:
        super().__init__(message)
        self.message = message
        self.code = code
