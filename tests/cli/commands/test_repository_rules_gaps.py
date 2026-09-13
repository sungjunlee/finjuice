"""Actual migration gap and simulation consistency without live file dependencies."""

import json
import shutil

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.pipeline.checkup.helpers import _tx_row, write_transactions


def _invoke(root, *args, legacy=False, human=False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "rules",
            "gaps",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


def _gaps_source(tmp_path):
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row("2026-08-01", -100, "one", category_final="식비", tags_final="[]"),
            _tx_row("2026-08-02", 40, "one", category_final="식비", tags_final='["식비"]'),
            _tx_row("2026-08-03", -300, "two", category_final="기타", tags_final='["식비"]'),
            _tx_row("2026-08-04", -20, "", category_final="기타", tags_final="[]"),
        ],
    )
    return source


@pytest.mark.parametrize("options", [[], ["--no-simulate"], ["--actionable-only"], ["--top", "0"]])
def test_gaps_preserve_baseline_and_ignore_invalid_live_rules(tmp_path, options):
    source = _gaps_source(tmp_path)
    # Rules are not an input to the gap classifier.
    (source / "rules.yaml").write_text("INVALID_CANONICAL_RULE: [\n")
    root = _activate(source, tmp_path)
    old, new = _invoke(root, *options, legacy=True), _invoke(root, *options)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    before, after = json.loads(old.output), json.loads(new.output)
    assert {k: v for k, v in before.items() if k != "_meta"} == {
        k: v for k, v in after.items() if k != "_meta"
    }
    assert after["_meta"]["dataset_revision"] == 0
    assert after["critical_gaps"][0]["total_amount"] == 60
    assert after["critical_gaps"][0]["transaction_count"] == 2
    if "--no-simulate" not in options:
        assert after["simulations"][0]["expected_tagged"] == 4
        assert after["simulations"][0]["coverage_improvement_pct"] == 50.0
    for name in ("rules.yaml", "transactions/2026/08/transactions.csv"):
        target = root.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_POISON: [\n")
    repeated = _invoke(root, *options)
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(repeated.output)["summary"] == after["summary"]
    assert "PRIVATE_POISON" not in repeated.output


def test_gaps_human_output_report_matches_legacy(tmp_path):
    root = _activate(_gaps_source(tmp_path), tmp_path)
    old_path, new_path = tmp_path / "old.txt", tmp_path / "new.txt"
    old = _invoke(root, "--output", str(old_path), legacy=True, human=True)
    new = _invoke(root, "--output", str(new_path), human=True)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    report = new_path.read_text()
    assert report.endswith(old_path.read_text())
    assert report.startswith("Authority: repository\n")
    assert f"Dataset generation: {root.generation}" in report
    assert "Dataset revision: 0" in report
    assert "Calculation policy: legacy_rules_gaps.v1" in report
    displayed = _invoke(root, human=True)
    assert displayed.exit_code == 0, displayed.output
    assert report in displayed.output
    assert "Repository revision 0" in new.output


@pytest.mark.parametrize("human", [True, False])
def test_gaps_incomplete_refuses_output_before_writing(tmp_path, human):
    source = _gaps_source(tmp_path)
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row(
                "2026-09-01", -777777, "PRIVATE_ROW", category_final="food", tags_final="broken["
            ),
        ],
    )
    root = _activate(source, tmp_path)
    target = tmp_path / "report.txt"
    result = _invoke(root, "--output", str(target), human=human)
    assert result.exit_code != 0
    assert "complete validated data" in result.output
    assert "PRIVATE_ROW" not in result.output and "777777" not in result.output
    assert not target.exists()


def test_gaps_empty_active_is_success(tmp_path):
    source = _source(tmp_path)
    shutil.rmtree(source / "transactions")
    (source / "transactions").mkdir()
    root = _activate(source, tmp_path)
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["summary"]["critical_count"] == 0
    assert payload["simulations"] == []
    assert payload["_meta"]["dataset_generation"] == root.generation
    human = _invoke(root, human=True)
    assert human.exit_code == 0
    assert "finjuice init" not in human.output


def test_canonical_gaps_ties_have_stable_json_and_report_bytes(tmp_path):
    source = _source(tmp_path)
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row(f"2026-08-0{index}", -1, merchant, category_final="food", tags_final="[]")
            for index, merchant in enumerate(("d", "b", "a", "c"), 1)
        ],
    )
    root = _activate(source, tmp_path)
    payloads = []
    reports = []
    humans = []
    for index in range(3):
        result = _invoke(root)
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert [gap["merchant"] for gap in payload["critical_gaps"]] == ["a", "b", "c", "d"]
        payload.pop("_meta")  # Envelope timestamp changes independently of canonical calculation.
        payloads.append(payload)
        report_path = tmp_path / f"report-{index}.txt"
        saved = _invoke(root, "--output", str(report_path), human=True)
        assert saved.exit_code == 0, saved.output
        reports.append(report_path.read_bytes())
        human = _invoke(root, human=True)
        assert human.exit_code == 0, human.output
        humans.append(human.output)
    assert payloads[0] == payloads[1] == payloads[2]
    assert reports[0] == reports[1] == reports[2]
    assert humans[0] == humans[1] == humans[2]
