"""Identity tests for the Banksalad overview cashflow helper split."""

from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.storage import csv_banksalad_overview as overview
from finjuice.pipeline.storage import csv_banksalad_overview_cashflow as cashflow

STORAGE_DIR = Path("src/finjuice/pipeline/storage")


def test_cashflow_partition_helpers_live_in_helper_module() -> None:
    """Cashflow partition-source helpers should not live in the CRUD module."""
    overview_text = (STORAGE_DIR / "csv_banksalad_overview.py").read_text(encoding="utf-8")
    cashflow_text = (STORAGE_DIR / "csv_banksalad_overview_cashflow.py").read_text(encoding="utf-8")

    assert "def read_banksalad_cashflow_month" in overview_text
    assert "def _cashflow_partition_source_expr" not in overview_text
    assert "def _validate_cashflow_partition_source" not in overview_text
    assert "def _cashflow_partition_source_expr" in cashflow_text
    assert "def _validate_cashflow_partition_source" in cashflow_text


def test_cashflow_partition_helpers_reexport_from_overview() -> None:
    """Existing overview imports should keep resolving to the cashflow helpers."""
    assert overview._cashflow_partition_source_expr is cashflow._cashflow_partition_source_expr
    assert (
        overview._validate_cashflow_partition_source is cashflow._validate_cashflow_partition_source
    )
    assert callable(overview.append_banksalad_cashflow)
    assert callable(overview.read_banksalad_cashflow_month)
    assert callable(overview.write_banksalad_cashflow_month)
    assert "append_banksalad_cashflow" in overview.__all__
    assert "read_banksalad_cashflow_month" in overview.__all__
    assert "write_banksalad_cashflow_month" in overview.__all__


def test_validate_cashflow_partition_source_rejects_non_yyyy_mm() -> None:
    """Invalid partition sources keep the original YYYY-MM error."""
    invalid_rows = pl.DataFrame({"_partition_source": [None, "2026/06"]})

    with pytest.raises(ValueError, match="Cashflow partition source must be populated as YYYY-MM"):
        overview._validate_cashflow_partition_source(invalid_rows)
