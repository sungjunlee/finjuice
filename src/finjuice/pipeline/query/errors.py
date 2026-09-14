"""Errors for the SQLite query read-compatibility layer."""


class QuerySourceError(RuntimeError):
    """The configured SQLite query source is missing or unusable."""
