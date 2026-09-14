"""Canonical history preserves legacy partition semantics and revision isolation."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.portfolio_display import PortfolioDisplay, PortfolioDisplayError
from finjuice.pipeline.portfolio_history import build_repository_history
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot


@pytest.fixture
def history_root(tmp_path: Path) -> QueryRoot:
    source = tmp_path / "source"
    for month, date in (("01", "2026-05-01"), ("02", "2026-01-01"), ("03", None)):
        target = source / f"assets/snapshots/2026/{month}/snapshots.csv"
        target.parent.mkdir(parents=True)
        target.write_text(
            "snapshot_date,account_id,instrument_id,quantity,market_value,currency\n"
            + (f"{date},account,holding,1,100,KRW\n" if date else "")
        )
    (source / "assets.yaml").write_text(
        "version: 1\nmanual_assets:\n  - name: holding\n    category: financial\n    value: 300\n"
        "liabilities:\n  - name: loan\n    principal: 20\n"
    )
    balance = source / "banksalad/balance/2026/02/balance.csv"
    balance.parent.mkdir(parents=True)
    balance.write_text("incomplete,opaque\nignored,90000\n")
    return _activate(source, tmp_path)


def _invoke(root: QueryRoot, *, legacy: bool = False, human: bool = False, months: int = 12):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "networth",
            "--date",
            "1900-01-01",
            "history",
            "--months",
            str(months),
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize("months", [1, 12])
def test_actual_history_parity_order_empty_manual_and_balance_ignored(
    history_root: QueryRoot, months: int
) -> None:
    old, new = (
        _invoke(history_root, legacy=True, months=months),
        _invoke(history_root, months=months),
    )
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    expected, actual = json.loads(old.output), json.loads(new.output)
    assert actual["history"] == expected["history"]
    assert all(row["net_worth"] == 280 for row in actual["history"])
    assert actual["history"][-1]["as_of"] == "2026-01-01"
    assert actual["_meta"]["as_of"] == "2026-01-01"
    assert actual["_meta"]["calculation_policy"] == "legacy_networth_history.v1"
    assert actual["_meta"]["dataset_revision"] == 0
    assert "Repository revision 0" in _invoke(history_root, human=True).output
    (history_root.root / "assets.yaml").write_text("PRIVATE_SENTINEL: invalid")
    csv = history_root.root / "assets/snapshots/2026/02/snapshots.csv"
    csv.parent.mkdir(parents=True)
    csv.write_text("PRIVATE_SENTINEL,invalid\n")
    repeated = _invoke(history_root, months=months)
    assert json.loads(repeated.output)["history"] == actual["history"]
    assert "PRIVATE_SENTINEL" not in repeated.output


def test_history_config_selection_and_pinned_revision(history_root: QueryRoot) -> None:
    snapshot = read_portfolio_snapshot(history_root.root, history_root.provider)
    assert snapshot is not None
    display = PortfolioDisplay(snapshot)
    before = build_repository_history(display, months=12)
    StorageMutationFacade(history_root.root, history_root.provider).replace_config(
        ConfigDocument("assets", b"PRIVATE_SENTINEL: [", "invalid", None, "test.v1")
    )
    assert build_repository_history(display, months=12) == before
    result = _invoke(history_root)
    assert result.exit_code != 0
    assert "PRIVATE_SENTINEL" not in result.output
    unselected = replace(snapshot.assets, head=None, selection_state="unselected")
    with pytest.raises(PortfolioDisplayError, match="valid selection"):
        build_repository_history(PortfolioDisplay(replace(snapshot, assets=unselected)), months=12)
