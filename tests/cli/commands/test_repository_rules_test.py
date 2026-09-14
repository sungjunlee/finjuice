"""Canonical single-rule tests preserve matcher and original partition semantics."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands.rules_cmd import testing_repository
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands.test_repository_assets import _activate, _assert_baseline
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, write_transactions

RULES = b"""version: 1
rules:
  - name: service
    match: OPENAI
    fields: [merchant_raw]
    tags: [AI]
report_filters:
  excluded_categories:
    - name: food
      reason: test
"""


@pytest.fixture
def root(tmp_path: Path) -> QueryRoot:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_bytes(RULES)
    row = _tx_row("2026-07-01", -20, "OPENAI", category_final="food", tags_final='["manual"]')
    row["tags_rule"] = '["AI", "cross"]'
    row["tags_manual"] = '["manual"]'
    write_transactions(source, "2026-08", [row])
    return _activate(source, tmp_path)


def _invoke(root: QueryRoot, extra: list[str], *, legacy: bool = False, human: bool = False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "rules",
            "test",
            *extra,
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.mark.parametrize(
    "args",
    [
        ["service"],
        ["service", "--limit", "0"],
        ["service", "--month", "2026-08"],
        ["servic"],
        ["service", "--month", "2026-09"],
    ],
)
def test_parity_and_live_poison(root: QueryRoot, args: list[str]) -> None:
    old, new = _invoke(root, args, legacy=True), _invoke(root, args)
    assert old.exit_code == new.exit_code, old.output + new.output
    _assert_baseline(json.loads(old.output), json.loads(new.output))
    (root.root / "rules.yaml").write_text("PRIVATE_SENTINEL: [")
    repeated = _invoke(root, args)
    assert repeated.exit_code == new.exit_code
    _assert_baseline(json.loads(new.output), json.loads(repeated.output))


def test_rule_tags_and_monthly_distribution_remain_distinct(root: QueryRoot) -> None:
    result = _invoke(root, ["service", "--month", "2026-08"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["match_count"] == 1
    assert payload["monthly_distribution"] == {"2026-07": 1}
    assert payload["cross_tags_top"] == [{"tag": "cross", "count": 1}]
    assert payload["sample"][0]["tags_final"] == ["manual"]
    assert payload["_meta"]["dataset_revision"] == 0
    assert "Repository revision 0" in _invoke(root, ["service"], human=True).output


@pytest.mark.parametrize(
    "content,status",
    [
        (b"PRIVATE_SENTINEL: [", "invalid"),
        (b"rules: []", "opaque"),
        (
            b"""rules:
  - name: service
    tags: [AI]
    conditions:
      - field: merchant_raw
        op: regex
        value: "PRIVATE_SENTINEL["
""",
            "parsed",
        ),
    ],
)
def test_invalid_canonical_rules_never_leak(
    root: QueryRoot, content: bytes, status: str, caplog: pytest.LogCaptureFixture
) -> None:
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", content, status, None, "test.v1")
    )
    (root.root / "rules.yaml").write_bytes(RULES)
    result = _invoke(root, ["service"])
    assert result.exit_code != 0
    assert "PRIVATE_SENTINEL" not in result.output + caplog.text
    assert str(root.root) not in result.output


def test_snapshot_pinned_after_mutation(root: QueryRoot, monkeypatch: pytest.MonkeyPatch) -> None:
    original = testing_repository.read_analysis_source
    calls = 0

    def read(*args):
        nonlocal calls
        calls += 1
        snapshot = original(*args)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("rules", b"rules: []", "parsed", None, "test.v1")
        )
        return snapshot

    monkeypatch.setattr(testing_repository, "read_analysis_source", read)
    result = _invoke(root, ["service"])
    assert result.exit_code == 0, result.output
    assert calls == 1 and json.loads(result.output)["_meta"]["dataset_revision"] == 0


def test_incomplete_selected_month_fails(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_bytes(RULES)
    write_transactions(
        source,
        "2026-08",
        [_tx_row("2026-08-01", -20, "PRIVATE_SENTINEL", category_final="food", tags_final="bad[")],
    )
    root = _activate(source, tmp_path)
    result = _invoke(root, ["service"])
    assert result.exit_code != 0
    assert "PRIVATE_SENTINEL" not in result.output
    assert "No transaction data found" not in result.output


def test_unselected_absent_and_authority_failure(root: QueryRoot, monkeypatch: pytest.MonkeyPatch):
    from dataclasses import replace

    snapshot = testing_repository.read_analysis_source(root.root, root.provider)
    assert snapshot is not None
    for state in ("unselected", "absent"):
        rules = replace(
            snapshot.rules,
            head=None,
            selection_state=state,
            revisions=() if state == "absent" else snapshot.rules.revisions,
        )
        monkeypatch.setattr(
            testing_repository, "read_analysis_source", lambda *_: replace(snapshot, rules=rules)
        )
        result = CliRunner().invoke(
            app,
            ["--data-dir", str(root.root), "--no-filter", "rules", "test", "service", "--json"],
            obj={"activation_evidence_provider": root.provider},
        )
        assert result.exit_code != 0
        assert "Canonical rules test could not be evaluated" in result.output


def test_duplicate_rule_diagnostic(root: QueryRoot) -> None:
    duplicate = b"""rules:
  - name: service
    match: OPENAI
    fields: [merchant_raw]
    tags: [AI]
  - name: service
    match: OPENAI
    fields: [merchant_raw]
    tags: [AI]
"""
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", duplicate, "parsed", None, "test.v1")
    )
    result = _invoke(root, ["service"])
    assert result.exit_code != 0
    assert "Multiple rules named" in result.output


def test_independent_authority_is_required(root: QueryRoot) -> None:
    result = CliRunner().invoke(
        app, ["--data-dir", str(root.root), "rules", "test", "service", "--json"]
    )
    assert result.exit_code != 0
    assert "Canonical rules test could not be evaluated" in result.output
    assert str(root.root) not in result.output
