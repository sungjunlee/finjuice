"""Spreadsheet export safety helpers."""

from __future__ import annotations

from typing import Any, Final

import polars as pl

FORMULA_PREFIXES: Final[tuple[str, ...]] = ("=", "+", "-", "@")
FORMULA_ADJACENT_PREFIX_CHARS: Final = "\t\r\n"


def neutralize_spreadsheet_formula(value: Any) -> Any:
    """Return an export-safe value for spreadsheet formula-like strings."""
    if not isinstance(value, str):
        return value

    if _is_formula_like(value):
        return f"'{value}"
    return value


def neutralize_spreadsheet_strings(df: pl.DataFrame) -> pl.DataFrame:
    """Return a copy with formula-like string cells neutralized for spreadsheets."""
    string_columns = [column for column, dtype in df.schema.items() if dtype == pl.Utf8]
    if not string_columns:
        return df

    return df.with_columns(_neutralize_column(column) for column in string_columns)


def _neutralize_column(column: str) -> pl.Expr:
    stripped = pl.col(column).str.strip_chars_start(FORMULA_ADJACENT_PREFIX_CHARS)
    formula_like = pl.any_horizontal(
        stripped.str.starts_with(prefix) for prefix in FORMULA_PREFIXES
    ).fill_null(False)
    return (
        pl.when(formula_like)
        .then(pl.lit("'") + pl.col(column))
        .otherwise(pl.col(column))
        .alias(column)
    )


def _is_formula_like(value: str) -> bool:
    return value.lstrip(FORMULA_ADJACENT_PREFIX_CHARS).startswith(FORMULA_PREFIXES)


__all__ = [
    "neutralize_spreadsheet_formula",
    "neutralize_spreadsheet_strings",
]
