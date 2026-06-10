"""Shared CLI fixtures for report_filters integration tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.storage.csv_transactions import write_month

runner = CliRunner()


def transaction_row(
    *,
    row_hash: str,
    date: str,
    merchant: str,
    amount: float,
    category: str,
) -> dict[str, object]:
    """Build a minimal transaction row for CLI filter tests."""
    return {
        "row_hash": row_hash,
        "date": date,
        "time": "09:00",
        "datetime": f"{date}T09:00:00",
        "type_raw": "지출" if amount < 0 else "수입",
        "type_norm": "expense" if amount < 0 else "income",
        "merchant_raw": merchant,
        "amount": amount,
        "account": "테스트카드",
        "category_final": category,
        "tags_final": ["테스트"],
        "is_transfer": 0,
    }


def write_rules_yaml(data_dir: Path, content: str) -> None:
    """Write rules.yaml for a CLI fixture."""
    (data_dir / "rules.yaml").write_text(
        textwrap.dedent(content).strip() + "\n",
        encoding="utf-8",
    )


def build_cli_data_dir(tmp_path: Path, rules_yaml: str) -> Path:
    """Create a minimal data directory for CLI report filter tests."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "metadata").mkdir(parents=True)
    (data_dir / "exports").mkdir(parents=True)
    write_rules_yaml(data_dir, rules_yaml)
    return data_dir


@pytest.fixture
def no_report_filters_data_dir(tmp_path: Path) -> Path:
    """Create a dataset without a report_filters block."""
    data_dir = build_cli_data_dir(
        tmp_path,
        """
        version: 1
        rules: []
        """,
    )
    rows = [
        transaction_row(
            row_hash="keep-1",
            date="2024-10-20",
            merchant="마트",
            amount=-50000.0,
            category="식비",
        )
    ]
    write_month(data_dir / "transactions", pl.DataFrame(rows), 2024, 10)
    return data_dir


@pytest.fixture
def report_filters_data_dir(tmp_path: Path) -> Path:
    """Create a dataset with overlapping report_filters for counter semantics tests."""
    data_dir = build_cli_data_dir(
        tmp_path,
        """
        version: 1
        report_filters:
          excluded_merchants:
            - pattern: "서울종합병원"
              reason: "진료 종료"
          excluded_categories:
            - name: "의료"
              reason: "병원비 제외"
          excluded_date_ranges:
            - start: "2024-10-10"
              end: "2024-10-10"
              reason: "이사 비용"
        rules: []
        """,
    )
    rows = [
        transaction_row(
            row_hash="hospital-overlap",
            date="2024-10-02",
            merchant="서울종합병원",
            amount=-100000.0,
            category="의료",
        ),
        transaction_row(
            row_hash="move-date-range",
            date="2024-10-10",
            merchant="이사센터",
            amount=-300000.0,
            category="생활",
        ),
        transaction_row(
            row_hash="keep-row",
            date="2024-10-20",
            merchant="마트",
            amount=-50000.0,
            category="식비",
        ),
    ]
    write_month(data_dir / "transactions", pl.DataFrame(rows), 2024, 10)
    return data_dir
