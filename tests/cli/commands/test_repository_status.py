"""Status over actual migrated repositories, including pinned detailed insights."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_status_snapshot
from tests.cli.commands.test_repository_mutation_fences import active_root as _empty_fixture
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_fixture

query_root = _query_fixture
empty_root = _empty_fixture


def _status(root, *, legacy=False, no_filter=False, detailed=False, human=False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            *(["--no-filter"] if no_filter else []),
            "status",
            *(["--detailed"] if detailed else []),
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": root.provider} if not legacy else {},
    )


def _payload(result):
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_status_baseline_counts_details_and_repository_identity(query_root: QueryRoot):
    old = _payload(_status(query_root, legacy=True, detailed=True))
    new = _payload(_status(query_root, detailed=True))
    for key in ("transactions", "tagging", "detailed_stats"):
        assert {field: new[key][field] for field in old[key]} == old[key], key
    assert new["_meta"]["dataset_revision"] == 0
    assert new["_meta"]["dataset_generation"] == query_root.generation
    assert new["_meta"]["calculation_policy"] == "legacy_status.v1"
    assert new["schema"]["authority"] == "repository"
    assert new["rules_file"]["path"] is None
    assert new["repository"]["source_counts"]["total_rows"] == 2
    assert new["last_import"]["imported_at"] is None
    assert new["repository"]["source_occurrence_counts"]["migration_capture"] > 0
    assert _status(query_root, human=True, detailed=True).exit_code == 0


def test_status_ignores_live_csv_rules_goals_and_import_history(query_root: QueryRoot):
    before = _payload(_status(query_root, detailed=True))
    for name in (
        "rules.yaml",
        "goals.yaml",
        "metadata/import_history.csv",
        "transactions/2026/09/transactions.csv",
    ):
        path = query_root.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE INVALID SENTINEL")
    after = _payload(_status(query_root, detailed=True))
    before["_meta"].pop("timestamp")
    after["_meta"].pop("timestamp")
    assert before == after


def test_status_without_host_evidence_has_no_csv_fallback(query_root: QueryRoot):
    result = CliRunner().invoke(app, ["--data-dir", str(query_root.root), "status", "--json"])
    assert result.exit_code != 0
    assert "validated source" in result.output
    assert "NO_DATA" not in result.output


@pytest.mark.parametrize("parsed_status", ["invalid", "opaque"])
def test_status_unparsed_rules_require_bypass_but_remain_critical(query_root, parsed_status):
    StorageMutationFacade(query_root.root, query_root.provider).replace_config(
        ConfigDocument("rules", b"rules: []\n# PRIVATE SENTINEL", parsed_status, None, "test")
    )
    failed = _status(query_root)
    assert failed.exit_code != 0
    assert "PRIVATE SENTINEL" not in failed.output
    result = _payload(_status(query_root, no_filter=True))
    assert result["transactions"]["count"] == 2
    assert result["health"]["status"] == "critical"
    assert result["repository"]["rules_head"]["parsed_status"] == parsed_status
    human = _status(query_root, no_filter=True, human=True)
    assert human.exit_code == 0
    assert "finjuice init" not in human.output
    assert "PRIVATE SENTINEL" not in human.output


def test_status_empty_repository_reports_missing_head_without_csv_init(empty_root):
    result = _payload(_status(empty_root, detailed=True))
    assert result["transactions"]["count"] == 0
    assert result["transactions"]["partition_count"] == 0
    assert result["health"]["status"] == "critical"
    assert result["repository"]["rules_head"]["parsed_status"] == "missing"
    human = _status(empty_root, human=True)
    assert human.exit_code == 0
    assert "finjuice init" not in human.output
    assert "legacy schema" not in human.output


def test_status_pins_rules_and_goals_through_real_mutation(query_root, monkeypatch):
    from finjuice.pipeline.cli.commands.status import repository_facts

    original = repository_facts.read_status_snapshot
    baseline = _payload(_status(query_root, detailed=True))
    calls = []

    def read_then_change(*args):
        snapshot = original(*args)
        calls.append(snapshot.info.dataset_revision)
        facade = StorageMutationFacade(query_root.root, query_root.provider)
        facade.replace_config(
            ConfigDocument.from_validated_yaml("rules", b"rules: []\n", parser_version="test")
        )
        facade.replace_config(ConfigDocument("goals", b"PRIVATE: [broken", "invalid", None, "test"))
        return snapshot

    monkeypatch.setattr(repository_facts, "read_status_snapshot", read_then_change)
    pinned = _payload(_status(query_root, detailed=True))
    assert calls == [0]
    assert pinned["transactions"] == baseline["transactions"]
    assert pinned["detailed_stats"] == baseline["detailed_stats"]
    assert pinned["_meta"]["dataset_revision"] == 0
    assert read_status_snapshot(query_root.root, query_root.provider).info.dataset_revision == 2


def test_status_detailed_invalid_goals_never_uses_live_fallback(query_root):
    StorageMutationFacade(query_root.root, query_root.provider).replace_config(
        ConfigDocument("goals", b"PRIVATE: [broken", "invalid", None, "test")
    )
    (query_root.root / "goals.yaml").write_text("goals: {}")
    result = _payload(_status(query_root, detailed=True))
    assert result["detailed_stats_warning"]
    assert result["repository"]["goals_head"]["parsed_status"] == "invalid"
    assert "PRIVATE" not in json.dumps(result)
    human = _status(query_root, detailed=True, human=True)
    assert human.exit_code == 0
    assert "Canonical goals could not be interpreted" in human.output
    assert "월평균 지출" in human.output
    assert "Top 5 카테고리" in human.output
    assert "detailed savings are unavailable" not in human.output
    assert "PRIVATE" not in human.output


def test_status_native_import_uses_occurrence_identity(empty_root):
    from tests.pipeline.test_sqlite_source_lookup import _import_workbook

    imported = _import_workbook(empty_root)
    result = _payload(_status(empty_root, no_filter=True, detailed=True))
    assert result["last_import"]["file_id"] is None
    assert result["last_import"]["occurrence_id"] == imported["occurrence_id"]
    assert result["last_import"]["origin"] == "native_import"
    assert result["transactions"]["count"] > 0
    human = _status(empty_root, no_filter=True, human=True)
    assert "occurrence_id" in human.output


def test_status_stored_final_arrays_survive_read_idempotently(query_root):
    before = read_status_snapshot(query_root.root, query_root.provider)
    for _ in range(2):
        _payload(_status(query_root, no_filter=True, detailed=True))
    after = read_status_snapshot(query_root.root, query_root.provider)
    assert after == before
    assert after.transactions.rows[0]["tags_final"] == before.transactions.rows[0]["tags_final"]


def test_status_transaction_mutation_during_compute_stays_pinned(query_root, monkeypatch):
    from finjuice.pipeline.cli.commands.status import repository_facts
    from finjuice.pipeline.storage.sqlite.mutations import ManualTransactionEdit

    baseline = _payload(_status(query_root, no_filter=True, detailed=True))
    original = repository_facts.read_status_snapshot
    calls = []

    def read_then_change(*args):
        snapshot = original(*args)
        calls.append(snapshot.info.dataset_revision)
        row = snapshot.transactions.rows[0]
        StorageMutationFacade(query_root.root, query_root.provider).edit_manual_transaction(
            ManualTransactionEdit(
                identifier=row["transaction_id"], note_supplied=True, note="later"
            )
        )
        return snapshot

    monkeypatch.setattr(repository_facts, "read_status_snapshot", read_then_change)
    pinned = _payload(_status(query_root, no_filter=True, detailed=True))
    assert calls == [0]
    assert pinned["transactions"] == baseline["transactions"]
    assert pinned["detailed_stats"] == baseline["detailed_stats"]
    assert pinned["_meta"]["dataset_revision"] == 0
    assert read_status_snapshot(query_root.root, query_root.provider).info.dataset_revision == 1


@pytest.mark.parametrize("empty_timestamp", [False, True])
def test_status_preserves_migrated_history_before_native_import(
    query_root, tmp_path, empty_timestamp
):
    import shutil

    from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
    from finjuice.pipeline.migration import build_migration, plan_migration
    from finjuice.pipeline.storage.authority import AuthorityPaths
    from finjuice.pipeline.storage.sqlite import RepositoryReader
    from tests.pipeline.test_sqlite_bulk_mutations import _write_activation
    from tests.pipeline.test_sqlite_source_lookup import _import_workbook

    history = query_root.legacy / "metadata/import_history.csv"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(
        "file_id,imported_at\nfirst,2024-01-01 10:00:00\nlatest,2025-01-01 10:00:00\n"
    )
    if empty_timestamp:
        with history.open("a") as stream:
            stream.write("unknown-time,\n")
    baseline = _payload(_status(query_root, legacy=True))
    capture, plan, candidate = (
        tmp_path / name for name in ("capture2", "plan2.json", "candidate2")
    )
    create_backup(
        CreateRequest(query_root.legacy, capture, ConsistencyEvidence("stopped_writers", ("test",)))
    )
    plan_migration(capture, output=plan, active_data_dir=query_root.legacy)
    build_migration(plan, candidate, active_data_dir=query_root.legacy)
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        generation = reader.info.dataset_generation
    root = tmp_path / "active2"
    paths = AuthorityPaths.for_data_dir(root)
    shutil.copytree(candidate, paths.generation(generation).root)
    _write_activation(paths, generation)
    from finjuice.pipeline.storage.authority import StaticActivationEvidenceProvider
    from tests.pipeline.test_sqlite_bulk_mutations import _evidence

    case = QueryRoot(
        root, query_root.legacy, StaticActivationEvidenceProvider(_evidence()), generation
    )
    result = _payload(_status(case))
    assert {key: result["last_import"][key] for key in baseline["last_import"]} == baseline[
        "last_import"
    ]
    assert result["last_import"]["origin"] == "legacy_import_history"
    assert result["last_import"]["occurrence_id"] is None
    assert result["repository"]["legacy_import_history_count"] == (3 if empty_timestamp else 2)
    human = _status(case, human=True)
    assert "preserved history" in human.output
    assert ("unknown-time" if empty_timestamp else "latest") in human.output
    assert "No recorded import" not in human.output
    # The actual native helper only needs the same root/provider interface.
    from types import SimpleNamespace

    imported = _import_workbook(
        SimpleNamespace(facade=StorageMutationFacade(case.root, case.provider))
    )
    refreshed = _payload(_status(case))
    assert refreshed["last_import"]["origin"] == "native_import"
    assert refreshed["last_import"]["file_id"] is None
    assert refreshed["last_import"]["occurrence_id"] == imported["occurrence_id"]


def test_status_repository_output_validates_schema(query_root):
    from tests.test_json_schemas import _load_schema, _validator_for

    result = _payload(_status(query_root, detailed=True))
    _validator_for(_load_schema("status.schema.json")).validate(result)


def test_status_detailed_uses_valid_canonical_goals_bytes(query_root):
    from tests.pipeline.test_insights_repository import GOALS

    facade = StorageMutationFacade(query_root.root, query_root.provider)
    receipt = facade.replace_config(
        ConfigDocument.from_validated_yaml("goals", GOALS, parser_version="test")
    )
    (query_root.root / "goals.yaml").write_text("PRIVATE: [invalid")
    result = _payload(_status(query_root, detailed=True))
    assert result["detailed_stats_warning"] is None
    assert result["detailed_stats"]["recurring_savings_monthly_amount"] == 100
    assert result["_meta"]["dataset_revision"] == receipt.committed_revision
    assert result["repository"]["goals_head"]["parsed_status"] == "parsed"
