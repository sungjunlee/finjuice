"""Identity tests for the Banksalad overview write/append split."""

from pathlib import Path

import polars as pl

from finjuice.pipeline.storage import csv_banksalad_overview as overview
from finjuice.pipeline.storage import csv_banksalad_overview_write as overview_write

STORAGE_DIR = Path("src/finjuice/pipeline/storage")

WRITE_FUNCS = (
    "write_banksalad_overview_facts_month",
    "append_banksalad_overview_facts",
    "write_banksalad_balance_month",
    "append_banksalad_balance",
    "write_banksalad_cashflow_month",
    "append_banksalad_cashflow",
    "write_banksalad_insurance_month",
    "append_banksalad_insurance",
    "write_banksalad_investment_month",
    "append_banksalad_investments",
    "write_banksalad_loan_month",
    "append_banksalad_loans",
)
READ_FUNCS = (
    "read_banksalad_overview_facts_month",
    "read_banksalad_balance_month",
    "read_banksalad_cashflow_month",
    "read_banksalad_insurance_month",
    "read_banksalad_investment_month",
    "read_banksalad_loan_month",
)


def test_write_append_functions_live_in_write_module() -> None:
    """write/append helpers should not live in the reader module."""
    overview_text = (STORAGE_DIR / "csv_banksalad_overview.py").read_text(encoding="utf-8")
    write_text = (STORAGE_DIR / "csv_banksalad_overview_write.py").read_text(encoding="utf-8")

    for name in READ_FUNCS:
        assert f"def {name}" in overview_text
        assert f"def {name}" not in write_text

    for name in WRITE_FUNCS:
        assert f"def {name}" not in overview_text
        assert f"def {name}" in write_text

    assert "def _cashflow_partition_source_expr" not in write_text
    assert "def _validate_cashflow_partition_source" not in write_text
    assert "def _read_month" not in write_text


def test_write_append_functions_reexport_from_overview() -> None:
    """Existing overview imports should keep resolving to the writers."""
    for name in WRITE_FUNCS:
        assert getattr(overview, name) is getattr(overview_write, name)
        assert callable(getattr(overview, name))
        assert name in overview.__all__
        assert name in overview_write.__all__

    for name in READ_FUNCS:
        assert callable(getattr(overview, name))
        assert name in overview.__all__
        assert name not in overview_write.__all__


def test_append_via_write_module_returns_empty_result_for_empty_frame() -> None:
    """Direct write-module imports keep the empty-append contract."""
    empty = pl.DataFrame()
    expected = {
        "total_rows": 0,
        "partitions_updated": 0,
        "rows_inserted": 0,
        "rows_skipped": 0,
    }

    assert overview_write.append_banksalad_overview_facts(Path("unused"), empty) == expected
    assert overview_write.append_banksalad_balance(Path("unused"), empty) == expected
    assert overview_write.append_banksalad_cashflow(Path("unused"), empty) == expected
    assert overview_write.append_banksalad_insurance(Path("unused"), empty) == expected
    assert overview_write.append_banksalad_investments(Path("unused"), empty) == expected
    assert overview_write.append_banksalad_loans(Path("unused"), empty) == expected
