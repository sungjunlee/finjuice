"""Preserve persisted transaction meaning and every row occurrence."""

from __future__ import annotations

import json
from typing import Any

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from finjuice.pipeline.storage.sqlite.records import AccountRecord, TransactionRecord

from .model import Emitter
from .values import exact, flag, tags

MARKER = "__finjuice_category_override__:"


def transaction(emitter: Emitter, row: dict[str, str | None], observation: str) -> bool:
    for name in sorted(row.keys() - set(CSV_COLUMNS)):
        emitter.issue("unknown_field", name, row[name])
    amount = exact(emitter, row, "amount")
    if row.get("amount") in (None, ""):
        emitter.issue("missing_required_field", "amount", row.get("amount"))
    required = ("date", "time", "datetime", "type_norm", "account")
    missing = [name for name in required if row.get(name) is None]
    for name in missing:
        emitter.issue("missing_required_field", name)
    sequences = {
        name: tags(emitter, row, name)
        for name in ("tags_rule", "tags_ai", "tags_manual", "tags_final")
    }
    if amount is None or missing or any(value is None for value in sequences.values()):
        return False
    manual = sequences["tags_manual"] or []
    visible = [tag for tag in manual if not tag.startswith(MARKER)]
    markers = [tag[len(MARKER) :] for tag in manual if tag.startswith(MARKER)]
    selected = next((value for value in reversed(markers) if value), None)
    account = emitter.identifier("account")
    emitter.entity("account", AccountRecord(account, "unknown", row["account"]))
    emitter.legacy(account, "account_text", row["account"] or "")
    optional = (
        "type_raw",
        "major_raw",
        "minor_raw",
        "merchant_raw",
        "memo_raw",
        "notes_manual",
        "counterparty",
        "category_rule",
        "category_final",
        "transfer_group_id",
    )
    kwargs: dict[str, Any] = {name: row.get(name) for name in optional}
    kwargs.update(
        {
            name: flag(emitter, row, name)
            for name in ("needs_review", "is_transfer_candidate", "is_transfer")
        }
    )
    kwargs.update(
        {f"{name}_json": json.dumps(value, ensure_ascii=False) for name, value in sequences.items()}
    )
    kwargs["tags_manual_json"] = json.dumps(visible, ensure_ascii=False)
    identifier = emitter.identifier("transaction")
    emitter.entity(
        "transaction",
        TransactionRecord(
            identifier,
            observation,
            emitter.identifier("provenance"),
            account,
            amount,
            row["date"] or "",
            row["time"] or "",
            row["datetime"] or "",
            type_norm=row["type_norm"] or "",
            account_text=row["account"] or "",
            category_manual=selected,
            confidence_value_id=exact(emitter, row, "confidence", "number", unit="confidence.v1"),
            **kwargs,
        ),
    )
    for name in ("row_hash", "file_id", "source_row"):
        if row.get(name) is not None:
            emitter.legacy(identifier, name, row[name] or "")
    return True
