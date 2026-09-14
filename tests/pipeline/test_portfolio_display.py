"""Display partitions retain proven source scope and exact sidecars."""

from __future__ import annotations

import math
from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline.migration.policy import MANUAL_STATE_POLICY
from finjuice.pipeline.portfolio_display import PortfolioDisplay, PortfolioDisplayError
from finjuice.pipeline.storage.sqlite import RepositoryReader
from tests.pipeline.test_sqlite_exact_import import _asset_book, _import, _overview_book, _Repo
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture
from tests.pipeline.test_sqlite_portfolio_reads import _candidate

repo = _repo_fixture


def test_actual_migration_primary_only_empty_month_exact_and_detached(tmp_path: Path) -> None:
    database = _candidate(tmp_path, extra_root=True)
    with RepositoryReader(database, expected_schema_version=5) as reader:
        snapshot = reader.portfolio_snapshot()
    (tmp_path / "source/assets/snapshots/2026/01/snapshots.csv").write_text("changed")
    display = PortfolioDisplay(snapshot)
    assert display.snapshot_months == ("2026-01", "2026-02")
    empty = display.snapshot_partition("2026-02")
    assert empty is not None and empty.is_empty()
    assert display.snapshot_partition("2026-03") is None
    frame = display.snapshot_partition("2026-01")
    assert frame is not None and frame.height == 1
    row = frame.row(0, named=True)
    assert (row["account_id"], row["instrument_id"]) == ("account", "resource")
    assert row["account_entity_id"] != row["account_id"]
    assert row["quantity_lexical"] == "-0.000"
    assert math.copysign(1, row["quantity"]) == -1
    assert row["currency"] is None
    assert row["currency_source"] == ""
    assert row["market_value_lexical"] == "9007199254740993.01"
    assert row["currency_unknown"] == 1
    balance = display.balance_partition("2026-01")
    assert balance is not None and balance.height == 1
    assert balance["source_basis"].to_list() == ["reported"]
    assert display.metadata()["preserved_reference_counts"] == {"ambiguous": 6, "missing": 4}


def test_path_month_is_not_rewritten_to_row_date(tmp_path: Path) -> None:
    with RepositoryReader(_candidate(tmp_path), expected_schema_version=5) as reader:
        snapshot = reader.portfolio_snapshot()
    row = {**snapshot.asset_snapshots[0], "snapshot_date": "2025-12-31"}
    display = PortfolioDisplay(replace(snapshot, asset_snapshots=(row,)))
    frame = display.snapshot_partition("2026-01")
    assert frame is not None and frame["snapshot_date"].to_list() == ["2025-12-31"]
    assert "2025-12" not in display.snapshot_months


def test_schema_capability_does_not_hide_unmaterialized_report(tmp_path: Path) -> None:
    with RepositoryReader(
        _candidate(tmp_path, MANUAL_STATE_POLICY), expected_schema_version=4
    ) as reader:
        snapshot = reader.portfolio_snapshot()
    display = PortfolioDisplay(snapshot)
    assert display.snapshot_months
    with pytest.raises(PortfolioDisplayError, match="lack typed"):
        display.balance_partition("2026-01")


def test_missing_asset_counterpart_and_float_overflow_are_static_errors(tmp_path: Path) -> None:
    with RepositoryReader(_candidate(tmp_path), expected_schema_version=5) as reader:
        snapshot = reader.portfolio_snapshot()
    with pytest.raises(PortfolioDisplayError, match="lack typed"):
        PortfolioDisplay(replace(snapshot, asset_snapshots=())).snapshot_partition("2026-01")
    values = tuple({**row, "coefficient": "9" * 400} for row in snapshot.evidence["exact_values"])
    overflow = replace(snapshot, evidence={**snapshot.evidence, "exact_values": values})
    with pytest.raises(PortfolioDisplayError, match="finite display range"):
        PortfolioDisplay(overflow).snapshot_partition("2026-01")


def test_native_rows_have_explicit_identity_labels_and_exact_sidecars(repo: _Repo) -> None:
    _import(repo, _asset_book(), key="asset", revision=0)
    _import(repo, _overview_book(), key="overview", revision=repo.revision())
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.portfolio_snapshot()
    display = PortfolioDisplay(snapshot)
    frame = display.snapshot_partition(display.snapshot_months[0])
    assert frame is not None
    row = frame.row(0, named=True)
    assert row["account_id"] == "native-account:" + row["account_entity_id"]
    assert row["instrument_id"] == "native-instrument:" + row["resource_entity_id"]
    assert row["market_value_lexical"] is not None
    balance = display.balance_partition(display.balance_months[0])
    assert balance is not None and balance["source_basis"].to_list() == ["native"]


def test_incomplete_report_headers_are_preserved_but_not_empty_display(tmp_path: Path) -> None:
    from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot
    from tests.cli.commands.test_repository_assets import _activate

    source = tmp_path / "source"
    report = source / "banksalad/balance/2026/03/balance.csv"
    report.parent.mkdir(parents=True)
    report.write_text(
        "snapshot_date,side,category,item_name,amount,currency,source_fact_id\n"
        "2026-03-15,asset,financial,holding,4300000.0,KRW,missing\n"
    )
    active = _activate(source, tmp_path)
    snapshot = read_portfolio_snapshot(active.root, active.provider)
    assert snapshot is not None
    assert snapshot.legacy_overview_reports["legacy_overview_reports"] == ()
    assert snapshot.evidence["legacy_payloads"]
    with pytest.raises(PortfolioDisplayError, match="lack typed"):
        PortfolioDisplay(snapshot).balance_partition("2026-03")
