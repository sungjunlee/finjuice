"""Actual migration review parity and authoritative notes boundaries."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import review
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands.test_repository_assets import _activate, _assert_baseline
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_review import review_data_dir as _review_fixture

review_data_dir = _review_fixture


@pytest.fixture
def root(review_data_dir: Path, tmp_path: Path) -> QueryRoot:
    for path in review_data_dir.glob("transactions/*/*/transactions.csv"):
        frame = pl.read_csv(path).with_columns(
            pl.lit("expense").alias("type_norm"),
            pl.lit("KRW").alias("currency"),
            pl.lit("synthetic").alias("file_id"),
            pl.lit("synthetic-account").alias("account"),
            *[pl.lit("[]").alias(name) for name in ("tags_rule", "tags_ai", "tags_manual")],
            pl.col("tags_final").fill_null("[]").replace("", "[]"),
        )
        frame.write_csv(path)
    return _activate(review_data_dir, tmp_path)


def _invoke(root: QueryRoot, args: list[str], *, legacy: bool = False, human: bool = False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "review",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--all-history"],
        ["--month", "2025-10"],
        ["--untagged", "--low-confidence", "0.7"],
        ["--limit", "1", "--cursor", "1"],
        ["--privacy", "redacted"],
        ["--privacy", "compact"],
    ],
)
def test_parity_and_poison(root: QueryRoot, args: list[str]) -> None:
    old, new = _invoke(root, args, legacy=True), _invoke(root, args)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    expected, actual = json.loads(old.output), json.loads(new.output)
    _assert_baseline(expected, actual)
    assert actual["_meta"]["dataset_revision"] == 0
    (root.root / "rules.yaml").write_text("PRIVATE_SENTINEL: [")
    partition = root.root / "transactions/2025/11/transactions.csv"
    partition.parent.mkdir(parents=True)
    partition.write_text("PRIVATE_SENTINEL,corrupt\n")
    assert _invoke(root, args).exit_code == 0
    _assert_baseline(actual, json.loads(_invoke(root, args).output))


def test_authority_human_and_max_bytes(root: QueryRoot) -> None:
    failed = CliRunner().invoke(app, ["--data-dir", str(root.root), "review", "--json"])
    assert failed.exit_code != 0
    assert "Repository review could not be read" in failed.output
    assert "Repository revision 0" in _invoke(root, [], human=True).output
    result = _invoke(root, ["--all-history", "--max-bytes", "3000"])
    assert result.exit_code == 0, result.output
    assert len(result.output.encode()) <= 3000
    assert json.loads(result.output)["_meta"]["calculation_policy"] == "legacy_review.v1"


def test_notes_invalid_and_unselected_warn_without_hiding_rows(
    root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = review.read_analysis_source
    snapshot = original(root.root, root.provider)
    assert snapshot is not None
    for rules in (
        replace(snapshot.rules, head=None, selection_state="unselected"),
        replace(snapshot.rules, head=replace(snapshot.rules.head, parsed_status="invalid")),
    ):
        monkeypatch.setattr(
            review, "read_analysis_source", lambda *_: replace(snapshot, rules=rules)
        )
        result = _invoke(root, [])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["signals"]["matched_count"] > 0
        assert payload["rule_notes"] == []
        assert "rule_notes_warning" in payload["_meta"]
        human = _invoke(root, [], human=True)
        assert human.exit_code == 0
        assert "Canonical rule notes are unavailable" in human.output


def test_read_is_pinned_after_config_mutation(root: QueryRoot, monkeypatch: pytest.MonkeyPatch):
    original = review.read_analysis_source
    calls = 0

    def read(*args):
        nonlocal calls
        calls += 1
        snapshot = original(*args)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("rules", b"PRIVATE_SENTINEL: [", "invalid", None, "test.v1")
        )
        return snapshot

    monkeypatch.setattr(review, "read_analysis_source", read)
    result = _invoke(root, [])
    assert result.exit_code == 0, result.output
    assert calls == 1
    assert json.loads(result.output)["_meta"]["dataset_revision"] == 0
    assert "rule_notes_warning" not in json.loads(result.output)["_meta"]


def test_valid_notes_ignore_report_filters_and_private_unknown_fields(
    root: QueryRoot, caplog: pytest.LogCaptureFixture
) -> None:
    content = b"""version: 1
rules:
  - name: visible rule
    match: coffee
    fields: [merchant_raw]
    tags: [food]
    notes: canonical note
    PRIVATE_SENTINEL: ignored
report_filters:
  excluded_categories: invalid
"""
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", content, "parsed", None, "test.v1")
    )
    result = _invoke(root, [])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rule_notes"][0]["notes"] == "canonical note"
    assert payload["signals"]["matched_count"] > 0
    assert "PRIVATE_SENTINEL" not in caplog.text
    assert "rule_notes_warning" not in payload["_meta"]


def test_explicit_month_filters_date_but_latest_does_not(
    review_data_dir: Path, tmp_path: Path
) -> None:
    for path in review_data_dir.glob("transactions/*/*/transactions.csv"):
        pl.read_csv(path).with_columns(
            pl.lit("expense").alias("type_norm"),
            pl.lit("synthetic").alias("account"),
            *[pl.lit("[]").alias(name) for name in ("tags_rule", "tags_ai", "tags_manual")],
            pl.col("tags_final").fill_null("[]").replace("", "[]"),
            pl.lit("2025-10-01").alias("date"),
        ).write_csv(path)
    selected = _activate(review_data_dir, tmp_path)
    for args in ([], ["--month", "2025-11"], ["--all-history"]):
        old, new = _invoke(selected, args, legacy=True), _invoke(selected, args)
        assert old.exit_code == new.exit_code == 0
        _assert_baseline(json.loads(old.output), json.loads(new.output))
    assert json.loads(_invoke(selected, ["--month", "2025-11"]).output)["total_count"] == 0
    assert json.loads(_invoke(selected, []).output)["total_count"] > 0


def test_empty_latest_and_missing_month_keep_legacy_contract(
    review_data_dir: Path, tmp_path: Path
) -> None:
    empty = review_data_dir / "transactions/2025/12/transactions.csv"
    empty.parent.mkdir(parents=True)
    frame = pl.read_csv(review_data_dir / "transactions/2025/11/transactions.csv").head(0)
    frame.write_csv(empty)
    selected = _activate(review_data_dir, tmp_path)
    for args in ([], ["--month", "2025-12"], ["--month", "2024-01"]):
        old, new = _invoke(selected, args, legacy=True), _invoke(selected, args)
        assert old.exit_code == new.exit_code, old.output + new.output
        _assert_baseline(json.loads(old.output), json.loads(new.output))
    payload = json.loads(_invoke(selected, []).output)
    assert payload["month"] == "2025-12" and payload["total_count"] == 0
    assert "rule_notes_warning" not in payload["_meta"]


@pytest.mark.parametrize("literal", ["", "NA", "NULL"])
def test_review_preserves_csv_null_display_literals(tmp_path, literal):
    from tests.cli.commands.test_repository_checkup import _source
    from tests.pipeline.checkup.helpers import _tx_row, write_transactions

    source = _source(tmp_path)
    row = _tx_row("2026-08-01", -100, literal, category_final=literal, tags_final="[]")
    write_transactions(source, "2026-08", [row])
    root = _activate(source, tmp_path)
    before, after = _invoke(root, [], legacy=True), _invoke(root, [])
    assert before.exit_code == after.exit_code == 0, before.output + after.output
    expected, actual = json.loads(before.output), json.loads(after.output)
    assert expected["transactions"] == actual["transactions"]
    assert actual["transactions"][0]["category_final"] is None
    assert actual["transactions"][0]["merchant_raw"] is None
