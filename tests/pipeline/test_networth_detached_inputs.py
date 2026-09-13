"""Detached assets configuration and net-worth selections preserve file API semantics."""

from datetime import date
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline import networth
from finjuice.pipeline.asset_config import (
    AssetsConfigValidationError,
    load_assets_config,
    load_assets_config_bytes,
    validate_assets_config_bytes,
    validate_assets_config_file,
)

CONFIG = (
    b"version: 1\nmanual_assets:\n  - name: fund\n    category: cash\n    value: 700\n"
    b"liabilities:\n  - name: loan\n    principal: 40\n"
)


@pytest.mark.parametrize(
    "content",
    [
        CONFIG,
        b"",
        b"version: 99\n",
        b"manual_assets: wrong\n",
        b"version: 1\nliabilities:\n  - name: bad\n    principal: wrong\n",
    ],
)
def test_file_and_bytes_share_complete_validation(tmp_path: Path, content: bytes) -> None:
    path = tmp_path / "assets.yaml"
    path.write_bytes(content)
    assert validate_assets_config_file(path) == validate_assets_config_bytes(
        content, source_label=path
    )
    result = validate_assets_config_bytes(content)
    if result.is_valid:
        assert load_assets_config_bytes(content) == load_assets_config(path)
    else:
        with pytest.raises(AssetsConfigValidationError):
            load_assets_config_bytes(content)


@pytest.mark.parametrize(
    "content,message",
    [
        (b"private-value: [", "invalid YAML syntax"),
        (b"private-value: \xff", "invalid UTF-8 encoding"),
    ],
)
def test_parser_errors_do_not_expose_original_bytes(content: bytes, message: str) -> None:
    result = validate_assets_config_bytes(content)
    assert [issue.message for issue in result.issues] == [message]
    with pytest.raises(AssetsConfigValidationError) as error:
        load_assets_config_bytes(content)
    assert "private-value" not in str(error.value)


def _selections():
    snapshot = networth.SnapshotSelection(
        "2026-02",
        date(2026, 2, 1),
        pl.DataFrame({"instrument_id": ["fund", "other"], "market_value": [999.0, 20.0]}),
    )
    balance = networth.BalanceSelection(
        "2026-01",
        date(2026, 1, 1),
        pl.DataFrame(
            {
                "side": ["asset", "liability"],
                "item_name": [" FUND ", " LOAN "],
                "category": ["deposit", "loan"],
                "amount": [900.0, 100.0],
                "currency": ["KRW", "KRW"],
            }
        ),
    )
    return snapshot, balance


@pytest.mark.parametrize(
    "use_balance,as_of", [(False, None), (True, None), (True, date(2026, 3, 1))]
)
def test_file_and_pure_position_use_same_precedence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, use_balance: bool, as_of: date | None
) -> None:
    snapshot, balance = _selections()
    path = tmp_path / "assets.yaml"
    path.write_bytes(CONFIG)
    monkeypatch.setattr(networth, "select_snapshot_as_of", lambda *args: snapshot)
    monkeypatch.setattr(networth, "select_balance_as_of", lambda *args: balance)
    expected = networth.build_networth_position(
        tmp_path / "snapshots",
        path,
        as_of=as_of,
        balance_dir=tmp_path / "balance" if use_balance else None,
    )
    config = load_assets_config_bytes(CONFIG)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected filesystem fallback")

    monkeypatch.setattr(networth, "select_snapshot_as_of", forbidden)
    monkeypatch.setattr(networth, "select_balance_as_of", forbidden)
    monkeypatch.setattr(networth, "load_assets_config", forbidden)
    monkeypatch.setattr(Path, "read_bytes", forbidden)
    actual = networth.build_networth_position_from_selections(
        snapshot, config, as_of=as_of, balance_selection=balance if use_balance else None
    )
    assert actual == expected
    assert actual.total_liabilities == 40
    assert actual.total_assets == (700 if use_balance else 720)
    assert actual.primary_source == ("overview" if use_balance else "snapshot")
    assert actual.as_of == (
        as_of or (balance.snapshot_date if use_balance else snapshot.snapshot_date)
    )


def test_manual_only_selection_and_missing_file_behavior(tmp_path: Path) -> None:
    missing = validate_assets_config_file(tmp_path / "missing.yaml")
    assert not missing.exists and missing.is_valid
    assert not validate_assets_config_file(
        tmp_path / "missing.yaml", allow_missing_file=False
    ).is_valid
    config = load_assets_config_bytes(CONFIG)
    result = networth.build_networth_position_from_selections(None, config)
    assert result.primary_source == "manual" and result.as_of is None
    assert result.net_worth == 660
