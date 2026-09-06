"""Structure tests for the csv_schema Banksalad helper-cluster split.

Banksalad overview column lists and Polars dtypes live in
``csv_schema_cluster`` and must stay identity-equal when re-exported from
``csv_schema``. Transaction and asset-snapshot schemas stay in
``csv_schema``. Partition path helpers stay in ``csv_schema_helpers``.
"""

from __future__ import annotations

import importlib
from pathlib import Path

STORAGE_DIR = Path("src/finjuice/pipeline/storage")
SCHEMA_MODULE = "finjuice.pipeline.storage.csv_schema"
CLUSTER_MODULE = "finjuice.pipeline.storage.csv_schema_cluster"

CLUSTER_CONSTANT_NAMES = (
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
)
PUBLIC_ENTRY_CONSTANT_NAMES = (
    "CSV_COLUMNS",
    "POLARS_SCHEMA",
    "ASSET_SNAPSHOT_COLUMNS",
    "ASSET_SNAPSHOT_POLARS_SCHEMA",
)
PATH_HELPER_NAMES = (
    "get_partition_path",
    "get_asset_snapshot_partition_path",
    "get_banksalad_overview_facts_partition_path",
    "get_banksalad_balance_partition_path",
    "get_banksalad_cashflow_partition_path",
    "get_banksalad_insurance_partition_path",
    "get_banksalad_investment_partition_path",
    "get_banksalad_loan_partition_path",
)


def test_csv_schema_reexports_banksalad_cluster_identity() -> None:
    """Banksalad schemas stay on csv_schema as re-exports after the split."""
    schema = importlib.import_module(SCHEMA_MODULE)
    cluster = importlib.import_module(CLUSTER_MODULE)

    for name in CLUSTER_CONSTANT_NAMES:
        assert getattr(schema, name) is getattr(cluster, name)
        assert name in schema.__all__

    for name in PUBLIC_ENTRY_CONSTANT_NAMES:
        assert getattr(schema, name)
        assert name in schema.__all__


def test_csv_schema_cluster_is_the_unique_home_for_moved_helpers() -> None:
    """The moved Banksalad cluster is defined exactly once, in csv_schema_cluster."""
    schema_text = (STORAGE_DIR / "csv_schema.py").read_text(encoding="utf-8")
    cluster_text = (STORAGE_DIR / "csv_schema_cluster.py").read_text(encoding="utf-8")
    helpers_text = (STORAGE_DIR / "csv_schema_helpers.py").read_text(encoding="utf-8")

    for name in CLUSTER_CONSTANT_NAMES:
        assert f"\n{name} =" not in schema_text
        assert f"\n{name} =" in cluster_text
        assert name in schema_text

    for name in PUBLIC_ENTRY_CONSTANT_NAMES:
        assert f"\n{name} =" in schema_text
        assert f"\n{name} =" not in cluster_text

    for name in PATH_HELPER_NAMES:
        assert f"def {name}" not in schema_text
        assert f"def {name}" not in cluster_text
        assert f"def {name}" in helpers_text
