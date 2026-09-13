"""One-way, full transaction CSV projection from an explicit repository frame."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from finjuice.pipeline.export.master import TAG_EXPORT_COLUMNS, _align_to_master_schema
from finjuice.pipeline.export.reports_polars_helpers import _write_csv_with_bom


def export_transactions_csv(source_df: pl.DataFrame, output_path: Path) -> int:
    """Write all audit columns and JSON tags, including headers for an empty frame."""
    frame = _align_to_master_schema(source_df, preserve_extra=True)
    for column in TAG_EXPORT_COLUMNS:
        if isinstance(frame.schema[column], pl.List):
            frame = frame.with_columns(
                pl.col(column).map_elements(_json_tags, return_dtype=pl.String).alias(column)
            )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv_with_bom(frame, output_path)
    return len(frame)


def _json_tags(value: pl.Series) -> str:
    return json.dumps(value.to_list(), ensure_ascii=False, separators=(",", ":"))
