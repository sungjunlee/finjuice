"""JSON-safe serialization of raw cell evidence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence, FormulaEvidence, RichText, TextRun

JSONValue = Any


def cell_has_content(cell: CellEvidence) -> bool:
    """Return whether a captured cell carries nonempty source evidence."""
    if cell.formula is not None:
        return True
    if cell.inline_text is not None and cell.inline_text.plain_text != "":
        return True
    if cell.shared_text is not None and cell.shared_text.plain_text != "":
        return True
    return cell.value_state == "present" and bool(cell.raw_value)


def serialize_cell(cell: CellEvidence) -> dict[str, JSONValue]:
    """Return one cell as canonical JSON without numeric conversion."""
    return {
        "cell_type": cell.cell_type,
        "column": cell.column,
        "formula": None if cell.formula is None else _formula(cell.formula),
        "inline_text": None if cell.inline_text is None else _rich_text(cell.inline_text),
        "raw_value": cell.raw_value,
        "reference": cell.reference,
        "row": cell.row,
        "shared_string_index": cell.shared_string_index,
        "shared_text": None if cell.shared_text is None else _rich_text(cell.shared_text),
        "shared_text_resolved": cell.shared_text_resolved,
        "source_xml": cell.source_xml,
        "style_index": cell.style_index,
        "type_declared": cell.type_declared,
        "value_state": cell.value_state,
    }


def serialize_cells(cells: Sequence[CellEvidence]) -> list[dict[str, JSONValue]]:
    """Serialize every supplied cell in source order."""
    return [serialize_cell(cell) for cell in cells]


def json_ready(value: JSONValue) -> JSONValue:
    """Convert tuples to lists so audit and payload encoding stay canonical."""
    if isinstance(value, tuple):
        return [json_ready(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list):
        return [json_ready(item) for item in value]
    return value


def _formula(formula: FormulaEvidence) -> dict[str, JSONValue]:
    return {
        "formula_type": formula.formula_type,
        "reference": formula.reference,
        "shared_index": formula.shared_index,
        "source_xml": formula.source_xml,
        "text": formula.text,
    }


def _rich_text(text: RichText) -> dict[str, JSONValue]:
    return {
        "plain_text": text.plain_text,
        "runs": [_text_run(run) for run in text.runs],
        "source_xml": text.source_xml,
    }


def _text_run(run: TextRun) -> dict[str, JSONValue]:
    return {"properties_xml": run.properties_xml, "text": run.text}
