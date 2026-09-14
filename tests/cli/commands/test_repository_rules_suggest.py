"""Canonical merchant suggestions preserve the existing CLI calculation contract."""

from __future__ import annotations

import json
import shutil

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_checkup import _source
from tests.pipeline.checkup.helpers import _tx_row, write_transactions
from tests.test_json_schemas import _load_schema, _validator_for


def _source_for_suggestions(tmp_path):
    source = _source(tmp_path)
    (source / "rules.yaml").write_text("version: 1\nrules: []\n")
    rows = []
    for index, (merchant, transfer, group, tags) in enumerate(
        [
            ("PRIVATE_CAFE", 0, "", "[]"),
            ("PRIVATE_CAFE", 0, "", "[]"),
            ("Market Green", 1, "", "[]"),
            ("Confirmed Transfer", 1, "pair", "[]"),
            ("Tagged Store", 0, "", '["food"]'),
        ],
        1,
    ):
        row = _tx_row(
            f"2026-08-0{index}",
            -1000,
            merchant,
            category_final="식비",
            tags_final=tags,
            is_transfer=transfer,
        )
        row.update(file_id="legacy-import", transfer_group_id=group, memo_raw="synthetic")
        rows.append(row)
    write_transactions(source, "2026-08", rows)
    return source


def _run(root, *args, human=False, legacy=False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "rules",
            "suggest",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize(
    "options", [[], ["--preview"], ["--file-id", "legacy-import"], ["--top", "1"]]
)
def test_suggestions_match_legacy_and_ignore_live_files(tmp_path, options):
    root = _activate(_source_for_suggestions(tmp_path), tmp_path)
    old, new = _run(root, *options, legacy=True), _run(root, *options)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    before, after = json.loads(old.output), json.loads(new.output)
    assert {k: v for k, v in before.items() if k != "_meta"} == {
        k: v for k, v in after.items() if k != "_meta"
    }
    assert after["total_count"] == 5
    assert after["suggestable_untagged_count"] == 3
    assert after["transfer_exclusions"]["excluded_count"] == 1
    assert after["_meta"]["authority"] == "repository"
    assert after["_meta"]["calculation_policy"] == "legacy_rules_suggest.v1"
    _validator_for(_load_schema("rules_suggest.schema.json")).validate(after)
    (root.root / "rules.yaml").write_text("PRIVATE_POISON: [")
    shutil.rmtree(root.root / "transactions", ignore_errors=True)
    repeated = _run(root, *options)
    assert repeated.exit_code == 0, repeated.output
    assert json.loads(repeated.output)["suggestions"] == after["suggestions"]


def test_canonical_dry_run_has_no_live_destination_or_mutation(tmp_path):
    root = _activate(_source_for_suggestions(tmp_path), tmp_path)
    before = read_transaction_snapshot(root.root, root.provider)
    result = _run(root, "--apply", "--dry-run")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rules_file"] is None and payload["rules_file_modified"] is False
    assert payload["would_apply"]
    _validator_for(_load_schema("rules_suggest.schema.json")).validate(payload)
    human = _run(root, "--apply", "--dry-run", human=True)
    assert human.exit_code == 0, human.output
    assert "Canonical rule candidates" in human.output
    assert "Dry run: no changes made" in human.output
    assert "Would update None" not in human.output
    after = read_transaction_snapshot(root.root, root.provider)
    assert before is not None and after is not None
    assert before.info.dataset_revision == after.info.dataset_revision == 0
    assert before.rows == after.rows


@pytest.mark.parametrize("privacy", ["redacted", "compact"])
@pytest.mark.parametrize("legacy", [False, True])
def test_suggestion_privacy_preserves_revision_without_merchant_details(tmp_path, privacy, legacy):
    root = _activate(_source_for_suggestions(tmp_path), tmp_path)
    result = _run(root, "--apply", "--dry-run", "--privacy", privacy, legacy=legacy)
    assert result.exit_code == 0, result.output
    assert "PRIVATE_CAFE" not in result.output
    if not legacy:
        assert json.loads(result.output)["_meta"]["dataset_revision"] == 0


def test_human_report_provenance_and_protected_destination(tmp_path):
    root = _activate(_source_for_suggestions(tmp_path), tmp_path)
    target = tmp_path / "suggestions.txt"
    result = _run(root, "--preview", "-o", str(target), human=True)
    assert result.exit_code == 0, result.output
    assert "Merchant Context Preview" in result.output
    assert "rules add --help" in result.output and "suggest --apply" not in result.output
    assert "Dataset revision: 0" in target.read_text()
    assert root.generation in target.read_text()
    blocked = root.root / "rules.yaml"
    blocked.write_bytes(b"original")
    failure = _run(root, "-o", str(blocked), human=True)
    assert failure.exit_code != 0
    assert blocked.read_bytes() == b"original"


@pytest.mark.parametrize(
    "options,code", [(["--dry-run"], 2), (["--file-id", "missing"], 4), (["--apply", "--yes"], 3)]
)
def test_invalid_options_missing_alias_and_actual_apply_fence(tmp_path, options, code):
    root = _activate(_source_for_suggestions(tmp_path), tmp_path)
    result = _run(root, *options)
    assert result.exit_code == code, result.output
    snapshot = read_transaction_snapshot(root.root, root.provider)
    assert snapshot is not None and snapshot.info.dataset_revision == 0


def test_empty_canonical_suggestions_are_not_missing_csv(tmp_path):
    source = _source_for_suggestions(tmp_path)
    shutil.rmtree(source / "transactions")
    root = _activate(source, tmp_path)
    result = _run(root, "--apply", "--dry-run")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total_count"] == 0 and payload["suggestions"] == []
    assert payload["rules_file"] is None and payload["would_apply"] == []
    assert payload["_meta"]["authority"] == "repository"
