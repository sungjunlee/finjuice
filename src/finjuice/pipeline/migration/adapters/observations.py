"""Typed snapshot and overview facts without inferred ownership or overlap."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.storage.csv_schema import (
    ASSET_SNAPSHOT_COLUMNS,
    BANKSALAD_OVERVIEW_FACT_COLUMNS,
)
from finjuice.pipeline.storage.sqlite.records import (
    AccountRecord,
    AssetSnapshotRecord,
    OverviewFactRecord,
    ResourceRecord,
)

from .model import Emitter
from .values import emit_exact, parse_exact


def asset(emitter: Emitter, row: dict[str, str | None], observation: str) -> bool:
    required = ("snapshot_date", "account_id", "instrument_id")
    if any(row.get(name) is None for name in required):
        emitter.issue("incomplete_asset_snapshot")
        return False
    quantity = parse_exact(emitter, row, "quantity", "quantity", unit="legacy_quantity.v1")
    market_value = parse_exact(emitter, row, "market_value")
    if quantity is None and market_value is None:
        emitter.issue("asset_snapshot_without_value")
        return False
    account = emitter.identifier("account")
    resource = emitter.identifier("resource")
    emitter.entity("account", AccountRecord(account, "unknown", row["account_id"]))
    emitter.legacy(account, "account_id", row["account_id"] or "")
    emitter.entity("resource", ResourceRecord(resource, "unknown", row["instrument_id"]))
    emitter.legacy(resource, "instrument_id", row["instrument_id"] or "")
    identifier = emitter.identifier("asset_snapshot")
    emitter.entity(
        "asset_snapshot",
        AssetSnapshotRecord(
            identifier,
            observation,
            emitter.identifier("provenance"),
            account,
            resource,
            emit_exact(emitter, "quantity", quantity),
            emit_exact(emitter, "market_value", market_value),
            row["snapshot_date"] or "",
        ),
    )
    identifiers(emitter, identifier, row)
    unknown_fields(emitter, row, set(ASSET_SNAPSHOT_COLUMNS))
    return True


def fact(emitter: Emitter, row: dict[str, str | None], observation: str) -> bool:
    required = ("snapshot_date", "sheet_name", "block_id", "block_title", "fact_kind")
    value_type = row.get("value_type")
    if any(row.get(name) is None for name in required) or value_type not in {
        "number",
        "text",
        "date",
        "empty",
        "unsupported",
    }:
        emitter.issue("incomplete_overview_fact")
        return False
    kwargs: dict[str, Any] = {name: row[name] for name in required}
    kwargs["value_type"] = value_type
    numeric = parse_exact(emitter, row, "value_numeric", "number", unit="overview_number.v1")
    if (value_type == "number") != (numeric is not None):
        emitter.issue(
            "overview_fact_numeric_type_mismatch", "value_numeric", row.get("value_numeric")
        )
        return False
    if value_type not in {"number", "empty"} and row.get("value_text") is None:
        emitter.issue("overview_fact_missing_text", "value_text")
        return False
    identifier = emitter.identifier("overview_fact")
    emitter.entity(
        "overview_fact",
        OverviewFactRecord(
            identifier,
            observation,
            emitter.identifier("provenance"),
            numeric_value_id=emit_exact(emitter, "value_numeric", numeric),
            value_text=row.get("value_text"),
            row_label=row.get("row_label"),
            column_label=row.get("column_label"),
            **kwargs,
        ),
    )
    identifiers(emitter, identifier, row)
    unknown_fields(emitter, row, set(BANKSALAD_OVERVIEW_FACT_COLUMNS))
    return True


def identifiers(emitter: Emitter, identifier: str, row: dict[str, str | None]) -> None:
    for name in ("fact_id", "file_id", "source_row", "source_col"):
        if row.get(name) is not None:
            emitter.legacy(identifier, name, row[name] or "")


def unknown_fields(emitter: Emitter, row: dict[str, str | None], known: set[str]) -> None:
    for name in sorted(row.keys() - known):
        emitter.issue("unknown_field", name, row[name])
