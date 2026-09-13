"""Immutable migration policies retain schema v4 when runtime current changes."""

from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
from finjuice.pipeline.migration import build_migration, plan_migration, verify_migration
from finjuice.pipeline.migration.common import MigrationError, canonical, seal, tree_inventory
from finjuice.pipeline.migration.plan import analyze_capture
from finjuice.pipeline.migration.policy import (
    CONFIG_HEAD_POLICY,
    LEGACY_POLICY,
    MANUAL_STATE_POLICY,
    OVERVIEW_REPORT_POLICY,
    PORTFOLIO_CONFIG_POLICY,
    migration_schema_version,
)
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import (
    GenerationPaths,
    RepositoryBuilder,
    RepositoryReader,
    schema,
)
from finjuice.pipeline.storage.sqlite.errors import RepositoryVersionError


@pytest.mark.parametrize("version", [True, False, "4", 4.0, 0, 3, 6])
def test_unsupported_schema_request_rejects_before_filesystem_access(
    tmp_path: Path, version: Any
) -> None:
    paths = GenerationPaths(tmp_path / "uncreated")
    with pytest.raises(RepositoryVersionError, match="Unsupported requested"):
        RepositoryBuilder(paths, str(uuid.uuid4()), expected_schema_version=version)
    with pytest.raises(RepositoryVersionError, match="Unsupported requested"):
        RepositoryReader(paths.database, expected_schema_version=version)
    with pytest.raises(RepositoryVersionError, match="Unsupported requested"):
        semantic_snapshot(paths.database, expected_schema_version=version)
    assert not paths.root.exists()


@pytest.mark.parametrize("header_version", [3, 5])
def test_pinned_reader_rejects_mismatched_database(tmp_path: Path, header_version: int) -> None:
    paths = GenerationPaths(tmp_path / "candidate")
    with RepositoryBuilder(paths, str(uuid.uuid4()), expected_schema_version=4) as builder:
        builder.finalize()
    with closing(sqlite3.connect(paths.database)) as connection:
        # Only fixed test constants are used in SQLite's non-parameterizable pragma.
        connection.execute(
            "PRAGMA user_version = 3" if header_version == 3 else "PRAGMA user_version = 5"
        )
    before = tree_inventory(paths.root)
    with pytest.raises(RepositoryVersionError, match="supported v4"):
        RepositoryReader(paths.database, expected_schema_version=4)
    assert tree_inventory(paths.root) == before


@pytest.mark.parametrize("policy", [LEGACY_POLICY, CONFIG_HEAD_POLICY, MANUAL_STATE_POLICY])
def test_migration_build_verify_and_retry_remain_v4_when_runtime_current_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, policy: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "opaque.bin").write_bytes(b"synthetic preservation evidence")
    capture = tmp_path / "capture"
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan_path = tmp_path / "plan.json"
    plan = plan_migration(capture, output=plan_path, active_data_dir=source).to_dict()["plan"]
    plan.pop("canonical_digest")
    plan["migration_policy"] = policy
    plan["inputs"] = analyze_capture(capture, plan["capture"], policy=policy)
    plan_path.write_text(canonical(seal(plan)))
    candidate = tmp_path / "candidate"
    build_migration(plan_path, candidate, active_data_dir=source)
    before = tree_inventory(candidate)
    original_digest = semantic_snapshot(
        GenerationPaths(candidate).database, expected_schema_version=4
    )

    # A future current-version bump must not change existing adapter policy semantics.
    # Simulate an unsupported future runtime version.
    monkeypatch.setattr(schema, "SQLITE_SCHEMA_VERSION", 6)
    assert migration_schema_version(policy) == 4
    with pytest.raises(RepositoryVersionError):
        RepositoryReader(GenerationPaths(candidate).database)
    with pytest.raises(RepositoryVersionError):
        RepositoryBuilder(GenerationPaths(tmp_path / "runtime"), str(uuid.uuid4()))
    assert verify_migration(candidate).to_dict()["status"] == "ok"
    assert (
        build_migration(plan_path, candidate, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    assert tree_inventory(candidate) == before

    replay = tmp_path / "replay"
    build_migration(plan_path, replay, active_data_dir=source)
    with RepositoryReader(GenerationPaths(replay).database, expected_schema_version=4) as reader:
        assert reader.info.schema_version == 4
        assert sorted(row["schema_version"] for row in reader.rows("schema_migrations")) == [
            1,
            2,
            3,
            4,
        ]
    assert (
        semantic_snapshot(GenerationPaths(replay).database, expected_schema_version=4)
        == original_digest
    )


def test_unknown_migration_policy_has_no_schema_fallback() -> None:
    with pytest.raises(MigrationError, match="Unsupported migration adapter policy"):
        migration_schema_version("legacy_preservation.unknown")


def test_new_overview_policy_requires_v5() -> None:
    assert migration_schema_version(OVERVIEW_REPORT_POLICY) == 5
    assert migration_schema_version(PORTFOLIO_CONFIG_POLICY) == 5
