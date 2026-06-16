"""CSV partition schema and path helpers for the v4 storage contract.

Shared by ``csv_transactions`` and ``csv_assets``. Kept separate from the CRUD
modules so changing partition geometry (paths) or schema column lists does not
require touching read/write logic.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

# CSV Schema (v4 - with manual row-level notes)
# Changes from v3:
#   - notes_manual: mutable row-level annotation separate from analysis tags
# CSV Schema (v3 - with category system for accurate aggregation)
# Changes from v2:
#   - category_rule: nullable string, set by rules.yaml
#   - category_final: calculated category for report aggregation
#   - tags_final: now for filtering only, not aggregation
#   - is_transfer_candidate: nullable integer transfer-like raw row flag
# Changes from v1:
#   - row_hash: 16 chars (was 64) - 48 char savings per row
#   - file_id: 8 chars (replaces source_file_path ~80 chars +
#     source_file_mtime 26 chars) - 98 char savings
CSV_COLUMNS = [
    "row_hash",  # 16 chars (SHA256[:16])
    "date",
    "time",
    "type_raw",
    "type_norm",
    "major_raw",
    "minor_raw",
    "merchant_raw",
    "memo_raw",
    "notes_manual",
    "amount",
    "account",
    "currency",
    "counterparty",
    "datetime",
    "category_rule",  # NEW in v3: category from rules.yaml (nullable)
    "category_final",  # NEW in v3: final category for aggregation (not null)
    "tags_rule",  # attribute tags from rules
    "tags_ai",
    "tags_manual",
    "tags_final",  # attribute tags for filtering (NOT for aggregation)
    "confidence",
    "needs_review",
    "is_transfer_candidate",
    "is_transfer",
    "transfer_group_id",
    "file_id",  # 8 chars (e.g., "241027_1") - links to data/metadata/import_history.csv
    "source_row",
]


# Polars schema mapping for CSV read (v3)
# Use explicit dtypes for performance and correctness
# Note: Tag columns are stored as JSON strings in CSV
# (Polars CSV writer doesn't support nested data)
POLARS_SCHEMA = {
    "row_hash": pl.Utf8,
    "date": pl.Utf8,  # Keep as string for compatibility
    "time": pl.Utf8,
    "type_raw": pl.Utf8,
    "type_norm": pl.Utf8,
    "major_raw": pl.Utf8,
    "minor_raw": pl.Utf8,
    "merchant_raw": pl.Utf8,
    "memo_raw": pl.Utf8,
    "notes_manual": pl.Utf8,
    "amount": pl.Float64,
    "account": pl.Utf8,
    "currency": pl.Utf8,
    "counterparty": pl.Utf8,
    "datetime": pl.Utf8,  # Keep as string for compatibility
    "category_rule": pl.Utf8,  # NEW in v3: category from rules.yaml
    "category_final": pl.Utf8,  # NEW in v3: final category for aggregation
    "tags_rule": pl.Utf8,  # JSON string (parsed to list on read)
    "tags_ai": pl.Utf8,  # JSON string (parsed to list on read)
    "tags_manual": pl.Utf8,  # JSON string (parsed to list on read)
    "tags_final": pl.Utf8,  # JSON string (parsed to list on read)
    "confidence": pl.Float64,
    "needs_review": pl.Int64,
    "is_transfer_candidate": pl.Int64,
    "is_transfer": pl.Int64,
    "transfer_group_id": pl.Utf8,
    "file_id": pl.Utf8,
    "source_row": pl.Int64,
}

# Asset snapshot schema (Issue #225)
ASSET_SNAPSHOT_COLUMNS = [
    "snapshot_date",
    "account_id",
    "instrument_id",
    "quantity",
    "market_value",
    "currency",
    "file_id",
    "source_row",
]

ASSET_SNAPSHOT_POLARS_SCHEMA = {
    "snapshot_date": pl.Utf8,
    "account_id": pl.Utf8,
    "instrument_id": pl.Utf8,
    "quantity": pl.Float64,
    "market_value": pl.Float64,
    "currency": pl.Utf8,
    "file_id": pl.Utf8,
    "source_row": pl.Int64,
}

# Banksalad overview workbook schemas (ADR-0013)
BANKSALAD_OVERVIEW_FACT_COLUMNS = [
    "fact_id",
    "snapshot_date",
    "sheet_name",
    "block_id",
    "block_title",
    "fact_kind",
    "row_label",
    "column_label",
    "value_numeric",
    "value_text",
    "value_type",
    "file_id",
    "source_row",
    "source_col",
]

BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA = {
    "fact_id": pl.Utf8,
    "snapshot_date": pl.Utf8,
    "sheet_name": pl.Utf8,
    "block_id": pl.Utf8,
    "block_title": pl.Utf8,
    "fact_kind": pl.Utf8,
    "row_label": pl.Utf8,
    "column_label": pl.Utf8,
    "value_numeric": pl.Float64,
    "value_text": pl.Utf8,
    "value_type": pl.Utf8,
    "file_id": pl.Utf8,
    "source_row": pl.Int64,
    "source_col": pl.Int64,
}

BANKSALAD_BALANCE_COLUMNS = [
    "snapshot_date",
    "side",
    "category",
    "item_name",
    "amount",
    "currency",
    "source_fact_id",
    "file_id",
    "source_row",
]

BANKSALAD_BALANCE_POLARS_SCHEMA = {
    "snapshot_date": pl.Utf8,
    "side": pl.Utf8,
    "category": pl.Utf8,
    "item_name": pl.Utf8,
    "amount": pl.Float64,
    "currency": pl.Utf8,
    "source_fact_id": pl.Utf8,
    "file_id": pl.Utf8,
    "source_row": pl.Int64,
}

BANKSALAD_CASHFLOW_COLUMNS = [
    "snapshot_date",
    "period_month",
    "category",
    "amount",
    "source_fact_id",
    "file_id",
]

BANKSALAD_CASHFLOW_POLARS_SCHEMA = {
    "snapshot_date": pl.Utf8,
    "period_month": pl.Utf8,
    "category": pl.Utf8,
    "amount": pl.Float64,
    "source_fact_id": pl.Utf8,
    "file_id": pl.Utf8,
}

BANKSALAD_INSURANCE_COLUMNS = [
    "snapshot_date",
    "institution",
    "policy_name",
    "contract_status",
    "paid_amount",
    "contract_date",
    "maturity_date",
    "currency",
    "source_fact_id",
    "file_id",
    "source_row",
]

BANKSALAD_INSURANCE_POLARS_SCHEMA = {
    "snapshot_date": pl.Utf8,
    "institution": pl.Utf8,
    "policy_name": pl.Utf8,
    "contract_status": pl.Utf8,
    "paid_amount": pl.Float64,
    "contract_date": pl.Utf8,
    "maturity_date": pl.Utf8,
    "currency": pl.Utf8,
    "source_fact_id": pl.Utf8,
    "file_id": pl.Utf8,
    "source_row": pl.Int64,
}

BANKSALAD_INVESTMENT_COLUMNS = [
    "snapshot_date",
    "product_type",
    "institution",
    "product_name",
    "principal_amount",
    "valuation_amount",
    "return_rate",
    "start_date",
    "maturity_date",
    "currency",
    "source_fact_id",
    "file_id",
    "source_row",
]

BANKSALAD_INVESTMENT_POLARS_SCHEMA = {
    "snapshot_date": pl.Utf8,
    "product_type": pl.Utf8,
    "institution": pl.Utf8,
    "product_name": pl.Utf8,
    "principal_amount": pl.Float64,
    "valuation_amount": pl.Float64,
    "return_rate": pl.Float64,
    "start_date": pl.Utf8,
    "maturity_date": pl.Utf8,
    "currency": pl.Utf8,
    "source_fact_id": pl.Utf8,
    "file_id": pl.Utf8,
    "source_row": pl.Int64,
}

BANKSALAD_LOAN_COLUMNS = [
    "snapshot_date",
    "loan_type",
    "institution",
    "product_name",
    "principal_amount",
    "balance_amount",
    "interest_rate",
    "start_date",
    "maturity_date",
    "currency",
    "source_fact_id",
    "file_id",
    "source_row",
]

BANKSALAD_LOAN_POLARS_SCHEMA = {
    "snapshot_date": pl.Utf8,
    "loan_type": pl.Utf8,
    "institution": pl.Utf8,
    "product_name": pl.Utf8,
    "principal_amount": pl.Float64,
    "balance_amount": pl.Float64,
    "interest_rate": pl.Float64,
    "start_date": pl.Utf8,
    "maturity_date": pl.Utf8,
    "currency": pl.Utf8,
    "source_fact_id": pl.Utf8,
    "file_id": pl.Utf8,
    "source_row": pl.Int64,
}


def get_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return CSV partition file path for the given transaction year/month.

    Example:
        >>> get_partition_path(Path('data/transactions'), 2024, 10)
        PosixPath('data/transactions/2024/10/transactions.csv')
    """
    return base_dir / str(year) / f"{month:02d}" / "transactions.csv"


def get_asset_snapshot_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return CSV partition file path for the given asset snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "snapshots.csv"


def get_banksalad_overview_facts_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad overview facts partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "facts.csv"


def get_banksalad_balance_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad balance projection partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "balance.csv"


def get_banksalad_cashflow_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad cashflow projection partition path for the given period year/month."""
    return base_dir / str(year) / f"{month:02d}" / "cashflow.csv"


def get_banksalad_insurance_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad insurance partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "insurance.csv"


def get_banksalad_investment_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad investment partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "investments.csv"


def get_banksalad_loan_partition_path(base_dir: Path, year: int, month: int) -> Path:
    """Return Banksalad loan partition path for the given snapshot year/month."""
    return base_dir / str(year) / f"{month:02d}" / "loans.csv"


__all__ = [
    "ASSET_SNAPSHOT_COLUMNS",
    "ASSET_SNAPSHOT_POLARS_SCHEMA",
    "BANKSALAD_BALANCE_COLUMNS",
    "BANKSALAD_BALANCE_POLARS_SCHEMA",
    "BANKSALAD_CASHFLOW_COLUMNS",
    "BANKSALAD_CASHFLOW_POLARS_SCHEMA",
    "BANKSALAD_INSURANCE_COLUMNS",
    "BANKSALAD_INSURANCE_POLARS_SCHEMA",
    "BANKSALAD_INVESTMENT_COLUMNS",
    "BANKSALAD_INVESTMENT_POLARS_SCHEMA",
    "BANKSALAD_LOAN_COLUMNS",
    "BANKSALAD_LOAN_POLARS_SCHEMA",
    "BANKSALAD_OVERVIEW_FACT_COLUMNS",
    "BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA",
    "CSV_COLUMNS",
    "POLARS_SCHEMA",
    "get_asset_snapshot_partition_path",
    "get_banksalad_balance_partition_path",
    "get_banksalad_cashflow_partition_path",
    "get_banksalad_insurance_partition_path",
    "get_banksalad_investment_partition_path",
    "get_banksalad_loan_partition_path",
    "get_banksalad_overview_facts_partition_path",
    "get_partition_path",
]
