"""Strict shared v1 backup receipt and payload verification."""

from __future__ import annotations

import hashlib
import json
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import UUID

from finjuice.pipeline.storage.sqlite.backup_io import (
    BackupPayloadError,
    checked_directories,
    copy_regular_file,  # noqa: F401 — public shared I/O seam
    fingerprint_regular_file,
    read_regular_bytes,
)

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.backup import BackupFileEntry, BackupManifest

MANIFEST_FILENAME = "backup-manifest.json"
POINTER_FILENAME = "backup-current.json"
_KEYS = {
    "schema_version",
    "kind",
    "backup_id",
    "created_at",
    "source_generation",
    "dataset_revision",
    "files",
    "manifest_digest",
}
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_HEX_ID = re.compile(r"[0-9a-f]{32}")


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise BackupPayloadError("incomplete_backup")
        result[key] = value
    return result


def _json(raw: bytes) -> dict[str, Any]:
    try:
        result = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (ValueError, UnicodeError):
        raise BackupPayloadError("incomplete_backup") from None


def _digest(value: Any) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def _validate_header(payload: dict[str, Any]) -> None:
    if (
        set(payload) != _KEYS
        or type(payload["schema_version"]) is not int
        or payload["schema_version"] != 1
    ):
        raise BackupPayloadError("incomplete_backup")
    if payload["kind"] != "finjuice.sqlite.generation-backup":
        raise BackupPayloadError("incomplete_backup")
    if type(payload["dataset_revision"]) is not int or payload["dataset_revision"] < 0:
        raise BackupPayloadError("incomplete_backup")
    try:
        identifier = payload["backup_id"]
        if not isinstance(identifier, str) or not _HEX_ID.fullmatch(identifier):
            raise ValueError
        UUID(identifier)
        generation = payload["source_generation"]
        if str(UUID(generation)) != generation:
            raise ValueError
        timestamp = datetime.fromisoformat(payload["created_at"])
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise BackupPayloadError("incomplete_backup") from None


def _file(raw: Any) -> BackupFileEntry:
    from finjuice.pipeline.storage.sqlite.backup import BackupFileEntry

    if not isinstance(raw, dict) or set(raw) != {"path", "sha256", "byte_length"}:
        raise BackupPayloadError("incomplete_backup")
    path, digest, size = raw["path"], raw["sha256"], raw["byte_length"]
    if not isinstance(path, str) or not _digest(digest) or type(size) is not int or size < 0:
        raise BackupPayloadError("incomplete_backup")
    hex_digest = digest.removeprefix("sha256:")
    if path != "finjuice.sqlite3" and path != f"objects/sha256/{hex_digest[:2]}/{hex_digest}":
        raise BackupPayloadError("incomplete_backup")
    return BackupFileEntry(path, digest, size)


def verify_manifest_bytes(raw: bytes) -> BackupManifest:
    """Parse exact v1 keys, canonical namespace and self-digest; reject duplicate JSON keys."""
    from finjuice.pipeline.storage.sqlite.backup import BackupManifest

    payload = _json(raw)
    _validate_header(payload)
    if not isinstance(payload["files"], list):
        raise BackupPayloadError("incomplete_backup")
    files = tuple(_file(item) for item in payload["files"])
    paths = [entry.path for entry in files]
    if paths != sorted(set(paths)) or paths.count("finjuice.sqlite3") != 1:
        raise BackupPayloadError("incomplete_backup")
    digest = payload["manifest_digest"]
    body = {key: value for key, value in payload.items() if key != "manifest_digest"}
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    if not _digest(digest) or digest != "sha256:" + hashlib.sha256(canonical).hexdigest():
        raise BackupPayloadError("manifest_digest_mismatch")
    return BackupManifest(**{**payload, "files": files})


def _exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False


def resolve_backup_input(path: Path) -> tuple[Path, BackupManifest, str]:
    """Resolve a direct v1 directory or exact current pointer without following links."""
    root = path.expanduser().absolute()
    try:
        checked_directories(root)
        direct, pointer = root / MANIFEST_FILENAME, root / POINTER_FILENAME
        if _exists(direct) and _exists(pointer):
            raise BackupPayloadError("ambiguous_backup_layout")
        if _exists(direct):
            return root, verify_manifest_bytes(read_regular_bytes(direct)), "direct_v1"
        if not _exists(pointer):
            reason = "missing_pointer" if _exists(root / "attempts") else "missing_manifest"
            raise BackupPayloadError(reason)
        return _resolve_pointer(root, read_regular_bytes(pointer))
    except FileNotFoundError:
        raise BackupPayloadError("missing_manifest") from None
    except OSError:
        raise BackupPayloadError("backup_unreadable") from None


def _resolve_pointer(root: Path, raw: bytes) -> tuple[Path, BackupManifest, str]:
    pointer = _json(raw)
    if set(pointer) != {"pointer_schema_version", "attempt_id", "manifest_path", "manifest_digest"}:
        raise BackupPayloadError("invalid_pointer")
    attempt = pointer["attempt_id"]
    if (
        type(pointer["pointer_schema_version"]) is not int
        or pointer["pointer_schema_version"] != 1
        or not isinstance(attempt, str)
        or not _HEX_ID.fullmatch(attempt)
        or pointer["manifest_path"] != f"attempts/{attempt}/{MANIFEST_FILENAME}"
        or not _digest(pointer["manifest_digest"])
    ):
        raise BackupPayloadError("invalid_pointer")
    payload_root = root / "attempts" / attempt
    manifest = verify_manifest_bytes(read_regular_bytes(payload_root / MANIFEST_FILENAME))
    if manifest.manifest_digest != pointer["manifest_digest"]:
        raise BackupPayloadError("pointer_digest_mismatch")
    return payload_root, manifest, "attempt"


def verify_payload(root: Path, manifest: BackupManifest) -> tuple[str, ...]:
    """Verify exact payload tree and unchanged source manifest without opening a database."""
    try:
        checked_directories(root)
        if verify_manifest_bytes(read_regular_bytes(root / MANIFEST_FILENAME)) != manifest:
            raise BackupPayloadError("manifest_changed")
        for entry in manifest.files:
            size, digest = fingerprint_regular_file(root / entry.path)
            if size != entry.byte_length:
                raise BackupPayloadError("payload_size_mismatch")
            if "sha256:" + digest != entry.sha256:
                raise BackupPayloadError("payload_digest_mismatch")
        _verify_tree(root, manifest)
        if verify_manifest_bytes(read_regular_bytes(root / MANIFEST_FILENAME)) != manifest:
            raise BackupPayloadError("manifest_changed")
        return ("manifest_digest", "payload_digests", "exact_payload_tree")
    except OSError:
        raise BackupPayloadError("payload_unreadable") from None


def _verify_tree(root: Path, manifest: BackupManifest) -> None:
    files = {entry.path for entry in manifest.files} | {MANIFEST_FILENAME}
    directories = {"objects", "objects/sha256"}
    directories.update(
        str(Path(entry.path).parent) for entry in manifest.files if entry.role == "object"
    )
    pending = [root]
    observed = set()
    while pending:
        parent = pending.pop()
        checked_directories(parent)
        for path in parent.iterdir():
            relative = path.relative_to(root).as_posix()
            mode = path.lstat().st_mode
            if stat.S_ISDIR(mode) and relative in directories:
                pending.append(path)
            elif stat.S_ISREG(mode) and relative in files:
                observed.add(relative)
            else:
                raise BackupPayloadError("unlisted_payload")
    if observed != files:
        raise BackupPayloadError("payload_missing")
