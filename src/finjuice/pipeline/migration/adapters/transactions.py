"""Preserve persisted transaction meaning and every row occurrence."""

from __future__ import annotations

import json
from typing import Any

from finjuice.pipeline.migration.policy import MANUAL_STATE_POLICY
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from finjuice.pipeline.storage.sqlite.records import AccountRecord, TransactionRecord

from .model import Emitter
from .values import emit_exact, exact, flag, parse_exact, tags

MARKER = "__finjuice_category_override__:"


def _manual_state(manual: list[str], policy: str) -> tuple[list[str], str | None]:
    """Freeze override selection while retaining original visible tag occurrences."""
    if policy != MANUAL_STATE_POLICY:
        visible = [tag for tag in manual if not tag.startswith(MARKER)]
        markers = [tag[len(MARKER) :] for tag in manual if tag.startswith(MARKER)]
        return visible, next((value for value in reversed(markers) if value), None)

    visible = [tag for tag in manual if not tag.strip().startswith(MARKER)]
    # Deduplicate whole normalized tags before selecting the last nonempty suffix.
    # Keep this frozen here: importing the live tag helper would change old replays.
    normalized = dict.fromkeys(tag.strip() for tag in manual if tag.strip())
    selected = None
    for tag in normalized:
        if tag.startswith(MARKER):
            suffix = tag[len(MARKER) :].strip()
            if suffix:
                selected = suffix
    return visible, selected


def transaction(emitter: Emitter, row: dict[str, str | None], observation: str) -> bool:
    for name in sorted(row.keys() - set(CSV_COLUMNS)):
        emitter.issue("unknown_field", name, row[name])
    amount_value = parse_exact(emitter, row, "amount")
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
    supported_type = row.get("type_norm") in {"expense", "income", "transfer", "other"}
    if not supported_type:
        emitter.issue("unsupported_transaction_type", "type_norm", row.get("type_norm"))
    if (
        amount_value is None
        or missing
        or not supported_type
        or any(value is None for value in sequences.values())
    ):
        return False
    amount = emit_exact(emitter, "amount", amount_value)
    assert amount is not None
    manual = sequences["tags_manual"] or []
    visible, selected = _manual_state(manual, emitter.context.migration_policy)
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
