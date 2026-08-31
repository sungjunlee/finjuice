"""Problem-construction helpers for goals.yaml field validation.

Owns source-location lookup and GoalsValidationProblem construction.
Scalar field checks and date/month ranges stay in
:mod:`finjuice.pipeline.goals_validators.fields`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.goals_validators.models import GoalsValidationProblem


def _problem(
    path: str,
    message: str,
    node: Any,
    *,
    key: str | int | None = None,
) -> GoalsValidationProblem:
    """Create a validation problem with best-effort source location data."""
    line, column = _position(node, key=key)
    return GoalsValidationProblem(path=path, message=message, line=line, column=column)


def _parse_error_problem(exc: Exception) -> GoalsValidationProblem:
    """Convert a YAML parse exception into a line-numbered problem."""
    mark = getattr(exc, "problem_mark", None)
    line = getattr(mark, "line", None)
    column = getattr(mark, "column", None)
    detail = getattr(exc, "problem", None) or "failed to parse YAML"
    return GoalsValidationProblem(
        path="goals.yaml",
        message=str(detail),
        line=(line + 1) if isinstance(line, int) else None,
        column=(column + 1) if isinstance(column, int) else None,
    )


def _position(node: Any, *, key: str | int | None = None) -> tuple[int | None, int | None]:
    """Return a 1-based (line, column) tuple for a ruamel node or mapping key."""
    line: int | None = None
    column: int | None = None
    lc = getattr(node, "lc", None)
    if lc is None:
        return None, None

    if key is not None:
        if isinstance(key, int):
            try:
                item_line, item_column = lc.item(key)
            except (IndexError, KeyError, TypeError):
                pass
            else:
                line = item_line + 1
                column = item_column + 1
                return line, column
        try:
            key_line, key_column = lc.key(key)
        except (KeyError, TypeError):
            pass
        else:
            line = key_line + 1
            column = key_column + 1
            return line, column

    raw_line = getattr(lc, "line", None)
    raw_column = getattr(lc, "col", None)
    if isinstance(raw_line, int):
        line = raw_line + 1
    if isinstance(raw_column, int):
        column = raw_column + 1
    return line, column
