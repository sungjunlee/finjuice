"""Synthetic tests for legacy complete backup create/verify/restore."""

from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.backup import (
    BackupError,
    ConsistencyEvidence,
    CreateRequest,
    SourceRoot,
    create_backup,
    restore_backup,
    verify_backup,
)
from finjuice.pipeline.backup import io as backup_io
from finjuice.pipeline.backup import ops as backup_ops
from finjuice.pipeline.backup import paths as backup_paths
from finjuice.pipeline.backup.types import MANIFEST_FILENAME

FREEZE = ConsistencyEvidence(kind="stopped_writers", stopped_writers=("cli",))


def _write(path: Path, text: str, mode: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if mode is not None:
        os.chmod(path, mode)


def _build_dataset(root: Path) -> Path:
    source = root / "source"
    _write(source / "transactions" / "2024" / "01" / "transactions.csv", "a,b\n1,2\n")
    _write(source / "exports" / "report.csv", "total,1\n")
    _write(source / "backups" / "partial.txt", "partial")
    (source / "empty_dir").mkdir(parents=True)
    _write(source / ".git" / "HEAD", "ref: refs/heads/unborn\n")
    _write(source / ".git" / "config", "[core]\nbare = false\n")
    _write(source / ".hidden", "hidden-bytes")
    _write(source / "rules.yaml", "version: 1\n", mode=0o640)
    return source


def _request(
    source: Path,
    output: Path,
    extra: tuple[SourceRoot, ...] = (),
) -> CreateRequest:
    return CreateRequest(source=source, output=output, consistency=FREEZE, extra_roots=extra)


def _rewrite_manifest(output: Path, manifest: dict[str, Any]) -> None:
    from finjuice.pipeline.backup.manifest import compute_manifest_digest

    manifest["canonical_digest"] = compute_manifest_digest(manifest)
    (output / MANIFEST_FILENAME).write_text(json.dumps(manifest), encoding="utf-8")
    (output / "FINJUICE_BACKUP_COMPLETE").write_text(
        manifest["canonical_digest"] + "\n", encoding="utf-8"
    )


def test_create_verify_restore_full_roots(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("overlay: true\n", encoding="utf-8")
    output = tmp_path / "backup"
    result = create_backup(
        _request(
            source,
            output,
            extra=(
                SourceRoot(name="overlay", presence="required", path=overlay),
                SourceRoot(name="image_cache", presence="optional", path=None),
            ),
        )
    )

    assert result.status == "ok"
    verified = verify_backup(output / MANIFEST_FILENAME)
    assert verified.manifest_digest == result.manifest_digest
    assert verified.absent_optional_count == 1

    target = tmp_path / "restored"
    restored = restore_backup(output / MANIFEST_FILENAME, target, active_data_dir=source)
    assert restored.generation_status == "inactive"
    assert (target / "generation.json").read_text(encoding="utf-8")
    assert (target / "data" / "empty_dir").is_dir()
    assert (target / "data" / ".git" / "HEAD").read_text(encoding="utf-8") == (
        source / ".git" / "HEAD"
    ).read_text(encoding="utf-8")
    assert (target / "data" / ".hidden").read_bytes() == (source / ".hidden").read_bytes()
    assert (target / "data" / "rules.yaml").read_bytes() == (source / "rules.yaml").read_bytes()
    assert stat.S_IMODE((target / "data" / "rules.yaml").stat().st_mode) == 0o640
    assert (target / "roots" / "overlay").read_bytes() == overlay.read_bytes()
    assert not (target / "roots" / "image_cache").exists()
    assert json.loads((target / "generation.json").read_text(encoding="utf-8"))["status"] == (
        "inactive"
    )


def test_create_retry_already_complete_leaves_source(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    first = create_backup(_request(source, output))
    before = (source / "rules.yaml").read_bytes()
    second = create_backup(_request(source, output))
    assert second.status == "already_complete"
    assert second.manifest_digest == first.manifest_digest
    assert (source / "rules.yaml").read_bytes() == before


def test_source_content_change_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    real_copy = backup_io.copy_inventory

    def mutate(*args: Any, **kwargs: Any) -> None:
        (source / "rules.yaml").write_text("changed\n", encoding="utf-8")
        real_copy(*args, **kwargs)

    monkeypatch.setattr(backup_io, "copy_inventory", mutate)
    monkeypatch.setattr("finjuice.pipeline.backup.ops.copy_inventory", mutate)
    with pytest.raises(BackupError, match="Source changed"):
        create_backup(_request(source, output))
    assert not output.exists()


def test_source_add_and_remove_during_capture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup-add"
    real_copy = backup_io.copy_inventory

    def add_file(*args: Any, **kwargs: Any) -> None:
        (source / "added.txt").write_text("new\n", encoding="utf-8")
        real_copy(*args, **kwargs)

    monkeypatch.setattr("finjuice.pipeline.backup.ops.copy_inventory", add_file)
    with pytest.raises(BackupError, match="Source changed"):
        create_backup(_request(source, output))

    output_remove = tmp_path / "backup-remove"

    def remove_file(*args: Any, **kwargs: Any) -> None:
        (source / "rules.yaml").unlink()
        real_copy(*args, **kwargs)

    monkeypatch.setattr("finjuice.pipeline.backup.ops.copy_inventory", remove_file)
    with pytest.raises(BackupError, match="Source changed"):
        create_backup(_request(source, output_remove))


def test_symlink_root_and_descendant_rejected(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    linked = tmp_path / "linked-source"
    linked.symlink_to(source)
    with pytest.raises(BackupError, match="symlink"):
        create_backup(_request(linked, tmp_path / "backup"))

    (source / "link-out").symlink_to(source / "rules.yaml")
    with pytest.raises(BackupError, match="Symlinks"):
        create_backup(_request(source, tmp_path / "backup2"))


def test_symlink_ancestor_rejected(tmp_path: Path) -> None:
    real_parent = tmp_path / "real"
    real_parent.mkdir()
    alias = tmp_path / "alias"
    alias.symlink_to(real_parent)
    source = _build_dataset(real_parent)
    with pytest.raises(BackupError, match="symlink"):
        create_backup(_request(alias / "source", tmp_path / "backup"))
    _ = source


def test_special_file_rejected(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    fifo = source / "pipe"
    os.mkfifo(fifo)
    with pytest.raises(BackupError, match="Special files"):
        create_backup(_request(source, tmp_path / "backup"))


def test_output_overlap_and_duplicate_roots(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    with pytest.raises(BackupError, match="overlap"):
        create_backup(_request(source, source / "nested-backup"))
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("x\n", encoding="utf-8")
    with pytest.raises(BackupError, match="Duplicate"):
        create_backup(
            _request(
                source,
                tmp_path / "backup",
                extra=(
                    SourceRoot(name="overlay", presence="required", path=overlay),
                    SourceRoot(name="overlay", presence="required", path=overlay),
                ),
            )
        )


def test_required_root_missing_is_never_skipped(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    with pytest.raises(BackupError, match="required external root is missing"):
        create_backup(
            _request(
                source,
                tmp_path / "backup",
                extra=(
                    SourceRoot(
                        name="journal",
                        presence="required",
                        path=tmp_path / "missing-journal",
                    ),
                ),
            )
        )
    assert not (tmp_path / "backup").exists()


def test_sqlite_unsupported(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    (source / "finjuice.sqlite3").write_bytes(b"SQLite format 3\x00")
    with pytest.raises(BackupError, match="SQLite"):
        create_backup(_request(source, tmp_path / "backup"))


def test_secret_file_refused(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    (source / ".env").write_text("TOKEN=1\n", encoding="utf-8")
    with pytest.raises(BackupError, match="secret"):
        create_backup(_request(source, tmp_path / "backup"))


def test_insufficient_space_and_enospc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"

    class Usage:
        free = 1
        total = 1
        used = 0

    monkeypatch.setattr(shutil, "disk_usage", lambda _path: Usage())
    with pytest.raises(BackupError, match="Insufficient disk space"):
        create_backup(_request(source, output))
    assert not output.exists()

    monkeypatch.setattr(
        shutil,
        "disk_usage",
        lambda _path: type("U", (), {"free": 10**12, "total": 10**12, "used": 0})(),
    )

    def boom(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("finjuice.pipeline.backup.ops.copy_inventory", boom)
    with pytest.raises(BackupError, match="Backup I/O failed|Disk is full"):
        create_backup(_request(source, tmp_path / "backup-enospc"))
    leftovers = list(tmp_path.glob(".finjuice-backup-staging-*"))
    assert leftovers == []


def test_tampered_and_malicious_manifests(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    manifest_path = output / MANIFEST_FILENAME
    original = json.loads(manifest_path.read_text(encoding="utf-8"))

    (output / "FINJUICE_BACKUP_COMPLETE").unlink()
    with pytest.raises(BackupError, match="completion marker"):
        verify_backup(manifest_path)
    (output / "FINJUICE_BACKUP_COMPLETE").write_text(original["canonical_digest"] + "\n")

    tampered = dict(original)
    tampered["canonical_digest"] = "sha256:" + ("ab" * 32)
    manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(BackupError, match="digest"):
        verify_backup(manifest_path)
    manifest_path.write_text(json.dumps(original), encoding="utf-8")

    payload_file = output / "payload" / "data" / "rules.yaml"
    payload_file.write_text("tampered\n", encoding="utf-8")
    with pytest.raises(BackupError, match="hash or size"):
        verify_backup(manifest_path)
    payload_file.write_bytes((source / "rules.yaml").read_bytes())
    rules_entry = next(
        entry
        for entry in original["entries"]
        if entry["root"] == "data" and entry["path"] == "rules.yaml"
    )
    os.utime(payload_file, ns=(rules_entry["mtime_ns"], rules_entry["mtime_ns"]))

    extra = output / "payload" / "data" / "extra.txt"
    extra.write_text("extra\n", encoding="utf-8")
    with pytest.raises(BackupError, match="conflict|metadata"):
        verify_backup(manifest_path)
    extra.unlink()
    missing = output / "payload" / "data" / "rules.yaml"
    missing.unlink()
    with pytest.raises(BackupError, match="conflict|missing|hash|metadata"):
        verify_backup(manifest_path)
    missing.write_bytes((source / "rules.yaml").read_bytes())
    os.utime(missing, ns=(rules_entry["mtime_ns"], rules_entry["mtime_ns"]))

    unknown = dict(original)
    unknown["schema_version"] = "finjuice.backup.v9"
    unknown.pop("canonical_digest")
    from finjuice.pipeline.backup.manifest import compute_manifest_digest

    unknown["canonical_digest"] = compute_manifest_digest(unknown)
    (output / "FINJUICE_BACKUP_COMPLETE").write_text(unknown["canonical_digest"] + "\n")
    manifest_path.write_text(json.dumps(unknown), encoding="utf-8")
    with pytest.raises(BackupError, match="Unsupported"):
        verify_backup(manifest_path)


@pytest.mark.parametrize(
    "bad_path",
    ["/etc/passwd", "../escape", "C:\\windows", "foo\\bar", "nul\x00name"],
)
def test_malicious_portable_paths(tmp_path: Path, bad_path: str) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    manifest_path = output / MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["entries"][0]["path"] = bad_path
    from finjuice.pipeline.backup.manifest import compute_manifest_digest

    manifest["canonical_digest"] = compute_manifest_digest(manifest)
    (output / "FINJUICE_BACKUP_COMPLETE").write_text(manifest["canonical_digest"] + "\n")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(BackupError, match="unsafe path|Unsupported|invalid"):
        verify_backup(manifest_path)


def test_restore_safeguards(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    manifest = output / MANIFEST_FILENAME

    nonempty = tmp_path / "nonempty"
    nonempty.mkdir()
    (nonempty / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(BackupError, match="not empty"):
        restore_backup(manifest, nonempty, active_data_dir=source)
    assert (nonempty / "keep.txt").read_text(encoding="utf-8") == "x"

    file_target = tmp_path / "file-target"
    file_target.write_text("nope", encoding="utf-8")
    with pytest.raises(BackupError, match="empty directory"):
        restore_backup(manifest, file_target, active_data_dir=source)

    link_target = tmp_path / "link-target"
    link_target.symlink_to(tmp_path / "missing")
    with pytest.raises(BackupError, match="symlink"):
        restore_backup(manifest, link_target, active_data_dir=source)

    with pytest.raises(BackupError, match="overlap"):
        restore_backup(manifest, output / "inside", active_data_dir=source)

    empty = tmp_path / "empty"
    empty.mkdir()
    restored = restore_backup(manifest, empty, active_data_dir=source)
    assert restored.status == "ok"
    assert (empty / "data" / "rules.yaml").is_file()


def test_restore_rejects_active_data_dir(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    with pytest.raises(BackupError, match="overlap"):
        restore_backup(output / MANIFEST_FILENAME, source, active_data_dir=source)


def test_program_repo_rejected() -> None:
    repo = Path(__file__).resolve().parents[2]
    with pytest.raises(BackupError, match="program repository"):
        create_backup(_request(repo, Path("/tmp/finjuice-backup-should-not-exist")))


def test_existing_conflict_when_source_changed(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    (source / "rules.yaml").write_text("later\n", encoding="utf-8")
    with pytest.raises(BackupError, match="does not match this input"):
        create_backup(_request(source, output))
    assert (output / MANIFEST_FILENAME).is_file()


def test_short_writes_are_completed_before_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    real_write = os.write

    def short_write(fd: int, data: bytes) -> int:
        return real_write(fd, data[: max(1, len(data) // 2)])

    monkeypatch.setattr(os, "write", short_write)
    result = create_backup(_request(source, output))
    verified = verify_backup(output)
    assert verified.manifest_digest == result.manifest_digest
    assert (output / "payload/data/rules.yaml").read_bytes() == (source / "rules.yaml").read_bytes()


def test_restore_publish_failure_preserves_existing_empty_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    target = tmp_path / "restored"
    target.mkdir(mode=0o750)
    before = target.stat()

    def fail_rename(*_args: Any, **_kwargs: Any) -> None:
        raise OSError(5, "synthetic I/O error")

    monkeypatch.setattr(os, "rename", fail_rename)
    with pytest.raises(BackupError):
        restore_backup(output, target, active_data_dir=source)
    assert target.is_dir()
    assert list(target.iterdir()) == []
    assert target.stat().st_ino == before.st_ino
    assert target.stat().st_mode == before.st_mode
    assert not list(tmp_path.glob(".finjuice-backup-staging-*"))


def test_new_output_appearing_during_capture_is_not_replaced(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    real_copy = backup_io.copy_inventory
    created: list[int] = []

    def create_racing_output(*args: Any, **kwargs: Any) -> None:
        real_copy(*args, **kwargs)
        output.mkdir(mode=0o750)
        created.append(output.stat().st_ino)

    monkeypatch.setattr("finjuice.pipeline.backup.ops.copy_inventory", create_racing_output)
    with pytest.raises(BackupError, match="already exists"):
        create_backup(_request(source, output))
    assert list(output.iterdir()) == []
    assert output.stat().st_ino == created[0]


def test_restore_reuses_the_manifest_object_that_was_verified(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    real_load = backup_ops.load_manifest
    calls = 0

    def changed_second_read(path: Path) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        manifest = real_load(path)
        if calls > 1:
            manifest["entries"] = []
            manifest["entry_count"] = 0
            manifest["file_count"] = 0
            manifest["directory_count"] = 0
            manifest["byte_count"] = 0
        return manifest

    monkeypatch.setattr(backup_ops, "load_manifest", changed_second_read)
    target = tmp_path / "restored"
    restored = restore_backup(output, target, active_data_dir=tmp_path / "active")

    assert restored.status == "ok"
    assert calls == 1
    assert (target / "data" / "rules.yaml").is_file()


def test_dot_segment_alias_cannot_restore_inside_active_data(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    (tmp_path / "alias").mkdir()
    target = tmp_path / "alias" / ".." / "source" / "restored"

    with pytest.raises(BackupError, match="overlap"):
        restore_backup(output, target, active_data_dir=source)
    assert not (source / "restored").exists()


def test_backend_rejects_unsafe_source_root_name(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    external = tmp_path / "external.txt"
    external.write_text("external", encoding="utf-8")
    escaped = tmp_path / "escaped-file"

    with pytest.raises(BackupError, match="Invalid source-root name"):
        create_backup(
            _request(
                source,
                tmp_path / "backup",
                extra=(SourceRoot("../../../escaped-file", "required", external),),
            )
        )
    assert not escaped.exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "empty_present_root",
        "unknown_entry_root",
        "wrong_counts",
        "bad_file_digest",
        "bad_directory_size",
        "bad_mode",
    ],
)
def test_manifest_rejects_broken_root_entry_closure(tmp_path: Path, mutation: str) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    manifest = json.loads((output / MANIFEST_FILENAME).read_text(encoding="utf-8"))

    if mutation == "empty_present_root":
        manifest["entries"] = []
        manifest["entry_count"] = 0
        manifest["file_count"] = 0
        manifest["directory_count"] = 0
        manifest["byte_count"] = 0
        shutil.rmtree(output / "payload")
    elif mutation == "unknown_entry_root":
        manifest["entries"][0]["root"] = "undeclared"
    elif mutation == "wrong_counts":
        manifest["byte_count"] += 1
    elif mutation == "bad_file_digest":
        file_entry = next(entry for entry in manifest["entries"] if entry["type"] == "file")
        file_entry["sha256"] = None
    elif mutation == "bad_directory_size":
        directory = next(entry for entry in manifest["entries"] if entry["type"] == "directory")
        directory["size"] = 1
    else:
        manifest["entries"][0]["mode"] = "not-octal"
    _rewrite_manifest(output, manifest)

    with pytest.raises(BackupError, match="manifest|root|count|entry"):
        verify_backup(output)


def test_fsync_directory_propagates_real_io_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(_fd: int) -> None:
        raise OSError(5, "synthetic I/O error")

    monkeypatch.setattr(backup_io, "fsync_fd", fail)
    with pytest.raises(OSError) as caught:
        backup_io.fsync_directory(tmp_path)
    assert caught.value.errno == 5


def test_read_only_directory_modes_are_applied_after_copy(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    readonly = source / "readonly"
    readonly.mkdir()
    (readonly / "inside.txt").write_text("preserved", encoding="utf-8")
    readonly.chmod(0o555)

    output = tmp_path / "backup"
    create_backup(_request(source, output))
    assert stat.S_IMODE((output / "payload/data/readonly").stat().st_mode) == 0o555
    assert (output / "payload/data/readonly/inside.txt").read_text() == "preserved"

    target = tmp_path / "restored"
    restore_backup(output, target, active_data_dir=tmp_path / "active")
    assert stat.S_IMODE((target / "data/readonly").stat().st_mode) == 0o555
    assert (target / "data/readonly/inside.txt").read_text() == "preserved"


def test_file_and_directory_mtime_ns_round_trip(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    rules = source / "rules.yaml"
    transactions = source / "transactions"
    file_mtime = 1_600_000_000_123_456_789
    directory_mtime = 1_600_000_100_987_654_321
    os.utime(rules, ns=(file_mtime, file_mtime))
    os.utime(transactions, ns=(directory_mtime, directory_mtime))

    output = tmp_path / "backup"
    create_backup(_request(source, output))
    target = tmp_path / "restored"
    restore_backup(output, target, active_data_dir=tmp_path / "active")

    assert (output / "payload/data/rules.yaml").stat().st_mtime_ns == file_mtime
    assert (target / "data/rules.yaml").stat().st_mtime_ns == file_mtime
    assert (output / "payload/data/transactions").stat().st_mtime_ns == directory_mtime
    assert (target / "data/transactions").stat().st_mtime_ns == directory_mtime


@pytest.mark.parametrize(
    "first,second",
    [
        (
            ConsistencyEvidence(kind="stopped_writers", stopped_writers=("cli",)),
            ConsistencyEvidence(kind="stopped_writers", stopped_writers=("scheduler",)),
        ),
        (
            ConsistencyEvidence(kind="named_snapshot", snapshot_name="snapshot-a"),
            ConsistencyEvidence(kind="named_snapshot", snapshot_name="snapshot-b"),
        ),
    ],
)
def test_retry_requires_identical_consistency_evidence(
    tmp_path: Path, first: ConsistencyEvidence, second: ConsistencyEvidence
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(CreateRequest(source, output, first))

    with pytest.raises(BackupError, match="does not match this input"):
        create_backup(CreateRequest(source, output, second))


@pytest.mark.parametrize(
    ("raw", "expected_version", "expected_status"),
    [("2\n", 2, "present"), (None, None, "missing"), ("private-value\n", None, "invalid")],
)
def test_manifest_records_frozen_source_schema_version(
    tmp_path: Path,
    raw: str | None,
    expected_version: int | None,
    expected_status: str,
) -> None:
    source = _build_dataset(tmp_path)
    if raw is not None:
        _write(source / "metadata/schema_version", raw)
    output = tmp_path / "backup"

    result = create_backup(_request(source, output))
    manifest = json.loads((output / MANIFEST_FILENAME).read_text(encoding="utf-8"))

    assert result.data_schema_version == expected_version
    assert result.data_schema_version_status == expected_status
    assert manifest["data_schema_version"] == expected_version
    assert manifest["data_schema_version_status"] == expected_status


def test_verify_recomputes_schema_evidence_from_payload(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    _write(source / "metadata/schema_version", "2\n")
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    manifest = json.loads((output / MANIFEST_FILENAME).read_text(encoding="utf-8"))
    manifest["data_schema_version"] = None
    manifest["data_schema_version_status"] = "missing"
    _rewrite_manifest(output, manifest)

    with pytest.raises(BackupError, match="schema evidence"):
        verify_backup(output)


@pytest.mark.parametrize("wrapper", ["manifest", "payload"])
def test_manifest_and_payload_wrapper_symlinks_are_rejected(tmp_path: Path, wrapper: str) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    if wrapper == "manifest":
        original = output / MANIFEST_FILENAME
        moved = tmp_path / "moved-manifest.json"
    else:
        original = output / "payload"
        moved = tmp_path / "moved-payload"
    original.rename(moved)
    original.symlink_to(moved)

    with pytest.raises(BackupError, match="symlink"):
        verify_backup(output)


def test_program_repo_guard_does_not_depend_on_running_from_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_repo = tmp_path / "finjuice-checkout"
    (fake_repo / ".git").mkdir(parents=True)
    (fake_repo / "src/finjuice").mkdir(parents=True)
    (fake_repo / "pyproject.toml").write_text("[project]\nname='finjuice'\n", encoding="utf-8")
    monkeypatch.setattr(backup_paths, "is_inside_program_repo", lambda _path: False)
    monkeypatch.setattr(backup_paths, "validate_not_program_repo_path", lambda *_a, **_kw: None)

    with pytest.raises(BackupError, match="program repository"):
        backup_paths.require_outside_program_repo(fake_repo / "new-backup", context="backup")


def test_capture_lineage_is_preserved_and_required_for_retry(tmp_path: Path) -> None:
    from datetime import datetime

    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    parent = "a" * 32
    request = CreateRequest(source, output, FREEZE, parent_attempt_id=parent)
    create_backup(request)
    manifest = json.loads((output / MANIFEST_FILENAME).read_text())
    capture = manifest["capture"]
    assert capture["parent_attempt_id"] == parent
    assert len(capture["attempt_id"]) == 32
    assert datetime.fromisoformat(capture["started_at"]) <= datetime.fromisoformat(
        capture["completed_at"]
    )
    assert create_backup(request).status == "already_complete"
    with pytest.raises(BackupError, match="lineage"):
        create_backup(_request(source, output))


def test_invalid_parent_attempt_fails_before_creating_output(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    with pytest.raises(BackupError, match="identifier"):
        create_backup(CreateRequest(source, output, FREEZE, parent_attempt_id="../invalid"))
    assert not output.exists()


@pytest.mark.parametrize("invalid_capture", [None, {}, {"attempt_id": "x" * 32}])
def test_missing_or_invalid_capture_evidence_is_rejected(
    tmp_path: Path, invalid_capture: Any
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    manifest = json.loads((output / MANIFEST_FILENAME).read_text())
    manifest["capture"] = invalid_capture
    _rewrite_manifest(output, manifest)
    with pytest.raises(BackupError):
        verify_backup(output)


def test_retry_does_not_hide_a_publication_fsync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import errno

    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    original = backup_io.fsync_directory

    def fail_parent(path: Path) -> None:
        if path == output.parent:
            raise OSError(errno.EIO, "synthetic directory sync failure")
        original(path)

    monkeypatch.setattr(backup_io, "fsync_directory", fail_parent)
    with pytest.raises(BackupError):
        create_backup(_request(source, output))
    assert output.exists()
    with pytest.raises(BackupError):
        create_backup(_request(source, output))
    monkeypatch.setattr(backup_io, "fsync_directory", original)
    assert create_backup(_request(source, output)).status == "already_complete"


def test_new_output_parent_chain_is_flushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "new" / "nested" / "backup"
    flushed = []
    original = backup_io.fsync_directory

    def record(path: Path) -> None:
        flushed.append(path)
        original(path)

    monkeypatch.setattr(backup_io, "fsync_directory", record)
    create_backup(_request(source, output))
    assert output.parent in flushed
    assert output.parent.parent in flushed
    assert tmp_path in flushed


@pytest.mark.parametrize("protected_root", ["source", "backup"])
def test_case_alias_cannot_restore_inside_a_protected_tree(
    tmp_path: Path, protected_root: str
) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    alias = tmp_path / protected_root.upper()
    if not alias.exists():
        pytest.skip("Filesystem distinguishes path case")
    assert alias.samefile(tmp_path / protected_root)

    with pytest.raises(BackupError, match="overlap"):
        restore_backup(output, alias / "restored", active_data_dir=source)
    assert not (tmp_path / protected_root / "restored").exists()


def test_case_alias_cannot_create_a_backup_inside_source(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    alias = tmp_path / "SOURCE"
    if not alias.exists():
        pytest.skip("Filesystem distinguishes path case")

    with pytest.raises(BackupError, match="overlap"):
        create_backup(_request(source, alias / "backup"))
    assert not (source / "backup").exists()


def test_distinct_paths_to_the_same_file_overlap(tmp_path: Path) -> None:
    original = tmp_path / "original"
    original.write_text("synthetic bytes")
    alias = tmp_path / "alias"
    alias.hardlink_to(original)

    with pytest.raises(BackupError, match="overlap"):
        backup_paths.reject_overlap(original, alias)


def test_restore_requires_an_explicit_active_data_boundary(tmp_path: Path) -> None:
    source = _build_dataset(tmp_path)
    output = tmp_path / "backup"
    create_backup(_request(source, output))
    with pytest.raises(TypeError, match="active_data_dir"):
        restore_backup(output, source / "restored")  # type: ignore[call-arg]
    with pytest.raises(BackupError, match="Active data directory"):
        restore_backup(output, source / "restored", active_data_dir=None)  # type: ignore[arg-type]
    assert not (source / "restored").exists()


@pytest.mark.parametrize("operation", ["create", "restore"])
def test_failure_cleans_readonly_staging_without_changing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    source = _build_dataset(tmp_path)
    readonly = source / "readonly"
    _write(readonly / "inside.txt", "private synthetic bytes")
    readonly.chmod(0o555)
    before = readonly.stat()
    output = tmp_path / "backup"

    def fail(*_args: Any, **_kwargs: Any) -> None:
        raise BackupError("synthetic failure", code="FILE_ACCESS_ERROR")

    try:
        if operation == "create":
            monkeypatch.setattr(backup_ops, "_write_manifest_and_marker", fail)
            with pytest.raises(BackupError, match="synthetic failure"):
                create_backup(_request(source, output))
            assert not output.exists()
        else:
            create_backup(_request(source, output))
            monkeypatch.setattr(backup_ops, "atomic_publish", fail)
            target = tmp_path / "restored"
            with pytest.raises(BackupError, match="synthetic failure"):
                restore_backup(output, target, active_data_dir=source)
            assert not target.exists()
            assert verify_backup(output).status == "ok"
        assert not list(tmp_path.glob(".finjuice-backup-staging-*"))
        assert readonly.stat().st_mode == before.st_mode
        assert readonly.stat().st_mtime_ns == before.st_mtime_ns
        assert (readonly / "inside.txt").read_text() == "private synthetic bytes"
    finally:
        readonly.chmod(0o755)
        if output.exists():
            (output / "payload/data/readonly").chmod(0o755)
