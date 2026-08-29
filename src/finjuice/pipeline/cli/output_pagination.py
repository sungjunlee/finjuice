"""Pagination and JSON ``_meta`` helpers for CLI output.

These helpers are the envelope cluster used by bounded read commands
(``query``, ``show``, ``template run``, ``review``). Public names stay
importable from :mod:`finjuice.pipeline.cli.output`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from finjuice import get_version

DEFAULT_PAGINATION_LIMIT = 100
DEFAULT_MAX_BYTES = 1_048_576
MAX_PAGINATION_LIMIT = 10_000


def _build_meta(
    command: str,
    schema_version: str = "1.0",
    extras: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Build _meta envelope for JSON output."""
    meta: dict[str, Any] = {
        "schema_version": schema_version,
        "finjuice_version": get_version(),
        "command": command,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extras:
        meta.update(extras)
    return meta


@dataclass
class Pagination:
    """Pagination envelope for bounded read commands.

    The cursor is intentionally opaque to callers. The current implementation
    stores an integer offset string, but this may switch to keyset pagination.
    """

    limit: int
    cursor: str = "0"
    next_cursor: Optional[str] = None
    has_more: bool = False
    total_estimate: Optional[int] = None
    truncated_by_bytes: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable pagination envelope."""
        return {
            "limit": self.limit,
            "cursor": self.cursor,
            "next_cursor": self.next_cursor,
            "has_more": self.has_more,
            "total_estimate": self.total_estimate,
            "truncated_by_bytes": self.truncated_by_bytes,
        }


def wrap_paginated_result(
    payload: dict[str, Any],
    *,
    pagination: Pagination,
) -> dict[str, Any]:
    """Inject `pagination` key into a payload prior to emit()."""
    payload["pagination"] = pagination.to_dict()
    return payload


def validate_pagination_args(
    limit: int,
    cursor: str,
    max_bytes: int,
    *,
    json_output: bool = False,
    command: str = "",
) -> tuple[int, int, int]:
    """Validate common pagination flags and return normalized values."""
    from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error

    if limit < 0:
        emit_error(
            "--limit must be greater than or equal to 0.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )
    if limit > MAX_PAGINATION_LIMIT:
        emit_error(
            f"--limit must be <= {MAX_PAGINATION_LIMIT}.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )
    if max_bytes < 0:
        emit_error(
            "--max-bytes must be greater than or equal to 0.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    try:
        cursor_offset = int(cursor)
    except ValueError:
        emit_error(
            "--cursor must be a valid pagination cursor.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )
    if cursor_offset < 0:
        emit_error(
            "--cursor must not be negative.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command=command,
        )

    return limit, cursor_offset, max_bytes


def build_offset_pagination(
    *,
    limit: int,
    cursor_offset: int,
    total_estimate: Optional[int],
    fetched_count: int,
) -> Pagination:
    """Build offset-backed pagination while keeping cursor format opaque."""
    has_more = False
    if limit > 0:
        if total_estimate is not None:
            has_more = cursor_offset + fetched_count < total_estimate
        else:
            has_more = fetched_count == limit
    return Pagination(
        limit=limit,
        cursor=str(cursor_offset),
        next_cursor=str(cursor_offset + fetched_count) if has_more else None,
        has_more=has_more,
        total_estimate=total_estimate,
    )


def truncate_rows_to_max_bytes(
    payload: dict[str, Any],
    *,
    pagination: Pagination,
    max_bytes: int,
    command: str,
    meta_extras: Optional[dict[str, Any]] = None,
    rows_key: str = "rows",
) -> dict[str, Any]:
    """Drop trailing rows until the serialized JSON envelope fits `max_bytes`."""
    rows = payload.get(rows_key)
    if not isinstance(rows, list):
        return wrap_paginated_result(payload, pagination=pagination)

    original_count = len(rows)

    def serialized_size() -> int:
        candidate = wrap_paginated_result(payload, pagination=pagination)
        envelope = {"_meta": _build_meta(command, extras=meta_extras), **candidate}
        return len(json.dumps(envelope, ensure_ascii=False, indent=2, default=str).encode())

    while serialized_size() > max_bytes and rows:
        rows.pop()
        pagination.truncated_by_bytes = True
        payload["row_count"] = len(rows)
        if original_count > len(rows):
            pagination.has_more = True
            try:
                cursor_offset = int(pagination.cursor)
            except ValueError:
                cursor_offset = 0
            pagination.next_cursor = str(cursor_offset + len(rows))

    if original_count > len(rows):
        pagination.truncated_by_bytes = True
        payload["row_count"] = len(rows)

    return wrap_paginated_result(payload, pagination=pagination)


def render_pagination_footer(row_count: int, pagination: Pagination) -> None:
    """Render a dim next-page hint for text-mode paginated output."""
    from finjuice.pipeline.cli.output import console

    if not pagination.has_more or pagination.next_cursor is None:
        return
    total = pagination.total_estimate if pagination.total_estimate is not None else "more"
    console.print(
        f"[dim]... (showing {row_count} of {total}, "
        f"use --cursor {pagination.next_cursor} for next page)[/dim]"
    )
