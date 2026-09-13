"""Canonical rule changes reach diagnostics without retagging stored transactions."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _fixture

query_root = _fixture


def _invoke(root: QueryRoot, args: list[str]):
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "rules", *args, "--json"],
        obj={"activation_evidence_provider": root.provider},
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_diagnostics_observe_config_revision_without_changing_stored_classifications(
    query_root: QueryRoot,
) -> None:
    # Arrange: gap analysis observes stored tags; rule testing simulates current rules.
    before = read_transaction_snapshot(query_root.root, query_root.provider)
    gaps_before = _invoke(query_root, ["gaps"])
    content = (
        b"rules:\n  - name: diagnostic-test\n    match: shop\n"
        b"    fields: [merchant_raw]\n    tags: [new_tag]\n    priority: 10\n"
    )
    StorageMutationFacade(query_root.root, query_root.provider).replace_config(
        ConfigDocument.from_validated_yaml("rules", content, parser_version="test")
    )
    (query_root.root / "rules.yaml").write_bytes(b"PRIVATE LIVE POISON: [\n")

    # Act: all three commands must see the committed rule revision.
    validation = _invoke(query_root, ["validate"])
    testing = _invoke(query_root, ["test", "diagnostic-test", "--limit", "0"])
    gaps_after = _invoke(query_root, ["gaps"])

    # Assert: simulation does not apply tags or rewrite source classifications.
    assert validation["total_rules"] == 1
    assert testing["match_count"] == 2 and testing["sample"] == []
    assert testing["cross_tags_top"] == []
    for payload in (validation, testing, gaps_after):
        assert payload["_meta"]["authority"] == "repository"
        assert payload["_meta"]["dataset_revision"] == 1
        assert "PRIVATE LIVE POISON" not in json.dumps(payload)
    assert {k: v for k, v in gaps_after.items() if k != "_meta"} == {
        k: v for k, v in gaps_before.items() if k != "_meta"
    }
    after = read_transaction_snapshot(query_root.root, query_root.provider)
    assert before is not None and after is not None
    assert before.rows == after.rows
    assert after.info.dataset_revision == 1
    from tests.test_json_schemas import _load_schema, _validator_for

    for name, payload in (("validate", validation), ("test", testing), ("gaps", gaps_after)):
        _validator_for(_load_schema(f"rules_{name}.schema.json")).validate(payload)
