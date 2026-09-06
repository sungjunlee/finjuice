"""Error-code and exit-code catalog helpers for CLI output.

Structured ``ErrorCode`` / ``ExitCode`` types, catalogs, and wire-value
normalization live here. Public names stay importable from
:mod:`finjuice.pipeline.cli.output`.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from types import MappingProxyType
from typing import Mapping


class ErrorCode(str, Enum):
    """Machine-readable error codes for agent consumption."""

    GENERAL_ERROR = "GENERAL_ERROR"
    DATA_DIR_NOT_INITIALIZED = "DATA_DIR_NOT_INITIALIZED"
    NO_DATA = "NO_DATA"
    RULES_FILE_NOT_FOUND = "RULES_FILE_NOT_FOUND"
    RULE_NOT_FOUND = "RULE_NOT_FOUND"
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_ACCESS_ERROR = "FILE_ACCESS_ERROR"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    INVALID_ARGS = "INVALID_ARGS"
    TAGGING_FAILED = "TAGGING_FAILED"
    TRANSFER_FAILED = "TRANSFER_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"
    QUERY_ERROR = "QUERY_ERROR"
    SIMULATION_FAILED = "SIMULATION_FAILED"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    USER_CANCELLED = "USER_CANCELLED"
    UNEXPECTED_ERROR = "UNEXPECTED_ERROR"

    def __str__(self) -> str:
        """Return the wire value for string-formatting compatibility."""
        return self.value

    @classmethod
    def values(cls) -> tuple[str, ...]:
        """Return accepted JSON error-code values in declaration order."""
        return tuple(code.value for code in cls)


class ExitCode(IntEnum):
    """Semantic exit codes for agent error-type distinction."""

    SUCCESS = 0
    OK = 0
    GENERAL_ERROR = 1
    USAGE_ERROR = 2
    VALIDATION_ERROR = 3
    NO_DATA = 4
    USER_CANCELLED = 130

    def __str__(self) -> str:
        """Return the integer wire value for string-formatting compatibility."""
        return str(int(self))

    @classmethod
    def items(cls, *, include_aliases: bool = True) -> tuple[tuple[str, int], ...]:
        """Return public exit-code names and integer values."""
        if include_aliases:
            return tuple((name, int(code)) for name, code in cls.__members__.items())
        return tuple((code.name, int(code)) for code in cls)

    @classmethod
    def values(cls) -> tuple[int, ...]:
        """Return unique accepted process exit integers in declaration order."""
        return tuple(int(code) for code in cls)


ERROR_CODE_CATALOG: Mapping[str, ErrorCode] = MappingProxyType(
    {code.value: code for code in ErrorCode}
)
EXIT_CODE_CATALOG: Mapping[str, ExitCode] = MappingProxyType(dict(ExitCode.__members__))


def error_code_values() -> tuple[str, ...]:
    """Return accepted JSON error-code values in declaration order."""
    return ErrorCode.values()


def exit_code_items(*, include_aliases: bool = True) -> tuple[tuple[str, int], ...]:
    """Return public exit-code names and values for manifest/schema discovery."""
    return ExitCode.items(include_aliases=include_aliases)


def exit_code_values() -> tuple[int, ...]:
    """Return unique accepted process exit integers in declaration order."""
    return ExitCode.values()


def _normalize_error_code(error_code: ErrorCode | str) -> str:
    """Return the JSON wire value for a typed or legacy string error code."""
    if isinstance(error_code, ErrorCode):
        return error_code.value
    return str(error_code)


def _normalize_exit_code(exit_code: ExitCode | int) -> int:
    """Return the process integer value for a typed or legacy integer exit code."""
    return int(exit_code)
