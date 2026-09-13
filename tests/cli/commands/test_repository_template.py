"""Template consumers use one verified repository snapshot, including canonical filters."""

import json

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.cli.commands import template_cmd
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_root_fixture

query_root = _query_root_fixture


def _run(root: QueryRoot, *, legacy=False, no_filter=False, name="monthly_spend", human=False):
    args = ["--data-dir", str(root.legacy if legacy else root.root)]
    if no_filter:
        args.append("--no-filter")
    args.extend(["template", "run", name])
    if name == "pivot":
        args.extend(["--param", "row=month", "--param", "col=category_final"])
    if not human:
        args.append("--json")
    return CliRunner().invoke(
        app, args, obj={} if legacy else {"activation_evidence_provider": root.provider}
    )


def test_template_matches_legacy_and_ignores_live_csv_and_rules(query_root: QueryRoot):
    baseline = _run(query_root, legacy=True)
    (query_root.root / "rules.yaml").write_text("rules: [invalid")
    partition = query_root.root / "transactions/2026/09/transactions.csv"
    partition.parent.mkdir(parents=True)
    partition.write_text("amount\n999999\n")
    active = _run(query_root)
    assert baseline.exit_code == active.exit_code == 0, active.output
    payload = json.loads(active.output)
    assert payload["rows"] == json.loads(baseline.output)["rows"]
    assert payload["rows"] == [{"month": "2026-09", "transaction_count": 1, "total_spend": 1200.25}]
    assert payload["_meta"]["dataset_generation"] == query_root.generation
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["_meta"]["filters_applied"] == 1
    human = _run(query_root, human=True)
    assert human.exit_code == 0, human.output
    assert "1200" in human.output.replace(",", "")


@pytest.mark.parametrize("status", ["invalid", "opaque"])
def test_template_rejects_unparsed_head_unless_explicit_bypass(query_root: QueryRoot, status):
    StorageMutationFacade(query_root.root, query_root.provider).replace_config(
        ConfigDocument("rules", b"rules: []\n", status, None, "test")
    )
    failed = _run(query_root)
    assert failed.exit_code != 0
    assert "Canonical rules head" in json.loads(failed.output)["error"]["message"]
    bypass = _run(query_root, no_filter=True)
    assert bypass.exit_code == 0, bypass.output
    payload = json.loads(bypass.output)
    assert payload["rows"][0]["transaction_count"] == 2
    assert payload["_meta"]["dataset_revision"] == 1
    assert payload["_meta"]["filters_applied"] == 0


def test_template_cannot_fall_back_without_independent_evidence(query_root: QueryRoot):
    failed = CliRunner().invoke(
        app, ["--data-dir", str(query_root.root), "template", "run", "monthly_spend", "--json"]
    )
    assert failed.exit_code != 0
    assert "evidence provider" in json.loads(failed.output)["error"]["message"]


def test_template_keeps_rules_revision_pinned_during_execution(query_root: QueryRoot, monkeypatch):
    facade = StorageMutationFacade(query_root.root, query_root.provider)

    class ConcurrentAnalytics(DuckDBAnalytics):
        def __enter__(self):
            result = super().__enter__()
            facade.replace_config(
                ConfigDocument.from_validated_yaml("rules", b"rules: []\n", parser_version="test")
            )
            return result

    with monkeypatch.context() as context:
        context.setattr(template_cmd, "DuckDBAnalytics", ConcurrentAnalytics)
        pinned = _run(query_root)
    assert pinned.exit_code == 0, pinned.output
    payload = json.loads(pinned.output)
    assert payload["rows"][0]["transaction_count"] == 1
    assert payload["_meta"]["dataset_revision"] == 0
    latest = _run(query_root)
    assert latest.exit_code == 0, latest.output
    payload = json.loads(latest.output)
    assert payload["rows"][0]["transaction_count"] == 2
    assert payload["_meta"]["dataset_revision"] == 1


def test_pivot_uses_same_repository_filters(query_root: QueryRoot):
    baseline = _run(query_root, legacy=True, name="pivot")
    active = _run(query_root, name="pivot")
    assert baseline.exit_code == active.exit_code == 0, active.output
    payload = json.loads(active.output)
    assert payload["rows"] == json.loads(baseline.output)["rows"]
    assert payload["_meta"]["filters_applied"] == 1
    assert payload["_meta"]["dataset_revision"] == 0
