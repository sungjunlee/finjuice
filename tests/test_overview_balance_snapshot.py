"""Pin overview balance snapshot assembly as the test surface.

Field mapping and missing-value policy live in ``overview.snapshot``.
Sheet walking stays in ``overview.balance``, which re-exports the assembly
helpers so existing imports keep working.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from finjuice.pipeline.ingest.overview import balance, snapshot
from finjuice.pipeline.ingest.overview.models import _OverviewBlockParseContext
from finjuice.pipeline.ingest.overview.snapshot import (
    _assemble_balance_snapshot_row,
    _BalanceSnapshotFields,
)
from finjuice.pipeline.storage.csv_schema_cluster import BANKSALAD_BALANCE_COLUMNS

OVERVIEW_DIR = Path("src/finjuice/pipeline/ingest/overview")
SNAPSHOT_MODULE = "finjuice.pipeline.ingest.overview.snapshot"
ASSEMBLY_NAMES = (
    "_BalanceSnapshotFields",
    "_assemble_balance_snapshot_row",
)


def _block_context() -> _OverviewBlockParseContext:
    return _OverviewBlockParseContext(
        sheet_name="뱅샐현황",
        snapshot_date="2026-06-15",
        file_id="260615_1",
        file_name="synthetic_overview.xlsx",
    )


def _fields(
    *,
    side: str = "asset",
    category: str | None = "예금",
    item_name: str | None = "Synthetic Deposit",
    amount: float | None = 1_250_000.0,
    source_fact_id: str | None = "fact-1",
    source_row: int = 5,
) -> _BalanceSnapshotFields:
    return _BalanceSnapshotFields(
        side=side,
        category=category,
        item_name=item_name,
        amount=amount,
        source_fact_id=source_fact_id,
        source_row=source_row,
    )


def test_balance_snapshot_assembly_lives_in_snapshot_module() -> None:
    """Assembly is defined once in snapshot.py; balance.py only re-exports it."""
    balance_text = (OVERVIEW_DIR / "balance.py").read_text(encoding="utf-8")
    snapshot_text = (OVERVIEW_DIR / "snapshot.py").read_text(encoding="utf-8")

    assert "def _parse_balance_block" in balance_text
    assert "def _read_balance_snapshot_fields" in balance_text
    assert "def _assemble_balance_snapshot_row" not in balance_text
    assert "class _BalanceSnapshotFields" not in balance_text

    assert "def _assemble_balance_snapshot_row" in snapshot_text
    assert "class _BalanceSnapshotFields" in snapshot_text
    assert "def _resolve_snapshot_date" in snapshot_text
    assert "def _parse_balance_block" not in snapshot_text
    assert "def _read_balance_snapshot_fields" not in snapshot_text


def test_balance_reexports_snapshot_assembly_identity() -> None:
    """Existing balance imports keep resolving to the snapshot assembly objects."""
    balance_text = (OVERVIEW_DIR / "balance.py").read_text(encoding="utf-8")

    for name in ASSEMBLY_NAMES:
        assert name in balance_text
        assert getattr(balance, name) is getattr(snapshot, name)

    assert balance._assemble_balance_snapshot_row.__module__ == SNAPSHOT_MODULE
    assert snapshot._assemble_balance_snapshot_row.__module__ == SNAPSHOT_MODULE
    assert balance._BalanceSnapshotFields.__module__ == SNAPSHOT_MODULE
    assert snapshot._BalanceSnapshotFields.__module__ == SNAPSHOT_MODULE
    assert callable(balance._parse_balance_block)
    assert callable(balance._read_balance_snapshot_fields)
    assert callable(snapshot._resolve_snapshot_date)


def test_assemble_balance_snapshot_row_maps_fields_and_krw_currency() -> None:
    """A complete row maps extracted fields onto the stored snapshot columns."""
    # Arrange
    context = _block_context()
    fields = _fields()

    # Act
    row = _assemble_balance_snapshot_row(context, fields)

    # Assert
    assert row == {
        "snapshot_date": "2026-06-15",
        "side": "asset",
        "category": "예금",
        "item_name": "Synthetic Deposit",
        "amount": 1_250_000.0,
        "currency": "KRW",
        "source_fact_id": "fact-1",
        "file_id": "260615_1",
        "source_row": 5,
    }
    assert list(row) == BANKSALAD_BALANCE_COLUMNS


def test_assemble_balance_snapshot_row_falls_back_item_name_to_category() -> None:
    """Missing item name uses category; the stored category stays the original value."""
    # Arrange
    fields = _fields(item_name=None, category="예금")

    # Act
    row = _assemble_balance_snapshot_row(_block_context(), fields)

    # Assert
    assert row is not None
    assert row["item_name"] == "예금"
    assert row["category"] == "예금"


@pytest.mark.parametrize(
    "overrides",
    [
        {"amount": None},
        {"item_name": None, "category": None},
        {"item_name": "", "category": None},
        {"item_name": "합계"},
        {"item_name": "총계"},
        {"item_name": "총자산"},
        {"item_name": "총부채"},
        {"item_name": " 합계 "},
        {"item_name": None, "category": "합계"},
        {"source_fact_id": None},
    ],
)
def test_assemble_balance_snapshot_row_drops_incomplete_or_summary_rows(
    overrides: dict[str, object],
) -> None:
    """Drop rows missing amount, a non-summary name, or a source fact id."""
    # Arrange
    fields = _fields(**overrides)

    # Act
    row = _assemble_balance_snapshot_row(_block_context(), fields)

    # Assert
    assert row is None


@pytest.mark.parametrize("item_name", ["이체", "내부이체", "계좌이체", "transfer"])
def test_assemble_balance_snapshot_row_does_not_exclude_transfer_labels(
    item_name: str,
) -> None:
    """Transfer-like labels are not a skip rule at the assembly layer."""
    # Arrange
    fields = _fields(item_name=item_name)

    # Act
    row = _assemble_balance_snapshot_row(_block_context(), fields)

    # Assert
    assert row is not None
    assert row["item_name"] == item_name


def test_assemble_balance_snapshot_row_keeps_zero_and_negative_amounts() -> None:
    """Only a missing amount is dropped; zero and negative values stay."""
    # Arrange / Act
    zero_row = _assemble_balance_snapshot_row(_block_context(), _fields(amount=0.0))
    negative_row = _assemble_balance_snapshot_row(
        _block_context(),
        _fields(side="liability", amount=-50_000.0),
    )

    # Assert
    assert zero_row is not None
    assert zero_row["amount"] == 0.0
    assert negative_row is not None
    assert negative_row["amount"] == -50_000.0
    assert negative_row["side"] == "liability"
