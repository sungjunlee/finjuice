"""Frozen canonical config selection preserves revisions without fallback guesses."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, SourceRoot, create_backup
from finjuice.pipeline.migration import build_migration, plan_migration, verify_migration
from finjuice.pipeline.migration.common import MigrationError, canonical, seal, tree_inventory
from finjuice.pipeline.migration.plan import analyze_capture
from finjuice.pipeline.migration.policy import PORTFOLIO_CONFIG_POLICY
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryReader

VALID_RULES = b"rules: []\namount: 9007199254740993.0100\n"
GOALS = b"goals: []\namount: 10.1000\n"


def _create_config_capture(
    tmp_path: Path, canonical_state: str
) -> tuple[Path, Path, Path, dict[str, bytes]]:
    source = tmp_path / "source"
    nested = source / "nested"
    nested.mkdir(parents=True)
    external = tmp_path / "external"
    external.mkdir()
    primary = b"rules: [invalid\n" if canonical_state == "invalid" else VALID_RULES
    expected = {
        "nested/rules.yaml": VALID_RULES,
        "rules.yml": VALID_RULES,
        "goals.json": b'{"goals": []}',
    }
    if canonical_state in {"valid", "invalid", "rules_only"}:
        expected["rules.yaml"] = primary
    if canonical_state in {"valid", "invalid", "goals_only"}:
        expected["goals.yaml"] = GOALS
    for name, content in expected.items():
        (source / name).write_bytes(content)
    (external / "rules.yaml").write_bytes(VALID_RULES)
    (external / "goals.yaml").write_bytes(GOALS)
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source,
            capture,
            ConsistencyEvidence("stopped_writers", ("synthetic",)),
            extra_roots=(SourceRoot("external", "required", external),),
        )
    )
    return source, external, capture, expected


@pytest.mark.parametrize(
    "canonical_state", ["valid", "invalid", "absent", "rules_only", "goals_only"]
)
def test_canonical_heads_preserve_every_revision_and_replay(
    tmp_path: Path, canonical_state: str
) -> None:
    source, external, capture, expected = _create_config_capture(tmp_path, canonical_state)
    before = tree_inventory(source), tree_inventory(external), tree_inventory(capture)
    plan_path = tmp_path / "plan.json"
    result = plan_migration(capture, output=plan_path, active_data_dir=source).to_dict()
    plan = result["plan"]
    assert plan["migration_policy"] == PORTFOLIO_CONFIG_POLICY
    planned_heads = sum(
        item.get("analysis", {}).get("record_counts", {}).get("config_head", 0)
        for item in plan["inputs"]
    )
    expected_head_kinds = {
        "valid": {"rules", "goals"},
        "invalid": {"rules", "goals"},
        "absent": set(),
        "rules_only": {"rules"},
        "goals_only": {"goals"},
    }[canonical_state]
    assert planned_heads == len(expected_head_kinds)
    candidate = tmp_path / "candidate"
    build_migration(plan_path, candidate, active_data_dir=source)
    paths = GenerationPaths(candidate)
    candidate_before = tree_inventory(candidate)
    assert verify_migration(candidate).to_dict()["cutover_ready"] is False
    assert (
        build_migration(plan_path, candidate, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    assert tree_inventory(candidate) == candidate_before
    with RepositoryReader(paths.database) as reader:
        revisions = [
            row for row in reader.rows("config_revisions") if row["config_kind"] != "other"
        ]
        assert len(revisions) == len(expected) + 2
        heads = reader.rows("config_heads")
        assert {head["config_kind"] for head in heads} == expected_head_kinds
        occurrences = {row["entity_id"]: row for row in reader.rows("source_occurrences")}
        provenance = {
            row["source_occurrence_id"]: json.loads(row["source_coordinate_json"])
            for row in reader.rows("record_provenance")
        }
        by_id = {row["entity_id"]: row for row in revisions}
        for head in heads:
            revision = by_id[head["revision_id"]]
            locator = provenance[revision["source_occurrence_id"]]
            assert locator == {"root": "data", "path": head["config_kind"] + ".yaml", "row": None}
            assert head["updated_at"] == plan["capture"]["capture"]["completed_at"]
            assert head["updated_changeset_id"] is None
            assert revision["parsed_status"] == (
                "invalid"
                if head["config_kind"] == "rules" and canonical_state == "invalid"
                else "parsed"
            )
        assert len({row["source_occurrence_id"] for row in revisions}) == len(revisions)
        for revision in revisions:
            locator = provenance[revision["source_occurrence_id"]]
            original = (
                expected[locator["path"]]
                if locator["root"] == "data"
                else (VALID_RULES if locator["path"] == "rules.yaml" else GOALS)
            )
            artifact = occurrences[revision["source_occurrence_id"]]["source_artifact_id"]
            assert artifact == "sha256:" + hashlib.sha256(original).hexdigest()
            assert paths.object_path(artifact.removeprefix("sha256:")).read_bytes() == original
            if original == VALID_RULES:
                assert (
                    json.loads(revision["canonical_payload_json"])["amount"]
                    == "9007199254740993.0100"
                )
        issues = reader.rows("preservation_issues")
        assert sum(row["issue_kind"] == "canonical_config_head_invalid" for row in issues) == (
            canonical_state == "invalid"
        )
    replay = tmp_path / "replay"
    build_migration(plan_path, replay, active_data_dir=source)
    assert semantic_snapshot(GenerationPaths(replay).database) == semantic_snapshot(paths.database)
    assert before == (tree_inventory(source), tree_inventory(external), tree_inventory(capture))


def test_legacy_plan_keeps_absent_heads_and_unknown_policy_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "rules.yaml").write_bytes(b"rules: []\n")
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("synthetic",)))
    )
    path = tmp_path / "plan.json"
    plan = plan_migration(capture, output=path, active_data_dir=source).to_dict()["plan"]
    modern = tmp_path / "modern"
    build_migration(path, modern, active_data_dir=source)
    plan.pop("migration_policy")
    plan.pop("canonical_digest")
    plan["inputs"] = analyze_capture(capture, plan["capture"])
    path.write_text(canonical(seal(plan)))
    candidate = tmp_path / "candidate"
    build_migration(path, candidate, active_data_dir=source)
    with RepositoryReader(GenerationPaths(candidate).database, expected_schema_version=4) as reader:
        assert reader.rows("config_heads") == []
        with RepositoryReader(GenerationPaths(modern).database) as current:
            assert reader.rows("repository_meta") != current.rows("repository_meta")
            assert reader.rows("source_occurrences") == current.rows("source_occurrences")
            assert reader.rows("config_revisions") == current.rows("config_revisions")
    assert verify_migration(candidate).to_dict()["status"] == "ok"
    plan["migration_policy"] = "unsupported.future"
    path.write_text(canonical(seal(plan)))
    with pytest.raises(MigrationError, match="adapter policy"):
        build_migration(path, tmp_path / "unknown", active_data_dir=source)
    assert not (tmp_path / "unknown").exists()

    evidence = GenerationPaths(candidate).manifests / "plan-evidence.json"
    evidence.write_text(canonical(seal(plan)))
    with pytest.raises(MigrationError, match="adapter policy"):
        verify_migration(candidate)
