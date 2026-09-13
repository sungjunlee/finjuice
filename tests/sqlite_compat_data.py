"""Shared synthetic builders for SQLite read-compatibility tests (#436).

Builds one logical transaction dataset and materializes it both as CSV
partitions (via the existing storage helpers) and as an authoritative SQLite
generation (via the repository builder), so read-path parity can be asserted
on identical data.
"""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4

import polars as pl

from finjuice.pipeline.storage.csv_transactions import write_month
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    ExactValue,
    GenerationPaths,
    LegacyIdentifierRecord,
    ObservationRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    SourceOccurrenceRecord,
    TransactionRecord,
)
from finjuice.pipeline.tagging.manual import MANUAL_CATEGORY_PREFIX, split_manual_tags

CAPTURE_DIGEST = "a" * 64


def logical_rows() -> list[dict[str, Any]]:
    """Return the logical CSV-shaped dataset used by parity tests.

    Tags are Python lists (CSV write format). ``tags_manual`` uses the
    persisted form, including the hidden category-override sentinel.
    """
    return [
        {
            "row_hash": "abc1234567890001",
            "date": "2024-10-01",
            "time": "10:00",
            "datetime": "2024-10-01T10:00:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "카페",
            "merchant_raw": "스타벅스",
            "memo_raw": None,
            "notes_manual": "",
            "amount": -5000.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": None,
            "category_rule": "카페",
            "category_final": "카페",
            "tags_rule": ["카페"],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": ["카페"],
            "confidence": 0.95,
            "needs_review": 0,
            "is_transfer_candidate": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
            "file_id": "241001_1",
            "source_row": 2,
        },
        {
            "row_hash": "abc1234567890002",
            "date": "2024-10-15",
            "time": "14:30",
            "datetime": "2024-10-15T14:30:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "교통",
            "minor_raw": "택시",
            "merchant_raw": "카카오택시",
            "memo_raw": None,
            "notes_manual": "",
            "amount": -15000.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": None,
            "category_rule": "교통",
            "category_final": "교통",
            "tags_rule": ["교통"],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": ["교통"],
            "confidence": 0.9,
            "needs_review": 0,
            "is_transfer_candidate": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
            "file_id": "241015_1",
            "source_row": 3,
        },
        {
            "row_hash": "abc1234567890003",
            "date": "2024-10-20",
            "time": "09:00",
            "datetime": "2024-10-20T09:00:00",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": None,
            "minor_raw": None,
            "merchant_raw": "신한은행",
            "memo_raw": None,
            "notes_manual": "",
            "amount": -100000.0,
            "account": "신한은행",
            "currency": "KRW",
            "counterparty": None,
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": [],
            "confidence": None,
            "needs_review": 1,
            "is_transfer_candidate": 1,
            "is_transfer": 1,
            "transfer_group_id": "grp-1",
            "file_id": "241020_1",
            "source_row": 4,
        },
        {
            "row_hash": "abc1234567890004",
            "date": "2024-10-31",
            "time": "18:00",
            "datetime": "2024-10-31T18:00:00",
            "type_raw": "입금",
            "type_norm": "income",
            "major_raw": "급여",
            "minor_raw": None,
            "merchant_raw": "회사",
            "memo_raw": None,
            "notes_manual": "",
            "amount": 3000000.0,
            "account": "급여계좌",
            "currency": "KRW",
            "counterparty": None,
            "category_rule": None,
            "category_final": "급여",
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": [],
            "confidence": None,
            "needs_review": 0,
            "is_transfer_candidate": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
            "file_id": "241031_1",
            "source_row": 5,
        },
        {
            "row_hash": "abc1234567890005",
            "date": "2024-11-05",
            "time": "12:30",
            "datetime": "2024-11-05T12:30:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "생활",
            "minor_raw": None,
            "merchant_raw": "GS25",
            "memo_raw": None,
            "notes_manual": "",
            "amount": -8000.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": None,
            "category_rule": None,
            "category_final": "생활",
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": [],
            "confidence": None,
            "needs_review": 1,
            "is_transfer_candidate": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
            "file_id": "241105_1",
            "source_row": 2,
        },
        {
            "row_hash": "abc1234567890006",
            "date": "2024-11-20",
            "time": "20:00",
            "datetime": "2024-11-20T20:00:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "의료",
            "minor_raw": None,
            "merchant_raw": "삼성병원",
            "memo_raw": None,
            "notes_manual": "",
            "amount": -50000.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": None,
            "category_rule": None,
            "category_final": "수동분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [f"{MANUAL_CATEGORY_PREFIX}수동분류"],
            "tags_final": ["의료"],
            "confidence": None,
            "needs_review": 0,
            "is_transfer_candidate": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
            "file_id": "241120_1",
            "source_row": 3,
        },
    ]


def write_csv_mirror(data_dir: Path, rows: list[dict[str, Any]] | None = None) -> None:
    """Write the logical dataset into CSV month partitions under ``data_dir``."""
    rows = logical_rows() if rows is None else rows
    by_month: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for row in rows:
        year, month = (int(part) for part in str(row["date"])[:7].split("-"))
        by_month.setdefault((year, month), []).append(row)
    for (year, month), month_rows in sorted(by_month.items()):
        write_month(data_dir / "transactions", pl.DataFrame(month_rows), year, month)


def build_generation(root: Path, rows: list[dict[str, Any]] | None = None) -> Path:
    """Build and publish one synthetic SQLite generation from the logical rows.

    Args:
        root: Generation root directory (must not exist yet).
        rows: Logical CSV-shaped rows; defaults to :func:`logical_rows`.

    Returns:
        Path to the published ``finjuice.sqlite3`` database.
    """
    rows = logical_rows() if rows is None else rows
    paths = GenerationPaths(root)
    occurrence_id = str(uuid4())
    observation_id = str(uuid4())
    account_ids: dict[str, str] = {}

    with RepositoryBuilder(paths, str(uuid4())) as builder:
        artifact = builder.publish_source(BytesIO(b"synthetic source bytes"))
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=occurrence_id,
                artifact_id=artifact.artifact_id,
                occurrence_kind="banksalad_xlsx",
                original_filename="synthetic.xlsx",
                imported_at="2024-11-21T00:00:00Z",
                parser_version="test-v1",
                source_schema_version="4",
            )
        )
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=occurrence_id,
                observed_at=None,
                effective_at="2024-10-01",
                collected_at="2024-11-21T00:00:00Z",
                scope_state="complete",
            )
        )
        for row in rows:
            _add_row(builder, row, occurrence_id, observation_id, account_ids)
        builder.finalize()
    return paths.database


def _add_row(
    builder: RepositoryBuilder,
    row: dict[str, Any],
    occurrence_id: str,
    observation_id: str,
    account_ids: dict[str, str],
) -> None:
    """Add provenance, values, one transaction, and its row_hash mapping."""
    account_text = str(row["account"])
    if account_text not in account_ids:
        account_id = str(uuid4())
        account_ids[account_text] = account_id
        builder.add_account(
            AccountRecord(
                account_id=account_id,
                account_kind="bank.v1",
                display_name=account_text,
            )
        )
    account_id = account_ids[account_text]

    provenance_id = str(uuid4())
    builder.add_provenance(
        ProvenanceRecord(
            provenance_id=provenance_id,
            occurrence_id=occurrence_id,
            source_coordinate={"sheet": "transactions", "row": row["source_row"]},
            legacy_locator={
                "locator_version": 1,
                "file_id": row["file_id"],
                "source_row": row["source_row"],
                "row_hash": row["row_hash"],
            },
            parser_version="test-v1",
            source_schema_version="4",
        )
    )

    amount_id = str(uuid4())
    builder.add_exact_value(
        amount_id,
        ExactValue.from_lexical(str(row["amount"]), value_kind="money", currency="KRW"),
        provenance_id=provenance_id,
    )
    confidence_id: str | None = None
    if row["confidence"] is not None:
        confidence_id = str(uuid4())
        builder.add_exact_value(
            confidence_id,
            ExactValue.from_lexical(
                str(row["confidence"]),
                value_kind="number",
                unit="confidence.v1",
            ),
            provenance_id=provenance_id,
        )

    visible_manual, manual_category = split_manual_tags(row["tags_manual"])
    transaction_id = str(uuid4())
    builder.add_transaction(
        TransactionRecord(
            transaction_id=transaction_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            account_id=account_id,
            amount_value_id=amount_id,
            date_raw=str(row["date"]),
            time_raw=str(row["time"]),
            datetime_raw=str(row["datetime"]),
            type_raw=row["type_raw"],
            type_norm=str(row["type_norm"]),
            major_raw=row["major_raw"],
            minor_raw=row["minor_raw"],
            merchant_raw=row["merchant_raw"],
            memo_raw=row["memo_raw"],
            notes_manual=row["notes_manual"] or None,
            account_text=account_text,
            counterparty=row["counterparty"],
            category_rule=row["category_rule"],
            category_manual=manual_category,
            category_final=row["category_final"],
            tags_rule_json=json.dumps(row["tags_rule"], ensure_ascii=False),
            tags_ai_json=json.dumps(row["tags_ai"], ensure_ascii=False),
            tags_manual_json=json.dumps(visible_manual, ensure_ascii=False),
            tags_final_json=json.dumps(row["tags_final"], ensure_ascii=False),
            confidence_value_id=confidence_id,
            needs_review=bool(row["needs_review"]),
            is_transfer_candidate=bool(row["is_transfer_candidate"]),
            is_transfer=bool(row["is_transfer"]),
            transfer_group_id=row["transfer_group_id"],
        )
    )
    builder.add_legacy_identifier(
        LegacyIdentifierRecord(
            entity_id=transaction_id,
            identifier_kind="row_hash",
            identifier_value=str(row["row_hash"]),
            capture_manifest_digest=CAPTURE_DIGEST,
            provenance_id=provenance_id,
        )
    )
