"""Strict backup receipts, exact inventories and descriptor-safe I/O."""

import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.storage.sqlite import backup_io
from finjuice.pipeline.storage.sqlite.backup_verify import (
    BackupPayloadError,
    copy_regular_file,
    fingerprint_regular_file,
    read_regular_bytes,
    resolve_backup_input,
    verify_manifest_bytes,
    verify_payload,
)


def _encoded(payload):
    body = {k: v for k, v in payload.items() if k != "manifest_digest"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return json.dumps(
        {**body, "manifest_digest": "sha256:" + hashlib.sha256(canonical).hexdigest()}
    ).encode()


def _backup(root: Path):
    root.mkdir(parents=True)
    data = b"synthetic database"
    (root / "finjuice.sqlite3").write_bytes(data)
    payload = {
        "schema_version": 1,
        "kind": "finjuice.sqlite.generation-backup",
        "backup_id": uuid4().hex,
        "created_at": "2026-09-14T00:00:00+00:00",
        "source_generation": str(uuid4()),
        "dataset_revision": 0,
        "files": [
            {
                "path": "finjuice.sqlite3",
                "sha256": "sha256:" + hashlib.sha256(data).hexdigest(),
                "byte_length": len(data),
            }
        ],
    }
    raw = _encoded(payload)
    (root / "backup-manifest.json").write_bytes(raw)
    return verify_manifest_bytes(raw)


def test_direct_and_pointer_roundtrip(tmp_path: Path) -> None:
    attempt = uuid4().hex
    root = tmp_path / "container"
    payload = root / "attempts" / attempt
    manifest = _backup(payload)
    pointer = {
        "pointer_schema_version": 1,
        "attempt_id": attempt,
        "manifest_path": f"attempts/{attempt}/backup-manifest.json",
        "manifest_digest": manifest.manifest_digest,
    }
    (root / "backup-current.json").write_text(json.dumps(pointer))
    assert resolve_backup_input(root) == (payload, manifest, "attempt")
    assert resolve_backup_input(payload) == (payload, manifest, "direct_v1")
    assert "exact_payload_tree" in verify_payload(payload, manifest)
    (payload / "objects/sha256").mkdir(parents=True)
    verify_payload(payload, manifest)
    (root / "backup-manifest.json").write_bytes((payload / "backup-manifest.json").read_bytes())
    with pytest.raises(BackupPayloadError, match="ambiguous_backup_layout"):
        resolve_backup_input(root)


@pytest.mark.parametrize(
    "change",
    ["unknown", "duplicate", "unsorted", "objectpath", "boolean", "id", "time", "selfhash"],
)
def test_strict_manifest_rejections(tmp_path: Path, change: str) -> None:
    root = tmp_path / "backup"
    _backup(root)
    payload = json.loads((root / "backup-manifest.json").read_bytes())
    if change == "unknown":
        payload["extra"] = 1
    elif change == "duplicate":
        payload["files"] *= 2
    elif change in {"unsorted", "objectpath"}:
        digest = "1" * 64
        entry = {
            "path": f"objects/sha256/11/{digest}",
            "sha256": "sha256:" + digest,
            "byte_length": 0,
        }
        if change == "objectpath":
            entry["path"] = "objects/arbitrary"
        payload["files"].insert(0, entry)
    elif change == "boolean":
        payload["dataset_revision"] = True
    elif change == "id":
        payload["backup_id"] = "bad"
    elif change == "time":
        payload["created_at"] = "2026-09-14"
    else:
        payload["manifest_digest"] = "sha256:" + "0" * 64
    raw = json.dumps(payload).encode() if change == "selfhash" else _encoded(payload)
    with pytest.raises(BackupPayloadError):
        verify_manifest_bytes(raw)


def test_duplicate_json_keys_rejected(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    _backup(root)
    raw = (root / "backup-manifest.json").read_bytes()
    with pytest.raises(BackupPayloadError):
        verify_manifest_bytes(raw.replace(b"{", b'{"schema_version":1,', 1))


@pytest.mark.parametrize(
    "defect,reason",
    [
        ("missing", "payload_missing"),
        ("size", "payload_size_mismatch"),
        ("digest", "payload_digest_mismatch"),
        ("extra", "unlisted_payload"),
        ("dir", "unlisted_payload"),
    ],
)
def test_payload_stable_reasons(tmp_path: Path, defect: str, reason: str) -> None:
    root = tmp_path / "backup"
    manifest = _backup(root)
    database = root / "finjuice.sqlite3"
    if defect == "missing":
        database.unlink()
    elif defect == "size":
        database.write_bytes(b"x")
    elif defect == "digest":
        database.write_bytes(b"x" * database.stat().st_size)
    elif defect == "extra":
        (root / "extra").write_bytes(b"x")
    else:
        (root / "extra").mkdir()
    with pytest.raises(BackupPayloadError) as caught:
        verify_payload(root, manifest)
    assert caught.value.reason == reason


def test_manifest_change_and_pointer_escape(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    manifest = _backup(root)
    raw = json.loads((root / "backup-manifest.json").read_bytes())
    raw["dataset_revision"] = 1
    (root / "backup-manifest.json").write_bytes(_encoded(raw))
    with pytest.raises(BackupPayloadError, match="manifest_changed"):
        verify_payload(root, manifest)
    (root / "backup-manifest.json").unlink()
    (root / "backup-current.json").write_text(
        json.dumps(
            {
                "pointer_schema_version": 1,
                "attempt_id": uuid4().hex,
                "manifest_path": "../bad",
                "manifest_digest": manifest.manifest_digest,
            }
        )
    )
    with pytest.raises(BackupPayloadError, match="invalid_pointer"):
        resolve_backup_input(root)


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_nonregular_is_rejected_before_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    path = tmp_path / "special"
    if kind == "fifo":
        os.mkfifo(path)
    else:
        path.symlink_to(tmp_path / "missing")

    def forbidden(*args, **kwargs):
        pytest.fail("nonregular file must not be opened")

    monkeypatch.setattr(os, "open", forbidden)
    with pytest.raises(BackupPayloadError, match="unsafe_file"):
        read_regular_bytes(path)


def test_copy_handles_partial_writes_and_does_not_clobber(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"abcdef" * 100)
    original = os.write
    monkeypatch.setattr(os, "write", lambda fd, chunk: original(fd, chunk[:3]))
    assert copy_regular_file(source, target) == fingerprint_regular_file(source)
    assert target.read_bytes() == source.read_bytes()
    with pytest.raises(BackupPayloadError):
        copy_regular_file(source, target)
    assert target.read_bytes() == source.read_bytes()


def test_changed_source_fails_and_owned_copy_cleans_up(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"abcdef")
    original = backup_io._write_all

    def mutate(fd, chunk):
        original(fd, chunk)
        source.write_bytes(b"changed")

    monkeypatch.setattr(backup_io, "_write_all", mutate)
    with pytest.raises(BackupPayloadError):
        copy_regular_file(source, target)
    assert not target.exists()


def test_exact_object_digest_namespace(tmp_path: Path) -> None:
    root = tmp_path / "backup"
    _backup(root)
    raw = json.loads((root / "backup-manifest.json").read_bytes())
    content = b"synthetic object"
    digest = hashlib.sha256(content).hexdigest()
    relative = f"objects/sha256/{digest[:2]}/{digest}"
    target = root / relative
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    raw["files"].append(
        {"path": relative, "sha256": "sha256:" + digest, "byte_length": len(content)}
    )
    encoded = _encoded(raw)
    (root / "backup-manifest.json").write_bytes(encoded)
    verify_payload(root, verify_manifest_bytes(encoded))
    raw["files"][-1]["sha256"] = "sha256:" + "1" * 64
    with pytest.raises(BackupPayloadError):
        verify_manifest_bytes(_encoded(raw))


def test_symlink_ancestor_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    (real / "file").write_bytes(b"content")
    alias = tmp_path / "alias"
    alias.symlink_to(real, target_is_directory=True)
    with pytest.raises(BackupPayloadError, match="unsafe_path"):
        read_regular_bytes(alias / "file")


def test_zero_write_fails_with_owned_cleanup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    source.write_bytes(b"content")
    monkeypatch.setattr(os, "write", lambda *args: 0)
    with pytest.raises(BackupPayloadError):
        copy_regular_file(source, target)
    assert not target.exists()


def test_replaced_file_during_read_is_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source"
    source.write_bytes(b"content")
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"content")
    original = os.read
    changed = False

    def replace_during_read(fd, count):
        nonlocal changed
        result = original(fd, count)
        if not changed:
            replacement.replace(source)
            changed = True
        return result

    monkeypatch.setattr(os, "read", replace_during_read)
    with pytest.raises(BackupPayloadError, match="payload_changed"):
        fingerprint_regular_file(source)
