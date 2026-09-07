"""Collector tests for tagging-pressure unavailable/clear/present behavior."""

from __future__ import annotations

from pathlib import Path

import pytest

import finjuice.pipeline.automation_tagging_pressure as tagging_pressure
from finjuice.pipeline.automation_tagging_pressure import (
    TaggingPressureSignal,
    _collect_tagging_pressure,
)
from finjuice.pipeline.config import Config
from tests.automation_fixtures import write_sample_transactions


def test_collect_tagging_pressure_clear_when_data_missing(tmp_path: Path) -> None:
    """Missing partitions should surface as a clear tagging-pressure signal."""
    # Arrange
    config = Config(data_dir=tmp_path)

    # Act
    signal, warning = _collect_tagging_pressure(config=config, sample_limit=5, min_count=2)

    # Assert
    assert isinstance(signal, TaggingPressureSignal)
    assert signal.status == "clear"
    assert signal.total_transactions == 0
    assert signal.untagged_transactions == 0
    assert signal.suggestable_untagged_transactions == 0
    assert signal.merchant_pressure == []
    assert warning is None


def test_collect_tagging_pressure_present_for_suggestable_untagged(tmp_path: Path) -> None:
    """Suggestable untagged merchants should surface as present pressure."""
    # Arrange
    write_sample_transactions(tmp_path)
    config = Config(data_dir=tmp_path)

    # Act
    signal, warning = _collect_tagging_pressure(config=config, sample_limit=3, min_count=2)

    # Assert
    assert signal.status == "present"
    assert signal.total_transactions == 5
    assert signal.untagged_transactions == 4
    assert signal.coverage_pct == pytest.approx(20.0)
    assert signal.suggestable_untagged_transactions == 4
    assert signal.suggestable_coverage_pct == pytest.approx(20.0)
    assert signal.transfer_excluded_untagged_transactions == 0
    assert [sample.merchant for sample in signal.merchant_pressure] == ["스타벅스"]
    assert warning is None


def test_collect_tagging_pressure_unavailable_on_import_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing DuckDB analytics should mark tagging pressure unavailable."""
    # Arrange
    config = Config(data_dir=tmp_path)

    def _raise_import_error(*_args: object, **_kwargs: object) -> None:
        raise ImportError("DuckDB is not installed")

    monkeypatch.setattr(tagging_pressure, "get_suggestion_coverage_stats", _raise_import_error)

    # Act
    signal, warning = _collect_tagging_pressure(config=config, sample_limit=5, min_count=2)

    # Assert
    assert signal.status == "unavailable"
    assert signal.total_transactions == 0
    assert signal.untagged_transactions == 0
    assert signal.suggestable_untagged_transactions == 0
    assert signal.merchant_pressure == []
    assert warning == "Tagging pressure unavailable; check DuckDB analytics setup."


def test_collect_tagging_pressure_unavailable_on_duckdb_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DuckDB query failures should mark tagging pressure unavailable."""
    # Arrange
    duckdb = pytest.importorskip("duckdb")
    config = Config(data_dir=tmp_path)

    def _raise_duckdb_error(*_args: object, **_kwargs: object) -> None:
        raise duckdb.Error("query failed")

    monkeypatch.setattr(tagging_pressure, "get_suggestion_coverage_stats", _raise_duckdb_error)

    # Act
    signal, warning = _collect_tagging_pressure(config=config, sample_limit=5, min_count=2)

    # Assert
    assert signal.status == "unavailable"
    assert signal.merchant_pressure == []
    assert warning == "Tagging pressure unavailable; check DuckDB analytics setup."


def test_collect_tagging_pressure_clear_on_missing_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FileNotFoundError is empty data, not an unavailable analytics setup."""
    # Arrange
    config = Config(data_dir=tmp_path)

    def _raise_missing(*_args: object, **_kwargs: object) -> None:
        raise FileNotFoundError("transactions")

    monkeypatch.setattr(tagging_pressure, "get_suggestion_coverage_stats", _raise_missing)

    # Act
    signal, warning = _collect_tagging_pressure(config=config, sample_limit=5, min_count=2)

    # Assert
    assert signal.status == "clear"
    assert signal.total_transactions == 0
    assert warning is None
