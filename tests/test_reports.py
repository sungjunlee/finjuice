"""
Unit tests for CSV report generation.

Tests export functions that generate reports from CSV partitions.
"""

import csv
from pathlib import Path
from typing import Any, Dict

import polars as pl
import pytest

from finjuice.pipeline.constants import REPORTS_COUNT
from finjuice.pipeline.export.reports import (
    export_by_account,
    export_by_category,
    export_by_tag,
    export_monthly_spend,
    export_transfers,
    generate_all_reports,
)
from finjuice.pipeline.storage import csv_partition


@pytest.fixture
def temp_csv_base_dir(tmp_path: Path):  # type: ignore[misc]
    """Create a temporary CSV partitions directory."""
    csv_dir = tmp_path / "transactions"
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir


@pytest.fixture
def sample_transactions() -> list[Dict[str, Any]]:
    """Sample transaction data for testing reports."""
    return [
        # Month 1: 2025-01
        {
            "row_hash": "a" * 64,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "외식",
            "merchant_raw": "스타벅스",
            "memo_raw": "커피",
            "amount": -5000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "스타벅스",
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["카페", "커피"],
            "tags_ai": [],
            "tags_final": ["카페", "커피"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "row_hash": "b" * 64,
            "file_id": "250101_1",
            "source_row": 2,
            "date": "2025-01-20",
            "time": "19:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "외식",
            "merchant_raw": "맥도날드",
            "memo_raw": "저녁",
            "amount": -10000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "맥도날드",
            "datetime": "2025-01-20T19:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["외식"],
            "tags_ai": [],
            "tags_final": ["외식"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        # Month 2: 2025-02
        {
            "row_hash": "c" * 64,
            "file_id": "250101_1",
            "source_row": 3,
            "date": "2025-02-10",
            "time": "10:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "교통",
            "minor_raw": "지하철",
            "merchant_raw": "서울교통공사",
            "memo_raw": "지하철",
            "amount": -2000,
            "account": "체크카드",
            "currency": "KRW",
            "counterparty": "서울교통공사",
            "datetime": "2025-02-10T10:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["교통"],
            "tags_ai": [],
            "tags_final": ["교통"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        # Transfer pair
        {
            "row_hash": "d" * 64,
            "file_id": "250101_1",
            "source_row": 4,
            "date": "2025-02-15",
            "time": "14:00",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한은행",
            "memo_raw": "계좌이체",
            "amount": -100000,
            "account": "신한은행",
            "currency": "KRW",
            "counterparty": "우리은행",
            "datetime": "2025-02-15T14:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 1,
            "transfer_group_id": "T0001",
        },
        {
            "row_hash": "e" * 64,
            "file_id": "250101_1",
            "source_row": 5,
            "date": "2025-02-15",
            "time": "14:01",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "우리은행",
            "memo_raw": "계좌이체",
            "amount": 100000,
            "account": "우리은행",
            "currency": "KRW",
            "counterparty": "신한은행",
            "datetime": "2025-02-15T14:01:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 1,
            "transfer_group_id": "T0001",
        },
    ]


def insert_transactions_to_csv(csv_base_dir: Path, transactions: list[Dict[str, Any]]) -> None:
    """Helper function to insert test transactions into CSV partitions."""
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)


# Test 1: export_monthly_spend success
def test_export_monthly_spend_success(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test monthly spend report generation with multiple months."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "monthly_spend.csv"

    # Act
    export_monthly_spend(temp_csv_base_dir, output_path)

    # Assert
    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2  # 2 months
    # Check February (should exclude transfers)
    feb_row = [r for r in rows if r["month"] == "2025-02"][0]
    assert float(feb_row["total_spend"]) == -2000  # Only subway, not transfers
    # Check January
    jan_row = [r for r in rows if r["month"] == "2025-01"][0]
    assert float(jan_row["total_spend"]) == -15000  # Coffee + McDonald's


# Test 2: export_by_tag success
def test_export_by_tag_success(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test tag-based spending report generation."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "by_tag.csv"

    # Act
    export_by_tag(temp_csv_base_dir, output_path)

    # Assert
    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) >= 3  # At least 3 unique tags
    tags = {r["tag"] for r in rows}
    assert "카페" in tags
    assert "외식" in tags
    assert "교통" in tags


# Test 3: export_by_account success
def test_export_by_account_success(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test account-based spending report generation."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "by_account.csv"

    # Act
    export_by_account(temp_csv_base_dir, output_path)

    # Assert
    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) >= 2  # At least 2 accounts
    accounts = {r["account"] for r in rows}
    assert "신한카드" in accounts
    assert "체크카드" in accounts


# Test 4: export_transfers success
def test_export_transfers_success(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test transfer audit log generation."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "transfers.csv"

    # Act
    export_transfers(temp_csv_base_dir, output_path)

    # Assert
    assert output_path.exists()
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert len(rows) == 2  # 2 transfer transactions
    assert all(r["transfer_group_id"] == "T0001" for r in rows)
    assert any(float(r["amount"]) == -100000 for r in rows)
    assert any(float(r["amount"]) == 100000 for r in rows)


# Test 5: generate_all_reports creates directory
def test_generate_all_reports_creates_directory(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test that generate_all_reports creates output directory if not exists."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    reports_dir = tmp_path / "reports"
    assert not reports_dir.exists()

    # Act
    summary = generate_all_reports(temp_csv_base_dir, reports_dir)

    # Assert
    assert reports_dir.exists()
    assert (reports_dir / "monthly_spend.csv").exists()
    assert (reports_dir / "by_category.csv").exists()
    assert (reports_dir / "by_tag.csv").exists()
    assert (reports_dir / "by_account.csv").exists()
    assert (reports_dir / "transfers.csv").exists()
    assert summary["reports"] == 5


# Test 6: generate_all_reports handles empty CSV partitions
def test_generate_all_reports_handles_empty_partitions(
    temp_csv_base_dir: Path, tmp_path: Path
) -> None:
    """Test report generation with empty CSV partitions.

    Note: When there are no transactions, CSV export functions return 0
    and do NOT create empty files (consistent with master export behavior).
    """
    # Arrange
    reports_dir = tmp_path / "reports"

    # Act
    summary = generate_all_reports(temp_csv_base_dir, reports_dir)

    # Assert
    assert reports_dir.exists()
    # No CSV files created when there's no data (they return 0 without creating files)
    assert not (reports_dir / "monthly_spend.csv").exists()
    assert summary["monthly_spend"] == 0
    assert summary["by_tag"] == 0
    assert summary["by_account"] == 0
    assert summary["transfers"] == 0
    # All export functions were called successfully (even if they returned 0 rows)
    assert summary["reports"] == 5


# Test 7: CSV encoding UTF-8 BOM
def test_csv_encoding_utf8_bom(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test that CSV files have UTF-8 BOM for Korean Excel compatibility."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "by_tag.csv"

    # Act
    export_by_tag(temp_csv_base_dir, output_path)

    # Assert
    with open(output_path, "rb") as f:
        first_bytes = f.read(3)
        assert first_bytes == b"\xef\xbb\xbf"  # UTF-8 BOM


# Test 8: generate_all_reports returns correct summary
def test_generate_all_reports_returns_summary(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test that generate_all_reports returns accurate summary."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    reports_dir = tmp_path / "reports"

    # Act
    summary = generate_all_reports(temp_csv_base_dir, reports_dir)

    # Assert
    assert summary["reports"] == 5
    assert summary["output_dir"] == str(reports_dir)
    assert summary["monthly_spend"] == 2  # 2 months
    # At least 3 unique tags
    assert isinstance(summary["by_tag"], int) and summary["by_tag"] >= 3
    # At least 2 accounts
    assert isinstance(summary["by_account"], int) and summary["by_account"] >= 2
    assert summary["transfers"] == 2  # 2 transfer transactions


def test_reports_count_matches_generated_report_set(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test REPORTS_COUNT tracks the reports generate_all_reports produces."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    reports_dir = tmp_path / "reports"

    # Act
    summary = generate_all_reports(temp_csv_base_dir, reports_dir)

    # Assert
    generated_reports = {path.name for path in reports_dir.glob("*.csv")}
    assert len(generated_reports) == summary["reports"] == REPORTS_COUNT


def test_csv_reports_neutralize_formula_strings_without_mutating_source_df(
    temp_csv_base_dir: Path, tmp_path: Path
) -> None:
    """CSV report string cells are safe for spreadsheets while source frames stay raw."""
    # Arrange
    source_df = pl.DataFrame(
        [
            {
                "date": "2025-01-15",
                "type_norm": "expense",
                "amount": -5000,
                "account": "=위험카드",
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "date": "2025-01-16",
                "type_norm": "expense",
                "amount": -7000,
                "account": "현금",
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
    )
    original_source = source_df.clone()
    output_path = tmp_path / "by_account.csv"

    # Act
    row_count = export_by_account(temp_csv_base_dir, output_path, source_df=source_df)

    # Assert
    assert row_count == 2
    with open(output_path, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    accounts = {row["account"]: float(row["net_total"]) for row in rows}
    assert accounts["'=위험카드"] == -5000
    assert accounts["현금"] == -7000
    assert source_df.to_dict(as_series=False) == original_source.to_dict(as_series=False)


# Test 9: export_monthly_spend with only income transactions
def test_export_monthly_spend_income_only(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Test monthly spend report excludes income transactions."""
    # Arrange
    income_transactions = [
        {
            "row_hash": "income1",
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "09:00",
            "type_raw": "수입",
            "type_norm": "income",
            "major_raw": "급여",
            "minor_raw": None,
            "merchant_raw": "회사",
            "memo_raw": "월급",
            "amount": 3000000,
            "account": "급여계좌",
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-15T09:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["급여"],
            "tags_ai": [],
            "tags_final": ["급여"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        }
    ]
    insert_transactions_to_csv(temp_csv_base_dir, income_transactions)
    output_path = tmp_path / "monthly_spend.csv"

    # Act
    row_count = export_monthly_spend(temp_csv_base_dir, output_path)

    # Assert - income transactions have type_norm='income', not 'expense'
    # So monthly_spend should be 0 (only expense types are included)
    assert row_count == 0


# Test 10: export_by_tag with empty tags_final
def test_export_by_tag_empty_tags(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Test by_tag report handles transactions with no tags."""
    # Arrange - transactions with empty tags_final
    empty_tag_transactions = [
        {
            "row_hash": "notag1",
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "외식",
            "merchant_raw": "미분류식당",
            "memo_raw": "점심",
            "amount": -8000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "미분류식당",
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],  # Empty tags
            "confidence": 0.3,
            "needs_review": 1,
            "is_transfer": 0,
            "transfer_group_id": None,
        }
    ]
    insert_transactions_to_csv(temp_csv_base_dir, empty_tag_transactions)
    output_path = tmp_path / "by_tag.csv"

    # Act
    row_count = export_by_tag(temp_csv_base_dir, output_path)

    # Assert - should return 0 since no valid tags
    assert row_count == 0


# Test 10b: export_by_tag excludes income transactions (bug fix verification)
def test_export_by_tag_excludes_income(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Test by_tag report excludes income transactions (only expenses included).

    This test verifies the bug fix where income transactions were incorrectly
    included in the by_tag report, causing positive amounts to appear.

    Scenario:
    - Expense transaction: -50,000원 with tag "디지털서비스"
    - Income transaction: +100,000원 with tag "디지털서비스"
    - Expected: Only expense (-50,000원) should appear in by_tag report
    """
    # Arrange - both expense and income with same tag
    mixed_transactions = [
        {
            "row_hash": "expense_kakao",
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "10:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "디지털",
            "minor_raw": None,
            "merchant_raw": "카카오",
            "memo_raw": None,
            "amount": -50000,
            "account": "카카오뱅크",
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-15T10:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["디지털서비스", "카카오"],
            "tags_ai": [],
            "tags_final": ["디지털서비스", "카카오"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "row_hash": "income_kakao",
            "file_id": "250101_1",
            "source_row": 2,
            "date": "2025-01-20",
            "time": "14:00",
            "type_raw": "수입",
            "type_norm": "income",  # Income transaction
            "major_raw": "수입",
            "minor_raw": None,
            "merchant_raw": "카카오페이 환급",
            "memo_raw": "포인트 환급",
            "amount": 100000,  # Positive income
            "account": "카카오뱅크",
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-20T14:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["디지털서비스", "카카오"],
            "tags_ai": [],
            "tags_final": ["디지털서비스", "카카오"],  # Same tags as expense
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
    ]
    insert_transactions_to_csv(temp_csv_base_dir, mixed_transactions)
    output_path = tmp_path / "by_tag.csv"

    # Act
    row_count = export_by_tag(temp_csv_base_dir, output_path)

    # Assert
    assert row_count == 2  # Two tags: 디지털서비스, 카카오

    # Read and verify the report
    import polars as pl

    df = pl.read_csv(output_path)

    # All amounts should be negative (expenses only)
    for row in df.iter_rows(named=True):
        assert row["total"] < 0, f"Tag '{row['tag']}' has positive amount {row['total']}"

    # Check specific tag amounts (should be -50000, not +50000 from income-expense diff)
    kakao_row = df.filter(pl.col("tag") == "카카오")
    assert len(kakao_row) == 1
    assert float(kakao_row["total"][0]) == -50000  # Only expense, income excluded


# Test 11: export_by_account with multiple accounts including income
def test_export_by_account_multiple_with_income(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Test by_account report correctly aggregates multiple accounts."""
    # Arrange
    multi_account_transactions = [
        {
            "row_hash": "card1",
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-10",
            "time": "10:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": None,
            "merchant_raw": "카페",
            "memo_raw": None,
            "amount": -5000,
            "account": "삼성카드",
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-10T10:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "row_hash": "card2",
            "file_id": "250101_1",
            "source_row": 2,
            "date": "2025-01-11",
            "time": "11:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "교통",
            "minor_raw": None,
            "merchant_raw": "택시",
            "memo_raw": None,
            "amount": -15000,
            "account": "삼성카드",
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-11T11:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "row_hash": "bank1",
            "file_id": "250101_1",
            "source_row": 3,
            "date": "2025-01-15",
            "time": "09:00",
            "type_raw": "수입",
            "type_norm": "income",
            "major_raw": "급여",
            "minor_raw": None,
            "merchant_raw": "회사",
            "memo_raw": None,
            "amount": 3000000,
            "account": "신한은행",
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-15T09:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
    ]
    insert_transactions_to_csv(temp_csv_base_dir, multi_account_transactions)
    output_path = tmp_path / "by_account.csv"

    # Act
    row_count = export_by_account(temp_csv_base_dir, output_path)

    # Assert
    assert row_count == 2  # 2 accounts (삼성카드, 신한은행)
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    accounts = {r["account"]: float(r["net_total"]) for r in rows}
    assert accounts["삼성카드"] == -20000  # -5000 + -15000
    assert accounts["신한은행"] == 3000000  # Income


# Test 12: export_transfers with no transfers
def test_export_transfers_no_transfers(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Test transfers report handles case with no transfer transactions."""
    # Arrange - only expense, no transfers
    expense_only = [
        {
            "row_hash": "exp1",
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": None,
            "merchant_raw": "식당",
            "memo_raw": None,
            "amount": -10000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        }
    ]
    insert_transactions_to_csv(temp_csv_base_dir, expense_only)
    output_path = tmp_path / "transfers.csv"

    # Act
    row_count = export_transfers(temp_csv_base_dir, output_path)

    # Assert - should return 0 and not create file (no data to export)
    assert row_count == 0


# Test 13: export_monthly_spend return value
def test_export_monthly_spend_return_value(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test that export_monthly_spend returns correct row count."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "monthly_spend.csv"

    # Act
    row_count = export_monthly_spend(temp_csv_base_dir, output_path)

    # Assert
    assert row_count == 2  # 2 months (Jan and Feb)


# Test 14: export_by_tag return value
def test_export_by_tag_return_value(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test that export_by_tag returns correct row count."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "by_tag.csv"

    # Act
    row_count = export_by_tag(temp_csv_base_dir, output_path)

    # Assert - at least 3 unique tags (카페, 커피, 외식, 교통)
    assert row_count >= 3


# Test 15: export_transfers correct grouping
def test_export_transfers_grouped_by_id(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test transfers report preserves transfer_group_id for audit."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    output_path = tmp_path / "transfers.csv"

    # Act
    export_transfers(temp_csv_base_dir, output_path)

    # Assert
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    # Both transfers should have same group_id
    group_ids = [r["transfer_group_id"] for r in rows]
    assert all(gid == "T0001" for gid in group_ids)


# Test 16: export with special characters in merchant names
def test_export_special_characters(temp_csv_base_dir: Path, tmp_path: Path) -> None:
    """Test export handles Korean and special characters properly."""
    # Arrange
    special_char_transactions = [
        {
            "row_hash": "special1",
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "카페",
            "merchant_raw": "(주)스타벅스코리아",  # Korean with parentheses
            "memo_raw": "아메리카노 & 케이크",  # Ampersand
            "amount": -10000,
            "account": "신한카드(개인)",  # Parentheses in account
            "currency": "KRW",
            "counterparty": None,
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["카페", "커피"],
            "tags_ai": [],
            "tags_final": ["카페", "커피"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        }
    ]
    insert_transactions_to_csv(temp_csv_base_dir, special_char_transactions)
    output_path = tmp_path / "by_account.csv"

    # Act
    row_count = export_by_account(temp_csv_base_dir, output_path)

    # Assert
    assert row_count == 1
    with open(output_path, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    assert rows[0]["account"] == "신한카드(개인)"


# Test 17: generate_all_reports success path
def test_generate_all_reports_success(
    temp_csv_base_dir: Path, sample_transactions: list[Dict[str, Any]], tmp_path: Path
) -> None:
    """Test that generate_all_reports succeeds with valid data."""
    # Arrange
    insert_transactions_to_csv(temp_csv_base_dir, sample_transactions)
    reports_dir = tmp_path / "reports"

    # Act
    summary = generate_all_reports(temp_csv_base_dir, reports_dir)

    # Assert - all reports should succeed
    assert summary["reports"] == 5


class TestReportsEdgeCases:
    """Additional edge case tests for reports module."""

    def test_export_monthly_spend_single_month(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test monthly spend with only one month of data."""
        # Arrange
        single_month = [
            {
                "row_hash": "single1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-03-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -25000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-03-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, single_month)
        output_path = tmp_path / "monthly_spend.csv"

        # Act
        row_count = export_monthly_spend(temp_csv_base_dir, output_path)

        # Assert
        assert row_count == 1
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["month"] == "2025-03"
        assert float(rows[0]["total_spend"]) == -25000

    def test_export_by_tag_multiple_tags_per_transaction(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test by_tag correctly explodes multiple tags per transaction."""
        # Arrange - one transaction with 3 tags
        multi_tag = [
            {
                "row_hash": "multi1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "카페",
                "memo_raw": None,
                "amount": -10000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": ["카페", "커피", "디저트"],
                "tags_ai": [],
                "tags_final": ["카페", "커피", "디저트"],  # 3 tags
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, multi_tag)
        output_path = tmp_path / "by_tag.csv"

        # Act
        row_count = export_by_tag(temp_csv_base_dir, output_path)

        # Assert - should have 3 rows (one per tag)
        assert row_count == 3
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        tags = {r["tag"] for r in rows}
        assert tags == {"카페", "커피", "디저트"}
        # Each tag should have the same total (full amount allocated to each tag)
        for row in rows:
            assert float(row["total"]) == -10000

    def test_export_transfers_sorted_by_datetime(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test transfers report is sorted by datetime descending."""
        # Arrange - multiple transfers at different times
        transfers = [
            {
                "row_hash": "tf1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-10",
                "time": "10:00",
                "type_raw": "이체",
                "type_norm": "transfer",
                "major_raw": "이체",
                "minor_raw": None,
                "merchant_raw": "은행A",
                "memo_raw": None,
                "amount": -50000,
                "account": "계좌A",
                "currency": "KRW",
                "counterparty": "계좌B",
                "datetime": "2025-01-10T10:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 1,
                "transfer_group_id": "TF01",
            },
            {
                "row_hash": "tf2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-20",
                "time": "15:00",
                "type_raw": "이체",
                "type_norm": "transfer",
                "major_raw": "이체",
                "minor_raw": None,
                "merchant_raw": "은행B",
                "memo_raw": None,
                "amount": -100000,
                "account": "계좌C",
                "currency": "KRW",
                "counterparty": "계좌D",
                "datetime": "2025-01-20T15:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 1,
                "transfer_group_id": "TF02",
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, transfers)
        output_path = tmp_path / "transfers.csv"

        # Act
        export_transfers(temp_csv_base_dir, output_path)

        # Assert - most recent first
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        datetimes = [r["datetime"] for r in rows]
        assert datetimes == sorted(datetimes, reverse=True)  # Descending

    def test_export_monthly_spend_sorted_descending(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test monthly spend report is sorted by month descending."""
        # Arrange - transactions over multiple months
        multi_month = [
            {
                "row_hash": f"mm{i}",
                "file_id": "250101_1",
                "source_row": i,
                "date": f"2025-0{i}-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -10000 * i,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": f"2025-0{i}-15T14:30:00",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
            for i in range(1, 5)  # Jan to Apr
        ]
        insert_transactions_to_csv(temp_csv_base_dir, multi_month)
        output_path = tmp_path / "monthly_spend.csv"

        # Act
        export_monthly_spend(temp_csv_base_dir, output_path)

        # Assert - months should be in descending order
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        months = [r["month"] for r in rows]
        assert months == sorted(months, reverse=True)  # Descending

    def test_export_by_tag_sorted_by_total_ascending(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test by_tag report is sorted by total ascending (largest expenses first)."""
        # Arrange - different amounts per tag
        varied_amounts = [
            {
                "row_hash": "va1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -50000,  # Largest expense
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": ["외식"],
                "tags_ai": [],
                "tags_final": ["외식"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "va2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "교통",
                "minor_raw": None,
                "merchant_raw": "택시",
                "memo_raw": None,
                "amount": -10000,  # Smaller expense
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-16T10:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": ["교통"],
                "tags_ai": [],
                "tags_final": ["교통"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, varied_amounts)
        output_path = tmp_path / "by_tag.csv"

        # Act
        export_by_tag(temp_csv_base_dir, output_path)

        # Assert - sorted ascending (largest expenses are most negative, so first)
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        totals = [float(r["total"]) for r in rows]
        assert totals == sorted(totals)  # Ascending


class TestReportsTransferExclusion:
    """Tests verifying that transfers are correctly excluded from reports."""

    def test_monthly_spend_excludes_transfers(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that monthly spend excludes transfer transactions."""
        # Arrange - mix of expenses and transfers in same month
        mixed_transactions = [
            {
                "row_hash": "exp1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -30000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "tf1",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "10:00",
                "type_raw": "이체",
                "type_norm": "transfer",
                "major_raw": "이체",
                "minor_raw": None,
                "merchant_raw": "은행",
                "memo_raw": None,
                "amount": -100000,  # Should NOT be included
                "account": "은행A",
                "currency": "KRW",
                "counterparty": "은행B",
                "datetime": "2025-01-16T10:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 1,  # Transfer flag
                "transfer_group_id": "TF01",
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, mixed_transactions)
        output_path = tmp_path / "monthly_spend.csv"

        # Act
        export_monthly_spend(temp_csv_base_dir, output_path)

        # Assert - only expense amount, not transfer
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert float(rows[0]["total_spend"]) == -30000  # Only the expense

    def test_monthly_spend_keeps_unpaired_transfer_candidate(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Unpaired transfer-like outgoing payments should remain counted as spend."""
        # Arrange
        mixed_transactions = [
            {
                "row_hash": "expense",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -30000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer_candidate": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "candidate_spend",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "10:00",
                "type_raw": "이체",
                "type_norm": "expense",
                "major_raw": "송금",
                "minor_raw": None,
                "merchant_raw": "학원비 송금",
                "memo_raw": None,
                "amount": -100000,
                "account": "은행A",
                "currency": "KRW",
                "counterparty": "학원",
                "datetime": "2025-01-16T10:00:00",
                "category_rule": None,
                "category_final": "교육",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer_candidate": 1,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "confirmed_transfer",
                "file_id": "250101_1",
                "source_row": 3,
                "date": "2025-01-16",
                "time": "11:00",
                "type_raw": "이체",
                "type_norm": "expense",
                "major_raw": "내계좌이체",
                "minor_raw": None,
                "merchant_raw": "은행",
                "memo_raw": None,
                "amount": -200000,
                "account": "은행A",
                "currency": "KRW",
                "counterparty": "은행B",
                "datetime": "2025-01-16T11:00:00",
                "category_rule": None,
                "category_final": "이체",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer_candidate": 1,
                "is_transfer": 1,
                "transfer_group_id": "TF01",
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, mixed_transactions)
        output_path = tmp_path / "monthly_spend.csv"

        # Act
        export_monthly_spend(temp_csv_base_dir, output_path)

        # Assert
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert float(rows[0]["total_spend"]) == -130000

    def test_monthly_spend_keeps_legacy_unpaired_transfer_candidate(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Legacy unpaired candidates with is_transfer=1 but no group stay in spend."""
        # Arrange
        legacy_candidate = [
            {
                "row_hash": "legacy_candidate",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-16",
                "time": "10:00",
                "type_raw": "이체",
                "type_norm": "expense",
                "major_raw": "송금",
                "minor_raw": None,
                "merchant_raw": "학원비 송금",
                "memo_raw": None,
                "amount": -100000,
                "account": "은행A",
                "currency": "KRW",
                "counterparty": "학원",
                "datetime": "2025-01-16T10:00:00",
                "category_rule": None,
                "category_final": "교육",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer_candidate": 1,
                "is_transfer": 1,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, legacy_candidate)
        output_path = tmp_path / "monthly_spend.csv"

        # Act
        export_monthly_spend(temp_csv_base_dir, output_path)

        # Assert
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert float(rows[0]["total_spend"]) == -100000

    def test_by_tag_excludes_transfers(self, temp_csv_base_dir: Path, tmp_path: Path) -> None:
        """Test that by_tag excludes transfer transactions."""
        # Arrange - transfers with tags (should be excluded)
        transfer_with_tag = [
            {
                "row_hash": "twt1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -20000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": ["외식"],
                "tags_ai": [],
                "tags_final": ["외식"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "twt2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "10:00",
                "type_raw": "이체",
                "type_norm": "transfer",
                "major_raw": "이체",
                "minor_raw": None,
                "merchant_raw": "은행",
                "memo_raw": None,
                "amount": -100000,
                "account": "은행A",
                "currency": "KRW",
                "counterparty": "은행B",
                "datetime": "2025-01-16T10:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": ["내부이체"],
                "tags_ai": [],
                "tags_final": ["내부이체"],  # Transfer with tag
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 1,  # Transfer flag
                "transfer_group_id": "TF01",
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, transfer_with_tag)
        output_path = tmp_path / "by_tag.csv"

        # Act
        row_count = export_by_tag(temp_csv_base_dir, output_path)

        # Assert - only "외식" tag, not "내부이체"
        assert row_count == 1
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["tag"] == "외식"

    def test_by_account_excludes_transfers(self, temp_csv_base_dir: Path, tmp_path: Path) -> None:
        """Test that by_account excludes transfer transactions."""
        # Arrange
        account_with_transfer = [
            {
                "row_hash": "awt1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -25000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "awt2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "10:00",
                "type_raw": "이체",
                "type_norm": "transfer",
                "major_raw": "이체",
                "minor_raw": None,
                "merchant_raw": "은행",
                "memo_raw": None,
                "amount": -100000,  # Transfer (excluded)
                "account": "신한카드",  # Same account
                "currency": "KRW",
                "counterparty": "우리은행",
                "datetime": "2025-01-16T10:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 1,
                "transfer_group_id": "TF01",
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, account_with_transfer)
        output_path = tmp_path / "by_account.csv"

        # Act
        export_by_account(temp_csv_base_dir, output_path)

        # Assert - only expense amount, not transfer
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 1
        assert float(rows[0]["net_total"]) == -25000  # Only expense


class TestReportsRefundHandling:
    """Tests verifying that refunds (positive amounts with expense type) are handled correctly.

    Banksalad marks refunds/cancellations as type='지출' with POSITIVE amount.
    These should reduce total spending when aggregated (Issue: refund-handling-fix).
    """

    def test_monthly_spend_with_refund_reduces_total(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that refunds (positive expense) reduce monthly spending total.

        Scenario:
        - Normal expense: -100,000원 (purchase)
        - Refund: +30,000원 (partial refund, type still '지출')
        - Expected total: -70,000원 (100k - 30k = 70k net expense)
        """
        # Arrange - expense and refund in same month
        transactions_with_refund = [
            {
                "row_hash": "exp_normal1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "쇼핑",
                "minor_raw": "백화점",
                "merchant_raw": "현대백화점",
                "memo_raw": None,
                "amount": -100000,  # Normal purchase
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": "[]",
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": "[]",
                "confidence": None,
                "needs_review": None,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "refund1",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-20",
                "time": "11:00",
                "type_raw": "지출",  # Banksalad marks refunds as "지출"
                "type_norm": "expense",  # type_norm is still expense
                "major_raw": "쇼핑",
                "minor_raw": "백화점",
                "merchant_raw": "현대백화점",
                "memo_raw": "부분환불",
                "amount": 30000,  # POSITIVE = refund/cancellation
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-20T11:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": "[]",
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": "[]",
                "confidence": None,
                "needs_review": None,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, transactions_with_refund)
        output_path = tmp_path / "monthly_spend.csv"

        # Act
        export_monthly_spend(temp_csv_base_dir, output_path)

        # Assert - refund should reduce total spending
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        jan_row = rows[0]
        assert jan_row["month"] == "2025-01"
        # -100,000 (expense) + 30,000 (refund) = -70,000 net expense
        assert float(jan_row["total_spend"]) == -70000

    def test_monthly_spend_full_refund_cancels_out(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that full refund completely cancels out the original expense.

        Scenario: 아시아나 항공권 구매 후 전액 취소
        - Original purchase: -349,100원
        - Full refund: +349,100원
        - Expected total: 0원
        """
        # Arrange
        full_refund_scenario = [
            {
                "row_hash": "flight_purchase",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-10",
                "time": "09:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "여행",
                "minor_raw": "항공",
                "merchant_raw": "아시아나항공",
                "memo_raw": "제주도 항공권",
                "amount": -349100,  # Original purchase
                "account": "삼성카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-10T09:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": "[]",
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": "[]",
                "confidence": None,
                "needs_review": None,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "flight_cancel",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-12",
                "time": "15:30",
                "type_raw": "지출",  # Still marked as "지출" by Banksalad
                "type_norm": "expense",
                "major_raw": "여행",
                "minor_raw": "항공",
                "merchant_raw": "아시아나항공",
                "memo_raw": "항공권 취소 환불",
                "amount": 349100,  # Full refund (positive)
                "account": "삼성카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-12T15:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": "[]",
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": "[]",
                "confidence": None,
                "needs_review": None,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, full_refund_scenario)
        output_path = tmp_path / "monthly_spend.csv"

        # Act
        export_monthly_spend(temp_csv_base_dir, output_path)

        # Assert - full refund cancels out
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert float(rows[0]["total_spend"]) == 0  # Completely cancelled out

    def test_by_tag_with_refund(self, temp_csv_base_dir: Path, tmp_path: Path) -> None:
        """Test that tag breakdown correctly handles refunds."""
        # Arrange - purchases and refund with same tag
        tagged_with_refund = [
            {
                "row_hash": "cafe1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스",
                "memo_raw": None,
                "amount": -15000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": '["카페"]',
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": '["카페"]',
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "cafe_refund",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-15",
                "time": "10:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스",
                "memo_raw": "주문 취소",
                "amount": 5000,  # Partial refund (positive)
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": '["카페"]',
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": '["카페"]',
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, tagged_with_refund)
        output_path = tmp_path / "by_tag.csv"

        # Act
        export_by_tag(temp_csv_base_dir, output_path)

        # Assert
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["tag"] == "카페"
        # -15,000 + 5,000 = -10,000 net expense for 카페 tag
        assert float(rows[0]["total"]) == -10000


class TestReportsErrorHandling:
    """Test error handling in reports generation (Issue: code-quality-improvements)."""

    def test_generate_all_reports_handles_permission_error(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that generate_all_reports handles PermissionError gracefully."""
        # Arrange - create sample data
        sample_data = [
            {
                "row_hash": "perm1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": ["식비"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)
        reports_dir = tmp_path / "reports"

        # Simulate PermissionError for monthly_spend
        from finjuice.pipeline.export import reports_polars

        original_func = reports_polars.export_monthly_spend_polars

        def mock_permission_error(*args, **kwargs):
            raise PermissionError("Permission denied")

        monkeypatch.setattr(reports_polars, "export_monthly_spend_polars", mock_permission_error)

        # Act
        summary = generate_all_reports(temp_csv_base_dir, reports_dir)

        # Assert - should continue processing other reports
        assert summary["monthly_spend"] == 0  # Failed
        assert summary["reports"] == 4  # Other 4 succeeded

        # Restore and verify other reports work
        monkeypatch.setattr(reports_polars, "export_monthly_spend_polars", original_func)

    def test_generate_all_reports_handles_runtime_error(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that generate_all_reports catches RuntimeError from export functions."""
        # Arrange
        sample_data = [
            {
                "row_hash": "rt1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": ["식비"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)
        reports_dir = tmp_path / "reports"

        # Simulate RuntimeError for by_tag
        from finjuice.pipeline.export import reports_polars

        original_func = reports_polars.export_by_tag_polars

        def mock_runtime_error(*args, **kwargs):
            raise RuntimeError("Data validation failed")

        monkeypatch.setattr(reports_polars, "export_by_tag_polars", mock_runtime_error)

        # Act
        summary = generate_all_reports(temp_csv_base_dir, reports_dir)

        # Assert - should continue processing other reports
        assert summary["by_tag"] == 0  # Failed
        assert summary["reports"] == 4  # Other 4 succeeded

        # Restore
        monkeypatch.setattr(reports_polars, "export_by_tag_polars", original_func)

    def test_generate_all_reports_handles_unexpected_exception(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that generate_all_reports catches unexpected Exception."""
        # Arrange
        sample_data = [
            {
                "row_hash": "ex1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)
        reports_dir = tmp_path / "reports"

        # Simulate unexpected exception for by_account
        from finjuice.pipeline.export import reports_polars

        original_func = reports_polars.export_by_account_polars

        def mock_unexpected_error(*args, **kwargs):
            raise ValueError("Unexpected data format")

        monkeypatch.setattr(reports_polars, "export_by_account_polars", mock_unexpected_error)

        # Act
        summary = generate_all_reports(temp_csv_base_dir, reports_dir)

        # Assert - should continue processing other reports
        assert summary["by_account"] == 0  # Failed
        assert summary["reports"] == 4  # Other 4 succeeded

        # Restore
        monkeypatch.setattr(reports_polars, "export_by_account_polars", original_func)

    def test_generate_all_reports_handles_transfers_error(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that generate_all_reports handles error in transfers report."""
        # Arrange
        sample_data = [
            {
                "row_hash": "tf1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": ["식비"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)
        reports_dir = tmp_path / "reports"

        # Simulate OSError for transfers
        from finjuice.pipeline.export import reports_polars

        original_func = reports_polars.export_transfers_polars

        def mock_os_error(*args, **kwargs):
            raise OSError("Disk full")

        monkeypatch.setattr(reports_polars, "export_transfers_polars", mock_os_error)

        # Act
        summary = generate_all_reports(temp_csv_base_dir, reports_dir)

        # Assert - should continue processing
        assert summary["transfers"] == 0  # Failed
        assert summary["reports"] == 4  # Other 4 succeeded

        # Restore
        monkeypatch.setattr(reports_polars, "export_transfers_polars", original_func)


class TestReportsPolarsErrorHandling:
    """Test error handling in reports_polars module."""

    def test_export_monthly_spend_polars_permission_error(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that export_monthly_spend_polars raises RuntimeError on PermissionError."""
        # Arrange
        sample_data = [
            {
                "row_hash": "msp1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)

        # Create read-only output directory
        output_path = tmp_path / "readonly" / "monthly.csv"

        # Mock the file write to raise PermissionError
        import builtins

        original_open = builtins.open

        def mock_open(*args, **kwargs):
            mode = kwargs.get("mode", args[1] if len(args) > 1 else "")
            if "readonly" in str(args[0]) and "wb" in str(mode):
                raise PermissionError("Permission denied")
            return original_open(*args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open)

        # Act & Assert
        from finjuice.pipeline.export.reports_polars import export_monthly_spend_polars

        with pytest.raises(RuntimeError, match="Failed to export monthly_spend report"):
            export_monthly_spend_polars(temp_csv_base_dir, output_path)

    def test_export_by_tag_polars_value_error(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that export_by_tag_polars raises RuntimeError on ValueError."""
        # Arrange - need data with tags
        sample_data = [
            {
                "row_hash": "btve1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": ["식비"],
                "tags_ai": [],
                "tags_final": ["식비"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)
        output_path = tmp_path / "by_tag.csv"

        # Mock get_all_transactions to raise ValueError
        from finjuice.pipeline.export import reports_polars
        from finjuice.pipeline.storage import csv_transactions

        def mock_get_all_raises_value_error(*args, **kwargs):
            raise ValueError("Invalid data format")

        monkeypatch.setattr(
            csv_transactions, "get_all_transactions", mock_get_all_raises_value_error
        )

        # Act & Assert
        with pytest.raises(RuntimeError, match="Data validation failed for by_tag"):
            reports_polars.export_by_tag_polars(temp_csv_base_dir, output_path)

    def test_export_by_account_polars_os_error(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that export_by_account_polars raises RuntimeError on OSError."""
        # Arrange
        sample_data = [
            {
                "row_hash": "baoe1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)
        output_path = tmp_path / "oserror" / "by_account.csv"

        # Mock open to raise OSError
        import builtins

        original_open = builtins.open

        def mock_open_oserror(*args, **kwargs):
            mode = kwargs.get("mode", args[1] if len(args) > 1 else "")
            if "oserror" in str(args[0]) and "wb" in str(mode):
                raise OSError("Disk is full")
            return original_open(*args, **kwargs)

        monkeypatch.setattr(builtins, "open", mock_open_oserror)

        # Act & Assert
        from finjuice.pipeline.export.reports_polars import export_by_account_polars

        with pytest.raises(RuntimeError, match="Failed to export by_account report"):
            export_by_account_polars(temp_csv_base_dir, output_path)

    def test_export_transfers_polars_key_error(
        self, temp_csv_base_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test that export_transfers_polars raises RuntimeError on KeyError."""
        # Arrange
        sample_data = [
            {
                "row_hash": "tfke1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "14:30",
                "type_raw": "이체",
                "type_norm": "transfer",
                "major_raw": "이체",
                "minor_raw": None,
                "merchant_raw": "은행",
                "memo_raw": None,
                "amount": -100000,
                "account": "신한은행",
                "currency": "KRW",
                "counterparty": "우리은행",
                "datetime": "2025-01-15T14:30:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 1,
                "transfer_group_id": "TF01",
            }
        ]
        insert_transactions_to_csv(temp_csv_base_dir, sample_data)
        output_path = tmp_path / "transfers.csv"

        # Mock get_all_transactions to raise KeyError
        from finjuice.pipeline.storage import csv_transactions

        def mock_get_all_raises_key_error(*args, **kwargs):
            raise KeyError("Missing required column")

        monkeypatch.setattr(csv_transactions, "get_all_transactions", mock_get_all_raises_key_error)

        # Act & Assert
        from finjuice.pipeline.export.reports_polars import export_transfers_polars

        with pytest.raises(RuntimeError, match="Data validation failed for transfers"):
            export_transfers_polars(temp_csv_base_dir, output_path)


class TestExportByCategory:
    """Tests for export_by_category() function (v3 schema)."""

    def test_export_by_category_success(self, temp_csv_base_dir: Path, tmp_path: Path) -> None:
        """Test by_category report groups by category_final without double-counting."""
        # Arrange - transactions with different categories
        category_transactions = [
            {
                "row_hash": "cat1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "카페",
                "category_final": "카페",  # Rule-assigned category
                "tags_rule": ["카페", "커피"],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": ["카페", "커피"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "cat2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "12:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "외식",
                "merchant_raw": "맥도날드",
                "memo_raw": None,
                "amount": -10000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-16T12:00:00",
                "category_rule": "",
                "category_final": "외식",  # Fallback to minor_raw
                "tags_rule": ["패스트푸드"],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": ["패스트푸드"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "cat3",
                "file_id": "250101_1",
                "source_row": 3,
                "date": "2025-01-17",
                "time": "14:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "교통",
                "minor_raw": None,
                "merchant_raw": "지하철",
                "memo_raw": None,
                "amount": -2000,
                "account": "체크카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-17T14:00:00",
                "category_rule": "",
                "category_final": "교통",  # Fallback to major_raw
                "tags_rule": ["교통"],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": ["교통"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, category_transactions)
        output_path = tmp_path / "by_category.csv"

        # Act
        row_count = export_by_category(temp_csv_base_dir, output_path)

        # Assert
        assert row_count == 3  # 3 unique categories
        assert output_path.exists()

        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        categories = {r["category"]: float(r["total"]) for r in rows}
        assert "카페" in categories
        assert "외식" in categories
        assert "교통" in categories
        assert categories["카페"] == -5000
        assert categories["외식"] == -10000
        assert categories["교통"] == -2000

    def test_export_by_category_no_double_counting(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that by_category doesn't double-count like by_tag can.

        Unlike by_tag where one transaction with multiple tags is counted
        in each tag's total, by_category uses category_final (single value)
        so each transaction is counted exactly once.
        """
        # Arrange - one transaction with MULTIPLE tags but ONE category
        multi_tag_single_category = [
            {
                "row_hash": "multi1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스",
                "memo_raw": None,
                "amount": -10000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "카페",
                "category_final": "카페",  # SINGLE category
                "tags_rule": ["카페", "커피", "디저트"],  # MULTIPLE tags
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": ["카페", "커피", "디저트"],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, multi_tag_single_category)
        output_path = tmp_path / "by_category.csv"

        # Act
        row_count = export_by_category(temp_csv_base_dir, output_path)

        # Assert - only ONE category row, not three like by_tag would have
        assert row_count == 1

        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert len(rows) == 1
        assert rows[0]["category"] == "카페"
        assert float(rows[0]["total"]) == -10000  # Full amount, once
        assert int(rows[0]["count"]) == 1  # Transaction counted once

    def test_export_by_category_excludes_transfers(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that by_category excludes transfer transactions."""
        # Arrange
        mixed_with_transfer = [
            {
                "row_hash": "exp_cat",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -20000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "",
                "category_final": "식비",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "tf_cat",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "11:00",
                "type_raw": "이체",
                "type_norm": "transfer",
                "major_raw": "이체",
                "minor_raw": None,
                "merchant_raw": "은행",
                "memo_raw": None,
                "amount": -100000,
                "account": "은행A",
                "currency": "KRW",
                "counterparty": "은행B",
                "datetime": "2025-01-16T11:00:00",
                "category_rule": "",
                "category_final": "이체",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 1,  # Transfer - should be excluded
                "transfer_group_id": "TF01",
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, mixed_with_transfer)
        output_path = tmp_path / "by_category.csv"

        # Act
        row_count = export_by_category(temp_csv_base_dir, output_path)

        # Assert - only expense, not transfer
        assert row_count == 1

        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["category"] == "식비"
        assert float(rows[0]["total"]) == -20000

    def test_export_by_category_excludes_income(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that by_category excludes income transactions."""
        # Arrange
        mixed_with_income = [
            {
                "row_hash": "exp_cat_inc",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -15000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "",
                "category_final": "식비",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "inc_cat",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-20",
                "time": "09:00",
                "type_raw": "수입",
                "type_norm": "income",  # Income - should be excluded
                "major_raw": "급여",
                "minor_raw": None,
                "merchant_raw": "회사",
                "memo_raw": None,
                "amount": 3000000,
                "account": "급여계좌",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-20T09:00:00",
                "category_rule": "",
                "category_final": "급여",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, mixed_with_income)
        output_path = tmp_path / "by_category.csv"

        # Act
        row_count = export_by_category(temp_csv_base_dir, output_path)

        # Assert - only expense, not income
        assert row_count == 1

        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["category"] == "식비"
        assert float(rows[0]["total"]) == -15000

    def test_export_by_category_sorted_by_total(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that by_category is sorted by total ascending (largest expenses first)."""
        # Arrange - different amounts per category
        varied_categories = [
            {
                "row_hash": "var1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -50000,  # Largest expense
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "",
                "category_final": "식비",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "var2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "11:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "교통",
                "minor_raw": None,
                "merchant_raw": "택시",
                "memo_raw": None,
                "amount": -10000,  # Smaller expense
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-16T11:00:00",
                "category_rule": "",
                "category_final": "교통",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, varied_categories)
        output_path = tmp_path / "by_category.csv"

        # Act
        export_by_category(temp_csv_base_dir, output_path)

        # Assert - sorted ascending (largest expenses first, as they're most negative)
        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        totals = [float(r["total"]) for r in rows]
        assert totals == sorted(totals)  # Ascending order

    def test_export_by_category_empty_returns_zero(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that by_category returns 0 with no expense transactions."""
        # Arrange - empty CSV base dir (no transactions)
        output_path = tmp_path / "by_category.csv"

        # Act
        row_count = export_by_category(temp_csv_base_dir, output_path)

        # Assert
        assert row_count == 0
        # File should not be created when there's no data
        assert not output_path.exists()

    def test_export_by_category_with_unclassified_fallback(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that transactions with '미분류' (unclassified) category are correctly grouped."""
        # Arrange - transactions where category_final is '미분류'
        unclassified_transactions = [
            {
                "row_hash": "uncl1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": None,  # No major_raw
                "minor_raw": None,  # No minor_raw
                "merchant_raw": "Unknown Store",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "",
                "category_final": "미분류",  # Fallback to 미분류
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 0.3,
                "needs_review": 1,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "uncl2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "11:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": None,
                "minor_raw": None,
                "merchant_raw": "Another Unknown",
                "memo_raw": None,
                "amount": -3000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-16T11:00:00",
                "category_rule": "",
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 0.2,
                "needs_review": 1,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, unclassified_transactions)
        output_path = tmp_path / "by_category.csv"

        # Act
        row_count = export_by_category(temp_csv_base_dir, output_path)

        # Assert - both should be grouped under 미분류
        assert row_count == 1

        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["category"] == "미분류"
        assert float(rows[0]["total"]) == -8000  # -5000 + -3000
        assert int(rows[0]["count"]) == 2

    def test_export_by_category_aggregates_same_category(
        self, temp_csv_base_dir: Path, tmp_path: Path
    ) -> None:
        """Test that multiple transactions with same category are aggregated."""
        # Arrange - multiple transactions with same category
        same_category = [
            {
                "row_hash": "same1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "스타벅스",
                "memo_raw": None,
                "amount": -5000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "카페",
                "category_final": "카페",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "same2",
                "file_id": "250101_1",
                "source_row": 2,
                "date": "2025-01-16",
                "time": "11:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "투썸플레이스",
                "memo_raw": None,
                "amount": -7000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-16T11:00:00",
                "category_rule": "카페",
                "category_final": "카페",  # Same category
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "same3",
                "file_id": "250101_1",
                "source_row": 3,
                "date": "2025-01-17",
                "time": "12:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "이디야",
                "memo_raw": None,
                "amount": -3000,
                "account": "체크카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-17T12:00:00",
                "category_rule": "카페",
                "category_final": "카페",  # Same category
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, same_category)
        output_path = tmp_path / "by_category.csv"

        # Act
        row_count = export_by_category(temp_csv_base_dir, output_path)

        # Assert - all 3 transactions aggregated into 1 category row
        assert row_count == 1

        with open(output_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        assert rows[0]["category"] == "카페"
        assert float(rows[0]["total"]) == -15000  # -5000 + -7000 + -3000
        assert int(rows[0]["count"]) == 3

    def test_export_by_category_utf8_bom(self, temp_csv_base_dir: Path, tmp_path: Path) -> None:
        """Test that by_category CSV has UTF-8 BOM for Excel compatibility."""
        # Arrange
        category_data = [
            {
                "row_hash": "bom1",
                "file_id": "250101_1",
                "source_row": 1,
                "date": "2025-01-15",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": None,
                "merchant_raw": "식당",
                "memo_raw": None,
                "amount": -10000,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2025-01-15T10:00:00",
                "category_rule": "",
                "category_final": "식비",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]
        insert_transactions_to_csv(temp_csv_base_dir, category_data)
        output_path = tmp_path / "by_category.csv"

        # Act
        export_by_category(temp_csv_base_dir, output_path)

        # Assert - check for UTF-8 BOM
        with open(output_path, "rb") as f:
            first_bytes = f.read(3)
            assert first_bytes == b"\xef\xbb\xbf"  # UTF-8 BOM

    def test_export_by_category_requires_v3_schema(self, tmp_path: Path, temp_csv_base_dir: Path):
        """Test that export_by_category raises RuntimeError for v2 schema without category_final."""
        # Arrange - Create v2 schema data (without category_final column)
        v2_data = [
            {
                "row_hash": "a1b2c3d4e5f67890",
                "date": "2024-10-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스",
                "memo_raw": None,
                "amount": -5000.0,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2024-10-15T14:30:00",
                "tags_rule": "[]",
                "tags_ai": "[]",
                "tags_manual": "[]",
                "tags_final": '["카페"]',
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
                "file_id": "241015_1",
                "source_row": 1,
                # Note: category_rule and category_final columns are MISSING (v2 schema)
            },
        ]

        # Write v2 schema CSV directly (without category_final column)
        import polars as pl

        partition_path = temp_csv_base_dir / "2024" / "10"
        partition_path.mkdir(parents=True, exist_ok=True)
        csv_path = partition_path / "transactions.csv"

        df = pl.DataFrame(v2_data)
        df.write_csv(csv_path)

        output_path = tmp_path / "by_category.csv"

        # Act & Assert - should raise RuntimeError (wrapped ValueError)
        with pytest.raises(RuntimeError, match="category_final column not found"):
            export_by_category(temp_csv_base_dir, output_path)

    def test_export_by_category_handles_null_category_final(
        self, tmp_path: Path, temp_csv_base_dir: Path
    ):
        """Test that export_by_category handles NULL/empty category_final gracefully."""
        # Arrange - Create data with NULL and empty category_final values
        mixed_data = [
            {
                "row_hash": "valid1",
                "file_id": "241015_1",
                "source_row": 1,
                "date": "2024-10-15",
                "time": "14:30",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스",
                "memo_raw": None,
                "amount": -5000.0,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2024-10-15T14:30:00",
                "category_rule": "",
                "category_final": "카페",  # Valid category
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 1.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "null1",
                "file_id": "241015_1",
                "source_row": 2,
                "date": "2024-10-15",
                "time": "15:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "교통",
                "minor_raw": None,
                "merchant_raw": "택시",
                "memo_raw": None,
                "amount": -10000.0,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2024-10-15T15:00:00",
                "category_rule": None,
                "category_final": None,  # NULL category_final
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 0.5,
                "needs_review": 1,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
            {
                "row_hash": "empty1",
                "file_id": "241015_1",
                "source_row": 3,
                "date": "2024-10-15",
                "time": "16:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "생활",
                "minor_raw": None,
                "merchant_raw": "편의점",
                "memo_raw": None,
                "amount": -3000.0,
                "account": "체크카드",
                "currency": "KRW",
                "counterparty": None,
                "datetime": "2024-10-15T16:00:00",
                "category_rule": "",
                "category_final": "",  # Empty string category_final
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 0.5,
                "needs_review": 1,
                "is_transfer": 0,
                "transfer_group_id": None,
            },
        ]

        insert_transactions_to_csv(temp_csv_base_dir, mixed_data)
        output_path = tmp_path / "by_category.csv"

        # Act - should not raise, should group NULL/empty appropriately
        result = export_by_category(temp_csv_base_dir, output_path)

        # Assert - file should be created with at least the valid category
        assert output_path.exists()
        assert result >= 1  # At least the valid "카페" category
