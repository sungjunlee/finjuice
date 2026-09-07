"""Collector tests for large-transaction unavailable/clear/present behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

import finjuice.pipeline.automation_large_transactions as large_transactions
from finjuice.pipeline.automation_large_transactions import (
    LargeTransactionSignal,
    _collect_large_transactions,
    _optional_text,
)
from finjuice.pipeline.config import Config
from tests.automation_fixtures import write_sample_transactions


def test_collect_large_transactions_clear_when_data_missing(tmp_path: Path) -> None:
    """Missing partitions should surface as a clear large-transaction signal."""
    # Arrange
    config = Config(data_dir=tmp_path)

    # Act
    signal, warning = _collect_large_transactions(
        config=config,
        threshold=300000,
        sample_limit=5,
    )

    # Assert
    assert isinstance(signal, LargeTransactionSignal)
    assert signal.status == "clear"
    assert signal.threshold == 300000
    assert signal.count == 0
    assert signal.samples == []
    assert warning is None


def test_collect_large_transactions_present_above_threshold(tmp_path: Path) -> None:
    """Expenses at or above the explicit threshold should surface as present."""
    # Arrange
    write_sample_transactions(tmp_path)
    config = Config(data_dir=tmp_path)

    # Act
    signal, warning = _collect_large_transactions(
        config=config,
        threshold=300000,
        sample_limit=3,
    )

    # Assert
    assert signal.status == "present"
    assert signal.threshold == 300000
    assert signal.count == 1
    assert signal.samples[0].merchant == "항공사"
    assert signal.samples[0].amount_krw == pytest.approx(800000.0)
    assert warning is None


def test_collect_large_transactions_clear_when_none_meet_threshold(tmp_path: Path) -> None:
    """A high threshold with only smaller expenses should stay clear."""
    # Arrange
    write_sample_transactions(tmp_path)
    config = Config(data_dir=tmp_path)

    # Act
    signal, warning = _collect_large_transactions(
        config=config,
        threshold=900000,
        sample_limit=3,
    )

    # Assert
    assert signal.status == "clear"
    assert signal.threshold == 900000
    assert signal.count == 0
    assert signal.samples == []
    assert warning is None


def test_collect_large_transactions_unavailable_on_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing DuckDB analytics should mark the large-transaction signal unavailable."""
    # Arrange
    config = Config(data_dir=tmp_path)

    def _raise_import_error(*_args: object, **_kwargs: object) -> None:
        raise ImportError("DuckDB is not installed")

    monkeypatch.setattr(large_transactions, "DuckDBAnalytics", _raise_import_error)

    # Act
    signal, warning = _collect_large_transactions(
        config=config,
        threshold=300000,
        sample_limit=5,
    )

    # Assert
    assert signal.status == "unavailable"
    assert signal.threshold == 300000
    assert signal.count == 0
    assert signal.samples == []
    assert warning == "Large-transaction signal unavailable; check DuckDB analytics setup."


def test_collect_large_transactions_unavailable_on_duckdb_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DuckDB query failures should mark the large-transaction signal unavailable."""
    # Arrange
    duckdb = pytest.importorskip("duckdb")
    config = Config(data_dir=tmp_path)

    class _FailingAnalytics:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise duckdb.Error("query failed")

        def __enter__(self) -> "_FailingAnalytics":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(large_transactions, "DuckDBAnalytics", _FailingAnalytics)

    # Act
    signal, warning = _collect_large_transactions(
        config=config,
        threshold=300000,
        sample_limit=5,
    )

    # Assert
    assert signal.status == "unavailable"
    assert signal.threshold == 300000
    assert warning == (
        "Large-transaction signal unavailable; check transaction data and analytics setup."
    )


def test_optional_text_normalizes_blank_values() -> None:
    """Blank merchant/account/category values should collapse to None."""
    assert _optional_text(None) is None
    assert _optional_text("") is None
    assert _optional_text("  ") is None
    assert _optional_text("항공사") == "항공사"
