"""Legacy analysis bundles come from one captured snapshot, never live CSV."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, SourceRoot, create_backup
from finjuice.pipeline.consumer_bundle import (
    BUNDLE_FORMAT,
    MANIFEST_NAME,
    MATERIALIZATION_POLICY,
    OVERLAY_OUTPUT,
    ConsumerBundleError,
    materialize_legacy_consumer_bundle,
)
from finjuice.pipeline.migration import build_migration, plan_migration
from finjuice.pipeline.migration.adapters.overview_reports import report_role
from finjuice.pipeline.migration.common import canonical, seal
from finjuice.pipeline.migration.plan import analyze_capture
from finjuice.pipeline.migration.policy import MANUAL_STATE_POLICY
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryReader, upgrade_repository
from tests.migration.test_overview_v4_integration import write_overview_sources
from tests.pipeline.test_sqlite_exact_import import _import, _overview_book, _Repo
from tests.pipeline.test_sqlite_exact_import import repo as _repo_fixture

repo = _repo_fixture
_STAGING_GLOB = ".finjuice-consumer-bundle.*.tmp"


def _prepare(
    tmp_path: Path,
    *,
    overlay: SourceRoot | None = None,
    extra_root: bool = False,
    empty_month: bool = False,
    policy: str | None = None,
) -> tuple[Path, dict[str, bytes], Path]:
    source = tmp_path / "source"
    files = write_overview_sources(source)
    if empty_month:
        empty = source / "banksalad/investments/2026/02/investments.csv"
        empty.parent.mkdir(parents=True)
        header = files["banksalad/investments/2026/01/investments.csv"].split(b"\n")[0]
        empty.write_bytes(header + b"\n")
        files[empty.relative_to(source).as_posix()] = empty.read_bytes()
    extra = (overlay,) if overlay is not None else ()
    other = tmp_path / "extra"
    if extra_root:
        write_overview_sources(other)
        extra = (*extra, SourceRoot("other", "required", other))
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source, capture, ConsistencyEvidence("stopped_writers", ("test",)), extra_roots=extra
        )
    )
    plan_path = tmp_path / "plan.json"
    plan = plan_migration(capture, output=plan_path, active_data_dir=source).to_dict()["plan"]
    if policy is not None:
        plan.pop("canonical_digest")
        plan["migration_policy"] = policy
        plan["inputs"] = analyze_capture(capture, plan["capture"], policy=policy)
        plan_path.write_text(canonical(seal(plan)))
    candidate = tmp_path / "candidate"
    build_migration(plan_path, candidate, active_data_dir=source)
    return source, files, candidate / "finjuice.sqlite3"


@pytest.mark.parametrize("overlay_root", ["overlay", "external-overlay"])
def test_bundle_uses_pinned_snapshot_and_ignores_poisoned_live_csv(
    tmp_path: Path, overlay_root: str
) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_bytes(b"# preserved overlay\r\nowners: []\r\n")
    source, files, database = _prepare(
        tmp_path,
        overlay=SourceRoot(overlay_root, "required", overlay),
        extra_root=True,
        empty_month=True,
    )
    dest = tmp_path / "bundle"
    with RepositoryReader(database, expected_schema_version=5) as reader:
        snapshot = reader.portfolio_snapshot()
        (source / "banksalad/balance/2026/01/balance.csv").write_text("poisoned\n")
        (source / "banksalad/investments/2026/01/investments.csv").write_text("poisoned\n")
        (source / "banksalad/loans/2026/01/loans.csv").write_text("poisoned\n")
        overlay.write_bytes(b"poisoned overlay\n")
        bundle = materialize_legacy_consumer_bundle(
            reader, dest, data_dir=source, source_roots=(source,)
        )

    assert bundle.manifest["dataset_generation"] == snapshot.info.dataset_generation
    assert bundle.manifest["dataset_revision"] == snapshot.info.dataset_revision
    assert bundle.manifest["sqlite_schema_version"] == 5
    assert bundle.manifest["format"] == BUNDLE_FORMAT
    assert bundle.manifest["materialization_policy"] == MATERIALIZATION_POLICY
    assert "no_native_report_coverage" in bundle.manifest["limitations"]
    assert "no_operational_acceptance" in bundle.manifest["limitations"]
    assert bundle.manifest["legacy_reports_support"] == "typed"
    for path in (
        "banksalad/balance/2026/01/balance.csv",
        "banksalad/investments/2026/01/investments.csv",
        "banksalad/loans/2026/01/loans.csv",
        "banksalad/investments/2026/02/investments.csv",
    ):
        assert (dest / path).read_bytes() == files[path]
    assert not (dest / "banksalad/loans/2026/02/loans.csv").exists()
    assert not (dest / "banksalad/cashflow/2026/01/cashflow.csv").exists()
    assert not any(dest.rglob("transactions.csv"))
    assert (dest / OVERLAY_OUTPUT).read_bytes() == b"# preserved overlay\r\nowners: []\r\n"
    assert bundle.overlay_path == dest / OVERLAY_OUTPUT
    assert bundle.manifest["source_identities"]["overlay"]["presence"] == "present"
    published = {row["path"] for row in bundle.manifest["source_identities"]["partitions"]}
    assert published == {
        "banksalad/balance/2026/01/balance.csv",
        "banksalad/investments/2026/01/investments.csv",
        "banksalad/loans/2026/01/loans.csv",
        "banksalad/investments/2026/02/investments.csv",
    }
    empty = (dest / "banksalad/investments/2026/02/investments.csv").read_bytes()
    assert empty.count(b"\n") == 1
    assert report_role("banksalad/investments/2026/02/investments.csv") == "investments"


def test_overlay_absence_is_preserved(tmp_path: Path) -> None:
    source, files, database = _prepare(tmp_path, overlay=SourceRoot("overlay", "optional", None))
    dest = tmp_path / "bundle"
    with RepositoryReader(database, expected_schema_version=5) as reader:
        bundle = materialize_legacy_consumer_bundle(reader, dest, data_dir=source)

    assert bundle.overlay_path is None
    assert not (dest / OVERLAY_OUTPUT).exists()
    assert bundle.manifest["source_identities"]["overlay"] == {"presence": "absent"}
    assert (dest / "banksalad/balance/2026/01/balance.csv").read_bytes() == files[
        "banksalad/balance/2026/01/balance.csv"
    ]


def test_deterministic_idempotent_rerun_preserves_previous_output(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_bytes(b"overlay: true\n")
    source, _files, database = _prepare(
        tmp_path, overlay=SourceRoot("overlay", "required", overlay)
    )
    dest = tmp_path / "bundle"
    with RepositoryReader(database, expected_schema_version=5) as reader:
        first = materialize_legacy_consumer_bundle(reader, dest, data_dir=source)
        before = {path: (dest / path).read_bytes() for path in (*first.files, MANIFEST_NAME)}
        second = materialize_legacy_consumer_bundle(reader, dest, data_dir=source)

    assert second.directory == first.directory == dest
    assert second.manifest == first.manifest
    assert {path: (dest / path).read_bytes() for path in before} == before
    assert list(dest.glob(_STAGING_GLOB)) == []


def test_overlap_and_symlink_targets_do_not_publish(tmp_path: Path) -> None:
    source, _files, database = _prepare(tmp_path)
    with RepositoryReader(database, expected_schema_version=5) as reader:
        with pytest.raises(ConsumerBundleError, match="overlaps"):
            materialize_legacy_consumer_bundle(reader, source / "bundle", data_dir=source)
        with pytest.raises(ConsumerBundleError, match="overlaps"):
            materialize_legacy_consumer_bundle(
                reader, database.parent / "bundle", source_roots=(source,)
            )
        alias = tmp_path / "alias"
        alias.symlink_to(tmp_path / "missing-target")
        with pytest.raises(ConsumerBundleError, match="unsafe|symlink"):
            materialize_legacy_consumer_bundle(reader, alias, data_dir=source)
        assert not (tmp_path / "missing-target").exists()
        assert alias.is_symlink()
        dest = tmp_path / "bundle"
        dest.mkdir()
        (dest / "kept.txt").write_text("previous")
        with pytest.raises(ConsumerBundleError, match="Previous output"):
            materialize_legacy_consumer_bundle(reader, dest, data_dir=source)
        assert (dest / "kept.txt").read_text() == "previous"
        assert not (dest / MANIFEST_NAME).exists()


def test_failed_publish_leaves_no_partial_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, _files, database = _prepare(tmp_path)
    dest = tmp_path / "bundle"

    def fail_rename(source_path: Path, destination: Path) -> None:
        raise OSError("forced publication failure")

    monkeypatch.setattr("finjuice.pipeline.consumer_bundle.rename_exclusive", fail_rename)
    with RepositoryReader(database, expected_schema_version=5) as reader:
        with pytest.raises(ConsumerBundleError, match="could not be published"):
            materialize_legacy_consumer_bundle(reader, dest, data_dir=source)

    assert not dest.exists()
    assert list(dest.parent.glob(_STAGING_GLOB)) == []


def test_schema4_clone_upgrade_keeps_capture_bytes_and_limits(tmp_path: Path) -> None:
    overlay = tmp_path / "overlay.yaml"
    overlay.write_bytes(b"manual: overlay\n")
    source, files, database = _prepare(
        tmp_path, overlay=SourceRoot("overlay", "required", overlay), policy=MANUAL_STATE_POLICY
    )
    upgraded = GenerationPaths(tmp_path / "upgraded")
    upgrade_repository(database, upgraded)
    dest = tmp_path / "bundle"
    with RepositoryReader(upgraded.database) as reader:
        snapshot = reader.portfolio_snapshot()
        bundle = materialize_legacy_consumer_bundle(reader, dest, data_dir=source)

    assert snapshot.legacy_reports_support == "typed"
    assert snapshot.legacy_overview_reports["legacy_overview_reports"] == ()
    assert bundle.manifest["legacy_reports_support"] == "typed"
    assert "historical_legacy_reference_projection" in bundle.manifest["limitations"]
    assert "no_native_report_coverage" in bundle.manifest["limitations"]
    assert (dest / "banksalad/loans/2026/01/loans.csv").read_bytes() == files[
        "banksalad/loans/2026/01/loans.csv"
    ]
    assert (dest / OVERLAY_OUTPUT).read_bytes() == b"manual: overlay\n"
    assert bundle.manifest["sqlite_schema_version"] == snapshot.info.schema_version
    assert bundle.manifest["dataset_generation"] == snapshot.info.dataset_generation


def test_native_reports_are_not_projected_as_legacy_csv(repo: _Repo) -> None:
    _import(repo, _overview_book(), key="overview", revision=0)
    dest = repo.data_dir.parent / "bundle"
    with RepositoryReader(repo.database) as reader:
        snapshot = reader.portfolio_snapshot()
        bundle = materialize_legacy_consumer_bundle(reader, dest, data_dir=repo.data_dir)

    assert snapshot.native_overview_reports["overview_balances"]
    assert snapshot.legacy_overview_reports["legacy_overview_reports"] == ()
    assert bundle.files == ()
    assert bundle.overlay_path is None
    assert bundle.manifest["source_identities"]["overlay"]["presence"] == "absent"
    assert bundle.manifest["source_identities"]["partitions"] == []
    assert json.loads((dest / MANIFEST_NAME).read_text(encoding="utf-8")) == bundle.manifest
    assert list(dest.rglob("*.csv")) == []


def test_ambiguous_overlay_roots_are_rejected() -> None:
    from finjuice.pipeline.consumer_bundle import _overlay_file

    scopes = (
        {"root": "overlay", "source_occurrence_id": "first"},
        {"root": "external-overlay", "source_occurrence_id": "second"},
    )
    with pytest.raises(ConsumerBundleError, match="ambiguous"):
        _overlay_file(scopes, {}, {}, GenerationPaths(Path("unused")))


def test_artifact_changed_after_verification_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hashlib
    from types import SimpleNamespace

    from finjuice.pipeline.consumer_bundle import _artifact_bytes
    from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore

    original = b"original"
    artifact_id = "sha256:" + hashlib.sha256(original).hexdigest()
    artifact = tmp_path / "object"
    artifact.write_bytes(original)

    def verify_then_change(self: object, identity: str, size: int) -> SimpleNamespace:
        artifact.write_bytes(b"modified")
        return SimpleNamespace(relative_path="object")

    monkeypatch.setattr(SourceObjectStore, "verify", verify_then_change)
    with pytest.raises(ConsumerBundleError, match="do not match"):
        _artifact_bytes(
            GenerationPaths(tmp_path),
            {"capture": {"occurrence_kind": "legacy_capture", "source_artifact_id": artifact_id}},
            {artifact_id: {"byte_length": len(original)}},
            "capture",
        )
