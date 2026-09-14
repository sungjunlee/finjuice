"""Managed local recovery-graph store inventory, lease, and actual prune."""

from __future__ import annotations

import json
import multiprocessing
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import pytest

from finjuice.pipeline.backup.publish import rename_exclusive
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityConflictError,
    BackupVerificationError,
)
from finjuice.pipeline.storage.sqlite.recovery_store import (
    capture_into_store,
    initialize_recovery_store,
    list_recovery_store,
    plan_recovery_store,
    protect_store_copy,
    prune_recovery_store,
    restore_store_copy,
)
from tests.cli.test_sqlite_recovery_bundle import _mutate_and_rebackup, _write_expected
from tests.pipeline.test_recovery_bundle import _live


def _prepare(tmp_path: Path):
    source, expected, paths, generation, transactions, account_id = _live(tmp_path)
    store = tmp_path / "recovery-store"
    initialize_recovery_store(store, expected)
    return source, expected, store, paths, generation, transactions, account_id


def _capture(store: Path, source, expected):
    # A deterministic clock controls snapshot evidence, without wall-clock sleeps.
    offset = len(list((store / "bundles").iterdir()))
    with patch("finjuice.pipeline.storage.sqlite.backup.datetime") as clock:
        clock.now.return_value = datetime(2026, 9, 14, tzinfo=timezone.utc) + timedelta(
            seconds=offset
        )
        return capture_into_store(store, source, expected)


def _copy_ids(store: Path, expected) -> list[str]:
    return [item.copy_id for item in list_recovery_store(store, expected).copies]


def test_unprotected_old_copy_is_removed_and_remaining_restore_mutates(
    tmp_path: Path,
) -> None:
    source, expected, store, _paths, _generation, transactions, _account = _prepare(tmp_path)
    first = _capture(store, source, expected)
    second = _capture(store, source, expected)
    third = _capture(store, source, expected)
    unrelated = tmp_path / "unrelated.txt"
    unrelated.write_text("keep", encoding="utf-8")

    pruned = prune_recovery_store(store, expected)
    remaining = set(_copy_ids(store, expected))

    assert first.copy_id not in pruned.deleted_ids
    assert third.copy_id not in pruned.deleted_ids
    assert second.copy_id in pruned.deleted_ids
    assert remaining == {first.copy_id, third.copy_id}
    assert not (store / "bundles" / second.copy_id).exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"

    _verified, restored = restore_store_copy(store, expected, third.copy_id, tmp_path / "workspace")
    _mutate_and_rebackup(restored, transactions, tmp_path / "rebackup")


def _capture_hold(store: str, source, expected, ready: object, release: object) -> None:
    from finjuice.pipeline.storage.sqlite import recovery_bundle

    original = recovery_bundle._materialize

    def paused(*args, **kwargs):
        original(*args, **kwargs)
        ready.set()  # type: ignore[attr-defined]
        assert release.wait(30)  # type: ignore[attr-defined]

    with patch.object(recovery_bundle, "_materialize", paused):
        capture_into_store(Path(store), source, expected)


def _restore_hold(
    store: str, expected_path: str, packed: str, ready: object, release: object
) -> None:
    from finjuice.pipeline.storage.sqlite import backup
    from finjuice.pipeline.storage.sqlite.backup_verify import resolve_backup_input
    from finjuice.pipeline.storage.sqlite.inactive_restore import restore_workspace

    copy_id, target, mode = packed.split("|", 2)
    expected = _load_expected(expected_path)
    bundle = Path(store) / "bundles" / copy_id
    original = backup._restore_database

    def paused(*args, **kwargs):
        ready.set()  # type: ignore[attr-defined]
        assert release.wait(30)  # type: ignore[attr-defined]
        return original(*args, **kwargs)

    with patch.object(backup, "_restore_database", paused):
        if mode == "store":
            restore_store_copy(Path(store), expected, copy_id, Path(target))
        else:
            attempt, _, _ = resolve_backup_input(bundle / "snapshot")
            if mode == "attempt":
                backup.restore_backup(attempt, Path(target))
            else:
                restore_workspace(attempt, Path(target))


def _load_expected(expected_path: str):
    from finjuice.pipeline.cli.commands.recovery_expected import load_expected_recovery_graph

    return load_expected_recovery_graph(Path(expected_path))


def _spawn(target, args):
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    release = context.Event()
    process = context.Process(target=target, args=(*args, ready, release))
    process.start()
    if not ready.wait(30):
        process.kill()
        process.join(5)
        pytest.fail("Child did not reach the bounded operation pause")
    return process, release


@pytest.mark.parametrize("mode", ["store", "attempt", "workspace-attempt"])
def test_actual_restore_blocks_prune(tmp_path: Path, mode: str) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    expected_path = str(_write_expected(tmp_path / "enrolled.json", expected))
    child, release = _spawn(
        _restore_hold, (str(store), expected_path, f"{first.copy_id}|{tmp_path / 'restore'}|{mode}")
    )
    try:
        with pytest.raises(AuthorityConflictError, match="timed out"):
            prune_recovery_store(store, expected, timeout_ms=80)
        assert (store / "bundles" / first.copy_id).is_dir()
    finally:
        release.set()
        child.join(15)
        if child.is_alive():
            child.kill()
            child.join(5)
    assert child.exitcode == 0


@pytest.mark.parametrize("interrupt", [False, True])
def test_actual_capture_blocks_prune_and_process_death_releases_lease(
    tmp_path: Path, interrupt: bool
) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    child, release = _spawn(_capture_hold, (str(store), source, expected))
    try:
        with pytest.raises(AuthorityConflictError, match="timed out"):
            prune_recovery_store(store, expected, timeout_ms=80)
    finally:
        if interrupt:
            child.kill()
        else:
            release.set()
        child.join(15)
        if child.is_alive():
            child.kill()
            child.join(5)
    assert (child.exitcode != 0) == interrupt
    inventory = list_recovery_store(store, expected)
    assert inventory.healthy_count == (1 if interrupt else 2)
    if interrupt:
        assert any(item.health == "held" for item in inventory.copies)
    prune_recovery_store(store, expected, timeout_ms=2_000)
    assert (store / "bundles" / first.copy_id).is_dir()


def test_stale_plan_is_rejected_after_new_capture(tmp_path: Path) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    _capture(store, source, expected)
    third = _capture(store, source, expected)
    planned = plan_recovery_store(store, expected)
    fourth = _capture(store, source, expected)

    with pytest.raises(BackupVerificationError):
        prune_recovery_store(store, expected, plan_digest=planned.plan_digest)

    remaining = set(_copy_ids(store, expected))
    assert remaining == {
        first.copy_id,
        planned.delete_ids[0],
        third.copy_id,
        fourth.copy_id,
    }
    pruned = prune_recovery_store(store, expected)
    kept = set(_copy_ids(store, expected))
    assert first.copy_id in kept
    assert fourth.copy_id in kept
    assert fourth.copy_id not in pruned.deleted_ids
    assert first.copy_id not in pruned.deleted_ids


def test_malformed_baseline_and_unhealthy_copies_are_not_deleted(tmp_path: Path) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    second = _capture(store, source, expected)
    third = _capture(store, source, expected)
    unknown = store / "bundles" / "not-a-uuid"
    unknown.mkdir(mode=0o700)
    (unknown / "marker.txt").write_text("held", encoding="utf-8")
    registration = store / ".finjuice-recovery-store" / "registration.json"
    original = registration.read_bytes()

    registration.write_bytes(b"{")
    with pytest.raises(BackupVerificationError):
        prune_recovery_store(store, expected)
    assert (store / "bundles" / second.copy_id).is_dir()

    registration.unlink()
    with pytest.raises(BackupVerificationError):
        prune_recovery_store(store, expected)
    assert (store / "bundles" / second.copy_id).is_dir()

    registration.write_bytes(original)
    for copy_id in (first.copy_id, second.copy_id, third.copy_id):
        (store / "bundles" / copy_id / "recovery-graph.json").write_bytes(b"{}")
    with pytest.raises(BackupVerificationError):
        prune_recovery_store(store, expected)
    assert unknown.is_dir()
    assert unknown.joinpath("marker.txt").read_text(encoding="utf-8") == "held"
    for copy_id in (first.copy_id, second.copy_id, third.copy_id):
        assert (store / "bundles" / copy_id).is_dir()


@pytest.mark.parametrize("replacement", ["unknown", "verified"])
def test_tombstone_resume_is_idempotent_and_preserves_recreated_names(
    tmp_path: Path, replacement: str
) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    second = _capture(store, source, expected)
    third = _capture(store, source, expected)
    unrelated = tmp_path / "outside"
    unrelated.mkdir()
    (unrelated / "keep.txt").write_text("safe", encoding="utf-8")

    inventory = list_recovery_store(store, expected)
    created_at = next(
        item.created_at for item in inventory.copies if item.copy_id == second.copy_id
    )
    bundle = store / "bundles" / second.copy_id
    info = bundle.lstat()
    intent_id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    intent = {
        "schema_version": 1,
        "kind": "finjuice.sqlite.local-recovery-tombstone",
        "intent_id": intent_id,
        "copy_id": second.copy_id,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
        "graph_digest": second.graph["graph_digest"],
        "created_at": created_at,
    }
    tombstone = store / "bundles" / f".tombstone-{intent_id}"
    rename_exclusive(bundle, tombstone)
    recreated = store / "bundles" / second.copy_id
    if replacement == "verified":
        shutil.copytree(tombstone, recreated)
        retained_file = recreated / "recovery-graph.json"
    else:
        recreated.mkdir(mode=0o700)
        retained_file = recreated / "original.txt"
        retained_file.write_text("new-object", encoding="utf-8")
    retained_bytes = retained_file.read_bytes()
    intent_path = store / ".finjuice-recovery-store" / "intents" / f"{intent_id}.json"
    intent_path.write_bytes(json.dumps(intent, sort_keys=True, separators=(",", ":")).encode())

    prune_recovery_store(store, expected)
    assert not tombstone.exists()
    assert retained_file.read_bytes() == retained_bytes
    assert (store / "bundles" / first.copy_id).is_dir()
    assert (store / "bundles" / third.copy_id).is_dir()
    assert unrelated.joinpath("keep.txt").read_text(encoding="utf-8") == "safe"

    if replacement == "unknown":
        prune_recovery_store(store, expected)
        assert retained_file.read_bytes() == retained_bytes


def test_protect_registers_verified_identity(tmp_path: Path) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    second = _capture(store, source, expected)
    protected = protect_store_copy(store, expected, second.copy_id)
    assert protected.graph_digest == second.graph["graph_digest"]
    pruned = prune_recovery_store(store, expected)
    kept = set(_copy_ids(store, expected))
    assert first.copy_id in kept
    assert second.copy_id in kept
    assert pruned.deleted_count == 0


@pytest.mark.parametrize("field", ["graph_digest", "snapshot_manifest_digest", "created_at"])
def test_registered_baseline_identity_must_match_verified_graph(tmp_path: Path, field: str) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    _capture(store, source, expected)
    middle = _capture(store, source, expected)
    _capture(store, source, expected)
    path = store / ".finjuice-recovery-store" / "registration.json"
    payload = json.loads(path.read_bytes())
    payload["baselines"][0][field] = (
        "2020-01-01T00:00:00+00:00" if field == "created_at" else "f" * 64
    )
    path.write_text(json.dumps(payload))

    with pytest.raises(BackupVerificationError):
        prune_recovery_store(store, expected)
    assert (store / "bundles" / middle.copy_id).is_dir()


def test_missing_registration_cannot_be_rebootstrapped(tmp_path: Path) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    registration = store / ".finjuice-recovery-store" / "registration.json"
    registration.unlink()
    before = set((store / "bundles").iterdir())

    with pytest.raises(BackupVerificationError):
        _capture(store, source, expected)
    with pytest.raises(BackupVerificationError):
        protect_store_copy(store, expected, first.copy_id)
    assert not registration.exists()
    assert set((store / "bundles").iterdir()) == before


def test_plan_binds_same_name_replacement_identity(tmp_path: Path) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    _capture(store, source, expected)
    middle = _capture(store, source, expected)
    _capture(store, source, expected)
    planned = plan_recovery_store(store, expected)
    original = store / "bundles" / middle.copy_id
    retained = tmp_path / "retained-copy"
    original.rename(retained)
    shutil.copytree(retained, original)

    with pytest.raises(BackupVerificationError):
        prune_recovery_store(store, expected, plan_digest=planned.plan_digest)
    assert original.is_dir()
    assert retained.is_dir()


def test_same_second_latest_revision_is_protected(tmp_path: Path) -> None:
    from finjuice.pipeline.backup.retention import RetentionPolicy
    from finjuice.pipeline.storage.sqlite import PartyRecord, new_entity_id
    from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationService
    from tests.pipeline.test_sqlite_mutations import _request

    source, expected, store, paths, generation, *_ = _prepare(tmp_path)
    identities = [f"{number:08x}-bbbb-4ccc-8ddd-eeeeeeeeeeee" for number in (3, 2, 1)]
    captured = []
    with (
        patch("finjuice.pipeline.storage.sqlite.backup.datetime") as clock,
        patch(
            "finjuice.pipeline.storage.sqlite.recovery_store._fresh_copy_id", side_effect=identities
        ),
    ):
        clock.now.return_value = datetime(2026, 9, 14, tzinfo=timezone.utc)
        for revision in range(1, 4):

            def add_party(context):
                context.add_party(PartyRecord(new_entity_id()))
                return MutationOutcome(result={"synthetic": True})

            MutationService(paths, expected.activation_evidence).execute(
                _request(generation, f"store-revision-{revision}", revision), add_party
            )
            captured.append(capture_into_store(store, source, expected))

    inventory = list_recovery_store(store, expected)
    assert len({item.created_at for item in inventory.copies}) == 1
    assert inventory.latest_healthy_id == captured[-1].copy_id
    result = prune_recovery_store(store, expected, RetentionPolicy(0, 0, 0))
    assert captured[-1].copy_id not in result.deleted_ids
    assert captured[0].copy_id not in result.deleted_ids
    assert captured[1].copy_id in result.deleted_ids


@pytest.mark.parametrize("stage", ["rename", "directory-sync", "partial-delete", "forget"])
def test_prune_faults_resume_without_deleting_protected_copies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from finjuice.pipeline.storage.sqlite import recovery_store as module

    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    middle = _capture(store, source, expected)
    latest = _capture(store, source, expected)
    bundles = store / "bundles"
    original_sync = module._fsync_directory
    original_remove = module._remove_identity_tree

    def fail(*args, **kwargs):
        raise OSError("Synthetic interrupted prune")

    def sync(path):
        if path == bundles:
            fail()
        original_sync(path)

    def partial(path, identity):
        file = next(child for child in path.rglob("*") if child.is_file())
        file.unlink()
        fail()

    with monkeypatch.context() as failure:
        if stage == "rename":
            failure.setattr(module, "rename_exclusive", fail)
        elif stage == "directory-sync":
            failure.setattr(module, "_fsync_directory", sync)
        elif stage == "partial-delete":
            failure.setattr(module, "_remove_identity_tree", partial)
        else:
            failure.setattr(module, "_forget_intent", fail)
        with pytest.raises(OSError, match="Synthetic"):
            prune_recovery_store(store, expected)
    assert module._remove_identity_tree is original_remove
    assert (bundles / first.copy_id).is_dir()
    assert (bundles / latest.copy_id).is_dir()

    resumed = prune_recovery_store(store, expected)
    repeated = prune_recovery_store(store, expected)
    assert resumed.deleted_ids == (() if stage == "forget" else (middle.copy_id,))
    assert resumed.deleted_count == (0 if stage == "forget" else 1)
    assert repeated.deleted_count == 0
    assert not (bundles / middle.copy_id).exists()
    assert not list(bundles.glob(".tombstone-*"))
    assert not list((store / ".finjuice-recovery-store" / "intents").iterdir())
    assert (bundles / first.copy_id).is_dir()
    assert (bundles / latest.copy_id).is_dir()


def _interrupt_before_rename(store, expected, monkeypatch):
    from finjuice.pipeline.storage.sqlite import recovery_store as module

    def fail(*args):
        raise OSError("Synthetic rename interruption")

    with monkeypatch.context() as failure:
        failure.setattr(module, "rename_exclusive", fail)
        with pytest.raises(OSError, match="Synthetic"):
            prune_recovery_store(store, expected)


def test_protection_after_interrupted_intent_cancels_old_deletion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    _capture(store, source, expected)
    middle = _capture(store, source, expected)
    _capture(store, source, expected)
    _interrupt_before_rename(store, expected, monkeypatch)
    protect_store_copy(store, expected, middle.copy_id)

    prune_recovery_store(store, expected)
    assert (store / "bundles" / middle.copy_id).is_dir()
    assert not list((store / ".finjuice-recovery-store" / "intents").iterdir())


def test_missing_baseline_prevents_tombstone_resume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    _capture(store, source, expected)
    middle = _capture(store, source, expected)
    _capture(store, source, expected)
    _interrupt_before_rename(store, expected, monkeypatch)
    registration = store / ".finjuice-recovery-store" / "registration.json"
    registration.unlink()
    before = (store / "bundles" / middle.copy_id / "recovery-graph.json").read_bytes()

    with pytest.raises(BackupVerificationError):
        prune_recovery_store(store, expected)
    assert (store / "bundles" / middle.copy_id / "recovery-graph.json").read_bytes() == before
    assert list((store / ".finjuice-recovery-store" / "intents").iterdir())


def test_first_registration_failure_cannot_restart_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.storage.sqlite import recovery_store as module

    source, expected, store, *_ = _prepare(tmp_path)

    def fail(*args):
        raise OSError("Synthetic registration failure")

    with monkeypatch.context() as failure:
        failure.setattr(module, "_write_registration", fail)
        with pytest.raises(OSError, match="Synthetic"):
            _capture(store, source, expected)
    copies = list((store / "bundles").iterdir())
    assert len(copies) == 1
    with pytest.raises(BackupVerificationError):
        _capture(store, source, expected)
    with pytest.raises(BackupVerificationError):
        protect_store_copy(store, expected, copies[0].name)
    assert list((store / "bundles").iterdir()) == copies


def test_initialization_syncs_root_parent_before_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.storage.sqlite import recovery_store as module

    source, expected, *_ = _live(tmp_path)
    seen = []
    original = module._fsync_directory

    def sync(path):
        original(path)
        seen.append(path)

    monkeypatch.setattr(module, "_fsync_directory", sync)
    initialize_recovery_store(tmp_path / "new-store", expected)
    assert seen[-1] == tmp_path
    assert source.data_dir.is_dir()


def _reader_gap_hold(store: str, expected_path: str, packed: str, ready, release) -> None:
    from typer.testing import CliRunner

    from finjuice.pipeline.cli.commands import sqlite_recovery_bundle as cli
    from finjuice.pipeline.cli.main import app
    from finjuice.pipeline.storage.sqlite import backup
    from finjuice.pipeline.storage.sqlite.backup_verify import resolve_backup_input

    copy_id, target, mode = packed.split("|", 2)
    bundle = Path(store) / "bundles" / copy_id
    if mode == "cli-gap":
        original = cli.verify_recovery_bundle

        def verified(*args):
            result = original(*args)
            ready.set()
            assert release.wait(30)
            return result

        with patch.object(cli, "verify_recovery_bundle", verified):
            result = CliRunner().invoke(
                app,
                [
                    "--data-dir",
                    str(Path(target).parent / "unused-active"),
                    "ssot",
                    "backup",
                    "restore-bundle",
                    str(bundle),
                    "--expected",
                    expected_path,
                    "--target",
                    target,
                    "--json",
                ],
            )
            assert result.exit_code == 0, result.output
    else:
        attempt, _, _ = resolve_backup_input(bundle / "snapshot")

        def resolve(path):
            ready.set()
            assert release.wait(30)
            return resolve_backup_input(path)

        with patch.object(backup, "resolve_backup_input", resolve):
            backup.read_backup_manifest(attempt)


@pytest.mark.parametrize("mode", ["cli-gap", "manifest"])
def test_existing_reader_holds_lease_across_selection_and_payload_access(
    tmp_path: Path, mode: str
) -> None:
    source, expected, store, *_ = _prepare(tmp_path)
    first = _capture(store, source, expected)
    expected_path = str(_write_expected(tmp_path / "enrolled.json", expected))
    child, release = _spawn(
        _reader_gap_hold,
        (str(store), expected_path, f"{first.copy_id}|{tmp_path / 'restore'}|{mode}"),
    )
    try:
        with pytest.raises(AuthorityConflictError, match="timed out"):
            prune_recovery_store(store, expected, timeout_ms=80)
    finally:
        release.set()
        child.join(15)
        if child.is_alive():
            child.kill()
            child.join(5)
    assert child.exitcode == 0
