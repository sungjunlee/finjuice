"""Identity coverage for the reports_polars export-error helper split (Issue #344)."""

from __future__ import annotations

import importlib

import polars as pl
import pytest


def _load_errors_module():
    return importlib.import_module("finjuice.pipeline.export.reports_polars_errors")


def test_reports_polars_reexports_error_translation_helper() -> None:
    """Error translation stays importable from reports_polars after the split."""
    reports_polars = importlib.import_module("finjuice.pipeline.export.reports_polars")
    errors = _load_errors_module()

    assert reports_polars._translate_export_errors is errors._translate_export_errors


def test_translate_export_errors_passes_through_clean_bodies() -> None:
    """Bodies that do not raise run unchanged and keep their return flow."""
    errors = _load_errors_module()

    with errors._translate_export_errors("monthly_spend"):
        result = 3

    assert result == 3


def test_translate_export_errors_maps_io_failures_to_runtime_error() -> None:
    """PermissionError/OSError keep the 'Failed to export ...' contract."""
    errors = _load_errors_module()

    with pytest.raises(RuntimeError) as excinfo:
        with errors._translate_export_errors("monthly_spend"):
            raise PermissionError("denied")
    assert str(excinfo.value) == "Failed to export monthly_spend report: denied"
    assert isinstance(excinfo.value.__cause__, PermissionError)

    with pytest.raises(RuntimeError) as excinfo:
        with errors._translate_export_errors("by_account"):
            raise OSError("disk full")
    assert str(excinfo.value) == "Failed to export by_account report: disk full"
    assert isinstance(excinfo.value.__cause__, OSError)


def test_translate_export_errors_maps_validation_failures_to_runtime_error() -> None:
    """ValueError/KeyError keep the 'Data validation failed for ...' contract."""
    errors = _load_errors_module()

    with pytest.raises(RuntimeError) as excinfo:
        with errors._translate_export_errors("by_tag"):
            raise ValueError("Invalid data format")
    assert str(excinfo.value) == "Data validation failed for by_tag: Invalid data format"
    assert isinstance(excinfo.value.__cause__, ValueError)

    with pytest.raises(RuntimeError) as excinfo:
        with errors._translate_export_errors("transfers"):
            raise KeyError("Missing required column")
    assert "Data validation failed for transfers" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, KeyError)


def test_translate_export_errors_maps_polars_failures_to_runtime_error() -> None:
    """Polars failures keep the 'Polars computation failed for ...' contract."""
    errors = _load_errors_module()

    with pytest.raises(RuntimeError) as excinfo:
        with errors._translate_export_errors("by_category"):
            raise pl.exceptions.PolarsError("boom")
    assert str(excinfo.value) == "Polars computation failed for by_category: boom"
    assert isinstance(excinfo.value.__cause__, pl.exceptions.PolarsError)


def test_reports_polars_export_functions_stay_callable() -> None:
    """All public export functions remain on reports_polars after the split."""
    reports_polars = importlib.import_module("finjuice.pipeline.export.reports_polars")

    for name in (
        "export_monthly_spend_polars",
        "export_by_tag_polars",
        "export_by_category_polars",
        "export_by_account_polars",
        "export_transfers_polars",
    ):
        assert callable(getattr(reports_polars, name))
