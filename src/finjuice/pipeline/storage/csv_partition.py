"""
CSV partition storage layer for transactions (Polars-only).

Provides year/month partitioned CSV storage optimized for:
- AI agent workflows (Claude Code Read/Edit tools)
- Token efficiency (56% less than JSON, 21x vs single file)
- Git trackability (line-oriented diffs)
- Human readability (grep, awk, csvkit compatible)

Backend:
    - Polars: 3-5x performance vs legacy pandas implementation
    - All functions use Polars DataFrames natively

Directory structure:
    data/transactions/
        2024/
            01/transactions.csv
            02/transactions.csv
            ...
        2025/
            01/transactions.csv
            ...

Each partition is sorted by datetime for stable diffs.
"""

from finjuice.pipeline.storage.csv_assets import (
    append_asset_snapshots,
    read_asset_snapshot_month,
    write_asset_snapshot_month,
)
from finjuice.pipeline.storage.csv_banksalad_overview import (
    BANKSALAD_BALANCE_DEDUP_KEY,
    BANKSALAD_CASHFLOW_DEDUP_KEY,
    BANKSALAD_INSURANCE_DEDUP_KEY,
    BANKSALAD_INVESTMENT_DEDUP_KEY,
    BANKSALAD_LOAN_DEDUP_KEY,
    BANKSALAD_OVERVIEW_FACT_DEDUP_KEY,
    append_banksalad_balance,
    append_banksalad_cashflow,
    append_banksalad_insurance,
    append_banksalad_investments,
    append_banksalad_loans,
    append_banksalad_overview_facts,
    read_banksalad_balance_month,
    read_banksalad_cashflow_month,
    read_banksalad_insurance_month,
    read_banksalad_investment_month,
    read_banksalad_loan_month,
    read_banksalad_overview_facts_month,
    write_banksalad_balance_month,
    write_banksalad_cashflow_month,
    write_banksalad_insurance_month,
    write_banksalad_investment_month,
    write_banksalad_loan_month,
    write_banksalad_overview_facts_month,
)
from finjuice.pipeline.storage.csv_schema import (
    ASSET_SNAPSHOT_COLUMNS,
    ASSET_SNAPSHOT_POLARS_SCHEMA,
    BANKSALAD_BALANCE_COLUMNS,
    BANKSALAD_BALANCE_POLARS_SCHEMA,
    BANKSALAD_CASHFLOW_COLUMNS,
    BANKSALAD_CASHFLOW_POLARS_SCHEMA,
    BANKSALAD_INSURANCE_COLUMNS,
    BANKSALAD_INSURANCE_POLARS_SCHEMA,
    BANKSALAD_INVESTMENT_COLUMNS,
    BANKSALAD_INVESTMENT_POLARS_SCHEMA,
    BANKSALAD_LOAN_COLUMNS,
    BANKSALAD_LOAN_POLARS_SCHEMA,
    BANKSALAD_OVERVIEW_FACT_COLUMNS,
    BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA,
    CSV_COLUMNS,
    POLARS_SCHEMA,
    get_asset_snapshot_partition_path,
    get_banksalad_balance_partition_path,
    get_banksalad_cashflow_partition_path,
    get_banksalad_insurance_partition_path,
    get_banksalad_investment_partition_path,
    get_banksalad_loan_partition_path,
    get_banksalad_overview_facts_partition_path,
    get_partition_path,
)
from finjuice.pipeline.storage.csv_transactions import (
    append_transactions,
    find_transaction_by_hash,
    get_all_transactions,
    read_month,
    read_range,
    upsert_transaction,
    write_month,
)

__all__ = [
    "CSV_COLUMNS",
    "POLARS_SCHEMA",
    "ASSET_SNAPSHOT_COLUMNS",
    "ASSET_SNAPSHOT_POLARS_SCHEMA",
    "BANKSALAD_OVERVIEW_FACT_COLUMNS",
    "BANKSALAD_OVERVIEW_FACT_POLARS_SCHEMA",
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
    "BANKSALAD_OVERVIEW_FACT_DEDUP_KEY",
    "BANKSALAD_BALANCE_DEDUP_KEY",
    "BANKSALAD_CASHFLOW_DEDUP_KEY",
    "BANKSALAD_INSURANCE_DEDUP_KEY",
    "BANKSALAD_INVESTMENT_DEDUP_KEY",
    "BANKSALAD_LOAN_DEDUP_KEY",
    "get_partition_path",
    "get_asset_snapshot_partition_path",
    "get_banksalad_overview_facts_partition_path",
    "get_banksalad_balance_partition_path",
    "get_banksalad_cashflow_partition_path",
    "get_banksalad_insurance_partition_path",
    "get_banksalad_investment_partition_path",
    "get_banksalad_loan_partition_path",
    "read_month",
    "read_asset_snapshot_month",
    "read_banksalad_overview_facts_month",
    "read_banksalad_balance_month",
    "read_banksalad_cashflow_month",
    "read_banksalad_insurance_month",
    "read_banksalad_investment_month",
    "read_banksalad_loan_month",
    "read_range",
    "write_month",
    "write_asset_snapshot_month",
    "write_banksalad_overview_facts_month",
    "write_banksalad_balance_month",
    "write_banksalad_cashflow_month",
    "write_banksalad_insurance_month",
    "write_banksalad_investment_month",
    "write_banksalad_loan_month",
    "append_transactions",
    "append_asset_snapshots",
    "append_banksalad_overview_facts",
    "append_banksalad_balance",
    "append_banksalad_cashflow",
    "append_banksalad_insurance",
    "append_banksalad_investments",
    "append_banksalad_loans",
    "upsert_transaction",
    "find_transaction_by_hash",
    "get_all_transactions",
]
