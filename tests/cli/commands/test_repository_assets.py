"""Actual migration parity and authority fences for raw asset commands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.migration import build_migration, plan_migration
from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityPaths,
    StaticActivationEvidenceProvider,
)
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryReader, upgrade_repository
from tests.cli.commands.test_assets import _write_balance
from tests.cli.commands.test_assets import asset_data_dir as _asset_fixture
from tests.cli.commands.test_repository_query import QueryRoot

asset_data_dir = _asset_fixture


def _activate(source: Path, tmp_path: Path) -> QueryRoot:
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    # M1 produces the pinned schema v5 capsule; activation uses an explicit clone upgrade.
    upgraded = GenerationPaths(tmp_path / "upgraded")
    upgrade_repository(candidate / "finjuice.sqlite3", upgraded)
    candidate = upgraded.root
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        info = reader.info
    root = tmp_path / "active"
    paths = AuthorityPaths.for_data_dir(root)
    shutil.copytree(candidate, paths.generation(info.dataset_generation).root)
    evidence = ActivationEvidence("test", "a" * 64, "b" * 64, "c" * 64)
    paths.control_root.mkdir(parents=True, mode=0o700)
    paths.activation.write_text(
        json.dumps(
            {
                "activation_schema_version": 1,
                "release_version": evidence.installed_release_version,
                "release_artifact_sha256": evidence.installed_release_artifact_sha256,
                "dataset_generation": info.dataset_generation,
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
    return QueryRoot(
        root, source, StaticActivationEvidenceProvider(evidence), info.dataset_generation
    )


@pytest.fixture
def portfolio_root(asset_data_dir: Path, tmp_path: Path) -> QueryRoot:
    _write_balance(
        asset_data_dir,
        "2026-03",
        [
            {
                "snapshot_date": "2026-03-15",
                "side": "asset",
                "category": "financial",
                "item_name": "holding",
                "amount": 4300000.0,
                "currency": "KRW",
                "source_fact_id": "missing",
                "file_id": "synthetic-source",
                "source_row": 1,
            }
        ],
    )
    return _activate(asset_data_dir, tmp_path)


def _invoke(root: QueryRoot, args: list[str], *, legacy: bool = False, human: bool = False):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "assets",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={} if legacy else {"activation_evidence_provider": root.provider},
    )


def _assert_baseline(expected: Any, actual: Any) -> None:
    if isinstance(expected, dict):
        for key, value in expected.items():
            if key != "_meta":
                _assert_baseline(value, actual[key])
    elif isinstance(expected, list):
        assert len(expected) == len(actual)
        for old, new in zip(expected, actual, strict=True):
            _assert_baseline(old, new)
    else:
        assert actual == expected


@pytest.mark.parametrize("args", [["status"], ["show", "--limit", "1"], ["balance"]])
def test_active_assets_preserve_baseline_and_ignore_live_files(
    portfolio_root: QueryRoot, args: list[str]
) -> None:
    old = _invoke(portfolio_root, args, legacy=True)
    new = _invoke(portfolio_root, args)
    assert old.exit_code == new.exit_code == 0, old.output + new.output
    expected, actual = json.loads(old.output), json.loads(new.output)
    _assert_baseline(expected, actual)
    assert actual["_meta"]["dataset_generation"] == portfolio_root.generation
    assert actual["_meta"]["dataset_revision"] == 0
    for relative in (
        "assets/snapshots/2026/03/snapshots.csv",
        "banksalad/balance/2026/03/balance.csv",
    ):
        target = portfolio_root.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("PRIVATE_SENTINEL,invalid\n")
    repeated = _invoke(portfolio_root, args)
    assert repeated.exit_code == 0, repeated.output
    _assert_baseline(actual, json.loads(repeated.output))
    assert "PRIVATE_SENTINEL" not in repeated.output
    human = _invoke(portfolio_root, args, human=True)
    assert human.exit_code == 0, human.output
    assert "Repository revision 0" in human.output


def test_active_show_retains_exact_identity_sidecars(portfolio_root: QueryRoot) -> None:
    result = _invoke(portfolio_root, ["show", "--account", "증권", "--limit", "1"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["total_count"] == 1
    row = data["holdings"][0]
    assert row["account_id"] == "증권계좌"
    assert row["account_entity_id"] != row["account_id"]
    assert row["market_value_coefficient"] is not None
    assert row["market_value_lexical"] is not None


def test_active_asset_reads_require_independent_authority(portfolio_root: QueryRoot) -> None:
    result = CliRunner().invoke(
        app, ["--data-dir", str(portfolio_root.root), "assets", "status", "--json"]
    )
    assert result.exit_code != 0
    assert "source completeness" in result.output


def test_empty_latest_partition_and_no_data_metadata(asset_data_dir: Path, tmp_path: Path) -> None:
    empty = asset_data_dir / "assets/snapshots/2026/04/snapshots.csv"
    empty.parent.mkdir(parents=True)
    empty.write_text("snapshot_date,account_id,instrument_id,quantity,market_value,currency\n")
    root = _activate(asset_data_dir, tmp_path)
    for args in (["status"], ["show"]):
        old, new = _invoke(root, args, legacy=True), _invoke(root, args)
        assert old.exit_code == new.exit_code
        _assert_baseline(json.loads(old.output), json.loads(new.output))
        assert json.loads(new.output)["_meta"]["dataset_revision"] == 0
    assert _invoke(root, ["show", "--month", "2026-03"]).exit_code == 0
