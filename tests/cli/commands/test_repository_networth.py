"""Pinned repository net worth parity, config authority, and date selection."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.portfolio_display import PortfolioDisplayError
from finjuice.pipeline.portfolio_networth import _assets_config, _select_partition
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.storage.sqlite.status_reads import ConfigHeadSnapshot
from tests.cli.commands.test_networth import _build_populated_data_dir, _write_balance
from tests.cli.commands.test_repository_assets import _activate, _assert_baseline
from tests.cli.commands.test_repository_query import QueryRoot


def _invoke(root: QueryRoot, args: list[str], *, legacy: bool = False, human: bool = False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "networth",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["breakdown", "--by", "category"],
        ["--date", "2026-02-15"],
        ["breakdown", "--by", "asset", "--date", "2026-02-15"],
    ],
)
@pytest.mark.parametrize("manual", [True, False])
def test_repository_parity_and_live_independence(tmp_path: Path, args: list[str], manual: bool):
    source = _build_populated_data_dir(tmp_path)
    if not manual:
        (source / "assets.yaml").unlink()
    _write_balance(
        source,
        "2026-03",
        [
            {
                "snapshot_date": "2026-03-15",
                "side": "asset",
                "category": "real_estate",
                "item_name": "거주 부동산",
                "amount": 1.0,
                "currency": "KRW",
                "file_id": "synthetic",
                "source_row": 1,
                "source_fact_id": "missing",
            },
            {
                "snapshot_date": "2026-03-15",
                "side": "liability",
                "category": "loan",
                "item_name": "담보대출",
                "amount": 2.0,
                "currency": "KRW",
                "file_id": "synthetic",
                "source_row": 2,
                "source_fact_id": "missing",
            },
        ],
    )
    root = _activate(source, tmp_path)
    old, new = _invoke(root, args, legacy=True), _invoke(root, args)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    expected, actual = json.loads(old.output), json.loads(new.output)
    _assert_baseline(expected, actual)
    assert actual["_meta"]["dataset_revision"] == 0
    assert actual["_meta"]["assets_selection_state"] == ("selected" if manual else "absent")
    assert actual["_meta"]["manual_config_policy"] == (
        "selected_assets_config.v1" if manual else "canonical_absence_empty.v1"
    )
    (root.root / "assets.yaml").write_text("PRIVATE_SENTINEL: [invalid")
    partition = root.root / "banksalad/balance/2026/03/balance.csv"
    partition.parent.mkdir(parents=True)
    partition.write_text("PRIVATE_SENTINEL,invalid\n")
    repeated = _invoke(root, args)
    assert repeated.exit_code == 0, repeated.output
    _assert_baseline(actual, json.loads(repeated.output))
    human = _invoke(root, args, human=True)
    assert human.exit_code == 0, human.output
    assert "Repository revision 0" in human.output
    assert "legacy_portfolio_display.v1" in human.output


@pytest.mark.parametrize("raw", ["version: 1\nmanual_assets: invalid\n", "PRIVATE_SENTINEL: ["])
def test_invalid_canonical_assets_never_falls_back(tmp_path: Path, raw: str):
    source = _build_populated_data_dir(tmp_path)
    (source / "assets.yaml").write_text(raw)
    root = _activate(source, tmp_path)
    (root.root / "assets.yaml").write_text("version: 1\nmanual_assets: []\nliabilities: []\n")
    for args in ([], ["breakdown", "--by", "category"]):
        result = _invoke(root, args)
        assert result.exit_code != 0
        assert "configuration" in result.output
        assert "PRIVATE_SENTINEL" not in result.output
        assert str(source) not in result.output


def test_config_absence_requires_empty_inventory():
    for selection in (
        PortfolioConfigSnapshot(None, "unselected", ({"revision_id": "one"},)),
        PortfolioConfigSnapshot(None, "absent", ({"revision_id": "one"},)),
        PortfolioConfigSnapshot(None, "selected", ()),
        PortfolioConfigSnapshot(
            ConfigHeadSnapshot("assets", "one", "opaque", "now", b""),
            "selected",
            ({"revision_id": "one"},),
        ),
    ):
        with pytest.raises(PortfolioDisplayError):
            _assets_config(selection)


def test_selection_uses_partition_order_and_skips_empty_months():
    frames = {
        "2026-01": pl.DataFrame({"snapshot_date": ["2026-03-25"]}),
        "2026-02": pl.DataFrame({"snapshot_date": ["2026-01-20", "2026-01-21"]}),
        "2026-03": pl.DataFrame(schema={"snapshot_date": pl.String}),
    }
    selected = _select_partition(tuple(frames), frames.get, None)
    assert selected is not None
    assert selected.month == "2026-02"
    assert selected.snapshot_date == date(2026, 1, 21)
    assert _select_partition(tuple(frames), frames.get, date(2026, 1, 30)) is None


def test_unselected_snapshot_does_not_use_valid_live_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dataclasses import replace

    from finjuice.pipeline.cli.commands import networth_payload
    from finjuice.pipeline.portfolio_display import PortfolioDisplay
    from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot

    source = _build_populated_data_dir(tmp_path)
    root = _activate(source, tmp_path)
    snapshot = read_portfolio_snapshot(root.root, root.provider)
    assert snapshot is not None
    display = PortfolioDisplay(
        replace(snapshot, assets=replace(snapshot.assets, head=None, selection_state="unselected"))
    )
    (root.root / "assets.yaml").write_text("version: 1\nmanual_assets: []\nliabilities: []\n")
    monkeypatch.setattr(networth_payload, "load_portfolio_display", lambda *_: display)
    result = _invoke(root, [])
    assert result.exit_code != 0
    assert "valid selection" in result.output


def test_authority_required_and_detached_calculation_is_pinned(tmp_path: Path) -> None:
    from finjuice.pipeline.portfolio_display import PortfolioDisplay
    from finjuice.pipeline.portfolio_networth import build_repository_networth
    from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
    from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot

    root = _activate(_build_populated_data_dir(tmp_path), tmp_path)
    rejected = CliRunner().invoke(app, ["--data-dir", str(root.root), "networth", "--json"])
    assert rejected.exit_code != 0
    assert "Repository portfolio evidence" in rejected.output
    snapshot = read_portfolio_snapshot(root.root, root.provider)
    assert snapshot is not None
    display = PortfolioDisplay(snapshot)
    before, metadata = build_repository_networth(display)
    facade = StorageMutationFacade(root.root, root.provider)
    facade.replace_config(
        ConfigDocument(
            "assets", b"version: 1\nmanual_assets: []\nliabilities: []\n", "parsed", None, "test.v1"
        )
    )
    after, after_metadata = build_repository_networth(display)
    assert after == before
    assert after_metadata == metadata
    fresh = read_portfolio_snapshot(root.root, root.provider)
    assert fresh is not None
    updated, updated_metadata = build_repository_networth(PortfolioDisplay(fresh))
    assert updated_metadata["dataset_revision"] == metadata["dataset_revision"] + 1
    assert updated.net_worth != before.net_worth
