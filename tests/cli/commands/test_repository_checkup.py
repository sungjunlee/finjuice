"""Actual migration checkup parity, output contracts, and canonical authority fences."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.checkup import collect_checkup_bundle
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config import Config
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions


def _source(tmp_path: Path) -> Path:
    source = init_data_dir(tmp_path, "source")
    # Partition identity is authoritative for latest-month collectors, not row date.
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row(
                "2026-07-12",
                -120000.0,
                "SYNTHETIC_MERCHANT",
                category_final="food",
                tags_final="[]",
                needs_review=1,
            ),
        ],
    )
    (source / "goals.yaml").write_text(
        "version: 1\nmonthly_budget:\n  total: 100000\n  categories:\n    food: 100000\n"
        "net_worth_target: 500000\n"
    )
    (source / "assets.yaml").write_text(
        "version: 1\nmanual_assets:\n  - name: synthetic home\n"
        "    category: real_estate\n    value: 200000\n"
    )
    return source


@pytest.fixture
def checkup_root(tmp_path: Path) -> QueryRoot:
    return _activate(_source(tmp_path), tmp_path)


def _invoke(root: QueryRoot, *args: str, legacy: bool = False):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.legacy if legacy else root.root), "checkup", *args],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


def test_python_checkup_preserves_legacy_domains_and_partition_month(checkup_root):
    root = checkup_root
    today = date(2026, 9, 14)
    old = collect_checkup_bundle(Config(data_dir=root.legacy), today=today)
    new = collect_checkup_bundle(
        Config(data_dir=root.root), today=today, evidence_provider=root.provider
    )
    for domain in ("pipeline", "review", "budget", "networth", "obligations"):
        assert getattr(new, domain) == getattr(old, domain), domain
    assert new.review.month == new.budget.month == "2026-08"
    assert new.budget.summary.actual == 120000
    assert new.repository["dataset_revision"] == 0
    assert new.repository["calculation_as_of"] == "2026-09-14"


@pytest.mark.parametrize("privacy", ["raw", "redacted", "compact"])
def test_cli_checkup_profiles_preserve_shape_and_metadata(checkup_root, privacy):
    old = _invoke(checkup_root, "--json", "--privacy", privacy, legacy=True)
    new = _invoke(checkup_root, "--json", "--privacy", privacy)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    before, after = json.loads(old.output), json.loads(new.output)
    assert before.keys() == after.keys()
    assert before["domains"] == after["domains"]
    assert after["_meta"]["dataset_generation"] == checkup_root.generation
    assert after["_meta"]["dataset_revision"] == 0
    assert after["_meta"]["calculation_policy"] == "legacy_checkup.v1"
    if privacy == "compact":
        assert "samples" not in after["domains"]["review"]
        assert "data_dir" not in after
    elif privacy == "redacted":
        assert after["domains"]["budget"]["summary"]["actual"] is None
    else:
        assert after["domains"]["budget"]["summary"]["actual"] == 120000


def test_active_checkup_ignores_live_csv_and_yaml(checkup_root):
    root = checkup_root
    original = _invoke(root, "--json")
    assert original.exit_code == 0, original.output
    for relative in (
        "transactions/2026/08/transactions.csv",
        "rules.yaml",
        "goals.yaml",
        "assets.yaml",
    ):
        target = root.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_POISON: [invalid\n")
    repeated = _invoke(root, "--json")
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(original.output)["domains"] == json.loads(repeated.output)["domains"]
    assert "PRIVATE_POISON" not in repeated.output
    human = _invoke(root)
    assert human.exit_code == 0, human.output
    assert "Repository revision 0" in human.output
    assert "legacy_checkup.v1" in human.output


def test_fast_checkup_keeps_metadata_and_explicit_skips(checkup_root):
    result = _invoke(checkup_root, "--json", "--fast")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["fast"] is True
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["domains"]["review"]["status"] == "skipped"
    assert payload["domains"]["obligations"]["status"] == "skipped"
    assert payload["domains"]["budget"]["month"] == "2026-08"


@pytest.mark.parametrize(
    "state", ["goals_absent", "goals_invalid", "assets_invalid", "rules_invalid"]
)
def test_canonical_invalid_configuration_is_explicit(tmp_path, state):
    source = _source(tmp_path)
    if state == "goals_absent":
        (source / "goals.yaml").unlink()
    else:
        kind = state.split("_")[0]
        (source / f"{kind}.yaml").write_text("version: 1\nPRIVATE_INVALID: [\n")
    root = _activate(source, tmp_path)
    result = _invoke(root, "--json")
    if state == "rules_invalid":
        assert result.exit_code != 0
        assert "Canonical rules" in result.output
        assert "PRIVATE_INVALID" not in result.output
        return
    assert result.exit_code == 0, result.output
    domains = json.loads(result.output)["domains"]
    if state == "goals_absent":
        assert domains["budget"]["status"] == "missing_config"
        assert domains["budget"]["goals_file_exists"] is False
    elif state == "goals_invalid":
        assert domains["budget"]["status"] == "invalid"
        assert domains["networth"]["status"] == "target_unknown"
        assert domains["obligations"]["status"] == "unavailable"
        actions = [
            action
            for action in json.loads(result.output)["next_actions"]
            if action["domain"] == "obligations"
        ]
        assert len(actions) == 1
        assert actions[0]["command"] == "finjuice budget validate"
        assert "후보 0개" not in actions[0]["reason"]
    else:
        assert domains["networth"]["status"] == "invalid"
    assert "PRIVATE_INVALID" not in result.output


def test_active_checkup_requires_independent_authority_evidence(checkup_root):
    root = checkup_root
    # Plausible live files must not permit a legacy fallback when evidence is absent.
    write_transactions(
        root.root,
        "2026-08",
        [
            _tx_row("2026-08-01", -1.0, "PRIVATE_FALLBACK", category_final="food", tags_final="[]"),
        ],
    )
    result = CliRunner().invoke(app, ["--data-dir", str(root.root), "checkup", "--json"])
    assert result.exit_code != 0
    payload = json.loads(result.output)
    assert "domains" not in payload
    assert "Repository checkup could not read validated evidence." in result.output
    assert "PRIVATE_FALLBACK" not in result.output


def test_invalid_goals_do_not_misdiagnose_fresh_pipeline(tmp_path):
    source = _source(tmp_path)
    (source / "goals.yaml").write_text("version: 1\nPRIVATE_INVALID: [\n")
    root = _activate(source, tmp_path)
    today = date(2026, 7, 13)
    before = collect_checkup_bundle(Config(data_dir=source), today=today)
    actual = collect_checkup_bundle(
        Config(data_dir=root.root), today=today, evidence_provider=root.provider
    )
    assert before.pipeline.status == "healthy"
    assert actual.pipeline == before.pipeline
    assert actual.budget.status == "invalid"
    assert actual.networth.status == "target_unknown"
    assert actual.obligations.status == "unavailable"
    assert actual.actionable
    assert not any(action.command == "finjuice doctor" for action in actual.next_actions)
    assert any(action.command == "finjuice budget validate" for action in actual.next_actions)
