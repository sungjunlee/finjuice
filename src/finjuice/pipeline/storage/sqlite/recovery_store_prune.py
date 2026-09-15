"""Tombstone and prune helpers for an initialized recovery-graph store.

Owns deletion intents, tombstone resume, identity-checked tree removal, and
intent-document parsing. Public names stay importable from
:mod:`finjuice.pipeline.storage.sqlite.recovery_store`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finjuice.pipeline.backup.retention import RetentionPlan
from finjuice.pipeline.storage.sqlite.backup_io import checked_directories, read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.recovery_store_lock import is_copy_id

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.recovery_store import (
        RecoveryGraphStore,
        StoreInventoryReceipt,
    )

_ERROR = "Local recovery store operation could not be verified."
_INTENTS = "intents"
_TOMBSTONE = ".tombstone-"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_INTENT_KIND = "finjuice.sqlite.local-recovery-tombstone"
_INTENT_KEYS = {
    "schema_version",
    "kind",
    "intent_id",
    "copy_id",
    "st_dev",
    "st_ino",
    "graph_digest",
    "created_at",
}


def _apply_deletions(
    store: RecoveryGraphStore,
    inventory: StoreInventoryReceipt,
    planned: RetentionPlan,
    held_originals: set[str],
) -> list[str]:
    from finjuice.pipeline.storage.sqlite.recovery_store import _inspect_copy

    protected = set(planned.protected_ids)
    latest = planned.latest_healthy_id
    healthy = {item.copy_id: item for item in inventory.copies if item.health == "healthy"}
    deleted: list[str] = []
    for copy_id in planned.delete_ids:
        if copy_id in held_originals:
            continue
        if copy_id in protected or copy_id == latest:
            raise BackupVerificationError(_ERROR)
        item = healthy.get(copy_id)
        if item is None or item.created_at is None or item.graph_digest is None:
            raise BackupVerificationError(_ERROR)
        bundle = store.bundles / copy_id
        current = _inspect_copy(store, bundle)
        if (
            current.health != "healthy"
            or current.directory_identity != item.directory_identity
            or current.graph_digest != item.graph_digest
            or current.created_at != item.created_at
        ):
            raise BackupVerificationError(_ERROR)
        _delete_copy(store, copy_id, item.graph_digest, item.created_at)
        deleted.append(copy_id)
    return deleted


def _delete_copy(
    store: RecoveryGraphStore, copy_id: str, graph_digest: str, created_at: str
) -> None:
    from finjuice.pipeline.storage.sqlite.recovery_store import (
        _canonical,
        _fsync_directory,
        _write_exclusive,
    )

    bundle = store.bundles / copy_id
    info = bundle.lstat()
    if not stat.S_ISDIR(info.st_mode) or bundle.is_symlink():
        raise BackupVerificationError(_ERROR)
    intent_id = str(uuid.uuid4())
    intent = {
        "schema_version": 1,
        "kind": _INTENT_KIND,
        "intent_id": intent_id,
        "copy_id": copy_id,
        "st_dev": info.st_dev,
        "st_ino": info.st_ino,
        "graph_digest": graph_digest,
        "created_at": created_at,
    }
    _write_exclusive(store.control / _INTENTS / f"{intent_id}.json", _canonical(intent))
    _fsync_directory(store.control / _INTENTS)
    _complete_tombstone(store, intent)


def _resume_tombstones(
    store: RecoveryGraphStore, inventory: StoreInventoryReceipt, planned: RetentionPlan
) -> tuple[list[str], set[str]]:
    from finjuice.pipeline.storage.sqlite.recovery_store import _forget_intent

    deleted: list[str] = []
    held_originals: set[str] = set()
    intents_root = store.control / _INTENTS
    checked_directories(intents_root)
    for child in sorted(intents_root.iterdir(), key=lambda path: path.name):
        if child.name.startswith("."):
            continue
        intent = _read_intent(child)
        copy_id = intent["copy_id"]
        current = next((item for item in inventory.copies if item.copy_id == copy_id), None)
        if current is not None and current.directory_identity != (
            intent["st_dev"],
            intent["st_ino"],
        ):
            held_originals.add(copy_id)
        if (
            current is not None
            and current.directory_identity == (intent["st_dev"], intent["st_ino"])
            and copy_id not in planned.delete_ids
        ):
            _forget_intent(store, intent["intent_id"])
            continue
        if _complete_tombstone(store, intent):
            deleted.append(copy_id)
    return deleted, held_originals


def _complete_tombstone(store: RecoveryGraphStore, intent: dict[str, Any]) -> bool:
    from finjuice.pipeline.storage.sqlite.recovery_store import (
        _forget_intent,
        _fsync_directory,
        _inspect_copy,
        _remove_identity_tree,
        rename_exclusive,
    )

    copy_id = intent["copy_id"]
    tombstone = store.bundles / f"{_TOMBSTONE}{intent['intent_id']}"
    original = store.bundles / copy_id
    expected = (intent["st_dev"], intent["st_ino"])
    if os.path.lexists(tombstone):
        _remove_identity_tree(tombstone, expected)
        _forget_intent(store, intent["intent_id"])
        return True
    if not os.path.lexists(original):
        _forget_intent(store, intent["intent_id"])
        return False
    info = original.lstat()
    if (info.st_dev, info.st_ino) != expected:
        _forget_intent(store, intent["intent_id"])
        return False
    verified = _inspect_copy(store, original)
    if (
        verified.health != "healthy"
        or verified.graph_digest != intent["graph_digest"]
        or verified.created_at != intent["created_at"]
    ):
        raise BackupVerificationError(_ERROR)
    rename_exclusive(original, tombstone)
    _fsync_directory(store.bundles)
    _remove_identity_tree(tombstone, expected)
    _forget_intent(store, intent["intent_id"])

    return True


def _reject_unknown_tombstones(store: RecoveryGraphStore) -> None:
    pending = {path.stem for path in (store.control / _INTENTS).iterdir() if path.suffix == ".json"}
    for child in store.bundles.iterdir():
        if not child.name.startswith(_TOMBSTONE):
            continue
        intent_id = child.name.removeprefix(_TOMBSTONE)
        if intent_id not in pending:
            raise BackupVerificationError(_ERROR)


def _forget_intent(store: RecoveryGraphStore, intent_id: str) -> None:
    from finjuice.pipeline.storage.sqlite.recovery_store import _fsync_directory

    path = store.control / _INTENTS / f"{intent_id}.json"
    if os.path.lexists(path):
        path.unlink()
        _fsync_directory(store.control / _INTENTS)


def _remove_identity_tree(path: Path, expected: tuple[int, int]) -> None:
    from finjuice.pipeline.storage.sqlite.recovery_store import _fsync_directory

    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != expected:
        raise BackupVerificationError(_ERROR)
    _remove_tree(path, expected[0])
    _fsync_directory(path.parent)


def _remove_tree(path: Path, expected_dev: int) -> None:
    checked_directories(path)
    for child in sorted(path.iterdir(), key=lambda item: item.name):
        info = child.lstat()
        if info.st_dev != expected_dev:
            raise BackupVerificationError(_ERROR)
        if stat.S_ISLNK(info.st_mode) or child.is_symlink():
            raise BackupVerificationError(_ERROR)
        if stat.S_ISDIR(info.st_mode):
            _remove_tree(child, expected_dev)
        elif stat.S_ISREG(info.st_mode):
            child.unlink()
        else:
            raise BackupVerificationError(_ERROR)
    path.rmdir()


def _read_intent(path: Path) -> dict[str, Any]:
    try:
        return _parse_intent(path, json.loads(read_regular_bytes(path).decode("utf-8")))
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _parse_intent(path: Path, payload: Any) -> dict[str, Any]:
    header_ok = (
        isinstance(payload, dict)
        and set(payload) == _INTENT_KEYS
        and payload["kind"] == _INTENT_KIND
        and payload["schema_version"] == 1
        and type(payload["schema_version"]) is int
    )
    identity_ok = (
        header_ok
        and is_copy_id(payload["copy_id"])
        and is_copy_id(payload["intent_id"])
        and type(payload["st_dev"]) is int
        and type(payload["st_ino"]) is int
        and _DIGEST.fullmatch(payload["graph_digest"])
        and type(payload["created_at"]) is str
        and payload["created_at"]
        and path.stem == payload["intent_id"]
    )
    if not identity_ok or not isinstance(payload, dict):
        raise BackupVerificationError(_ERROR)
    return payload
