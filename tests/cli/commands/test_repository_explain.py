"""Actual migration explain reads preserve stored state and simulate pinned rules."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot
from tests.cli.commands import test_repository_query as query_fixture
from tests.cli.commands.test_repository_query import QueryRoot

RULES = b"""rules:
  - name: proposed
    match: shop
    fields: [merchant_raw]
    tags: [predicted]
    category: simulated
    priority: 50
report_filters:
  excluded_categories:
    - name: excluded
      reason: synthetic
"""


@pytest.fixture
def explain_root(tmp_path: Path, monkeypatch) -> QueryRoot:
    create = query_fixture.create_backup

    def with_rules(request):
        (request.source / "rules.yaml").write_bytes(RULES)
        return create(request)

    monkeypatch.setattr(query_fixture, "create_backup", with_rules)
    return query_fixture.query_root.__wrapped__(tmp_path)


def _explain(
    root: QueryRoot,
    query="shop",
    *args,
    legacy=False,
    no_filter=False,
    human=False,
    **runner_kwargs,
):
    argv = ["--data-dir", str(root.legacy if legacy else root.root)]
    if no_filter:
        argv.append("--no-filter")
    argv.extend(["explain", query, *args])
    if not human:
        argv.append("--json")
    return CliRunner().invoke(
        app,
        argv,
        obj={} if legacy else {"activation_evidence_provider": root.provider},
        **runner_kwargs,
    )


def _replace_rules(root: QueryRoot, content: bytes):
    return StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument.from_validated_yaml("rules", content, parser_version="test")
    )


def test_explain_keeps_stored_classification_separate_and_matches_legacy_simulation(
    explain_root: QueryRoot,
):
    before = read_transaction_snapshot(explain_root.root, explain_root.provider)
    baseline = _explain(explain_root, "shop-0", legacy=True)
    active = _explain(explain_root, "shop-0")
    assert baseline.exit_code == active.exit_code == 0, active.output
    payload = json.loads(active.output)
    assert payload["classification"] == json.loads(baseline.output)["classification"]
    assert payload["classification_basis"] == "current_rules_simulation"
    assert payload["_meta"]["calculation_policy"] == "current_rules_simulation.v1"
    assert payload["classification"]["category"] == "simulated"
    assert payload["stored_classification"]["category_final"] == "kept"
    assert payload["stored_classification"]["category_manual"] == "manual"
    assert payload["stored_classification"]["tags_final"] == ["persisted", "persisted"]
    assert payload["stored_classification"]["tags_manual"] == ["visible"]
    assert payload["stored_classification"]["notes_manual"] == "manual\nnotes"
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["_meta"]["dataset_generation"] == explain_root.generation
    assert read_transaction_snapshot(explain_root.root, explain_root.provider) == before
    human = _explain(explain_root, "shop-0", human=True)
    assert human.exit_code == 0, human.output
    assert "kept" in human.output and "simulated" in human.output


def test_explain_ignores_report_filters_and_live_projection_files(explain_root: QueryRoot):
    (explain_root.root / "rules.yaml").write_text("rules: [invalid")
    path = explain_root.root / "transactions/2099/12/transactions.csv"
    path.parent.mkdir(parents=True)
    path.write_text("amount\n1\n")
    default = _explain(explain_root)
    bypass = _explain(explain_root, no_filter=True)
    assert default.exit_code == bypass.exit_code == 0, default.output
    normal = json.loads(default.output)
    explicit = json.loads(bypass.output)
    assert normal["match_count"] == explicit["match_count"] == 2
    assert normal["candidates"] == explicit["candidates"]
    ids = [row["transaction_id"] for row in normal["candidates"]]
    assert ids == sorted(ids)
    picked = _explain(explain_root, "shop", "--pick", "2")
    assert picked.exit_code == 0, picked.output
    assert json.loads(picked.output)["transaction"]["transaction_id"] == ids[1]
    invalid = _explain(explain_root, "shop", "--pick", "3")
    assert invalid.exit_code != 0
    interactive = _explain(explain_root, human=True, input="2\n")
    assert interactive.exit_code == 0, interactive.output
    cancel = _explain(explain_root, human=True, input="0\n")
    assert cancel.exit_code == 0, cancel.output


@pytest.mark.parametrize("status", ["invalid", "opaque"])
def test_explain_invalid_head_cannot_be_bypassed(explain_root: QueryRoot, status, caplog):
    secret = "SYNTHETIC_RULE_CONTENT_MUST_NOT_LEAK"
    StorageMutationFacade(explain_root.root, explain_root.provider).replace_config(
        ConfigDocument("rules", f"rules: []\n# {secret}\n".encode(), status, None, "test")
    )
    for bypass in (False, True):
        failed = _explain(explain_root, no_filter=bypass)
        assert failed.exit_code != 0
        assert secret not in failed.output
    assert secret not in caplog.text


def test_explain_no_match_and_empty_rules_keep_revision_metadata(explain_root: QueryRoot):
    missing = _explain(explain_root, "unmatched")
    assert missing.exit_code == 0, missing.output
    payload = json.loads(missing.output)
    assert payload["match_count"] == 0 and payload["_meta"]["dataset_revision"] == 0
    _replace_rules(explain_root, b"rules: []\n")
    empty = _explain(explain_root)
    assert empty.exit_code == 0, empty.output
    payload = json.loads(empty.output)
    assert payload["transaction"] is None
    assert payload["_meta"]["dataset_revision"] == 1


def test_explain_does_not_fall_back_without_evidence(explain_root: QueryRoot):
    result = CliRunner().invoke(
        app, ["--data-dir", str(explain_root.root), "explain", "shop", "--json"]
    )
    assert result.exit_code != 0
    assert "_meta" in json.loads(result.output)


def test_explain_condition_rule_uses_full_transaction_and_matching_trace(explain_root: QueryRoot):
    _replace_rules(
        explain_root,
        b"""rules:
  - name: full-row-condition
    conditions:
      - {field: account, op: is, value: synthetic}
      - {field: amount, op: less_than, value: '-1000'}
    logic: all
    category: conditional
    tags: [conditional]
    priority: 90
""",
    )
    result = _explain(explain_root, "shop-0")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["classification"]["matched_rules"] == ["full-row-condition"]
    assert [row["rule_name"] for row in payload["rule_trace"]] == ["full-row-condition"]
    other = _explain(explain_root, "shop-1")
    assert other.exit_code == 0, other.output
    assert json.loads(other.output)["rule_trace"] == []


def test_explain_revision_stays_pinned_across_real_rules_mutation(
    explain_root: QueryRoot, monkeypatch
):
    from finjuice.pipeline.cli.commands import explain_reads

    read = explain_reads.read_transaction_snapshot

    def mutate_after_capture(*args, **kwargs):
        snapshot = read(*args, **kwargs)
        _replace_rules(explain_root, RULES.replace(b"proposed", b"changed"))
        return snapshot

    with monkeypatch.context() as context:
        context.setattr(explain_reads, "read_transaction_snapshot", mutate_after_capture)
        old = _explain(explain_root, "shop-0")
    assert old.exit_code == 0, old.output
    payload = json.loads(old.output)
    assert payload["classification"]["matched_rules"] == ["proposed"]
    assert payload["_meta"]["dataset_revision"] == 0
    current = json.loads(_explain(explain_root, "shop-0").output)
    assert current["classification"]["matched_rules"] == ["changed"]
    assert current["_meta"]["dataset_revision"] == 1


def test_explain_numeric_conditions_use_exact_source_amount(tmp_path: Path, monkeypatch):
    create = query_fixture.create_backup

    def exact_capture(request):
        csv = request.source / "transactions/2026/09/transactions.csv"
        csv.write_text(csv.read_text().replace("-1200.25", "9007199254740993.01"))
        return create(request)

    monkeypatch.setattr(query_fixture, "create_backup", exact_capture)
    root = query_fixture.query_root.__wrapped__(tmp_path)
    _replace_rules(
        root,
        b"""rules:
  - name: exact-lower
    conditions: [{field: amount, op: greater_than, value: '9007199254740993'}]
    tags: [lower]
  - name: rounded-false-positive
    conditions: [{field: amount, op: greater_than, value: '9007199254740993.5'}]
    tags: [wrong]
""",
    )
    result = _explain(root, "shop-0")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["classification"]["matched_rules"] == ["exact-lower"]
    assert [trace["rule_name"] for trace in payload["rule_trace"]] == ["exact-lower"]


def test_explain_native_null_alias_candidates_are_selected_by_uuid(tmp_path: Path, monkeypatch):
    import shutil
    from dataclasses import replace

    from finjuice.pipeline.storage.authority import AuthorityPaths, StaticActivationEvidenceProvider
    from finjuice.pipeline.storage.sqlite import RepositoryBuilder, RepositoryReader
    from tests.pipeline.test_sqlite_bulk_mutations import _evidence, _write_activation
    from tests.pipeline.test_sqlite_transaction_scopes import _native

    add = RepositoryBuilder.add_transaction

    def named_transaction(builder, record):
        return add(builder, replace(record, merchant_raw="shop-native", memo_raw="memo"))

    with monkeypatch.context() as context:
        context.setattr(RepositoryBuilder, "add_transaction", named_transaction)
        candidate = _native(tmp_path, ["2026-09-01", "2026-09-01"])
    with RepositoryReader(candidate.database) as reader:
        generation = reader.info.dataset_generation
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    shutil.copytree(candidate.root, paths.generation(generation).root)
    _write_activation(paths, generation)
    case = QueryRoot(
        root, tmp_path / "unused", StaticActivationEvidenceProvider(_evidence()), generation
    )
    _replace_rules(case, RULES)
    result = _explain(case, "shop-native", "--pick", "2")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert all(row["row_hash"] is None for row in payload["candidates"])
    ids = [row["transaction_id"] for row in payload["candidates"]]
    assert ids == sorted(ids)
    assert payload["transaction"]["transaction_id"] == ids[1]
    assert payload["_meta"]["dataset_revision"] == 1


def test_invalid_regex_does_not_log_rule_contents(explain_root: QueryRoot, caplog):
    marker = "SYNTHETIC_REGEX_PRIVATE_MARKER"
    content = (
        "rules:\n  - name: private\n    tags: [test]\n    conditions:\n"
        f"      - {{field: merchant_raw, op: regex, value: '[{marker}'}}\n"
    ).encode()
    _replace_rules(explain_root, content)
    result = _explain(explain_root)
    assert result.exit_code != 0
    assert marker not in result.output and marker not in caplog.text


def test_repository_explain_date_validation_keeps_cli_contract(explain_root: QueryRoot):
    result = _explain(explain_root, "shop", "--date", "bad-date")
    assert result.exit_code == 3, result.output
    assert json.loads(result.output)["error"]["code"] == "VALIDATION_FAILED"


def test_disabled_regex_does_not_block_explanation(explain_root: QueryRoot, caplog):
    content = RULES.replace(
        b"report_filters:",
        b"  - name: disabled\n    enabled: false\n    tags: [ignored]\n"
        b"    conditions: [{field: merchant_raw, op: regex, value: '[private'}]\n"
        b"report_filters:",
    )
    _replace_rules(explain_root, content)
    result = _explain(explain_root, "shop-0")
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["classification"]["matched_rules"] == ["proposed"]
    assert "[private" not in caplog.text


def test_unknown_rule_fields_do_not_log_rule_names_or_keys(
    explain_root: QueryRoot, caplog, monkeypatch
):
    from unittest.mock import Mock

    from finjuice.pipeline.tagging import validator

    warning = Mock(wraps=validator.logger.warning)
    monkeypatch.setattr(validator.logger, "warning", warning)
    marker = "SYNTHETIC_PRIVATE_RULE"
    content = RULES.replace(b"proposed", marker.encode()).replace(
        b"    priority: 50", f"    priority: 50\n    {marker}_field: private-value".encode()
    )
    _replace_rules(explain_root, content)
    result = _explain(explain_root, "shop-0")
    assert result.exit_code == 0, result.output
    assert marker not in caplog.text
    assert "private-value" not in caplog.text
    warning.assert_called_with("Rule has %s unknown fields; they will be ignored.", 1)
