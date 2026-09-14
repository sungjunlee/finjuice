"""Rules list/export reads captured configuration without live YAML fallback."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands.rules_cmd import export_repository
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes
from finjuice.pipeline.tagging.suggestions import (
    format_rules_as_banksalad_guide,
    format_rules_as_markdown,
)
from tests.cli.commands.test_repository_assets import _activate

CONTENT = b"""# Preserve source comments and scalar spellings.
version: 1
rules:
  - name: first
    match: shop
    fields: [merchant_raw]
    tags: [food]
    priority: 10
    confidence: 7.5e-1
  - name: second
    enabled: false
    tags: [exact]
    priority: 90
    conditions:
      - field: amount
        op: greater_than
        value: 9007199254740993.01
      - field: amount
        op: is_not
        value: -0.00
""".replace(b"\n", b"\r\n")


def _root(tmp_path: Path, content: bytes | None = CONTENT, *, nested: bool = False):
    source = tmp_path / "source"
    source.mkdir()
    if content is not None:
        path = source / ("nested/rules.yaml" if nested else "rules.yaml")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    partition = source / "transactions/2026/01/transactions.csv"
    partition.parent.mkdir(parents=True)
    partition.write_bytes(b"amount,amount\n1,2\n")
    return _activate(source, tmp_path)


def _run(root, *args: str):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "rules", *args],
        obj={"activation_evidence_provider": root.provider},
    )


def test_json_list_export_projection_and_live_yaml_poison(tmp_path: Path) -> None:
    root = _root(tmp_path)
    initial = _run(root, "export", "--json")
    assert initial.exit_code == 0, initial.output
    payload = json.loads(initial.output)
    assert payload["rules"] == [
        {
            "name": "second",
            "match": "",
            "fields": [],
            "tags": ["exact"],
            "category": "",
            "priority": 90,
        },
        {
            "name": "first",
            "match": "shop",
            "fields": ["merchant_raw"],
            "tags": ["food"],
            "category": "",
            "priority": 10,
        },
    ]
    assert payload["_meta"]["calculation_policy"] == "legacy_rules_export.v1"
    assert payload["_meta"]["rules_revision_id"] is not None
    (root.root / "rules.yaml").write_bytes(b"PRIVATE_POISON: [")
    listing = _run(root, "list", "--json")
    assert listing.exit_code == 0, listing.output
    listed = json.loads(listing.output)
    assert listed["rules"] == payload["rules"]
    from tests.test_json_schemas import _load_schema, _validator_for

    for name, result in (("export", payload), ("list", listed)):
        _validator_for(_load_schema(f"rules_{name}.schema.json")).validate(result)
    assert "Canonical rules; repository revision 0" in _run(root, "list").output


@pytest.mark.parametrize("format_type", ["yaml", "banksalad", "markdown"])
def test_file_formats_use_captured_bytes_and_existing_formatters(
    tmp_path: Path, format_type: str
) -> None:
    root = _root(tmp_path)
    output = tmp_path / f"derived.{format_type}"
    result = _run(root, "export", "--format", format_type, "-o", str(output))
    assert result.exit_code == 0, result.output
    expected = CONTENT
    rules = load_rules_bytes(CONTENT)
    if format_type == "banksalad":
        expected = format_rules_as_banksalad_guide(rules).encode()
    elif format_type == "markdown":
        expected = format_rules_as_markdown(rules).encode()
    assert output.read_bytes() == expected
    assert "Canonical rules; repository revision 0" in result.output


@pytest.mark.parametrize("command", ["export", "list"])
def test_invalid_flags_and_invalid_semantics_fail_statically(tmp_path: Path, command: str) -> None:
    root = _root(tmp_path)
    facade = StorageMutationFacade(root.root, root.provider)
    for status, content in (
        ("invalid", CONTENT),
        ("opaque", CONTENT),
        ("parsed", b"rules: [PRIVATE_SCHEMA_SENTINEL]\n"),
        ("parsed", b"PRIVATE_PARSE_SENTINEL: ["),
    ):
        facade.replace_config(ConfigDocument("rules", content, status, None, "test.v1"))
        result = _run(root, command, "--json")
        assert result.exit_code == 3, result.output
        assert "PRIVATE_" not in result.output
        assert json.loads(result.output)["error"]["code"] == "VALIDATION_FAILED"


@pytest.mark.parametrize("nested", [False, True])
def test_absent_and_unselected_keep_distinct_metadata(tmp_path: Path, nested: bool) -> None:
    root = _root(tmp_path, CONTENT if nested else None, nested=nested)
    result = _run(root, "export", "--json")
    assert result.exit_code == (3 if nested else 2), result.output
    metadata = json.loads(result.output)["_meta"]
    assert metadata["rules_selection_state"] == ("unselected" if nested else "absent")
    assert metadata["rules_revision_id"] is None
    assert _run(root, "export").exit_code == (3 if nested else 1)
    assert _run(root, "list").exit_code == (3 if nested else 2)


def test_empty_and_json_ignore_output_and_format(tmp_path: Path) -> None:
    root = _root(tmp_path, b"# Empty source\nrules: []\n")
    destination = root.root / "rules.yaml"
    destination.write_bytes(b"# live legacy configuration\nrules: []\n")
    original = destination.read_bytes()
    result = _run(root, "export", "--format", "unknown", "-o", str(destination))
    assert result.exit_code == 0, result.output
    assert "등록된 규칙이 없습니다" in result.output
    assert "Canonical rules" in result.output
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", CONTENT, "parsed", None, "test.v1")
    )
    result = _run(root, "export", "--json", "--format", "unknown", "-o", str(destination))
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["rule_count"] == 2
    assert destination.read_bytes() == original


def test_read_once_then_mutation_keeps_captured_output(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    original = export_repository.read_analysis_source
    calls = 0

    def read_then_mutate(*args, **kwargs):
        nonlocal calls
        calls += 1
        snapshot = original(*args, **kwargs)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("rules", b"rules: []\n", "parsed", None, "test.v1")
        )
        return snapshot

    monkeypatch.setattr(export_repository, "read_analysis_source", read_then_mutate)
    result = _run(root, "export", "--json")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert calls == 1 and payload["rule_count"] == 2
    assert payload["_meta"]["dataset_revision"] == 0
    monkeypatch.setattr(export_repository, "read_analysis_source", original)
    fresh = json.loads(_run(root, "list", "--json").output)
    assert fresh["rule_count"] == 0 and fresh["_meta"]["dataset_revision"] == 1


def test_active_evidence_is_required_without_live_fallback(tmp_path: Path) -> None:
    root = _root(tmp_path)
    result = CliRunner().invoke(app, ["--data-dir", str(root.root), "rules", "list", "--json"])
    assert result.exit_code == 3
    assert str(root.root) not in result.output


def test_output_cannot_replace_live_configuration(tmp_path: Path) -> None:
    root = _root(tmp_path)
    destination = root.root / "rules.yaml"
    destination.write_bytes(b"# live legacy configuration\nrules: []\n")
    original = destination.read_bytes()
    result = _run(root, "export", "-o", str(destination))
    assert result.exit_code != 0
    assert destination.read_bytes() == original


def test_formatter_failure_has_static_error(tmp_path: Path, monkeypatch, caplog) -> None:
    from finjuice.pipeline.tagging import suggestions

    root = _root(tmp_path)

    def fail(*args, **kwargs):
        raise ValueError("PRIVATE_FORMATTER_SENTINEL")

    monkeypatch.setattr(suggestions, "format_rules_as_markdown", fail)
    result = _run(root, "export", "--format", "markdown")
    assert result.exit_code == 3
    assert "PRIVATE_FORMATTER_SENTINEL" not in result.output + caplog.text


def test_list_is_not_simulation_or_filter_validation(tmp_path: Path) -> None:
    content = b"""rules:
  - name: substring
    match: '['
    fields: [merchant_raw]
    tags: [x]
  - name: condition
    conditions:
      - field: merchant_raw
        op: regex
        value: '['
    tags: [x]
report_filters: [not-a-filter-object]
"""
    root = _root(tmp_path)
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("rules", content, "parsed", None, "test.v1")
    )
    result = _run(root, "list", "--json")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["rule_count"] == 2
