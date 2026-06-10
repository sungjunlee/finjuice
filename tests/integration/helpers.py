"""Helper utilities for integration tests.

This module provides reusable utilities for validating pipeline outputs,
comparing dataframes, and calculating metrics.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import polars as pl

from finjuice.pipeline.storage import csv_partition

logger = logging.getLogger(__name__)


def compare_dataframes(
    df1: pl.DataFrame,
    df2: pl.DataFrame,
    ignore_columns: Optional[List[str]] = None,
    tolerance: float = 0.01,
) -> Tuple[bool, List[str]]:
    """Compare two dataframes with tolerance for numeric values.

    Args:
        df1: First dataframe (actual)
        df2: Second dataframe (expected)
        ignore_columns: Columns to exclude from comparison
        tolerance: Relative tolerance for numeric comparisons

    Returns:
        Tuple of (is_equal, list_of_differences)
    """
    differences = []

    # Check shape
    if df1.shape != df2.shape:
        differences.append(f"Shape mismatch: {df1.shape} vs {df2.shape}")
        return False, differences

    # Filter columns
    if ignore_columns:
        cols_to_keep1 = [c for c in df1.columns if c not in ignore_columns]
        cols_to_keep2 = [c for c in df2.columns if c not in ignore_columns]
        df1 = df1.select(cols_to_keep1)
        df2 = df2.select(cols_to_keep2)

    # Check column names
    if set(df1.columns) != set(df2.columns):
        differences.append(f"Column mismatch: {set(df1.columns) ^ set(df2.columns)}")
        return False, differences

    # Compare values
    for col in df1.columns:
        dtype = df1[col].dtype
        if dtype in [pl.Float32, pl.Float64, pl.Int32, pl.Int64]:
            # Numeric comparison with tolerance
            vals1 = df1[col].to_list()
            vals2 = df2[col].to_list()
            for i, (v1, v2) in enumerate(zip(vals1, vals2)):
                if v1 is None and v2 is None:
                    continue
                if v1 is None or v2 is None:
                    differences.append(f"Values differ in column {col} at row {i}: {v1} vs {v2}")
                elif abs(v1 - v2) > max(abs(v1), abs(v2), 1e-9) * tolerance:
                    differences.append(f"Values differ in column {col} at row {i}: {v1} vs {v2}")
        else:
            # Exact comparison for non-numeric
            vals1 = df1[col].to_list()
            vals2 = df2[col].to_list()
            for i, (v1, v2) in enumerate(zip(vals1, vals2)):
                if v1 != v2:
                    differences.append(f"Values differ in column {col} at row {i}: {v1} vs {v2}")

    is_equal = len(differences) == 0
    return is_equal, differences


def validate_xlsx_structure(
    file_path: Path, required_columns: List[str], sheet_name: int | str = 0
) -> Tuple[bool, List[str]]:
    """Validate XLSX file structure and columns.

    Args:
        file_path: Path to XLSX file
        required_columns: List of required column names
        sheet_name: Sheet to validate (default: first sheet)

    Returns:
        Tuple of (is_valid, list_of_issues)
    """
    issues = []

    # Check file exists
    if not file_path.exists():
        issues.append(f"File not found: {file_path}")
        return False, issues

    try:
        # Read file (Polars read_excel with openpyxl engine)
        # Note: Polars sheet_id is 1-indexed (1 = first sheet)
        # Polars sheet_name parameter accepts string names
        if isinstance(sheet_name, str):
            # Use sheet_name parameter for string names
            df = pl.read_excel(
                file_path,
                sheet_name=sheet_name,
                engine="openpyxl",
            )
        else:
            # Convert 0-indexed to 1-indexed for sheet_id
            sheet_idx = sheet_name + 1 if sheet_name >= 0 else 1
            df = pl.read_excel(
                file_path,
                sheet_id=sheet_idx,
                engine="openpyxl",
            )

        # Check columns
        missing_cols = set(required_columns) - set(df.columns)
        if missing_cols:
            issues.append(f"Missing columns: {missing_cols}")

        extra_cols = set(df.columns) - set(required_columns)
        if extra_cols:
            logger.warning(f"Extra columns found: {extra_cols}")

        # Check not empty
        if len(df) == 0:
            issues.append("File is empty")

    except Exception as e:
        issues.append(f"Error reading file: {e}")

    is_valid = len(issues) == 0
    return is_valid, issues


def calculate_report_metrics(csv_base_dir: Path) -> Dict[str, Any]:
    """Calculate summary metrics from CSV partitions.

    Args:
        csv_base_dir: Path to CSV partition base directory

    Returns:
        Dictionary of metrics (total_transactions, total_transfers, etc.)
    """
    df = csv_partition.get_all_transactions(csv_base_dir)

    if len(df) == 0:
        return {
            "total_transactions": 0,
            "by_type": {},
            "transfer_pairs": 0,
            "unpaired_transfers": 0,
            "tagged_count": 0,
            "tag_coverage": 0.0,
            "needs_review_count": 0,
        }

    metrics = {}

    # Total transactions
    metrics["total_transactions"] = len(df)

    # By type (Polars value_counts)
    type_counts = df["type_norm"].value_counts()
    type_names = type_counts["type_norm"].to_list()
    type_vals = type_counts["count"].to_list()
    metrics["by_type"] = dict(zip(type_names, type_vals))

    # Transfer pairs (Polars filter)
    paired_transfers = df.filter(
        (pl.col("is_transfer") == 1) & pl.col("transfer_group_id").is_not_null()
    )
    metrics["transfer_pairs"] = paired_transfers["transfer_group_id"].n_unique()

    # Unpaired transfers
    unpaired_transfers = df.filter(
        (pl.col("is_transfer") == 1) & pl.col("transfer_group_id").is_null()
    )
    metrics["unpaired_transfers"] = len(unpaired_transfers)

    # Tagged transactions (tags_final can be a Python list or JSON string)
    def has_tags(tags_val) -> bool:
        if tags_val is None:
            return False
        if isinstance(tags_val, list):
            return len(tags_val) > 0
        if isinstance(tags_val, str):
            return tags_val not in ("", "[]")
        return False

    tags_list = df["tags_final"].to_list()
    metrics["tagged_count"] = sum(1 for tags in tags_list if has_tags(tags))

    # Tag coverage percentage
    if metrics["total_transactions"] > 0:
        metrics["tag_coverage"] = (metrics["tagged_count"] / metrics["total_transactions"]) * 100
    else:
        metrics["tag_coverage"] = 0.0

    # Needs review count
    metrics["needs_review_count"] = len(df.filter(pl.col("needs_review") == 1))

    return metrics


def validate_transfer_pairing(
    csv_base_dir: Path, expected_pairs: List[Tuple[str, str]]
) -> Tuple[bool, List[str]]:
    """Validate that specific transfer pairs are correctly matched.

    Args:
        csv_base_dir: Path to CSV partition base directory
        expected_pairs: List of (merchant1, merchant2) tuples that should pair

    Returns:
        Tuple of (all_paired_correctly, list_of_errors)
    """
    errors = []
    df = csv_partition.get_all_transactions(csv_base_dir)

    for merchant1, merchant2 in expected_pairs:
        results = df.filter(pl.col("merchant_raw").is_in([merchant1, merchant2]))

        if len(results) != 2:
            errors.append(
                f"Expected 2 transactions for pair ({merchant1}, {merchant2}), found {len(results)}"
            )
            continue

        for row in results.iter_rows(named=True):
            if row["is_transfer"] != 1:
                errors.append(f"Transaction {row['merchant_raw']} not marked as transfer")

        group_ids = results["transfer_group_id"].to_list()
        if group_ids[0] is None or group_ids[1] is None:
            errors.append(f"Transfer pair ({merchant1}, {merchant2}) not assigned group_id")
        elif group_ids[0] != group_ids[1]:
            errors.append(
                f"Transfer pair ({merchant1}, {merchant2}) have different "
                f"group_ids: {group_ids[0]} vs {group_ids[1]}"
            )

    all_correct = len(errors) == 0
    return all_correct, errors


def validate_rule_matching(
    csv_base_dir: Path, expected_matches: Dict[str, List[str]]
) -> Tuple[bool, List[str]]:
    """Validate that transactions match expected rules.

    Args:
        csv_base_dir: Path to CSV partition base directory
        expected_matches: Dict mapping merchant names to expected tags

    Returns:
        Tuple of (all_matched_correctly, list_of_errors)
    """
    errors = []
    df = csv_partition.get_all_transactions(csv_base_dir)

    for merchant, expected_tags in expected_matches.items():
        result = df.filter(pl.col("merchant_raw") == merchant)

        if result.is_empty():
            errors.append(f"No transaction found for merchant: {merchant}")
            continue

        tags_value = result.row(0, named=True).get("tags_final")
        if isinstance(tags_value, list):
            actual_tags = tags_value
        else:
            actual_tags = json.loads(tags_value) if tags_value else []

        missing_tags = set(expected_tags) - set(actual_tags)
        if missing_tags:
            errors.append(
                f"Merchant {merchant} missing tags: {missing_tags}. Actual: {actual_tags}"
            )

    all_matched = len(errors) == 0
    return all_matched, errors


def get_report_summary(csv_path: Path) -> Dict[str, Any]:
    """Get summary statistics from a CSV report.

    Args:
        csv_path: Path to CSV report file

    Returns:
        Dictionary with summary stats (row_count, total_amount, etc.)
    """
    if not csv_path.exists():
        return {"error": f"File not found: {csv_path}"}

    try:
        df = pl.read_csv(csv_path)

        summary = {
            "row_count": len(df),
            "columns": list(df.columns),
        }

        # Add column-specific stats
        if "amount" in df.columns:
            summary["total_amount"] = df["amount"].sum()
            summary["avg_amount"] = df["amount"].mean()

        if "count" in df.columns:
            summary["total_count"] = df["count"].sum()

        return summary

    except Exception as e:
        return {"error": str(e)}


def validate_idempotency(csv_base_dir1: Path, csv_base_dir2: Path) -> Tuple[bool, List[str]]:
    """Validate that two pipeline runs produce identical CSV partitions.

    Args:
        csv_base_dir1: Path to first CSV partition directory (run 1)
        csv_base_dir2: Path to second CSV partition directory (run 2)

    Returns:
        Tuple of (is_identical, list_of_differences)
    """
    differences = []

    # Load all transactions from both runs
    df1 = csv_partition.get_all_transactions(csv_base_dir1)
    df2 = csv_partition.get_all_transactions(csv_base_dir2)

    # Compare row counts
    count1 = len(df1)
    count2 = len(df2)

    if count1 != count2:
        differences.append(f"Row count mismatch: {count1} vs {count2}")
        return False, differences

    # Compare row hashes (Polars)
    hashes1 = set(df1["row_hash"].to_list())
    hashes2 = set(df2["row_hash"].to_list())

    if hashes1 != hashes2:
        differences.append(
            f"Row hash mismatch. "
            f"Only in CSV1: {len(hashes1 - hashes2)}, "
            f"Only in CSV2: {len(hashes2 - hashes1)}"
        )

    # Compare tags and transfers
    # Sort both by row_hash for consistent comparison (Polars)
    df1_sorted = df1.sort("row_hash").select(["row_hash", "tags_final", "transfer_group_id"])
    df2_sorted = df2.sort("row_hash").select(["row_hash", "tags_final", "transfer_group_id"])

    # Iterate using Polars iter_rows
    for row1, row2 in zip(df1_sorted.iter_rows(named=True), df2_sorted.iter_rows(named=True)):
        # Compare row_hash
        if row1["row_hash"] != row2["row_hash"]:
            differences.append("Row hash order mismatch")
            continue

        # Compare tags_final (can be Python lists or JSON strings)
        if row1["tags_final"] != row2["tags_final"]:
            differences.append(
                f"Tag mismatch for row_hash {row1['row_hash']}: "
                f"{row1['tags_final']} vs {row2['tags_final']}"
            )

        # Compare transfer_group_id (handle None)
        if row1["transfer_group_id"] is None and row2["transfer_group_id"] is None:
            continue
        elif row1["transfer_group_id"] != row2["transfer_group_id"]:
            differences.append(
                f"Transfer group_id mismatch for row_hash {row1['row_hash']}: "
                f"{row1['transfer_group_id']} vs {row2['transfer_group_id']}"
            )

    is_identical = len(differences) == 0
    return is_identical, differences
