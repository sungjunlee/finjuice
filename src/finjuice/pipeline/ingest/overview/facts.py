"""Overview fact-row construction."""

from __future__ import annotations

from datetime import date, datetime
from hashlib import sha256
from typing import Any

from .cells import _cell_text, _format_date_value, _parse_numeric_value
from .models import _FactContext, _FactLabels


def _source_fact_id(
    fact_ids: dict[tuple[int, int], str],
    source_row: int,
    preferred_cols: tuple[int | None, ...],
) -> str | None:
    for source_col in preferred_cols:
        if source_col is None:
            continue
        source_fact_id = fact_ids.get((source_row, source_col))
        if source_fact_id is not None:
            return source_fact_id
    return None


def _make_fact(
    context: _FactContext,
    labels: _FactLabels,
    value: Any,
    source_row: int,
    source_col: int,
) -> dict[str, Any]:
    value_numeric = _parse_numeric_value(value)
    value_text: str | None = None
    value_type = "empty"

    if value_numeric is not None:
        value_type = "number"
    elif isinstance(value, (date, datetime)):
        value_type = "date"
        value_text = _format_date_value(value)
    else:
        value_text = _cell_text(value)
        if value_text:
            value_type = "text"

    fact_id = _build_fact_id(
        context=context,
        labels=labels,
        source_row=source_row,
        source_col=source_col,
    )

    return {
        "fact_id": fact_id,
        "snapshot_date": context.snapshot_date,
        "sheet_name": context.sheet_name,
        "block_id": context.block_id,
        "block_title": context.block_title,
        "fact_kind": labels.fact_kind,
        "row_label": labels.row_label,
        "column_label": labels.column_label,
        "value_numeric": value_numeric,
        "value_text": value_text,
        "value_type": value_type,
        "file_id": context.file_id,
        "source_row": source_row,
        "source_col": source_col,
    }


def _build_fact_id(
    context: _FactContext,
    labels: _FactLabels,
    source_row: int,
    source_col: int,
) -> str:
    key = "|".join(
        (
            context.snapshot_date,
            context.block_id,
            labels.fact_kind,
            _normalize_fact_key_part(labels.row_label),
            _normalize_fact_key_part(labels.column_label),
            str(source_row),
            str(source_col),
        )
    )
    return sha256(key.encode("utf-8")).hexdigest()[:16]


def _normalize_fact_key_part(value: str | None) -> str:
    if value is None:
        return ""
    return " ".join(value.strip().lower().split())
