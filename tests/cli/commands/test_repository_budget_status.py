"""Standalone budget status parity across actual preservation migration."""

import json

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.pipeline.checkup.helpers import _tx_row, write_transactions


def _invoke(root, *args, legacy=False, no_filter=False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            *(["--no-filter"] if no_filter else []),
            "budget",
            "status",
            "--json",
            *args,
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize("month", [None, "2026-08", "2026-07"])
def test_repository_budget_matches_standalone_baseline(tmp_path, month):
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row("2026-07-12", -120000, "food", category_final="food", tags_final="[]"),
            _tx_row("2026-08-01", -900000, "savings", category_final="저축", tags_final='["저축"]'),
        ],
    )
    root = _activate(source, tmp_path)
    args = ["--month", month] if month else []
    old, new = _invoke(root, *args, legacy=True), _invoke(root, *args)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    before, after = json.loads(old.output), json.loads(new.output)
    for key in before.keys() - {"_meta", "goals_file"}:
        assert after[key] == before[key], key
    assert after["goals_file"]["path"] is None
    assert after["goals_file"]["authority"] == "repository"
    assert after["_meta"]["dataset_revision"] == 0
    assert after["summary"]["actual"] == (0 if month == "2026-07" else 120000)
    assert after["month"] == (month or "2026-08")
    for name in ("rules.yaml", "goals.yaml", "transactions/2026/08/transactions.csv"):
        target = root.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_POISON: [\n")
    again = _invoke(root, *args)
    assert again.exit_code == 0, again.output
    assert json.loads(again.output)["summary"] == after["summary"]
    assert "PRIVATE_POISON" not in again.output


@pytest.mark.parametrize("invalid_rules", [False, True])
def test_repository_budget_filters_are_lazy_and_bypassable(tmp_path, invalid_rules):
    source = _source(tmp_path)
    (source / "rules.yaml").write_text(
        "version: 1\nPRIVATE_RULES: [\n"
        if invalid_rules
        else "version: 1\nrules: []\nreport_filters:\n  excluded_merchants:\n"
        "    - pattern: SYNTHETIC_MERCHANT\n      reason: fixture\n"
    )
    root = _activate(source, tmp_path)
    missing = _invoke(root, "--month", "2026-09")
    assert missing.exit_code == 0, missing.output
    assert json.loads(missing.output)["_meta"]["filters_applied"] == 0
    bypass = _invoke(root, no_filter=True)
    assert bypass.exit_code == 0, bypass.output
    assert json.loads(bypass.output)["summary"]["actual"] == 120000
    filtered = _invoke(root)
    if invalid_rules:
        assert filtered.exit_code != 0
        assert "--no-filter" in filtered.output
        assert "PRIVATE_RULES" not in filtered.output
    else:
        assert filtered.exit_code == 0, filtered.output
        assert json.loads(filtered.output)["summary"]["actual"] == 0
        assert json.loads(filtered.output)["_meta"]["filters_applied"] == 1


@pytest.mark.parametrize("state", ["absent", "invalid"])
def test_repository_budget_goals_state(tmp_path, state):
    source = _source(tmp_path)
    if state == "absent":
        (source / "goals.yaml").unlink()
    else:
        (source / "goals.yaml").write_text("version: 1\nPRIVATE_GOALS: [\n")
    root = _activate(source, tmp_path)
    result = _invoke(root)
    if state == "invalid":
        assert result.exit_code != 0
        assert "PRIVATE_GOALS" not in result.output
    else:
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["summary"] is None
        assert payload["goals_file"]["exists"] is False
        assert payload["next_steps"][0]["command"] == "finjuice budget edit --help"


def test_repository_budget_never_falls_back_without_evidence(tmp_path):
    root = _activate(_source(tmp_path), tmp_path)
    result = CliRunner().invoke(app, ["--data-dir", str(root.root), "budget", "status", "--json"])
    assert result.exit_code != 0
    assert "Canonical analysis evidence could not be read." in result.output


def test_repository_budget_empty_latest_partition_stays_latest(tmp_path):
    source = _source(tmp_path)
    latest = source / "transactions/2026/09/transactions.csv"
    latest.parent.mkdir(parents=True)
    original = source / "transactions/2026/08/transactions.csv"
    latest.write_text(original.read_text().splitlines()[0] + "\n")
    root = _activate(source, tmp_path)
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["month"] == "2026-09"
    assert payload["summary"]["actual"] == 0


def test_repository_budget_pins_goals_before_concurrent_edit(tmp_path, monkeypatch):
    from finjuice.pipeline import budget_repository
    from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade

    root = _activate(_source(tmp_path), tmp_path)
    original = budget_repository.read_analysis_source
    calls = []

    def read_then_edit(data_dir, provider):
        snapshot = original(data_dir, provider)
        calls.append(snapshot.info.dataset_revision)
        facade = StorageMutationFacade(root.root, root.provider)
        facade.replace_config(
            ConfigDocument.from_validated_yaml(
                "goals",
                b"version: 1\nmonthly_budget:\n  total: 900000\n  categories: {}\n",
                parser_version="test",
            )
        )
        return snapshot

    monkeypatch.setattr(budget_repository, "read_analysis_source", read_then_edit)
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert calls == [0]
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["summary"]["target"] == 100000
    assert original(root.root, root.provider).info.dataset_revision == 1


def test_repository_budget_no_partitions_uses_calendar_month(tmp_path):
    import shutil
    from datetime import date

    source = _source(tmp_path)
    shutil.rmtree(source / "transactions")
    (source / "transactions").mkdir()
    root = _activate(source, tmp_path)
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["month"] == date.today().strftime("%Y-%m")
    assert payload["summary"]["actual"] == 0


def test_repository_budget_human_shows_canonical_revision(tmp_path):
    root = _activate(_source(tmp_path), tmp_path)
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "budget", "status"],
        obj={"activation_evidence_provider": root.provider},
    )
    assert result.exit_code == 0, result.output
    assert "Repository revision 0" in result.output
    assert "Canonical goals" in result.output


def test_repository_budget_unmaterialized_source_is_not_reported_as_zero(tmp_path):
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row(
                "2026-08-01", -10000, "raw excluded", category_final="food", tags_final="savings["
            ),
            _tx_row("2026-08-02", -20000, "raw kept", category_final="food", tags_final="broken["),
            _tx_row("2026-08-03", -30000, "filtered", category_final="food", tags_final="broken["),
        ],
    )
    (source / "rules.yaml").write_text(
        "version: 1\nrules: []\nreport_filters:\n  excluded_merchants:\n"
        "    - pattern: filtered\n      reason: fixture\n"
    )
    root = _activate(source, tmp_path)
    before, after = _invoke(root, legacy=True), _invoke(root)
    assert before.exit_code == 0, before.output
    expected = json.loads(before.output)
    assert expected["summary"]["actual"] == 20000
    assert expected["_meta"]["filters_applied"] == 1
    assert after.exit_code != 0, after.output
    actual = json.loads(after.output)
    assert "error" in actual and "summary" not in actual
    assert "20000" not in after.output
    assert "broken[" not in after.output
    assert "raw kept" not in after.output


@pytest.mark.parametrize("literal", ["", "NA", "NULL"])
def test_repository_budget_preserves_csv_null_category_fallback(tmp_path, literal):
    source = _source(tmp_path)
    row = _tx_row("2026-08-01", -100, "synthetic fallback", category_final=literal, tags_final="[]")
    row.update(category_rule=literal, minor_raw="food", major_raw="consumption")
    write_transactions(source, "2026-08", [row])
    root = _activate(source, tmp_path)
    before, after = _invoke(root, legacy=True), _invoke(root)
    assert before.exit_code == after.exit_code == 0, before.output + after.output
    expected, actual = json.loads(before.output), json.loads(after.output)
    assert expected["categories"] == actual["categories"]
    assert [row["name"] for row in actual["categories"]] == ["food"]
