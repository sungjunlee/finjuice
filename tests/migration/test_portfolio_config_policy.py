"""Portfolio config heads extend the frozen v4 policy without changing stored rows."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, SourceRoot, create_backup
from finjuice.pipeline.migration import build_migration, plan_migration, verify_migration
from finjuice.pipeline.migration.common import canonical, seal, tree_inventory
from finjuice.pipeline.migration.plan import analyze_capture
from finjuice.pipeline.migration.policy import OVERVIEW_REPORT_POLICY, PORTFOLIO_CONFIG_POLICY
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader

CONFIG = b"version: 1\nmanual_amount: 9007199254740993.0100\nitems: []\n"
INVALID = b"private-invalid: [\n"


def _capture(tmp_path: Path, kind: str, state: str):
    source = tmp_path / "source"
    source.mkdir()
    extra = tmp_path / "extra"
    extra.mkdir()
    original = {"rules.yaml": b"rules: []\n", "goals.yaml": b"goals: []\n"}
    for name in ("assets", "scenarios"):
        if name != kind or state != "absent":
            original[f"{name}.yaml"] = INVALID if name == kind and state == "invalid" else CONFIG
        original[f"nested/{name}.yaml"] = CONFIG
        original[f"{name}.yml"] = CONFIG
        original[f"{name}.json"] = b'{"valid": true}'
        (extra / f"{name}.yaml").write_bytes(CONFIG)
    for name, content in original.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source,
            capture,
            ConsistencyEvidence("stopped_writers", ("test",)),
            extra_roots=(SourceRoot("extra", "required", extra),),
        )
    )
    return source, extra, capture, original


@pytest.mark.parametrize("kind", ["assets", "scenarios"])
@pytest.mark.parametrize("state", ["valid", "invalid", "absent"])
def test_portfolio_heads_select_only_primary_exact_paths_and_preserve_all_bytes(
    tmp_path, kind, state
):
    source, extra, capture, original = _capture(tmp_path, kind, state)
    before = tree_inventory(source), tree_inventory(extra), tree_inventory(capture)
    path = tmp_path / "plan.json"
    plan = plan_migration(capture, output=path, active_data_dir=source).to_dict()["plan"]
    assert plan["migration_policy"] == PORTFOLIO_CONFIG_POLICY
    expected = {"rules", "goals", "assets", "scenarios"} - ({kind} if state == "absent" else set())
    assert sum(
        item["analysis"]["record_counts"].get("config_head", 0)
        for item in plan["inputs"]
        if "analysis" in item
    ) == len(expected)
    candidate = tmp_path / "candidate"
    build_migration(path, candidate, active_data_dir=source)
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        assert reader.info.schema_version == 5
        revisions = {
            row["entity_id"]: row
            for row in reader.rows("config_revisions")
            if row["config_kind"] != "other"
        }
        heads = reader.rows("config_heads")
        assert {row["config_kind"] for row in heads} == expected
        assert len(revisions) == len(original) + 2
        provenance = {
            row["source_occurrence_id"]: json.loads(row["source_coordinate_json"])
            for row in reader.rows("record_provenance")
        }
        for head in heads:
            revision = revisions[head["revision_id"]]
            assert provenance[revision["source_occurrence_id"]] == {
                "root": "data",
                "path": head["config_kind"] + ".yaml",
                "row": None,
            }
            assert head["updated_at"] == plan["capture"]["capture"]["completed_at"]
            assert head["updated_changeset_id"] is None
            assert revision["parsed_status"] == (
                "invalid" if state == "invalid" and head["config_kind"] == kind else "parsed"
            )
        for revision in revisions.values():
            locator = provenance[revision["source_occurrence_id"]]
            raw = original[locator["path"]] if locator["root"] == "data" else CONFIG
            assert revision["source_artifact_id"] == "sha256:" + hashlib.sha256(raw).hexdigest()
            if raw == CONFIG:
                assert (
                    json.loads(revision["canonical_payload_json"])["manual_amount"]
                    == "9007199254740993.0100"
                )
    assert verify_migration(candidate).to_dict()["cutover_ready"] is False
    stable = tree_inventory(candidate)
    assert (
        build_migration(path, candidate, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    assert tree_inventory(candidate) == stable
    replay = tmp_path / "replay"
    build_migration(path, replay, active_data_dir=source)
    assert semantic_snapshot(replay / "finjuice.sqlite3") == semantic_snapshot(
        candidate / "finjuice.sqlite3"
    )
    assert before == (tree_inventory(source), tree_inventory(extra), tree_inventory(capture))


def test_v5_inherits_v4_report_and_manual_state_without_reclassification(tmp_path):
    import csv

    from tests.migration.test_overview_v4_integration import write_overview_sources

    source, _, _, _ = _capture(tmp_path, "assets", "invalid")
    write_overview_sources(source)
    path = source / "transactions/2026/01/transactions.csv"
    path.parent.mkdir(parents=True)
    row = {
        "row_hash": "synthetic",
        "date": "2026-01-01",
        "time": "00:00",
        "datetime": "2026-01-01T00:00",
        "type_norm": "expense",
        "account": "synthetic",
        "tags_rule": "[]",
        "tags_ai": "[]",
        "amount": "-9007199254740993.0100",
        "category_final": "stored-final",
        "tags_manual": '[" x ", "x", " x ", " __finjuice_category_override__: A "]',
        "tags_final": '["same", "same"]',
        "notes_manual": "line1\nline2",
    }
    with path.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(row))
        writer.writeheader()
        writer.writerow(row)
    capture = tmp_path / "capture2"
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan_path = tmp_path / "plan.json"
    plan = plan_migration(capture, output=plan_path, active_data_dir=source).to_dict()["plan"]
    new = tmp_path / "new"
    build_migration(plan_path, new, active_data_dir=source)
    plan.pop("canonical_digest")
    plan["migration_policy"] = OVERVIEW_REPORT_POLICY
    plan["inputs"] = analyze_capture(capture, plan["capture"], policy=OVERVIEW_REPORT_POLICY)
    plan_path = tmp_path / "v4.json"
    plan_path.write_text(canonical(seal(plan)))
    old = tmp_path / "old"
    build_migration(plan_path, old, active_data_dir=source)
    with (
        RepositoryReader(old / "finjuice.sqlite3") as previous,
        RepositoryReader(new / "finjuice.sqlite3") as current,
    ):
        assert previous.table_names == current.table_names
        assert previous.info.dataset_generation != current.info.dataset_generation
        assert previous.info.schema_version == current.info.schema_version == 5
        assert previous.info.dataset_revision == current.info.dataset_revision == 0
        for table in previous.table_names:
            if table not in {
                "config_heads",
                "preservation_issues",
                "schema_migrations",
                "repository_meta",
            }:
                assert sorted(previous.rows(table), key=canonical) == sorted(
                    current.rows(table), key=canonical
                ), table
        assert {row["config_kind"] for row in previous.rows("config_heads")} == {"rules", "goals"}
        assert {row["config_kind"] for row in current.rows("config_heads")} == {
            "rules",
            "goals",
            "assets",
            "scenarios",
        }
        txn = current.rows("transactions")[0]
        assert txn["category_manual"] == "A"
        assert txn["category_final"] == "stored-final"
        assert json.loads(txn["tags_final_json"]) == ["same", "same"]
        assert txn["notes_manual"] == "line1\nline2"
        for issue in previous.rows("preservation_issues"):
            assert issue in current.rows("preservation_issues")
    assert verify_migration(new).to_dict()["status"] == "ok"
    assert verify_migration(old).to_dict()["status"] == "ok"
