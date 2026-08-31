"""Identity tests for the csv_schema helper split."""

from pathlib import Path

from finjuice.pipeline.storage import csv_schema, csv_schema_helpers

STORAGE_DIR = Path("src/finjuice/pipeline/storage")


def test_partition_path_helpers_live_in_helper_module() -> None:
    """Year/month partition path builders should not live in csv_schema.py."""
    schema_text = (STORAGE_DIR / "csv_schema.py").read_text(encoding="utf-8")
    helpers_text = (STORAGE_DIR / "csv_schema_helpers.py").read_text(encoding="utf-8")

    assert "CSV_COLUMNS = [" in schema_text
    assert "POLARS_SCHEMA = {" in schema_text
    assert "ASSET_SNAPSHOT_COLUMNS = [" in schema_text
    assert "BANKSALAD_OVERVIEW_FACT_COLUMNS = [" in schema_text
    assert "def get_partition_path" not in schema_text
    assert "def get_asset_snapshot_partition_path" not in schema_text
    assert "def get_banksalad_overview_facts_partition_path" not in schema_text
    assert "def get_banksalad_balance_partition_path" not in schema_text
    assert "def get_banksalad_cashflow_partition_path" not in schema_text
    assert "def get_banksalad_insurance_partition_path" not in schema_text
    assert "def get_banksalad_investment_partition_path" not in schema_text
    assert "def get_banksalad_loan_partition_path" not in schema_text
    assert "def get_partition_path" in helpers_text
    assert "def get_asset_snapshot_partition_path" in helpers_text
    assert "def get_banksalad_overview_facts_partition_path" in helpers_text
    assert "def get_banksalad_balance_partition_path" in helpers_text
    assert "def get_banksalad_cashflow_partition_path" in helpers_text
    assert "def get_banksalad_insurance_partition_path" in helpers_text
    assert "def get_banksalad_investment_partition_path" in helpers_text
    assert "def get_banksalad_loan_partition_path" in helpers_text


def test_partition_path_helpers_reexport_from_csv_schema() -> None:
    """Existing csv_schema imports should keep resolving to the path helpers."""
    assert csv_schema.get_partition_path is csv_schema_helpers.get_partition_path
    assert (
        csv_schema.get_asset_snapshot_partition_path
        is csv_schema_helpers.get_asset_snapshot_partition_path
    )
    assert (
        csv_schema.get_banksalad_overview_facts_partition_path
        is csv_schema_helpers.get_banksalad_overview_facts_partition_path
    )
    assert (
        csv_schema.get_banksalad_balance_partition_path
        is csv_schema_helpers.get_banksalad_balance_partition_path
    )
    assert (
        csv_schema.get_banksalad_cashflow_partition_path
        is csv_schema_helpers.get_banksalad_cashflow_partition_path
    )
    assert (
        csv_schema.get_banksalad_insurance_partition_path
        is csv_schema_helpers.get_banksalad_insurance_partition_path
    )
    assert (
        csv_schema.get_banksalad_investment_partition_path
        is csv_schema_helpers.get_banksalad_investment_partition_path
    )
    assert (
        csv_schema.get_banksalad_loan_partition_path
        is csv_schema_helpers.get_banksalad_loan_partition_path
    )
    assert csv_schema.CSV_COLUMNS
    assert csv_schema.POLARS_SCHEMA
    assert csv_schema.ASSET_SNAPSHOT_COLUMNS
    assert csv_schema.BANKSALAD_OVERVIEW_FACT_COLUMNS
