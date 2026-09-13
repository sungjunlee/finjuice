"""Real migration-to-query checks for activated repository reads."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.migration import build_migration, plan_migration
from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityPaths,
    StaticActivationEvidenceProvider,
)
from finjuice.pipeline.storage.read_facade import read_transaction_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.errors import AuthorityEvidenceUnavailableError
from tests.cli.commands.test_repository_mutation_fences import (
    _ActiveRoot,
)
from tests.cli.commands.test_repository_mutation_fences import (
    active_root as _empty_root_fixture,
)

empty_root = _empty_root_fixture


@dataclass(frozen=True)
class QueryRoot:
    root: Path
    legacy: Path
    provider: StaticActivationEvidenceProvider
    generation: str


def _query(root: QueryRoot, sql: str, *, legacy: bool = False, no_filter: bool = False):
    argv = ["--data-dir", str(root.legacy if legacy else root.root)]
    if no_filter:
        argv.append("--no-filter")
    return CliRunner().invoke(
        app,
        [*argv, "query", sql, "--json"],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


@pytest.fixture
def query_root(tmp_path: Path) -> QueryRoot:
    legacy = tmp_path / "legacy"
    partition = legacy / "transactions/2026/09/transactions.csv"
    partition.parent.mkdir(parents=True)
    rows = []
    for i, amount in enumerate(("-1200.25", "-300.50")):
        rows.append(
            {
                "row_hash": f"{i:016x}",
                "date": "2026-09-01",
                "time": "12:30:00",
                "datetime": "2026-09-01T12:30:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "food",
                "minor_raw": "cafe",
                "merchant_raw": f"shop-{i}",
                "memo_raw": "memo",
                "account": "synthetic",
                "amount": amount,
                "currency": "KRW",
                "category_rule": "rule",
                "category_final": "kept" if i == 0 else "excluded",
                "tags_rule": "[]",
                "tags_ai": "[]",
                "tags_manual": '["visible", "__finjuice_category_override__:manual"]',
                "tags_final": '["persisted", "persisted"]',
                "notes_manual": "manual\nnotes",
                "confidence": "1",
                "needs_review": "0",
                "is_transfer": "0",
                "is_transfer_candidate": "0",
                "file_id": "source",
                "source_row": str(i + 1),
            }
        )
    with partition.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (legacy / "rules.yaml").write_text(
        "rules: []\nreport_filters:\n  excluded_categories:\n"
        "    - name: excluded\n      reason: test\n"
    )
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(CreateRequest(legacy, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan_migration(capture, output=plan, active_data_dir=legacy)
    build_migration(plan, candidate, active_data_dir=legacy)
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        info = reader.info
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    generation = info.dataset_generation
    shutil.copytree(candidate, paths.generation(generation).root)
    evidence = ActivationEvidence("test", "a" * 64, "b" * 64, "c" * 64)
    paths.control_root.mkdir(parents=True, mode=0o700)
    paths.activation.write_text(
        json.dumps(
            {
                "activation_schema_version": 1,
                "release_version": evidence.installed_release_version,
                "release_artifact_sha256": evidence.installed_release_artifact_sha256,
                "dataset_generation": generation,
                "sqlite_schema_version": info.schema_version,
                "dataset_revision": info.dataset_revision,
                "migration_manifest_sha256": evidence.verified_migration_manifest_sha256,
                "pre_cutover_backup_manifest_sha256": (
                    evidence.verified_pre_cutover_backup_manifest_sha256
                ),
                "activated_at": "2026-09-13T00:00:00Z",
            }
        )
    )
    return QueryRoot(root, legacy, StaticActivationEvidenceProvider(evidence), generation)


def test_query_matches_baseline_and_ignores_edited_derived_files(query_root: QueryRoot) -> None:
    sql = "SELECT category_final, sum(amount) AS total FROM transactions GROUP BY category_final"
    baseline = _query(query_root, sql, legacy=True)
    result = _query(query_root, sql)
    assert baseline.exit_code == result.exit_code == 0, baseline.output + result.output
    old, new = json.loads(baseline.output), json.loads(result.output)
    assert new["rows"] == old["rows"] == [{"category_final": "kept", "total": -1200.25}]
    assert new["_meta"]["dataset_generation"] == query_root.generation
    assert new["_meta"]["dataset_revision"] == 0
    assert new["_meta"]["filters_applied"] == 1
    (query_root.root / "rules.yaml").write_text("rules: [invalid")
    partition = query_root.root / "transactions/2026/09/transactions.csv"
    partition.parent.mkdir(parents=True)
    partition.write_text("amount\n999999\n")
    after = _query(query_root, sql)
    assert after.exit_code == 0, after.output
    repeated = json.loads(after.output)
    repeated["_meta"].pop("timestamp")
    new["_meta"].pop("timestamp")
    assert repeated == new
    unfiltered = _query(query_root, "SELECT count(*) AS n FROM transactions", no_filter=True)
    assert json.loads(unfiltered.output)["rows"] == [{"n": 2}]


def test_query_preserves_visible_manual_state_and_exact_columns(query_root: QueryRoot) -> None:
    result = _query(
        query_root,
        "SELECT row_hash, transaction_id, tags_manual, tags_final, "
        "category_manual, category_final, notes_manual, amount_coefficient, "
        "amount_scale FROM transactions",
    )
    assert result.exit_code == 0, result.output
    row = json.loads(result.output)["rows"][0]
    assert row["row_hash"] == "0000000000000000"
    assert row["transaction_id"] != row["row_hash"]
    assert json.loads(row["tags_manual"]) == ["visible"]
    assert json.loads(row["tags_final"]) == ["persisted", "persisted"]
    assert row["category_manual"] == "manual"
    assert row["category_final"] == "kept"
    assert row["notes_manual"] == "manual\nnotes"
    assert row["amount_coefficient"] == "-120025" and row["amount_scale"] == 2


def test_active_read_without_independent_evidence_cannot_fall_back(query_root: QueryRoot) -> None:
    with pytest.raises(AuthorityEvidenceUnavailableError, match="evidence provider"):
        read_transaction_snapshot(query_root.root)
    result = CliRunner().invoke(
        app, ["--data-dir", str(query_root.root), "query", "SELECT 1", "--json"]
    )
    assert result.exit_code != 0
    assert "evidence provider" in json.loads(result.output)["error"]["message"]


def test_duckdb_snapshot_and_read_partitions_use_repository(query_root: QueryRoot) -> None:
    with DuckDBAnalytics(query_root.root, evidence_provider=query_root.provider) as analytics:
        assert analytics.read_partitions().height == 2
        assert analytics.read_partitions(columns=["amount"]).columns == ["amount"]
        assert analytics.repository_snapshot is not None
        assert analytics.repository_snapshot.info.dataset_revision == 0
        with pytest.raises(ValueError, match="Partition-pattern"):
            analytics.read_partitions("2026/09/*.csv")


def test_open_analytics_stays_on_one_revision_after_real_mutation(query_root: QueryRoot) -> None:
    from finjuice.pipeline.storage.mutation_facade import StorageMutationFacade
    from finjuice.pipeline.storage.sqlite.mutations import ManualTransactionEdit

    with DuckDBAnalytics(query_root.root, evidence_provider=query_root.provider) as analytics:
        row = analytics.query_readonly(
            "SELECT transaction_id, notes_manual FROM transactions ORDER BY row_hash LIMIT 1"
        ).fetchone()
        receipt = StorageMutationFacade(
            query_root.root, query_root.provider
        ).edit_manual_transaction(
            ManualTransactionEdit(identifier=row[0], note_supplied=True, note="new note")
        )
        assert receipt.committed_revision == 1
        assert analytics.query_readonly(
            "SELECT notes_manual FROM transactions WHERE transaction_id = ?", [row[0]]
        ).fetchone() == ("manual\nnotes",)
        assert analytics.repository_snapshot.info.dataset_revision == 0
    result = _query(query_root, "SELECT notes_manual FROM transactions")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["dataset_revision"] == 1
    assert payload["rows"] == [{"notes_manual": "new note"}]


def test_repository_date_functions_match_csv_baseline(query_root: QueryRoot) -> None:
    sql = "SELECT strftime(date, '%Y-%m') AS month, count(*) AS n FROM transactions GROUP BY month"
    baseline = _query(query_root, sql, legacy=True)
    active = _query(query_root, sql)
    assert baseline.exit_code == active.exit_code == 0, baseline.output + active.output
    assert json.loads(baseline.output)["rows"] == json.loads(active.output)["rows"]


def test_query_uses_new_canonical_rules_revision_and_rejects_invalid_head(
    query_root: QueryRoot,
) -> None:
    from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade

    facade = StorageMutationFacade(query_root.root, query_root.provider)
    with DuckDBAnalytics(query_root.root, evidence_provider=query_root.provider) as analytics:
        old_content = analytics.repository_snapshot.rules_content
        facade.replace_config(
            ConfigDocument.from_validated_yaml("rules", b"rules: []\n", parser_version="test")
        )
        assert analytics.repository_snapshot.rules_content == old_content
    result = _query(query_root, "SELECT count(*) AS n FROM transactions")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [{"n": 2}]
    assert payload["_meta"]["dataset_revision"] == 1
    facade.replace_config(ConfigDocument("rules", b"rules: [invalid", "invalid", None, "test"))
    (query_root.root / "rules.yaml").write_text("rules: []\n")
    failed = _query(query_root, "SELECT count(*) AS n FROM transactions")
    assert failed.exit_code != 0
    assert "Canonical rules head" in json.loads(failed.output)["error"]["message"]


def test_human_query_uses_repository(query_root: QueryRoot) -> None:
    result = CliRunner().invoke(
        app,
        ["--data-dir", str(query_root.root), "query", "SELECT count(*) AS total FROM transactions"],
        obj={"activation_evidence_provider": query_root.provider},
    )
    assert result.exit_code == 0, result.output
    assert "Query Result" in " ".join(result.output.split()) and "total" in result.output


@pytest.mark.parametrize("status", ["invalid", "opaque"])
def test_valid_yaml_with_unparsed_head_is_not_used_as_filter(
    query_root: QueryRoot, status: str
) -> None:
    from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade

    StorageMutationFacade(query_root.root, query_root.provider).replace_config(
        ConfigDocument("rules", b"rules: []\n", status, None, "test")
    )
    result = _query(query_root, "SELECT count(*) AS n FROM transactions")
    assert result.exit_code != 0
    assert "Canonical rules head" in json.loads(result.output)["error"]["message"]
    explicit_bypass = _query(query_root, "SELECT count(*) AS n FROM transactions", no_filter=True)
    assert explicit_bypass.exit_code == 0, explicit_bypass.output
    assert json.loads(explicit_bypass.output)["rows"] == [{"n": 2}]


def test_empty_repository_honors_require_transactions(empty_root: _ActiveRoot) -> None:
    with pytest.raises(FileNotFoundError, match="No transaction data"):
        DuckDBAnalytics(empty_root.root, evidence_provider=empty_root.provider)
    with DuckDBAnalytics(
        empty_root.root, evidence_provider=empty_root.provider, require_transactions=False
    ) as analytics:
        assert analytics.query_readonly("SELECT count(*) FROM transactions").fetchone() == (0,)
