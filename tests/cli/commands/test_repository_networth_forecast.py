"""Forecast parity and configuration authority through real synthetic migrations."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import networth_forecast
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.portfolio_display import PortfolioDisplay
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot
from tests.cli.commands.test_networth import _build_populated_data_dir, _write_scenarios_yaml
from tests.cli.commands.test_repository_assets import _activate, _assert_baseline
from tests.cli.commands.test_repository_query import QueryRoot


def _source(tmp_path: Path, *, goals: bool = True) -> Path:
    source = _build_populated_data_dir(tmp_path)
    _write_scenarios_yaml(source)
    if goals:
        (source / "goals.yaml").write_text(
            "version: 1\nmonthly_budget: {total: 0, categories: {}}\nnet_worth_target: 2000000000\n"
        )
    return source


def _invoke(root: QueryRoot, args: list[str], *, legacy: bool = False, human: bool = False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "networth",
            "forecast",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize("goals", [True, False])
@pytest.mark.parametrize(
    "args", [["--years", "1"], ["--scenario", "all", "--years", "1", "--from", "2026-02-15"]]
)
def test_forecast_matches_legacy_and_ignores_live_files(
    tmp_path: Path, goals: bool, args: list[str]
):
    root = _activate(_source(tmp_path, goals=goals), tmp_path)
    legacy, active = _invoke(root, args, legacy=True), _invoke(root, args)
    assert legacy.exit_code == active.exit_code == 0, legacy.output + active.output
    before = json.loads(active.output)
    _assert_baseline(json.loads(legacy.output), before)
    assert before["_meta"]["dataset_revision"] == 0
    assert before["_meta"]["calculation_policy"] == "legacy_networth_forecast.v1"
    assert before["_meta"]["goals_selection_state"] == ("selected" if goals else "absent")
    for name in ("assets.yaml", "scenarios.yaml", "goals.yaml"):
        (root.root / name).write_text("PRIVATE_SENTINEL: [invalid")
    repeated = _invoke(root, args)
    assert repeated.exit_code == 0, repeated.output
    _assert_baseline(before, json.loads(repeated.output))
    human = _invoke(root, args, human=True)
    assert human.exit_code == 0, human.output
    assert "Repository revision 0" in human.output
    assert "legacy_networth_forecast.v1" in human.output


@pytest.mark.parametrize(
    ("name", "content"),
    [
        ("scenarios.yaml", None),
        ("scenarios.yaml", b"PRIVATE_SENTINEL: ["),
        ("scenarios.yaml", b"version: 1\nassumptions: PRIVATE_SENTINEL\n"),
        ("goals.yaml", b"version: 1\nmonthly_budget: PRIVATE_SENTINEL\n"),
        ("goals.yaml", b"PRIVATE_SENTINEL: ["),
        ("goals.yaml", b"\xffPRIVATE_SENTINEL"),
    ],
)
def test_forecast_rejects_invalid_or_missing_canonical_config(
    tmp_path: Path, name: str, content: bytes | None
):
    source = _source(tmp_path)
    if content is None:
        (source / name).unlink()
    else:
        (source / name).write_bytes(content)
    root = _activate(source, tmp_path)
    _write_scenarios_yaml(root.root)
    (root.root / "goals.yaml").write_text(
        "version: 1\nmonthly_budget: {total: 0, categories: {}}\n"
    )
    result = _invoke(root, ["--years", "1"])
    assert result.exit_code != 0
    assert "configuration" in result.output
    assert "PRIVATE_SENTINEL" not in result.output
    assert str(source) not in result.output


@pytest.mark.parametrize("kind", ["scenarios", "goals"])
def test_forecast_unselected_revision_is_not_absence(tmp_path: Path, monkeypatch, kind: str):
    root = _activate(_source(tmp_path), tmp_path)
    snapshot = read_portfolio_snapshot(root.root, root.provider)
    assert snapshot is not None
    selection = getattr(snapshot, kind)
    snapshot = replace(
        snapshot, **{kind: replace(selection, head=None, selection_state="unselected")}
    )
    monkeypatch.setattr(
        networth_forecast, "load_portfolio_display", lambda *_: PortfolioDisplay(snapshot)
    )
    result = _invoke(root, ["--years", "1"])
    assert result.exit_code != 0
    assert "valid selection" in result.output


def test_forecast_pins_all_configs_across_real_mutations(tmp_path: Path, monkeypatch):
    root = _activate(_source(tmp_path), tmp_path)
    expected = _invoke(root, ["--years", "1"])
    assert expected.exit_code == 0, expected.output
    original = networth_forecast.load_portfolio_display
    calls = []

    def load_then_mutate(*args):
        display = original(*args)
        assert display is not None
        calls.append(display.snapshot.info.dataset_revision)
        facade = StorageMutationFacade(root.root, root.provider)
        scenarios = display.snapshot.scenarios.head
        assert scenarios is not None
        facade.replace_config(
            ConfigDocument(
                "scenarios",
                scenarios.content.replace(b"2000000", b"0"),
                "parsed",
                None,
                "test.v1",
            )
        )
        facade.replace_config(
            ConfigDocument(
                "goals",
                b"version: 1\nmonthly_budget: {total: 0, categories: {}}\n",
                "parsed",
                None,
                "test.v1",
            )
        )
        return display

    monkeypatch.setattr(networth_forecast, "load_portfolio_display", load_then_mutate)
    actual = _invoke(root, ["--years", "1"])
    assert actual.exit_code == 0, actual.output
    _assert_baseline(json.loads(expected.output), json.loads(actual.output))
    assert calls == [0]
    monkeypatch.setattr(networth_forecast, "load_portfolio_display", original)
    fresh = _invoke(root, ["--years", "1"])
    assert fresh.exit_code == 0, fresh.output
    assert json.loads(fresh.output)["_meta"]["dataset_revision"] == 2
    assert json.loads(fresh.output)["summary"] != json.loads(actual.output)["summary"]


def test_forecast_requires_independent_authority_evidence(tmp_path: Path):
    root = _activate(_source(tmp_path), tmp_path)
    result = CliRunner().invoke(
        app, ["--data-dir", str(root.root), "networth", "forecast", "--years", "1", "--json"]
    )
    assert result.exit_code != 0
    assert "Repository portfolio evidence" in result.output
