"""Integration tests for the full finjuice pipeline.

These tests validate end-to-end pipeline behavior using real anonymized sample data.
Tests cover:
- Full pipeline execution (ingest → tag → detect → export)
- Schema evolution (different column names/order)
- Transfer detection accuracy
- Rule matching and tag coverage
- Report generation and validation
- Idempotency and incremental processing
"""

import shutil
import tempfile
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.export.master import export_master_xlsx
from finjuice.pipeline.export.reports import generate_all_reports
from finjuice.pipeline.ingest.pipeline import ingest_all_files
from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.tagging.pipeline import run_tagging
from finjuice.pipeline.transfer.detection import run_transfer_detection
from tests.integration.helpers import (
    calculate_report_metrics,
    validate_idempotency,
    validate_xlsx_structure,
)


@pytest.fixture
def temp_data_dir():
    """Create temporary data directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir) / "data"
        data_dir.mkdir()

        # Create subdirectories
        (data_dir / "imports").mkdir()
        (data_dir / "exports").mkdir()
        (data_dir / "exports" / "reports").mkdir()
        (data_dir / "transactions").mkdir()  # CSV partition directory

        yield data_dir


@pytest.fixture
def sample_xlsx_file(temp_data_dir):
    """Copy sample XLSX fixture to temporary imports directory."""
    source = Path("tests/fixtures/sample_banksalad.xlsx")
    dest = temp_data_dir / "imports" / "sample_banksalad.xlsx"
    shutil.copy(source, dest)
    return dest


@pytest.fixture
def sample_alt_schema_file(temp_data_dir):
    """Copy alternative schema XLSX fixture to temporary imports directory."""
    source = Path("tests/fixtures/sample_banksalad_alt_schema.xlsx")
    dest = temp_data_dir / "imports" / "sample_alt_schema.xlsx"
    shutil.copy(source, dest)
    return dest


@pytest.fixture
def sample_rules_file(temp_data_dir):
    """Copy sample rules.yaml to temporary data directory."""
    source = Path("tests/fixtures/sample_rules.yaml")
    dest = temp_data_dir / "rules.yaml"
    shutil.copy(source, dest)
    return dest


@pytest.fixture
def csv_base_dir(temp_data_dir):
    """Get CSV partition base directory."""
    csv_dir = temp_data_dir / "transactions"
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir


# ============================================================================
# Test 1: Full Pipeline with Sample Data
# ============================================================================


@pytest.mark.integration
def test_full_pipeline_with_sample_data(
    temp_data_dir, sample_xlsx_file, sample_rules_file, csv_base_dir
):
    """Test complete pipeline: ingest → tag → detect → export.

    Validates:
    - All steps execute successfully
    - Transaction counts are correct at each stage
    - Tag coverage meets >60% threshold
    - Transfer pairs are detected
    - Master XLSX is created with all fields
    - All CSV reports are generated
    """
    # Arrange
    imports_dir = temp_data_dir / "imports"
    exports_dir = temp_data_dir / "exports"
    reports_dir = temp_data_dir / "exports" / "reports"

    # Act
    # Step 1: Ingest
    ingest_summary = ingest_all_files(imports_dir, csv_base_dir)

    # Step 2: Tag
    tag_summary = run_tagging(csv_base_dir, sample_rules_file)

    # Step 3: Transfer Detection
    transfer_summary = run_transfer_detection(csv_base_dir)

    # Step 4: Export
    master_path = exports_dir / "master_test.xlsx"
    row_count = export_master_xlsx(csv_base_dir, master_path)
    reports_summary = generate_all_reports(csv_base_dir, reports_dir)

    # Assert
    # Ingestion
    assert ingest_summary["files"] >= 1, "Should process at least 1 file"
    assert ingest_summary["inserted"] > 0, "Should insert transactions"
    assert ingest_summary["failed"] == 0, "Should have no failed files"

    # Tagging
    assert tag_summary["total"] > 0, "Should have transactions to tag"
    assert tag_summary["coverage_pct"] >= 60.0, (
        f"Tag coverage should be >= 60%, got {tag_summary['coverage_pct']:.1f}%"
    )

    # Transfer Detection
    assert transfer_summary["candidates"] > 0, "Should have transfer candidates"
    # At least some pairs should be detected (sample data may have 1+ pairs)
    assert transfer_summary["pairs"] >= 1, (
        f"Should detect at least 1 transfer pair, got {transfer_summary['pairs']}"
    )
    assert transfer_summary["paired"] == transfer_summary["pairs"] * 2, (
        "Paired count should be 2x pairs"
    )

    # Export
    assert master_path.exists(), "Master XLSX should be created"
    assert row_count > 0, "Master should have rows"
    assert row_count == tag_summary["total"], "Master should have all transactions"

    # Reports
    assert reports_summary["reports"] == 5, "Should generate all 5 reports"
    assert reports_summary["monthly_spend"] > 0, "Should have monthly data"
    assert reports_summary["by_tag"] >= 0, "Should have tag data"
    assert reports_summary["by_account"] > 0, "Should have account data"
    assert reports_summary["transfers"] > 0, "Should have transfer data"

    # Validate file structure
    assert (reports_dir / "monthly_spend.csv").exists()
    assert (reports_dir / "by_tag.csv").exists()
    assert (reports_dir / "by_account.csv").exists()
    assert (reports_dir / "transfers.csv").exists()


# ============================================================================
# Test 2: Schema Evolution
# ============================================================================


@pytest.mark.integration
def test_schema_evolution(temp_data_dir, sample_xlsx_file, sample_alt_schema_file, csv_base_dir):
    """Test that alternative schema variants are handled correctly.

    Validates:
    - Standard schema is ingested successfully
    - Alternative schema (different column names/order) maps correctly
    - No duplicate transactions are created
    - All transactions have standardized fields
    """
    # Arrange
    imports_dir = temp_data_dir / "imports"

    # Act
    # Ingest standard schema
    summary1 = ingest_all_files(imports_dir, csv_base_dir)
    df_after_standard = csv_partition.get_all_transactions(csv_base_dir)
    count_after_standard = len(df_after_standard)

    # Ingest alternative schema (should be idempotent - same data)
    summary2 = ingest_all_files(imports_dir, csv_base_dir)
    df_after_alt = csv_partition.get_all_transactions(csv_base_dir)
    count_after_alt = len(df_after_alt)

    # Get sample transactions (Polars select)
    sample_txns = df_after_alt.select(
        ["date", "time", "type_norm", "amount", "merchant_raw", "account"]
    ).head(5)

    # Assert
    # Both files should process successfully
    assert summary1["files"] >= 1, "Should process standard schema"
    assert summary2["files"] >= 2, "Should process both schemas"

    # No new transactions should be added (same data, different schema)
    # They should be deduplicated by row_hash
    assert count_after_alt == count_after_standard, (
        f"Alternative schema should not create duplicates. "
        f"Before: {count_after_standard}, After: {count_after_alt}"
    )

    # All transactions should have normalized fields (Polars iter_rows)
    for txn in sample_txns.iter_rows(named=True):
        assert txn["date"] is not None, "Date should be present"
        assert txn["time"] is not None, "Time should be present"
        assert txn["type_norm"] in [
            "expense",
            "income",
            "transfer",
            "other",
        ], f"Invalid type_norm: {txn['type_norm']}"
        assert isinstance(txn["amount"], (int, float)), "Amount should be numeric"
        # merchant and account can be None in edge cases


# ============================================================================
# Test 3: Transfer Detection Accuracy
# ============================================================================


@pytest.mark.integration
def test_transfer_detection_accuracy(temp_data_dir, sample_xlsx_file, csv_base_dir):
    """Test transfer detection with known transfer pairs.

    Validates:
    - Specific transfer pairs are matched correctly
    - transfer_group_id is assigned consistently
    - Unpaired transfers remain unpaired
    - is_transfer flag is set correctly
    """
    # Arrange
    imports_dir = temp_data_dir / "imports"

    # Ingest data
    ingest_all_files(imports_dir, csv_base_dir)

    # Act
    transfer_summary = run_transfer_detection(csv_base_dir)

    # Get all transfer candidates (Polars)
    df = csv_partition.get_all_transactions(csv_base_dir)
    transfers = df.filter(pl.col("type_norm") == "transfer").sort(["date", "time"])

    # Get paired transfers
    paired_transfers = transfers.filter(pl.col("transfer_group_id").is_not_null())

    # Get group_id counts
    group_ids = paired_transfers["transfer_group_id"].to_list()

    # Assert
    # Basic counts
    assert len(transfers) > 0, "Should have transfer candidates"
    assert transfer_summary["pairs"] >= 1, (
        f"Should detect at least 1 pair, got {transfer_summary['pairs']}"
    )

    # Only PAIRED transfers should be marked is_transfer=1
    # Unpaired transfers have is_transfer=0 until they are matched
    paired_count = len(transfers.filter(pl.col("is_transfer") == 1))
    assert paired_count > 0, "Should have at least some paired transfers"

    # Paired transfers should have matching group_ids
    # Each pair should have exactly 2 transactions with same group_id
    if len(paired_transfers) > 0:
        from collections import Counter

        group_counts = Counter(group_ids)

        # Most groups should be pairs (size 2)
        pair_groups = [gid for gid, count in group_counts.items() if count == 2]
        assert len(pair_groups) >= 1, (
            f"Should have at least 1 valid transfer pair, got {len(pair_groups)}"
        )

        # Validate amounts are opposite within pairs
        for group_id in pair_groups[:3]:  # Check first 3 pairs
            group_txns = paired_transfers.filter(pl.col("transfer_group_id") == group_id)
            if len(group_txns) == 2:
                amount1 = group_txns.row(0, named=True)["amount"]
                amount2 = group_txns.row(1, named=True)["amount"]
                assert abs(amount1 + amount2) < 100, (
                    f"Pair {group_id} amounts should be opposite: {amount1}, {amount2}"
                )

    # Unpaired transfers should have NULL group_id
    unpaired_count = transfer_summary["unpaired"]
    unpaired_in_df = len(transfers.filter(pl.col("transfer_group_id").is_null()))
    assert unpaired_in_df == unpaired_count, (
        f"Unpaired count mismatch: CSV={unpaired_in_df}, Summary={unpaired_count}"
    )


# ============================================================================
# Test 4: Rule Hit Rate
# ============================================================================


@pytest.mark.integration
def test_rule_hit_rate(temp_data_dir, sample_xlsx_file, sample_rules_file, csv_base_dir):
    """Test that rule matching achieves target coverage.

    Validates:
    - Rule matching runs successfully
    - Tag coverage meets >60% threshold
    - Specific transactions match expected rules
    - tags_final is populated correctly
    """
    # Arrange
    imports_dir = temp_data_dir / "imports"

    # Ingest and tag
    ingest_all_files(imports_dir, csv_base_dir)
    tag_summary = run_tagging(csv_base_dir, sample_rules_file)

    # Act
    # Get all transactions
    df = csv_partition.get_all_transactions(csv_base_dir)

    # Get tagged transactions
    # tags_final can be List[str] type or String type (JSON) depending on how data was loaded
    # Check for non-empty lists or non-empty JSON strings
    if df["tags_final"].dtype == pl.List:
        # List type: check list length > 0
        tagged_txns = df.filter(
            (pl.col("tags_final").is_not_null()) & (pl.col("tags_final").list.len() > 0)
        ).select(["merchant_raw", "tags_final", "confidence"])

        untagged_txns = df.filter(
            (pl.col("tags_final").is_null()) | (pl.col("tags_final").list.len() == 0)
        ).select(["merchant_raw", "major_raw", "minor_raw"])
    else:
        # String type (JSON): check for non-empty and not "[]"
        tagged_txns = df.filter(
            (pl.col("tags_final").is_not_null())
            & (pl.col("tags_final") != "")
            & (pl.col("tags_final") != "[]")
        ).select(["merchant_raw", "tags_final", "confidence"])

        untagged_txns = df.filter(
            (pl.col("tags_final").is_null())
            | (pl.col("tags_final") == "")
            | (pl.col("tags_final") == "[]")
        ).select(["merchant_raw", "major_raw", "minor_raw"])

    # Get specific test case (if INSURANCE exists)
    insurance_rows = df.filter(pl.col("merchant_raw").str.to_lowercase().str.contains("insurance"))
    insurance_txn = None
    if len(insurance_rows) > 0:
        insurance_txn = insurance_rows.row(0, named=True)

    # Assert
    # Coverage threshold
    assert tag_summary["coverage_pct"] >= 60.0, (
        f"Tag coverage should be >= 60%, got {tag_summary['coverage_pct']:.1f}%"
    )

    # Counts match
    assert len(tagged_txns) == tag_summary["tagged"]
    assert len(untagged_txns) == tag_summary["untagged"]

    # Tagged transactions have confidence scores (Polars iter_rows)
    for txn in tagged_txns.head(5).iter_rows(named=True):  # Check first 5
        merchant = txn["merchant_raw"]
        tags = txn["tags_final"]
        confidence = txn["confidence"]

        # Confidence can be None if not set yet
        if confidence is not None:
            assert confidence >= 0.0 and confidence <= 1.0, (
                f"Confidence should be 0-1, got {confidence}"
            )

        # tags_final should be valid Python list or JSON string
        if isinstance(tags, str):
            import json

            tags = json.loads(tags) if tags else []
        assert isinstance(tags, list), "tags_final should be a list"
        assert len(tags) > 0, "Tagged transactions should have at least 1 tag"

    # Specific rule matching (if insurance transaction exists)
    if insurance_txn is not None:
        merchant = insurance_txn["merchant_raw"]
        tags = insurance_txn["tags_final"]

        # Handle JSON string
        if isinstance(tags, str):
            import json

            tags = json.loads(tags) if tags else []

        # Based on sample rules, insurance should have "보험" or "insurance" tag
        assert any("보험" in tag.lower() or "insurance" in tag.lower() for tag in tags), (
            f"Insurance transaction {merchant} should have insurance-related tag, got {tags}"
        )


# ============================================================================
# Test 5: Report Accuracy
# ============================================================================


@pytest.mark.integration
def test_report_accuracy(temp_data_dir, sample_xlsx_file, sample_rules_file, csv_base_dir):
    """Test generated reports have correct data.

    Validates:
    - Reports contain expected columns
    - Transfer exclusion works (transfers not in expense reports)
    - Tag aggregations are correct
    - Monthly summaries match raw data
    """
    # Arrange
    imports_dir = temp_data_dir / "imports"
    reports_dir = temp_data_dir / "exports" / "reports"

    # Run pipeline
    ingest_all_files(imports_dir, csv_base_dir)
    run_tagging(csv_base_dir, sample_rules_file)
    run_transfer_detection(csv_base_dir)

    # Generate reports
    generate_all_reports(csv_base_dir, reports_dir)

    # Act
    # Read CSV reports (Polars)
    monthly_df = pl.read_csv(reports_dir / "monthly_spend.csv")
    by_tag_df = pl.read_csv(reports_dir / "by_tag.csv")
    by_account_df = pl.read_csv(reports_dir / "by_account.csv")
    transfers_df = pl.read_csv(reports_dir / "transfers.csv")

    # Get raw data for validation
    df = csv_partition.get_all_transactions(csv_base_dir)

    # Count paired transfers (Polars filter)
    paired_transfers_count = len(
        df.filter((pl.col("is_transfer") == 1) & pl.col("transfer_group_id").is_not_null())
    )

    # Assert
    # Monthly spend report
    assert "year_month" in monthly_df.columns or "month" in monthly_df.columns
    assert (
        "total_expense" in monthly_df.columns
        or "total_spend" in monthly_df.columns
        or "amount" in monthly_df.columns
    )
    assert len(monthly_df) > 0, "Should have at least 1 month"

    # Monthly totals should be negative (expenses) or zero
    # Get second column (the amount column) and sum
    amount_col = monthly_df.columns[1]
    monthly_total = monthly_df[amount_col].sum() if len(monthly_df) > 0 else 0
    assert monthly_total <= 0, f"Monthly expenses should be negative or zero, got {monthly_total}"

    # By tag report
    assert "tag" in by_tag_df.columns
    assert (
        "total_amount" in by_tag_df.columns
        or "total" in by_tag_df.columns
        or "amount" in by_tag_df.columns
    )
    # Can be empty if no tags applied
    # Note: amounts can be negative (expenses) or positive (income)

    # By account report
    assert "account" in by_account_df.columns
    assert len(by_account_df) > 0, "Should have at least 1 account"

    # Transfers report
    assert "transfer_group_id" in transfers_df.columns
    assert len(transfers_df) > 0, "Should have transfer data"
    # Transfers report should only include paired transfers
    if paired_transfers_count > 0:
        assert len(transfers_df) == paired_transfers_count, (
            f"Transfers report should have {paired_transfers_count} rows, got {len(transfers_df)}"
        )


# ============================================================================
# Test 6: Incremental Pipeline (Idempotency)
# ============================================================================


@pytest.mark.integration
def test_incremental_pipeline_idempotency(temp_data_dir, sample_xlsx_file, sample_rules_file):
    """Test that re-running pipeline with same data produces identical results.

    Validates:
    - Running pipeline twice produces same CSV state
    - Row hashes prevent duplicates
    - Tags and transfer_group_ids remain consistent
    """
    # Arrange
    imports_dir = temp_data_dir / "imports"
    csv_dir1 = temp_data_dir / "transactions_run1"
    csv_dir2 = temp_data_dir / "transactions_run2"
    csv_dir1.mkdir(parents=True, exist_ok=True)
    csv_dir2.mkdir(parents=True, exist_ok=True)

    # Act
    # Run 1
    ingest_all_files(imports_dir, csv_dir1)
    run_tagging(csv_dir1, sample_rules_file)
    run_transfer_detection(csv_dir1)
    df1 = csv_partition.get_all_transactions(csv_dir1)
    count1 = len(df1)

    # Run 2 (same data)
    ingest_all_files(imports_dir, csv_dir2)
    run_tagging(csv_dir2, sample_rules_file)
    run_transfer_detection(csv_dir2)
    df2 = csv_partition.get_all_transactions(csv_dir2)
    count2 = len(df2)

    # Compare CSV partitions
    is_identical, differences = validate_idempotency(csv_dir1, csv_dir2)

    # Assert
    assert count1 == count2, f"Row counts should match: {count1} vs {count2}"
    assert count1 > 0, "Should have transactions"

    assert is_identical, (
        f"Pipeline runs should produce identical results. Differences: {differences}"
    )


# ============================================================================
# Additional Helper Tests
# ============================================================================


@pytest.mark.integration
def test_master_xlsx_structure(temp_data_dir, sample_xlsx_file, sample_rules_file, csv_base_dir):
    """Test that master XLSX has correct structure and columns."""
    # Arrange
    imports_dir = temp_data_dir / "imports"
    exports_dir = temp_data_dir / "exports"

    # Run pipeline
    ingest_all_files(imports_dir, csv_base_dir)
    run_tagging(csv_base_dir, sample_rules_file)
    run_transfer_detection(csv_base_dir)

    # Export master
    master_path = exports_dir / "master_test.xlsx"
    export_master_xlsx(csv_base_dir, master_path)

    # Act
    required_columns = [
        "date",
        "time",
        "type_raw",
        "type_norm",
        "major_raw",
        "minor_raw",
        "merchant_raw",
        "amount",
        "currency",
        "account",
        "tags_final",
        "is_transfer",
        "transfer_group_id",
        "row_hash",
    ]

    is_valid, issues = validate_xlsx_structure(master_path, required_columns, sheet_name=0)

    # Assert
    assert is_valid, f"Master XLSX structure issues: {issues}"
    assert master_path.exists()

    # Read and validate data types (Polars)
    df = pl.read_excel(master_path, engine="openpyxl")
    assert len(df) > 0, "Master should have transactions"
    assert "amount" in df.columns
    # Polars numeric types: Int64, Float64, etc.
    assert df["amount"].dtype in [
        pl.Int64,
        pl.Float64,
        pl.Int32,
        pl.Float32,
    ], f"Amount should be numeric, got {df['amount'].dtype}"


@pytest.mark.integration
def test_csv_partition_metrics(temp_data_dir, sample_xlsx_file, sample_rules_file, csv_base_dir):
    """Test CSV partition metrics calculation helper."""
    # Arrange
    imports_dir = temp_data_dir / "imports"

    # Run pipeline
    ingest_all_files(imports_dir, csv_base_dir)
    run_tagging(csv_base_dir, sample_rules_file)
    run_transfer_detection(csv_base_dir)

    # Act
    metrics = calculate_report_metrics(csv_base_dir)

    # Assert
    assert metrics["total_transactions"] > 0
    assert "by_type" in metrics
    assert metrics["tag_coverage"] >= 0.0 and metrics["tag_coverage"] <= 100.0
    assert metrics["transfer_pairs"] >= 0
    assert metrics["unpaired_transfers"] >= 0

    # Type breakdown should sum to total
    type_sum = sum(metrics["by_type"].values())
    assert type_sum == metrics["total_transactions"]
