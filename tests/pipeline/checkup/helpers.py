"""Shared fixtures for checkup collector and composer tests."""

from __future__ import annotations

from pathlib import Path

import polars as pl


def init_data_dir(tmp_path: Path, name: str = "data") -> Path:
    """Create a minimal initialized finjuice data directory."""
    data_dir = tmp_path / name
    data_dir.mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def write_transactions(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write one transaction partition for tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "transactions" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "transactions.csv")


def write_snapshot(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write one asset snapshot partition for tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "assets" / "snapshots" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "snapshots.csv")


def month_labels(start_year: int, start_month: int, count: int) -> list[str]:
    """Return count YYYY-MM labels starting at year/month."""
    labels: list[str] = []
    year = start_year
    month = start_month
    for _ in range(count):
        labels.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return labels


def _tx_row(
    tx_date: str,
    amount: float,
    merchant: str,
    *,
    category_final: str,
    tags_final: str,
    needs_review: int = 0,
    confidence: float | None = 0.95,
    type_norm: str = "expense",
    type_raw: str = "지출",
    is_transfer: int = 0,
    row_hash: str | None = None,
) -> dict[str, object]:
    """Build a canonical transaction row for checkup tests."""
    row_id = row_hash or f"{tx_date}-{merchant}-{int(amount)}"
    time_value = "09:00" if amount >= 0 else "13:00"
    return {
        "row_hash": row_id,
        "date": tx_date,
        "time": time_value,
        "datetime": f"{tx_date}T{time_value}:00",
        "type_raw": type_raw,
        "type_norm": type_norm,
        "major_raw": category_final,
        "minor_raw": category_final,
        "merchant_raw": merchant,
        "memo_raw": None,
        "amount": amount,
        "account": "테스트계좌",
        "currency": "KRW",
        "counterparty": None,
        "category_rule": category_final,
        "category_final": category_final,
        "tags_rule": tags_final,
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": tags_final,
        "confidence": confidence,
        "needs_review": needs_review,
        "is_transfer": is_transfer,
        "transfer_group_id": None,
        "file_id": "fixture_1",
        "source_row": 1,
    }
