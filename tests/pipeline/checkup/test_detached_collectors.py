"""Detached collectors preserve legacy calculations without reopening source files."""

from datetime import date

import polars as pl
import pytest

from finjuice.pipeline.asset_config import validate_assets_config_file
from finjuice.pipeline.checkup import budget, networth, obligations, review
from finjuice.pipeline.checkup.partitions import read_all_partitions, read_month_partition
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import load_goals_file
from finjuice.pipeline.networth import build_networth_position, discover_snapshot_months
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions


def _forbid_read(*args, **kwargs):
    raise AssertionError("Detached calculation attempted file I/O")


def _rows():
    return [
        _tx_row("2026-01-12", -105_000.0, "market", category_final="food", tags_final='["food"]'),
        _tx_row("2026-01-15", -30_000.0, "clinic", category_final="medical", tags_final="[]"),
        {
            **_tx_row(
                "2026-01-16",
                -90_000.0,
                "transfer",
                category_final="food",
                tags_final="[]",
                is_transfer=1,
            ),
            "transfer_group_id": "confirmed",
        },
    ]


@pytest.mark.parametrize("goals_state", ["missing", "invalid", "valid"])
@pytest.mark.parametrize("empty", [False, True])
def test_detached_budget_matches_legacy(tmp_path, monkeypatch, goals_state, empty):
    data_dir = init_data_dir(tmp_path)
    config = Config(data_dir=data_dir)
    if goals_state != "missing":
        config.goals_file.write_text(
            "version: 1\nmonthly_budget: invalid\n"
            if goals_state == "invalid"
            else "version: 1\nmonthly_budget:\n  total: 100000\n  categories:\n    food: 100000\n"
        )
    write_transactions(data_dir, "2026-01", _rows())
    frame = read_month_partition(config.csv_base_dir, "2026-01")
    if empty:
        frame = frame.head(0)
        frame.write_csv(config.csv_base_dir / "2026/01/transactions.csv")
    expected = budget.collect_budget_posture(config, today=date(2030, 1, 1))
    goals = load_goals_file(config.goals_file)
    monkeypatch.setattr(budget, "load_goals_file", _forbid_read)
    monkeypatch.setattr(budget, "read_month_partition", _forbid_read)
    monkeypatch.setattr(budget, "load_report_filters", _forbid_read)
    actual = budget.build_budget_posture(
        goals, frame, month="2026-01", report_filters=ReportFilters()
    )
    assert actual == expected
    assert actual.month == "2026-01"
    if goals_state == "valid" and not empty:
        assert actual.summary.actual == 135000
        assert actual.unbudgeted_categories == ["medical"]
        assert actual.over_budget_categories == ["food"]


@pytest.mark.parametrize("assets_state", ["missing", "invalid", "manual"])
def test_detached_networth_matches_legacy(tmp_path, monkeypatch, assets_state):
    data_dir = init_data_dir(tmp_path)
    config = Config(data_dir=data_dir)
    if assets_state != "missing":
        config.assets_file.write_text(
            "version: 1\nmanual_assets: invalid\n"
            if assets_state == "invalid"
            else "version: 1\nmanual_assets:\n  - name: home\n"
            "    category: real_estate\n    value: 200000\n"
            "liabilities:\n  - name: mortgage\n    principal: 300000\n"
        )
    config.goals_file.write_text(
        "version: 1\nmonthly_budget:\n  total: 100000\n  categories: {}\nnet_worth_target: 400000\n"
    )
    expected = networth.collect_networth_posture(config)
    validation = validate_assets_config_file(config.assets_file, allow_missing_file=True)
    months = discover_snapshot_months(data_dir / "assets/snapshots")
    position = (
        build_networth_position(data_dir / "assets/snapshots", config.assets_file)
        if validation.is_valid
        else None
    )
    target = networth._load_networth_target(config.goals_file)
    monkeypatch.setattr(networth, "validate_assets_config_file", _forbid_read)
    monkeypatch.setattr(networth, "build_networth_position", _forbid_read)
    monkeypatch.setattr(networth, "load_goals_file", _forbid_read)
    actual = networth.build_networth_posture(months, validation, position, target)
    assert actual == expected
    assert actual.target == 400000
    if assets_state == "manual":
        assert actual.status == "negative"


@pytest.mark.parametrize("known", [False, True])
@pytest.mark.parametrize("empty", [False, True])
def test_detached_review_and_obligations_match_legacy(tmp_path, monkeypatch, empty, known):
    data_dir = init_data_dir(tmp_path)
    config = Config(data_dir=data_dir)
    if not empty:
        for month in tuple(f"2026-{month:02d}" for month in range(1, 9)):
            write_transactions(
                data_dir,
                month,
                [
                    _tx_row(
                        f"{month}-01", -600000, "rent", category_final="미분류", tags_final="[]"
                    ),
                ],
            )
    if known:
        config.goals_file.write_text(
            "version: 1\nmonthly_budget:\n  total: 1000000\n  categories: {}\n"
            "known_obligations:\n  - label: rent\n    kind: other\n    amount: 600000\n"
            "    frequency: monthly\n    as_of: '2026-08-01'\n"
        )
    review_expected = review.collect_review_pressure(config, sample_limit=2)
    obligations_expected = obligations.collect_obligation_confirmation(config)
    frame = read_all_partitions(config.csv_base_dir)
    monthly = read_month_partition(config.csv_base_dir, "2026-08") if not empty else None
    goals = load_goals_file(config.goals_file)
    notes = review._load_checkup_rule_notes(config.rules_file)
    monkeypatch.setattr(review, "read_month_partition", _forbid_read)
    monkeypatch.setattr(review, "_load_checkup_rule_notes", _forbid_read)
    monkeypatch.setattr(obligations, "read_all_partitions", _forbid_read)
    monkeypatch.setattr(obligations, "load_goals_file", _forbid_read)
    assert (
        review.build_review_pressure(
            monthly, month="2026-08" if not empty else None, sample_limit=2, rule_notes=notes
        )
        == review_expected
    )
    assert obligations.build_obligation_confirmation(frame, goals) == obligations_expected
    assert obligations_expected.known_obligation_count == int(known)
    if not empty:
        assert obligations_expected.candidate_count == (0 if known else 1)


def test_detached_budget_preserves_supplied_filter_warning(tmp_path):
    goals = load_goals_file(tmp_path / "missing.yaml")
    result = budget.build_budget_posture(
        goals,
        pl.DataFrame(),
        month="2026-01",
        report_filters=ReportFilters(),
        filter_warning="unavailable",
    )
    assert "unavailable" in result.warning
    assert "unconfigured" in result.warning


def test_detached_budget_uses_supplied_filters(tmp_path):
    data_dir = init_data_dir(tmp_path)
    config = Config(data_dir=data_dir)
    config.goals_file.write_text("version: 1\nmonthly_budget:\n  total: 100000\n  categories: {}\n")
    config.rules_file.write_text(
        "version: 1\nrules: []\nreport_filters:\n  excluded_merchants:\n"
        "    - pattern: clinic\n      reason: fixture\n"
    )
    write_transactions(data_dir, "2026-01", _rows())
    expected = budget.collect_budget_posture(config, today=date(2030, 1, 1))
    actual = budget.build_budget_posture(
        load_goals_file(config.goals_file),
        read_month_partition(config.csv_base_dir, "2026-01"),
        month="2026-01",
        report_filters=load_report_filters(config.rules_file),
    )
    assert actual == expected
    assert actual.filters_applied == 1
    assert actual.summary.actual == 105000
