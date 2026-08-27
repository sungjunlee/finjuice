"""Investment block parser for Banksalad overview sheets."""

from __future__ import annotations

from typing import Any

from .cells import _date_at, _number_at, _text_at
from .constants import _INVESTMENT_BLOCK_ID, _STRUCTURED_TABLE_HEADERS
from .facts import _source_fact_id
from .models import _SectionRange
from .structured import _detect_structured_table, _has_entity_identity, _table_data_rows


def _parse_investment_rows(
    sheet: Any,
    snapshot_date: str,
    file_id: str,
    sections: list[_SectionRange],
    fact_ids: dict[tuple[int, int], str],
) -> list[dict[str, Any]]:
    table = _detect_structured_table(
        sheet,
        sections,
        _INVESTMENT_BLOCK_ID,
        _STRUCTURED_TABLE_HEADERS["investments"],
    )
    if table is None:
        return []

    rows: list[dict[str, Any]] = []
    for source_row in _table_data_rows(sheet, table):
        institution = _text_at(sheet, source_row, table.columns.get("institution"))
        product_name = _text_at(sheet, source_row, table.columns.get("product_name"))
        if not _has_entity_identity(institution, product_name):
            continue

        rows.append(
            {
                "snapshot_date": snapshot_date,
                "product_type": _text_at(sheet, source_row, table.columns.get("product_type")),
                "institution": institution,
                "product_name": product_name,
                "principal_amount": _number_at(
                    sheet,
                    source_row,
                    table.columns.get("principal_amount"),
                ),
                "valuation_amount": _number_at(
                    sheet,
                    source_row,
                    table.columns.get("valuation_amount"),
                ),
                "return_rate": _number_at(sheet, source_row, table.columns.get("return_rate")),
                "start_date": _date_at(sheet, source_row, table.columns.get("start_date")),
                "maturity_date": _date_at(sheet, source_row, table.columns.get("maturity_date")),
                "currency": "KRW",
                "source_fact_id": _source_fact_id(
                    fact_ids,
                    source_row,
                    (table.columns.get("product_name"), table.columns.get("institution")),
                ),
                "file_id": file_id,
                "source_row": source_row,
            }
        )
    return rows
