"""Tests for the assets CLI command group."""

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _write_snapshot(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write an asset snapshot partition for tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "assets" / "snapshots" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "snapshots.csv")


def _write_balance(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write a Banksalad balance partition for tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "banksalad" / "balance" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "balance.csv")


@pytest.fixture
def asset_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with asset snapshot fixtures."""
    data_dir = tmp_path / "asset-data"
    data_dir.mkdir()

    # Minimal required dirs for Config validation
    (data_dir / "imports").mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n")

    _write_snapshot(
        data_dir,
        "2026-03",
        [
            {
                "snapshot_date": "2026-03-15",
                "account_id": "증권계좌",
                "instrument_id": "AAPL",
                "quantity": 10.0,
                "market_value": 2500000.0,
                "currency": "KRW",
                "file_id": "260315_1",
                "source_row": 1,
            },
            {
                "snapshot_date": "2026-03-15",
                "account_id": "증권계좌",
                "instrument_id": "MSFT",
                "quantity": 5.0,
                "market_value": 1800000.0,
                "currency": "KRW",
                "file_id": "260315_1",
                "source_row": 2,
            },
            {
                "snapshot_date": "2026-03-15",
                "account_id": "미래에셋",
                "instrument_id": "SPY",
                "quantity": 20.0,
                "market_value": 5000000.0,
                "currency": "KRW",
                "file_id": "260315_1",
                "source_row": 3,
            },
        ],
    )

    return data_dir


@pytest.fixture
def empty_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with no asset snapshots."""
    data_dir = tmp_path / "empty-data"
    data_dir.mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n")
    return data_dir


class TestAssetsStatus:
    """Tests for finjuice assets status."""

    def test_status_shows_portfolio_overview(self, asset_data_dir: Path) -> None:
        result = runner.invoke(app, ["--data-dir", str(asset_data_dir), "assets", "status"])

        assert result.exit_code == 0
        assert "2026-03-15" in result.output
        assert "증권계좌" in result.output
        assert "미래에셋" in result.output

    def test_status_json_output(self, asset_data_dir: Path) -> None:
        result = runner.invoke(
            app, ["--data-dir", str(asset_data_dir), "assets", "status", "--json"]
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "assets status"
        assert payload["has_data"] is True
        assert payload["total_value"] == 9300000.0
        assert payload["account_count"] == 2
        assert payload["position_count"] == 3
        assert payload["snapshot_date"] == "2026-03-15"

    def test_status_no_data(self, empty_data_dir: Path) -> None:
        result = runner.invoke(app, ["--data-dir", str(empty_data_dir), "assets", "status"])

        assert result.exit_code == 0
        assert "없음" in result.output

    def test_status_no_data_json(self, empty_data_dir: Path) -> None:
        result = runner.invoke(
            app, ["--data-dir", str(empty_data_dir), "assets", "status", "--json"]
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "assets status"
        assert payload["has_data"] is False


class TestAssetsShow:
    """Tests for finjuice assets show."""

    def test_show_lists_holdings(self, asset_data_dir: Path) -> None:
        result = runner.invoke(app, ["--data-dir", str(asset_data_dir), "assets", "show"])

        assert result.exit_code == 0
        assert "AAPL" in result.output
        assert "MSFT" in result.output
        assert "SPY" in result.output
        assert "3 positions" in result.output

    def test_show_json_output(self, asset_data_dir: Path) -> None:
        result = runner.invoke(app, ["--data-dir", str(asset_data_dir), "assets", "show", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "assets show"
        assert payload["has_data"] is True
        assert payload["total_count"] == 3
        assert len(payload["holdings"]) == 3
        # Sorted by market_value descending
        assert payload["holdings"][0]["instrument_id"] == "SPY"

    def test_show_account_filter(self, asset_data_dir: Path) -> None:
        result = runner.invoke(
            app,
            ["--data-dir", str(asset_data_dir), "assets", "show", "--account", "증권계좌"],
        )

        assert result.exit_code == 0
        assert "AAPL" in result.output
        assert "MSFT" in result.output
        assert "2 positions" in result.output

    def test_show_limit(self, asset_data_dir: Path) -> None:
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(asset_data_dir),
                "assets",
                "show",
                "--limit",
                "1",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "assets show"
        assert payload["total_count"] == 1

    def test_show_no_data(self, empty_data_dir: Path) -> None:
        result = runner.invoke(app, ["--data-dir", str(empty_data_dir), "assets", "show"])

        assert result.exit_code != 0  # exits with error for no data

    def test_show_no_data_json_command_name(self, empty_data_dir: Path) -> None:
        result = runner.invoke(app, ["--data-dir", str(empty_data_dir), "assets", "show", "--json"])

        assert result.exit_code == 4
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "assets show"
        assert payload["error"]["code"] == "NO_DATA"

    def test_show_help(self, asset_data_dir: Path) -> None:
        result = runner.invoke(app, ["--data-dir", str(asset_data_dir), "assets", "show", "--help"])

        assert result.exit_code == 0
        assert "--month" in result.output
        assert "--account" in result.output
        assert "--limit" in result.output


class TestAssetsBalance:
    """Tests for finjuice assets balance."""

    def test_balance_json_returns_latest_overview_rows(self, empty_data_dir: Path) -> None:
        _write_balance(
            empty_data_dir,
            "2026-05",
            [
                {
                    "snapshot_date": "2026-05-20",
                    "side": "asset",
                    "category": "deposit",
                    "item_name": "예금",
                    "amount": 1000000.0,
                    "currency": "KRW",
                    "source_fact_id": "fact_old",
                    "file_id": "260520_1",
                    "source_row": 5,
                }
            ],
        )
        _write_balance(
            empty_data_dir,
            "2026-06",
            [
                {
                    "snapshot_date": "2026-06-15",
                    "side": "asset",
                    "category": "deposit",
                    "item_name": "입출금",
                    "amount": 3000000.0,
                    "currency": "KRW",
                    "source_fact_id": "fact_asset",
                    "file_id": "260615_1",
                    "source_row": 5,
                },
                {
                    "snapshot_date": "2026-06-15",
                    "side": "liability",
                    "category": "loan",
                    "item_name": "신용대출",
                    "amount": 1200000.0,
                    "currency": "KRW",
                    "source_fact_id": "fact_liability",
                    "file_id": "260615_1",
                    "source_row": 6,
                },
            ],
        )

        result = runner.invoke(
            app,
            ["--data-dir", str(empty_data_dir), "assets", "balance", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "assets balance"
        assert payload["has_data"] is True
        assert payload["latest_month"] == "2026-06"
        assert payload["snapshot_date"] == "2026-06-15"
        assert payload["total_assets"] == 3000000.0
        assert payload["total_liabilities"] == 1200000.0
        assert payload["assets"] == [
            {
                "category": "deposit",
                "item_name": "입출금",
                "amount": 3000000.0,
                "currency": "KRW",
            }
        ]
        assert payload["liabilities"] == [
            {
                "category": "loan",
                "item_name": "신용대출",
                "amount": 1200000.0,
                "currency": "KRW",
            }
        ]
        assert "source_fact_id" not in result.output
        assert "file_id" not in result.output

    def test_balance_no_data_json(self, empty_data_dir: Path) -> None:
        result = runner.invoke(
            app,
            ["--data-dir", str(empty_data_dir), "assets", "balance", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "assets balance"
        assert payload["has_data"] is False
        assert payload["assets"] == []
        assert payload["liabilities"] == []
