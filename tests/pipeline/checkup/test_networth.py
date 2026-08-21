"""Focused tests for the net worth posture collector."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.checkup.networth import collect_networth_posture
from finjuice.pipeline.config import Config
from tests.pipeline.checkup.helpers import init_data_dir, write_snapshot


def test_collect_networth_posture_missing_data_is_actionable(tmp_path: Path) -> None:
    """No snapshots or assets.yaml entries should be an explicit missing_data posture."""
    data_dir = init_data_dir(tmp_path, "missing-networth")
    summary = collect_networth_posture(Config(data_dir=data_dir))

    assert summary.status == "missing_data"
    assert summary.actionable is True
    assert summary.warning is not None


def test_collect_networth_posture_invalid_assets_is_actionable(tmp_path: Path) -> None:
    """Invalid assets.yaml should not collapse into a healthy net worth posture."""
    data_dir = init_data_dir(tmp_path, "invalid-assets")
    (data_dir / "assets.yaml").write_text(
        "version: 1\nmanual_assets: not-a-list\n", encoding="utf-8"
    )

    summary = collect_networth_posture(Config(data_dir=data_dir))

    assert summary.status == "invalid"
    assert summary.actionable is True
    assert summary.assets_file_exists is True
    assert summary.warning is not None


def test_collect_networth_posture_negative_is_actionable(tmp_path: Path) -> None:
    """Liabilities exceeding assets should mark net worth as negative."""
    data_dir = init_data_dir(tmp_path, "negative")
    write_snapshot(
        data_dir,
        "2026-01",
        [
            {
                "snapshot_date": "2026-01-31",
                "account_id": "증권",
                "instrument_id": "ETF",
                "quantity": 1.0,
                "market_value": 20000000.0,
                "currency": "KRW",
                "file_id": "fixture_1",
                "source_row": 1,
            }
        ],
    )
    (data_dir / "assets.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "liabilities:",
                "  - name: 대출",
                "    principal: 40000000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    summary = collect_networth_posture(Config(data_dir=data_dir))

    assert summary.status == "negative"
    assert summary.actionable is True
    assert summary.net_worth == -20000000.0
