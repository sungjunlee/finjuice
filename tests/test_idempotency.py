"""End-to-end idempotency tests for the pipeline.

These tests verify that the pipeline produces identical results when run
multiple times with the same inputs - a critical requirement for data integrity.

Test scenarios:
1. Full pipeline idempotency (ingest → tag → detect → export)
2. Incremental import idempotency (adding new files)
3. Tagging idempotency (re-running with same rules)
4. Transfer detection idempotency (re-running detection)
5. Export idempotency (re-exporting same data)
"""

from pathlib import Path
from typing import List

import polars as pl
import pytest

from finjuice.pipeline.export.master import export_master_xlsx
from finjuice.pipeline.ingest.pipeline import ingest_all_files
from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.tagging.manual import build_manual_tags
from finjuice.pipeline.tagging.pipeline import run_tagging
from finjuice.pipeline.transfer.detection import run_transfer_detection

# Mark all tests in this module as idempotency tests
pytestmark = pytest.mark.idempotent


@pytest.fixture
def temp_csv_base_dir(tmp_path: Path):  # type: ignore[misc]
    """Create a temporary CSV partitions directory."""
    csv_dir = tmp_path / "transactions"
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir


def _write_banksalad_xlsx(file_path: Path, data_rows: list[dict]) -> None:
    """Write a Banksalad-format XLSX with 2 sheets using xlsxwriter.

    Args:
        file_path: Path to output XLSX file
        data_rows: List of dicts for the transaction data sheet
    """
    import xlsxwriter

    workbook = xlsxwriter.Workbook(file_path)

    # Sheet 0: 요약 (Summary)
    summary_sheet = workbook.add_worksheet("요약")
    summary_sheet.write(0, 0, "요약")
    summary_sheet.write(1, 0, "테스트 데이터")

    # Sheet 1: 가계부 내역 (Transaction data)
    detail_sheet = workbook.add_worksheet("가계부 내역")
    if data_rows:
        columns = list(data_rows[0].keys())
        for col_idx, col_name in enumerate(columns):
            detail_sheet.write(0, col_idx, col_name)
        for row_idx, row in enumerate(data_rows):
            for col_idx, col_name in enumerate(columns):
                detail_sheet.write(row_idx + 1, col_idx, row[col_name])

    workbook.close()


@pytest.fixture
def sample_xlsx_files(temp_import_dir: Path) -> List[Path]:
    """Create multiple sample XLSX files for idempotency testing.

    Creates Banksalad-format XLSX with 2 sheets:
    - Sheet 0 (요약): Summary (empty)
    - Sheet 1 (가계부 내역): Transaction data
    """
    # File 1 - January transactions
    file1 = temp_import_dir / "transactions_jan.xlsx"
    data1 = [
        {
            "날짜": "2025-01-15",
            "시간": "14:30",
            "타입": "지출",
            "대분류": "식비",
            "중분류": "외식",
            "내용": "스타벅스",
            "메모": "커피 구매",
            "금액": -5000,
            "화폐": "KRW",
            "결제수단": "신한카드",
        },
        {
            "날짜": "2025-01-20",
            "시간": "19:00",
            "타입": "지출",
            "대분류": "식비",
            "중분류": "외식",
            "내용": "맥도날드",
            "메모": "저녁 식사",
            "금액": -10000,
            "화폐": "KRW",
            "결제수단": "신한카드",
        },
    ]
    _write_banksalad_xlsx(file1, data1)

    # File 2 - February transfers
    file2 = temp_import_dir / "transactions_feb.xlsx"
    data2 = [
        {
            "날짜": "2025-02-15",
            "시간": "14:00",
            "타입": "이체",
            "대분류": "내계좌이체",
            "중분류": "이체",
            "내용": "신한은행",
            "메모": "계좌이체",
            "금액": -100000,
            "화폐": "KRW",
            "결제수단": "신한카드",
        },
        {
            "날짜": "2025-02-15",
            "시간": "14:01",
            "타입": "이체",
            "대분류": "내계좌이체",
            "중분류": "이체",
            "내용": "신한카드",
            "메모": "계좌이체",
            "금액": 100000,
            "화폐": "KRW",
            "결제수단": "신한은행",
        },
    ]
    _write_banksalad_xlsx(file2, data2)

    return [file1, file2]


# ============================================================================
# Full Pipeline Idempotency
# ============================================================================


@pytest.mark.integration
def test_full_pipeline_idempotency(
    temp_csv_base_dir, sample_xlsx_files, sample_rules_file, tmp_path
):
    """Test that running the full pipeline twice produces identical results."""
    # Arrange
    import_dir = sample_xlsx_files[0].parent

    # Act - Run 1
    summary1 = ingest_all_files(import_dir, temp_csv_base_dir)
    run_tagging(temp_csv_base_dir, sample_rules_file)
    run_transfer_detection(temp_csv_base_dir)

    # Capture state after run 1
    df1 = csv_partition.get_all_transactions(temp_csv_base_dir)
    state1 = df1.select(["row_hash", "tags_final", "is_transfer", "transfer_group_id"]).sort(
        "row_hash"
    )

    # Act - Run 2 (same inputs)
    summary2 = ingest_all_files(import_dir, temp_csv_base_dir)
    run_tagging(temp_csv_base_dir, sample_rules_file)
    run_transfer_detection(temp_csv_base_dir)

    # Capture state after run 2
    df2 = csv_partition.get_all_transactions(temp_csv_base_dir)
    state2 = df2.select(["row_hash", "tags_final", "is_transfer", "transfer_group_id"]).sort(
        "row_hash"
    )

    # Assert
    assert summary1["inserted"] == 4  # Initial insert
    assert summary2["updated"] == 4  # All updated (duplicates skipped via deduplication)
    # Compare states using Polars equals
    assert state1.equals(state2), "States should be identical after second run"


# ============================================================================
# Incremental Import Idempotency
# ============================================================================


@pytest.mark.integration
def test_incremental_import_idempotency(temp_csv_base_dir, temp_import_dir):
    """Test that re-importing same files doesn't create duplicates."""
    # Arrange - Create file1 (2-sheet Banksalad format)
    file1 = temp_import_dir / "file1.xlsx"
    data1 = [
        {
            "날짜": "2025-01-15",
            "시간": "14:30",
            "타입": "지출",
            "대분류": "식비",
            "중분류": "카페",
            "내용": "스타벅스",
            "메모": "",
            "금액": -5000,
            "화폐": "KRW",
            "결제수단": "신한카드",
        }
    ]
    _write_banksalad_xlsx(file1, data1)

    # Act - Import file1
    summary1 = ingest_all_files(temp_import_dir, temp_csv_base_dir)
    count1 = len(csv_partition.get_all_transactions(temp_csv_base_dir))

    # Create file2 (2-sheet Banksalad format)
    file2 = temp_import_dir / "file2.xlsx"
    data2 = [
        {
            "날짜": "2025-02-20",
            "시간": "19:00",
            "타입": "지출",
            "대분류": "식비",
            "중분류": "외식",
            "내용": "맥도날드",
            "메모": "",
            "금액": -10000,
            "화폐": "KRW",
            "결제수단": "신한카드",
        }
    ]
    _write_banksalad_xlsx(file2, data2)

    # Act - Import both files
    summary2 = ingest_all_files(temp_import_dir, temp_csv_base_dir)
    count2 = len(csv_partition.get_all_transactions(temp_csv_base_dir))

    # Act - Re-import (should be idempotent)
    summary3 = ingest_all_files(temp_import_dir, temp_csv_base_dir)
    count3 = len(csv_partition.get_all_transactions(temp_csv_base_dir))

    # Assert
    assert summary1["inserted"] == 1
    assert count1 == 1
    assert summary2["inserted"] == 1  # Only file2 is new
    assert count2 == 2
    assert summary3["inserted"] == 0  # No new records
    assert summary3["updated"] == 2  # Both files' records marked as duplicates
    assert count3 == 2  # Count unchanged


# ============================================================================
# Tagging Idempotency
# ============================================================================


def test_tagging_idempotency(temp_csv_base_dir, sample_rules_file, tmp_path):
    """Test that tagging is idempotent with same rules."""
    # Arrange - Insert test transaction
    transactions = [
        {
            "row_hash": "a" * 64,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "카페",
            "merchant_raw": "스타벅스",
            "memo_raw": "커피",
            "amount": -5000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "스타벅스",
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
        }
    ]
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(temp_csv_base_dir, df, deduplicate=False)

    # Act - Tag run 1
    run_tagging(temp_csv_base_dir, sample_rules_file)
    df1 = csv_partition.get_all_transactions(temp_csv_base_dir)
    row1 = df1.row(0, named=True)
    tags1 = row1["tags_final"]
    conf1 = row1["confidence"]

    # Act - Tag run 2 (same rules)
    run_tagging(temp_csv_base_dir, sample_rules_file)
    df2 = csv_partition.get_all_transactions(temp_csv_base_dir)
    row2 = df2.row(0, named=True)
    tags2 = row2["tags_final"]
    conf2 = row2["confidence"]

    # Assert
    assert tags1 == tags2, "Tags should be identical on re-run"
    # Use None comparison for NaN
    assert (conf1 is None and conf2 is None) or (conf1 == conf2), (
        "Confidence should be identical on re-run"
    )
    assert tags1 == ["카페", "커피", "외식"], "Should match cafe_starbucks rule"


def test_tagging_rule_change_idempotency(temp_csv_base_dir, tmp_path):
    """Test that changing rules produces consistent results."""
    # Arrange - Insert test transaction
    transactions = [
        {
            "row_hash": "b" * 64,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "카페",
            "merchant_raw": "이디야",
            "memo_raw": "커피",
            "amount": -3000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "이디야",
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_final": [],
        }
    ]
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(temp_csv_base_dir, df, deduplicate=False)

    # Create rules version 1
    rules1 = tmp_path / "rules1.yaml"
    rules1.write_text(
        """version: 1
rules:
  - name: cafe_ediya
    match: "이디야|EDIYA"
    fields: [merchant_raw]
    tags: ["카페", "커피"]
    priority: 80
    enabled: true
""",
        encoding="utf-8",
    )

    # Act - Tag with rules1
    run_tagging(temp_csv_base_dir, rules1)
    df1 = csv_partition.get_all_transactions(temp_csv_base_dir)
    tags1 = df1.row(0, named=True)["tags_final"]

    # Create rules version 2 (different tags)
    rules2 = tmp_path / "rules2.yaml"
    rules2.write_text(
        """version: 1
rules:
  - name: cafe_ediya
    match: "이디야|EDIYA"
    fields: [merchant_raw]
    tags: ["카페", "커피", "소액지출"]
    priority: 80
    enabled: true
""",
        encoding="utf-8",
    )

    # Act - Tag with rules2
    run_tagging(temp_csv_base_dir, rules2)
    df2 = csv_partition.get_all_transactions(temp_csv_base_dir)
    tags2 = df2.row(0, named=True)["tags_final"]

    # Act - Tag with rules1 again (should restore original tags)
    run_tagging(temp_csv_base_dir, rules1)
    df3 = csv_partition.get_all_transactions(temp_csv_base_dir)
    tags3 = df3.row(0, named=True)["tags_final"]

    # Assert
    assert tags1 == ["카페", "커피"]
    assert tags2 == ["카페", "커피", "소액지출"]
    assert tags3 == tags1, "Should restore original tags when reverting rules"


def test_tagging_preserves_manual_category_override_and_binary_confidence(
    temp_csv_base_dir, tmp_path
):
    """Re-tagging should merge tags but keep manual category override semantics."""
    # Arrange
    transactions = [
        {
            "row_hash": "manual_" + "a" * 57,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "카페",
            "merchant_raw": "스타벅스 강남점",
            "memo_raw": "라떼",
            "amount": -5000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "스타벅스",
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "카페",
            "tags_rule": [],
            "tags_ai": ["ai-suggested", "음료"],
            "tags_manual": build_manual_tags(["수동태그", "카페"], "수동카테고리"),
            "tags_final": ["카페"],
            "confidence": 0.0,
            "needs_review": 1,
        },
        {
            "row_hash": "empty_" + "b" * 58,
            "file_id": "250101_1",
            "source_row": 2,
            "date": "2025-01-16",
            "time": "10:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "",
            "minor_raw": "",
            "merchant_raw": "무매칭상점",
            "memo_raw": "",
            "amount": -1000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "무매칭상점",
            "datetime": "2025-01-16T10:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": [],
            "confidence": 1.0,
            "needs_review": 0,
        },
    ]
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(temp_csv_base_dir, df, deduplicate=False)

    rules_file = tmp_path / "rules.yaml"
    rules_file.write_text(
        """version: 1
rules:
  - name: starbucks_generic
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["브랜드", "카페"]
    category: "낮은카테고리"
    priority: 60
    enabled: true
  - name: latte_specific
    match: "라떼"
    fields: [memo_raw]
    tags: ["카페", "음료"]
    category: "규칙카테고리"
    priority: 90
    enabled: true
""",
        encoding="utf-8",
    )

    # Act
    run_tagging(temp_csv_base_dir, rules_file)
    run_tagging(temp_csv_base_dir, rules_file)
    df_after = csv_partition.get_all_transactions(temp_csv_base_dir)
    rows = {row["row_hash"]: row for row in df_after.iter_rows(named=True)}
    tagged = rows["manual_" + "a" * 57]
    untagged = rows["empty_" + "b" * 58]

    # Assert
    assert tagged["category_rule"] == "규칙카테고리"
    assert tagged["category_final"] == "수동카테고리"
    assert tagged["tags_rule"] == ["카페", "음료", "브랜드"]
    assert tagged["tags_final"] == ["카페", "음료", "브랜드", "ai-suggested", "수동태그"]
    assert tagged["confidence"] == 1.0
    assert tagged["needs_review"] == 0

    assert untagged["category_final"] == "미분류"
    assert untagged["tags_final"] == []
    assert untagged["confidence"] == 0.0
    assert untagged["needs_review"] == 1


# ============================================================================
# Transfer Detection Idempotency
# ============================================================================


def test_transfer_detection_idempotency(temp_csv_base_dir):
    """Test that transfer detection is idempotent."""
    # Arrange - Insert transfer pair
    transactions = [
        {
            "row_hash": "out_" + "a" * 61,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-02-15",
            "time": "14:00",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한은행",
            "memo_raw": "계좌이체",
            "amount": -100000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "신한은행",
            "datetime": "2025-02-15T14:00:00",
        },
        {
            "row_hash": "in_" + "b" * 62,
            "file_id": "250101_1",
            "source_row": 2,
            "date": "2025-02-15",
            "time": "14:01",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한카드",
            "memo_raw": "계좌이체",
            "amount": 100000,
            "account": "신한은행",
            "currency": "KRW",
            "counterparty": "신한카드",
            "datetime": "2025-02-15T14:01:00",
        },
    ]
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(temp_csv_base_dir, df, deduplicate=False)

    # Act - Run detection 1
    summary1 = run_transfer_detection(temp_csv_base_dir)
    df1 = csv_partition.get_all_transactions(temp_csv_base_dir)
    state1 = df1.select(["row_hash", "is_transfer", "transfer_group_id"]).sort("row_hash")

    # Act - Run detection 2
    summary2 = run_transfer_detection(temp_csv_base_dir)
    df2 = csv_partition.get_all_transactions(temp_csv_base_dir)
    state2 = df2.select(["row_hash", "is_transfer", "transfer_group_id"]).sort("row_hash")

    # Assert
    assert summary1["paired"] == 2
    assert summary2["paired"] == 2  # Same result
    assert state1.equals(state2), "States should be identical after second run"
    assert all(row == 1 for row in df1["is_transfer"].to_list()), (
        "Both should be marked as transfers"
    )
    assert df1["transfer_group_id"].n_unique() == 1, "Should have same transfer_group_id"


def test_transfer_detection_incremental_idempotency(temp_csv_base_dir):
    """Test that adding new transfers doesn't affect existing pairs."""
    # Arrange - Insert first pair
    transactions1 = [
        {
            "row_hash": "pair1_out_" + "a" * 55,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-02-15",
            "time": "14:00",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한은행",
            "memo_raw": "계좌이체",
            "amount": -100000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "신한은행",
            "datetime": "2025-02-15T14:00:00",
        },
        {
            "row_hash": "pair1_in_" + "b" * 56,
            "file_id": "250101_1",
            "source_row": 2,
            "date": "2025-02-15",
            "time": "14:01",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한카드",
            "memo_raw": "계좌이체",
            "amount": 100000,
            "account": "신한은행",
            "currency": "KRW",
            "counterparty": "신한카드",
            "datetime": "2025-02-15T14:01:00",
        },
    ]
    df1 = pl.DataFrame(transactions1)
    csv_partition.append_transactions(temp_csv_base_dir, df1, deduplicate=False)

    # Act - Detect first pair
    run_transfer_detection(temp_csv_base_dir)
    df = csv_partition.get_all_transactions(temp_csv_base_dir)
    pair1_rows = df.filter(pl.col("row_hash").str.starts_with("pair1_"))
    group_id1 = pair1_rows.row(0, named=True)["transfer_group_id"]

    # Add second pair
    transactions2 = [
        {
            "row_hash": "pair2_out_" + "c" * 55,
            "file_id": "250101_1",
            "source_row": 3,
            "date": "2025-03-10",
            "time": "10:00",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "우리은행",
            "memo_raw": "계좌이체",
            "amount": -50000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "우리은행",
            "datetime": "2025-03-10T10:00:00",
        },
        {
            "row_hash": "pair2_in_" + "d" * 56,
            "file_id": "250101_1",
            "source_row": 4,
            "date": "2025-03-10",
            "time": "10:01",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한카드",
            "memo_raw": "계좌이체",
            "amount": 50000,
            "account": "우리은행",
            "currency": "KRW",
            "counterparty": "신한카드",
            "datetime": "2025-03-10T10:01:00",
        },
    ]
    df2 = pl.DataFrame(transactions2)
    csv_partition.append_transactions(temp_csv_base_dir, df2, deduplicate=False)

    # Act - Detect again (should pair second transfer)
    run_transfer_detection(temp_csv_base_dir)
    df = csv_partition.get_all_transactions(temp_csv_base_dir)

    pair1_rows_after = df.filter(pl.col("row_hash").str.starts_with("pair1_"))
    pair2_rows = df.filter(pl.col("row_hash").str.starts_with("pair2_"))
    group_id1_after = pair1_rows_after.row(0, named=True)["transfer_group_id"]
    group_id2 = pair2_rows.row(0, named=True)["transfer_group_id"]

    # Assert
    assert group_id1 == group_id1_after, "Existing pair should keep same group ID"
    assert group_id2 is not None, "New pair should be detected"
    assert group_id1 != group_id2, "Pairs should have different group IDs"


# ============================================================================
# Export Idempotency
# ============================================================================


def test_export_idempotency(temp_csv_base_dir, sample_transactions, tmp_path):
    """Test that exporting twice produces identical files."""
    # Arrange - Insert sample data
    df = pl.DataFrame(sample_transactions)
    csv_partition.append_transactions(temp_csv_base_dir, df, deduplicate=False)

    # Act - Export 1
    output1 = tmp_path / "master1.xlsx"
    export_master_xlsx(temp_csv_base_dir, output1)
    df1 = pl.read_excel(output1, engine="openpyxl")

    # Act - Export 2
    output2 = tmp_path / "master2.xlsx"
    export_master_xlsx(temp_csv_base_dir, output2)
    df2 = pl.read_excel(output2, engine="openpyxl")

    # Assert - Compare DataFrames (data should be identical)
    assert df1.equals(df2), "Exported DataFrames should be identical"
    # Note: XLSX file sizes may differ slightly due to metadata/timestamps
    # but the data content is what matters for idempotency
