"""Canonical rules diagnostics remain independent of opaque transaction projections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.rules_validation_repository import load_repository_rules_validation
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.sqlite import RepositoryReader
from tests.cli.commands.test_repository_assets import _activate

VALID = (
    b"version: 1\n"
    b"rules:\n"
    b"  - name: sample\n"
    b"    match: shop\n"
    b"    fields: [merchant_raw]\n"
    b"    tags: [food]\n"
    b"    confidence: 0.75\n"
)


def _root(tmp_path: Path, content: bytes | None = VALID, *, nested: bool = False):
    source = tmp_path / "source"
    source.mkdir()
    if content is not None:
        path = source / ("nested/rules.yaml" if nested else "rules.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    opaque = source / "transactions/2026/01/transactions.csv"
    opaque.parent.mkdir(parents=True)
    opaque.write_bytes(b"amount,amount\n1,2\n")
    return _activate(source, tmp_path)


def _run(root, *, strict=False, human=False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.root),
            "rules",
            "validate",
            *(["--strict"] if strict else []),
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": root.provider},
    )


def test_valid_rules_ignore_opaque_transactions_and_live_poison(tmp_path: Path) -> None:
    root = _root(tmp_path)
    result = _run(root)
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["total_rules"] == 1
    assert data["_meta"]["dataset_revision"] == 0
    assert data["_meta"]["rules_revision_id"] is not None
    (root.root / "rules.yaml").write_text("PRIVATE_SENTINEL: [")
    assert json.loads(_run(root).output)["problems"] == data["problems"]
    assert "Canonical rules" in _run(root, human=True).output


@pytest.mark.parametrize("status", ["invalid", "opaque"])
def test_recorded_invalid_status_cannot_become_valid_success(tmp_path: Path, status: str) -> None:
    root = _root(tmp_path)
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", VALID, status, None, "test.v1")
    )
    result = _run(root)
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["total_rules"] == 1 and data["errors"] >= 1
    assert any("not marked parsed" in problem["message"] for problem in data["problems"])


@pytest.mark.parametrize("nested", [False, True])
def test_absence_and_unselected_are_distinct(tmp_path: Path, nested: bool) -> None:
    root = _root(tmp_path, VALID if nested else None, nested=nested)
    result = _run(root)
    assert result.exit_code == (1 if nested else 2)
    data = json.loads(result.output)
    assert data["_meta"]["rules_selection_state"] == ("unselected" if nested else "absent")
    if nested:
        assert data["total_rules"] == 0 and data["errors"] == 1
    else:
        assert data["error"]["code"] == "RULES_FILE_NOT_FOUND"


def test_collect_all_strict_and_private_parser_failure(tmp_path: Path) -> None:
    invalid = VALID + b"  - name: missing-tags\n    match: x\n    fields: [merchant_raw]\n"
    root = _root(tmp_path, invalid)
    collected = _run(root)
    assert collected.exit_code == 1, collected.output
    assert json.loads(collected.output)["total_rules"] == 2
    assert _run(root, strict=True).exit_code == 3
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", b"PRIVATE_SENTINEL: [", "invalid", None, "test.v1")
    )
    result = _run(root)
    assert result.exit_code == 3
    assert "PRIVATE_SENTINEL" not in result.output


def test_one_reader_mutation_keeps_pinned_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _root(tmp_path)
    initial = load_repository_rules_validation(root.root, root.provider)
    original = RepositoryReader.transaction_snapshot

    def mutate(reader):
        transactions = original(reader)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("rules", b"rules: []\n", "parsed", {"rules": []}, "test.v1")
        )
        return transactions

    monkeypatch.setattr(RepositoryReader, "transaction_snapshot", mutate)
    assert load_repository_rules_validation(root.root, root.provider) == initial
    monkeypatch.setattr(RepositoryReader, "transaction_snapshot", original)
    fresh = load_repository_rules_validation(root.root, root.provider)
    assert fresh is not None and fresh.rules == [] and fresh.metadata["dataset_revision"] == 1


def test_condition_regex_error_is_indexed_without_counting_extra_rule(tmp_path: Path) -> None:
    content = VALID + (
        b"  - name: bad-condition\n"
        b"    tags: [x]\n"
        b"    conditions:\n"
        b"      - field: merchant_raw\n"
        b"        op: regex\n"
        b"        value: '['\n"
    )
    root = _root(tmp_path, content)
    result = _run(root)
    assert result.exit_code == 1, result.output
    data = json.loads(result.output)
    assert data["total_rules"] == 2
    assert any(
        problem["rule_index"] == 1 and "invalid regular expression" in problem["message"]
        for problem in data["problems"]
    )


def test_missing_authority_has_static_public_error(tmp_path: Path) -> None:
    root = _root(tmp_path)
    result = CliRunner().invoke(app, ["--data-dir", str(root.root), "rules", "validate", "--json"])
    assert result.exit_code == 3
    data = json.loads(result.output)
    assert data["error"]["message"] == (
        "Canonical rules validation could not read selected configuration."
    )
    assert str(root.root) not in result.output


def test_regex_source_index_survives_priority_duplicate_names_and_schema_errors(
    tmp_path: Path,
) -> None:
    content = b"""rules:
  - name: duplicate
    match: shop
    fields: [merchant_raw]
    tags: [x]
    priority: 1
  - name: duplicate
    priority: 50
  - name: duplicate
    tags: [x]
    priority: 100
    conditions:
      - field: merchant_raw
        op: regex
        value: '['
"""
    root = _root(tmp_path, content)
    result = _run(root)
    data = json.loads(result.output)
    assert result.exit_code == 1
    assert data["total_rules"] == 3
    assert data["passed"] == 1
    assert any(
        problem["rule_index"] == 2 and "invalid regular expression" in problem["message"]
        for problem in data["problems"]
    )
    assert _run(root, strict=True).exit_code == 3


def test_collected_invalid_fields_and_names_do_not_expose_source_values(tmp_path: Path) -> None:
    root = _root(
        tmp_path,
        b"""rules:
  - name: {nested: PRIVATE_SENTINEL}
    match: shop
    fields: [merchant_raw]
    tags: [x]
  - name: other
    tags: [x]
    conditions:
      - field: merchant_raw
        op: PRIVATE_SENTINEL
        value: x
""",
    )
    for human in (False, True):
        result = _run(root, human=human)
        assert result.exit_code == 1, result.output
        assert "PRIVATE_SENTINEL" not in result.output
        if not human:
            payload = json.loads(result.output)
            assert payload["total_rules"] == 2
            assert {p["rule_index"] for p in payload["problems"] if p["rule_index"] >= 0} == {0, 1}
