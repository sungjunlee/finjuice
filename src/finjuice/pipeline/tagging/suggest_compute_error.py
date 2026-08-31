"""Domain error helpers for `finjuice rules suggest` JSON compute.

Owns :class:`SuggestComputeError` and the raise helper used by JSON compute.
JSON compute stays in :mod:`finjuice.pipeline.tagging.suggest_compute`, which
re-exports these names so existing callers can keep importing from that
module. Compact privacy projection lives in
:mod:`finjuice.pipeline.tagging.suggest_compute_compact`.
"""

from __future__ import annotations


class SuggestComputeError(Exception):
    """Domain failure for `rules suggest` compute; CLI maps it to emit_error."""

    def __init__(
        self,
        message: str,
        *,
        error_code: str,
        exit_code: int,
        suggestion: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.exit_code = exit_code
        self.suggestion = suggestion


def _fail(
    message: str,
    *,
    error_code: str,
    exit_code: int,
    suggestion: str | None = None,
) -> None:
    raise SuggestComputeError(
        message,
        error_code=error_code,
        exit_code=exit_code,
        suggestion=suggestion,
    )
