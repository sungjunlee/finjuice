"""Marker-based membership for an explicitly initialized recovery-graph store.

Recognition uses the exact initialized layout only. It does not infer source
authority from filesystem structure or adopt unmarked legacy directories.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from finjuice.pipeline.storage.authority import CoordinationLease, CoordinationPaths
from finjuice.pipeline.storage.sqlite.backup_io import checked_directories, read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError

_ERROR = "Local recovery store operation could not be verified."
CONTROL_NAME = ".finjuice-recovery-store"
BUNDLES_NAME = "bundles"
IDENTITY_NAME = "identity.json"
STORE_KIND = "finjuice.sqlite.local-recovery-store"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_IDENTITY_KEYS = {
    "schema_version",
    "kind",
    "store_id",
    "activation_sha256",
    "enrollment_digest",
    "created_at",
}


def store_control(root: Path) -> Path:
    """Return the stable private control directory for one store root."""
    return Path(os.path.abspath(root)) / CONTROL_NAME


def store_bundles(root: Path) -> Path:
    """Return the UUID bundle namespace for one store root."""
    return Path(os.path.abspath(root)) / BUNDLES_NAME


def store_lock_paths(root: Path) -> CoordinationPaths:
    """Return the lock namespace that stays outside deletable bundles."""
    return CoordinationPaths(store_control(root))


def is_copy_id(value: str) -> bool:
    """Return whether ``value`` is a canonical UUID copy identity."""
    return isinstance(value, str) and _UUID.fullmatch(value) is not None


def recognize_managed_recovery_path(path: Path) -> tuple[Path, str] | None:
    """Return ``(store_root, copy_id)`` for an exact UUID bundle or snapshot.

    A missing control marker is not a store. A present but unreadable marker
    fails closed. This does not walk arbitrary parents or source data dirs.
    """
    root = Path(os.path.abspath(path))
    layout = _exact_bundle_layout(root)
    if layout is None and root.name == "snapshot":
        layout = _exact_bundle_layout(root.parent)
    if (
        layout is None
        and re.fullmatch(r"[0-9a-f]{32}", root.name)
        and root.parent.name == "attempts"
        and root.parent.parent.name == "snapshot"
    ):
        layout = _exact_bundle_layout(root.parent.parent.parent)
    if layout is None:
        return None
    store_root, copy_id = layout
    state = initialized_store_state(store_root)
    if state == "absent":
        return None
    if state != "valid":
        raise BackupVerificationError(_ERROR)
    return store_root, copy_id


def initialized_store_state(store_root: Path) -> str:
    """Return ``absent``, ``valid``, or raise when a marker is unsafe."""
    root = Path(os.path.abspath(store_root))
    control = store_control(root)
    identity = control / IDENTITY_NAME
    if not os.path.lexists(control) and not os.path.lexists(identity):
        return "absent"
    try:
        checked_directories(control)
        payload = _identity_payload(read_regular_bytes(identity))
        if payload["store_id"] != str(payload["store_id"]) or not is_copy_id(payload["store_id"]):
            raise BackupVerificationError(_ERROR)
        return "valid"
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def read_store_identity(store_root: Path) -> dict[str, Any]:
    """Return the durable identity document for an initialized store."""
    if initialized_store_state(store_root) != "valid":
        raise BackupVerificationError(_ERROR)
    return _identity_payload(read_regular_bytes(store_control(store_root) / IDENTITY_NAME))


@contextmanager
def managed_read_lease(path: Path, *, timeout_ms: int = 5_000) -> Iterator[None]:
    """Hold the store shared lease when ``path`` is an initialized member."""
    member = recognize_managed_recovery_path(path)
    if member is None:
        yield
        return
    store_root, copy_id = member
    with CoordinationLease(store_lock_paths(store_root), exclusive=False, timeout_ms=timeout_ms):
        later = recognize_managed_recovery_path(path)
        if later != (store_root, copy_id):
            raise BackupVerificationError(_ERROR)
        yield


def _exact_bundle_layout(path: Path) -> tuple[Path, str] | None:
    if not is_copy_id(path.name) or path.parent.name != BUNDLES_NAME:
        return None
    return path.parent.parent, path.name


def _identity_payload(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict) or set(payload) != _IDENTITY_KEYS:
        raise BackupVerificationError(_ERROR)
    if payload["kind"] != STORE_KIND or payload["schema_version"] != 1:
        raise BackupVerificationError(_ERROR)
    for key in ("store_id", "activation_sha256", "enrollment_digest", "created_at"):
        if type(payload[key]) is not str or not payload[key]:
            raise BackupVerificationError(_ERROR)
    if type(payload["schema_version"]) is not int:
        raise BackupVerificationError(_ERROR)
    return payload
