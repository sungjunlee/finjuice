"""Banksalad overview CSV column lists and Polars dtypes.

Owns the ADR-0013 overview fact, balance, cashflow, insurance, investment,
and loan storage contracts. Transaction and asset-snapshot schemas stay in
:mod:`finjuice.pipeline.storage.csv_schema`, which re-exports these names
so existing callers can keep importing from that module.
"""

from __future__ import annotations

import polars as pl

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
