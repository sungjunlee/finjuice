"""Collector tests for tagging-pressure unavailable/clear/present behavior."""

from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

import finjuice.pipeline.automation_tagging_pressure as tagging_pressure
from finjuice.pipeline.automation_tagging_pressure import (
    TaggingPressureSignal,
    _collect_tagging_pressure,
)
from finjuice.pipeline.config import Config


def _write_sample_transactions(data_dir: Path) -> None:
    """Create a minimal partition with untagged merchant pressure."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "row_hash": ["r1", "r2", "r3", "r4", "r5"],
            "date": ["2024-10-01", "2024-10-03", "2024-10-05", "2024-10-07", "2024-10-08"],
            "time": ["09:00", "09:15", "12:00", "20:10", "08:00"],
            "merchant_raw": ["스타벅스", "스타벅스", "넷플릭스", "항공사", "내계좌이체"],
            "memo_raw": ["아이스 아메리카노", "", "정기결제", "출장", ""],
            "amount": [-4500.0, -5200.0, -17000.0, -800000.0, -120000.0],
            "account": ["신한카드", "신한카드", "현대카드", "기업카드", "신한은행"],
            "major_raw": ["식비", "식비", "구독", "여행", "이체"],
            "minor_raw": ["카페", "카페", "동영상", "항공", "이체"],
            "category_final": ["", "", "구독", "", "이체"],
            "category_rule": ["", "", "구독", "", ""],
            "tags_final": ["[]", "[]", '["구독"]', "[]", "[]"],
            "is_transfer": [0, 0, 0, 0, 1],
        }
    ).write_csv(partition_dir / "transactions.csv")


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
    _write_sample_transactions(tmp_path)
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
