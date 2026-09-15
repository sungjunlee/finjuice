"""Managed local recovery-graph store with verified GFS retention.

The store is an explicitly initialized container of complete recovery graphs.
Nested snapshot attempts are not independent retention objects. Callers must
supply independently enrolled expectations on every command; store metadata is
not a trust substitute. This adapter does not delete source artifacts or
generations.

Inventory and GFS-plan helpers live in
:mod:`finjuice.pipeline.storage.sqlite.recovery_store_inventory` and are
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup.publish import rename_exclusive
from finjuice.pipeline.backup.retention import RetentionPlan, RetentionPolicy
from finjuice.pipeline.storage.authority import CoordinationLease, CoordinationPaths
from finjuice.pipeline.storage.sqlite.backup_io import (
    checked_directories,
    copy_regular_file,
    read_regular_bytes,
)
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.inactive_restore import restore_workspace
from finjuice.pipeline.storage.sqlite.inactive_restore_descriptor import RestoredWorkspaceReceipt
from finjuice.pipeline.storage.sqlite.objects import _mkdir_checked
from finjuice.pipeline.storage.sqlite.recovery_bundle import (
    ExpectedRecoveryGraph,
    RecoveryCaptureInput,
    RecoveryGraphReceipt,
    capture_recovery_bundle,
    verify_recovery_bundle,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    Health as Health,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    StoreCopyRecord as StoreCopyRecord,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    StoreInventoryReceipt as StoreInventoryReceipt,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    StorePlanReceipt as StorePlanReceipt,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _bundle_children as _bundle_children,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _inspect_copy as _inspect_copy,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _inventory as _inventory,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _parse_created as _parse_created,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _plan_from_inventory as _plan_from_inventory,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _plan_receipt as _plan_receipt,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _snapshot_created_at as _snapshot_created_at,
)
from finjuice.pipeline.storage.sqlite.recovery_store_inventory import (
    _validate_baselines as _validate_baselines,
)
from finjuice.pipeline.storage.sqlite.recovery_store_lock import (
    IDENTITY_NAME,
    STORE_KIND,
    is_copy_id,
    read_store_identity,
    store_bundles,
    store_control,
    store_lock_paths,
)

_ERROR = "Local recovery store operation could not be verified."
_REGISTRATION = "registration.json"
_CAPTURE_STARTED = "capture-started"
_INTENTS = "intents"
_TOMBSTONE = ".tombstone-"
_RECEIVE_PREFIX = ".recv-"
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_REG_KIND = "finjuice.sqlite.local-recovery-registration"
_INTENT_KIND = "finjuice.sqlite.local-recovery-tombstone"
_REG_KEYS = {"schema_version", "kind", "baselines"}
_BASELINE_KEYS = {"copy_id", "graph_digest", "snapshot_manifest_digest", "created_at"}
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


@dataclass(frozen=True)
class StoreInitReceipt:
    """Privacy-safe receipt for an explicitly initialized local store."""

    kind: str
    store_id: str
    activation_sha256: str
    enrollment_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StoreCaptureReceipt:
    """Verified capture published into a managed store."""

    kind: str
    copy_id: str
    baseline_registered: bool
    graph: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.graph,
            "baseline_registered": self.baseline_registered,
            "copy_id": self.copy_id,
            "kind": self.kind,
        }


@dataclass(frozen=True)
class StoreProtectReceipt:
    """Durable additional baseline registration after actual graph verification."""

    kind: str
    copy_id: str
    graph_digest: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class StorePruneReceipt:
    """Actual deletion receipt; held copies are never reported as deleted."""

    kind: str
    deleted_count: int
    kept_count: int
    held_count: int
    plan_digest: str
    deleted_ids: tuple[str, ...]
    kept_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["deleted_ids"] = list(self.deleted_ids)
        payload["kept_ids"] = list(self.kept_ids)
        return payload


@dataclass(frozen=True)
class RecoveryGraphStore:
    """One initialized local store bound to one enrolled activation."""

    root: Path
    expected: ExpectedRecoveryGraph
    timeout_ms: int = 5_000

    @property
    def control(self) -> Path:
        return store_control(self.root)

    @property
    def bundles(self) -> Path:
        return store_bundles(self.root)

    def shared_lease(self) -> CoordinationLease:
        return CoordinationLease(
            store_lock_paths(self.root), exclusive=False, timeout_ms=self.timeout_ms
        )

    def exclusive_lease(self) -> CoordinationLease:
        return CoordinationLease(
            store_lock_paths(self.root), exclusive=True, timeout_ms=self.timeout_ms
        )


def enrollment_digest(expected: ExpectedRecoveryGraph) -> str:
    """Return the durable enrollment fingerprint for one independently supplied graph."""
    body = {
        "activation_evidence": asdict(expected.activation_evidence),
        "activation_sha256": expected.activation_sha256,
        "capsule": {
            "activation_evidence": asdict(expected.capsule.activation_evidence),
            "migration_semantics": expected.capsule.migration_semantics,
            "pre_cutover_semantics": expected.capsule.pre_cutover_semantics,
        },
        "release": {
            "activation_evidence": asdict(expected.release.activation_evidence),
            "binding_sha256": expected.release.binding_sha256,
        },
        "wheel_basename": expected.wheel_basename,
    }
    return _sha(_canonical(body))


def initialize_recovery_store(store: Path, expected: ExpectedRecoveryGraph) -> StoreInitReceipt:
    """Create an empty initialized store bound to one enrolled activation."""
    root = Path(os.path.abspath(store))
    if os.path.lexists(root) or any(part.casefold() == ".finjuice" for part in root.parts):
        raise BackupVerificationError(_ERROR)
    checked_directories(root.parent)
    store_id = str(uuid.uuid4())
    digest = enrollment_digest(expected)
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    identity = {
        "schema_version": 1,
        "kind": STORE_KIND,
        "store_id": store_id,
        "activation_sha256": expected.activation_sha256,
        "enrollment_digest": digest,
        "created_at": created,
    }
    try:
        _mkdir_checked(root)
        _mkdir_checked(store_control(root), boundary=root)
        _mkdir_checked(store_bundles(root), boundary=root)
        _mkdir_checked(store_control(root) / _INTENTS, boundary=root)
        _write_exclusive(store_control(root) / IDENTITY_NAME, _canonical(identity))
        _fsync_directory(store_control(root))
        _fsync_directory(root)
        _fsync_directory(root.parent)
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None
    return StoreInitReceipt(
        "local_recovery_store_initialized",
        store_id,
        expected.activation_sha256,
        digest,
    )


def open_recovery_store(
    store: Path, expected: ExpectedRecoveryGraph, *, timeout_ms: int = 5_000
) -> RecoveryGraphStore:
    """Open one initialized store after matching independently supplied expectations."""
    root = Path(os.path.abspath(store))
    identity = read_store_identity(root)
    if identity["activation_sha256"] != expected.activation_sha256:
        raise BackupVerificationError(_ERROR)
    if identity["enrollment_digest"] != enrollment_digest(expected):
        raise BackupVerificationError(_ERROR)
    checked_directories(store_control(root))
    checked_directories(store_bundles(root))
    return RecoveryGraphStore(root, expected, timeout_ms)


def capture_into_store(
    store: Path,
    source: RecoveryCaptureInput,
    expected: ExpectedRecoveryGraph,
    *,
    timeout_ms: int = 5_000,
) -> StoreCaptureReceipt:
    """Publish one verified graph under the shared store lease."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    _reject_overlap(opened.root, source.data_dir, source.migration_candidate)
    _reject_overlap(opened.root, source.release_paths.wheel)
    with (
        opened.shared_lease(),
        CoordinationLease(
            CoordinationPaths(opened.control / "registration-lock"),
            exclusive=True,
            timeout_ms=timeout_ms,
        ),
    ):
        first = _admit_capture_registration(opened)
        copy_id = _fresh_copy_id(opened.bundles)
        destination = opened.bundles / copy_id
        published = capture_recovery_bundle(replace(source, destination=destination), expected)
        created_at = _snapshot_created_at(destination)
        if first:
            record = _baseline_record(copy_id, published, created_at)
            _write_registration(opened, (record,))
        _fsync_directory(opened.bundles)
        return StoreCaptureReceipt(
            "local_recovery_store_captured", copy_id, first, published.to_dict()
        )


def receive_graph_into_store(
    store: Path,
    source_bundle: Path,
    expected: ExpectedRecoveryGraph,
    *,
    expected_graph: RecoveryGraphReceipt,
    timeout_ms: int = 5_000,
) -> StoreCaptureReceipt:
    """Publish one already-verified graph into a destination store by file copy."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    source_root = Path(os.path.abspath(source_bundle))
    _reject_overlap(opened.root, source_root)
    from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

    with (
        managed_read_lease(source_root, timeout_ms=timeout_ms),
        opened.shared_lease(),
        CoordinationLease(
            CoordinationPaths(opened.control / "registration-lock"),
            exclusive=True,
            timeout_ms=timeout_ms,
        ),
    ):
        _require_receive_registration(opened)
        copy_id = _fresh_copy_id(opened.bundles)
        staging = opened.bundles / f"{_RECEIVE_PREFIX}{uuid.uuid4().hex}"
        try:
            return _publish_received_graph(opened, source_root, staging, copy_id, expected_graph)
        except Exception:
            _discard_tree(staging)
            raise


def _admit_capture_registration(store: RecoveryGraphStore, *, receiving: bool = False) -> bool:
    current = _read_registration(store)
    if current is not None:
        _inventory(store)
        return False
    started = store.control / _CAPTURE_STARTED
    if os.path.lexists(started) or any(
        not receiving or not child.name.startswith(_RECEIVE_PREFIX)
        for child in store.bundles.iterdir()
    ):
        raise BackupVerificationError(_ERROR)
    # Once a first capture starts, missing registration is never a fresh store.
    _write_exclusive(started, b"1\n")
    _fsync_directory(store.control)
    return True


def list_recovery_store(
    store: Path, expected: ExpectedRecoveryGraph, *, timeout_ms: int = 5_000
) -> StoreInventoryReceipt:
    """Inventory and verify every known copy under the shared store lease."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    with opened.shared_lease():
        return _inventory(opened)


def verify_store_copy(
    store: Path,
    expected: ExpectedRecoveryGraph,
    copy_id: str,
    *,
    timeout_ms: int = 5_000,
) -> RecoveryGraphReceipt:
    """Verify one managed copy against independently enrolled expectations."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    if not is_copy_id(copy_id):
        raise BackupVerificationError(_ERROR)
    with opened.shared_lease():
        bundle = opened.bundles / copy_id
        checked_directories(bundle)
        return verify_recovery_bundle(bundle, expected)


def restore_store_copy(
    store: Path,
    expected: ExpectedRecoveryGraph,
    copy_id: str,
    target: Path,
    *,
    timeout_ms: int = 5_000,
) -> tuple[RecoveryGraphReceipt, RestoredWorkspaceReceipt]:
    """Hold the shared lease from graph verification through inactive restore."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    if not is_copy_id(copy_id):
        raise BackupVerificationError(_ERROR)
    _reject_overlap(opened.root, target)
    with opened.shared_lease():
        bundle = opened.bundles / copy_id
        checked_directories(bundle)
        verified = verify_recovery_bundle(bundle, expected)
        restored = restore_workspace(bundle / "snapshot", target)
        if (
            restored.source_manifest_digest != verified.snapshot_manifest_digest
            or restored.dataset_generation != verified.snapshot_generation
            or restored.sqlite_schema_version != verified.snapshot_schema_version
            or restored.initial_dataset_revision != verified.snapshot_revision
        ):
            raise BackupVerificationError(_ERROR)
        return verified, restored


def protect_store_copy(
    store: Path,
    expected: ExpectedRecoveryGraph,
    copy_id: str,
    *,
    timeout_ms: int = 5_000,
) -> StoreProtectReceipt:
    """Verify one copy and durably register it as an additional baseline."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    if not is_copy_id(copy_id):
        raise BackupVerificationError(_ERROR)
    with opened.exclusive_lease():
        _plan_from_inventory(_inventory(opened), RetentionPolicy(0, 0, 0))
        bundle = opened.bundles / copy_id
        checked_directories(bundle)
        verified = verify_recovery_bundle(bundle, expected)
        created_at = _snapshot_created_at(bundle)
        record = _baseline_record(copy_id, verified, created_at)
        current = _read_registration(opened)
        if current is None:
            raise BackupVerificationError(_ERROR)
        elif not any(_same_baseline(item, record) for item in current):
            _write_registration(opened, (*current, record))
        return StoreProtectReceipt("local_recovery_store_protected", copy_id, verified.graph_digest)


def plan_recovery_store(
    store: Path,
    expected: ExpectedRecoveryGraph,
    policy: RetentionPolicy | None = None,
    *,
    timeout_ms: int = 5_000,
) -> StorePlanReceipt:
    """Recompute a GFS plan from verified inventory under the shared lease."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    with opened.shared_lease():
        inventory = _inventory(opened)
        planned = _plan_from_inventory(inventory, policy)
        return _plan_receipt(planned, inventory)


def prune_recovery_store(
    store: Path,
    expected: ExpectedRecoveryGraph,
    policy: RetentionPolicy | None = None,
    *,
    plan_digest: str | None = None,
    timeout_ms: int = 5_000,
) -> StorePruneReceipt:
    """Re-inventory, replan, and delete under an exclusive store lease."""
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    if plan_digest is not None and (
        type(plan_digest) is not str or not _DIGEST.fullmatch(plan_digest)
    ):
        raise BackupVerificationError(_ERROR)
    with opened.exclusive_lease():
        _reject_unknown_tombstones(opened)
        inventory = _inventory(opened)
        planned = _plan_from_inventory(inventory, policy)
        receipt = _plan_receipt(planned, inventory)
        if plan_digest is not None and plan_digest != receipt.plan_digest:
            raise BackupVerificationError(_ERROR)
        resumed, held_originals = _resume_tombstones(opened, inventory, planned)
        inventory = _inventory(opened)
        planned = _plan_from_inventory(inventory, policy)
        deleted = resumed + _apply_deletions(opened, inventory, planned, held_originals)
        later = _inventory(opened)
        return StorePruneReceipt(
            "local_recovery_store_pruned",
            len(deleted),
            later.healthy_count,
            later.held_count,
            receipt.plan_digest,
            tuple(deleted),
            tuple(item.copy_id for item in later.copies if item.health == "healthy"),
        )


def _apply_deletions(
    store: RecoveryGraphStore,
    inventory: StoreInventoryReceipt,
    planned: RetentionPlan,
    held_originals: set[str],
) -> list[str]:
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
    path = store.control / _INTENTS / f"{intent_id}.json"
    if os.path.lexists(path):
        path.unlink()
        _fsync_directory(store.control / _INTENTS)


def _remove_identity_tree(path: Path, expected: tuple[int, int]) -> None:
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


def _write_registration(store: RecoveryGraphStore, baselines: tuple[dict[str, str], ...]) -> None:
    staged = store.control / f".{_REGISTRATION}.{uuid.uuid4().hex}"
    _write_exclusive(staged, _canonical(_registration_document(baselines)))
    os.replace(staged, store.control / _REGISTRATION)
    _fsync_directory(store.control)


def _read_registration(store: RecoveryGraphStore) -> tuple[dict[str, str], ...] | None:
    path = store.control / _REGISTRATION
    if not os.path.lexists(path):
        return None
    try:
        return _parse_registration(json.loads(read_regular_bytes(path).decode("utf-8")))
    except BackupVerificationError:
        raise
    except Exception:
        raise BackupVerificationError(_ERROR) from None


def _parse_registration(payload: Any) -> tuple[dict[str, str], ...]:
    if not isinstance(payload, dict) or set(payload) != _REG_KEYS:
        raise BackupVerificationError(_ERROR)
    if payload["kind"] != _REG_KIND or payload["schema_version"] != 1:
        raise BackupVerificationError(_ERROR)
    if type(payload["schema_version"]) is not int:
        raise BackupVerificationError(_ERROR)
    rows = payload["baselines"]
    if not isinstance(rows, list) or not rows:
        raise BackupVerificationError(_ERROR)
    parsed: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in rows:
        parsed.append(_parse_baseline(raw, seen))
    return tuple(parsed)


def _parse_baseline(raw: Any, seen: set[str]) -> dict[str, str]:
    if not isinstance(raw, dict) or set(raw) != _BASELINE_KEYS:
        raise BackupVerificationError(_ERROR)
    if any(type(raw[key]) is not str or not raw[key] for key in _BASELINE_KEYS):
        raise BackupVerificationError(_ERROR)
    if not is_copy_id(raw["copy_id"]) or raw["copy_id"] in seen:
        raise BackupVerificationError(_ERROR)
    if not _DIGEST.fullmatch(raw["graph_digest"]):
        raise BackupVerificationError(_ERROR)
    if not _DIGEST.fullmatch(raw["snapshot_manifest_digest"].removeprefix("sha256:")):
        raise BackupVerificationError(_ERROR)
    _parse_created(raw["created_at"])
    seen.add(raw["copy_id"])
    return {key: raw[key] for key in _BASELINE_KEYS}


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


def _baseline_record(
    copy_id: str, receipt: RecoveryGraphReceipt, created_at: str
) -> dict[str, str]:
    return {
        "copy_id": copy_id,
        "graph_digest": receipt.graph_digest,
        "snapshot_manifest_digest": receipt.snapshot_manifest_digest,
        "created_at": created_at,
    }


def _same_baseline(left: dict[str, str], right: dict[str, str]) -> bool:
    return left == right


def _registration_document(baselines: tuple[dict[str, str], ...]) -> dict[str, Any]:
    return {"schema_version": 1, "kind": _REG_KIND, "baselines": list(baselines)}


def _fresh_copy_id(bundles: Path) -> str:
    for _ in range(8):
        copy_id = str(uuid.uuid4())
        destination = bundles / copy_id
        if not os.path.lexists(destination):
            return copy_id
    raise BackupVerificationError(_ERROR)


def _after_graph_file_copied() -> None:
    """Test seam invoked after each regular file is copied into a receive staging tree."""
    return None


def _publish_received_graph(
    opened: RecoveryGraphStore,
    source_root: Path,
    staging: Path,
    copy_id: str,
    expected_graph: RecoveryGraphReceipt,
) -> StoreCaptureReceipt:
    expected = opened.expected
    _copy_graph_tree(source_root, staging)
    published = verify_recovery_bundle(staging, expected)
    if (
        published.graph_digest != expected_graph.graph_digest
        or published.snapshot_manifest_digest != expected_graph.snapshot_manifest_digest
        or published.snapshot_generation != expected_graph.snapshot_generation
        or published.snapshot_revision != expected_graph.snapshot_revision
    ):
        raise BackupVerificationError(_ERROR)
    first = _admit_capture_registration(opened, receiving=True)
    destination = opened.bundles / copy_id
    rename_exclusive(staging, destination)
    created_at = _snapshot_created_at(destination)
    if first:
        _write_registration(opened, (_baseline_record(copy_id, published, created_at),))
    _fsync_directory(opened.bundles)
    later = verify_recovery_bundle(destination, expected)
    if later.graph_digest != published.graph_digest:
        raise BackupVerificationError(_ERROR)
    return StoreCaptureReceipt("local_recovery_store_received", copy_id, first, later.to_dict())


def _require_receive_registration(opened: RecoveryGraphStore) -> None:
    """Reject lost registration before copying; bootstrap begins only at publication."""
    if _read_registration(opened) is not None:
        _inventory(opened)
    elif os.path.lexists(opened.control / _CAPTURE_STARTED) or any(
        not child.name.startswith(_RECEIVE_PREFIX) for child in opened.bundles.iterdir()
    ):
        raise BackupVerificationError(_ERROR)


def _copy_graph_tree(source: Path, destination: Path) -> None:
    from finjuice.pipeline.storage.sqlite.backup_publication import fsync_attempt_tree

    root = Path(os.path.abspath(source))
    target_root = Path(os.path.abspath(destination))
    checked_directories(root)
    _mkdir_checked(target_root, boundary=target_root.parent)
    pending = [root]
    while pending:
        parent = pending.pop()
        checked_directories(parent)
        for child in sorted(parent.iterdir(), key=lambda item: item.name):
            relative = child.relative_to(root).as_posix()
            info = child.lstat()
            target = target_root / relative
            if stat.S_ISLNK(info.st_mode) or child.is_symlink():
                raise BackupVerificationError(_ERROR)
            if stat.S_ISDIR(info.st_mode):
                _mkdir_checked(target, boundary=target_root)
                pending.append(child)
            elif stat.S_ISREG(info.st_mode):
                _mkdir_checked(target.parent, boundary=target_root)
                copy_regular_file(child, target)
                os.chmod(target, stat.S_IMODE(info.st_mode))
                _after_graph_file_copied()
            else:
                raise BackupVerificationError(_ERROR)
    fsync_attempt_tree(target_root)


def _discard_tree(path: Path) -> None:
    if not os.path.lexists(path):
        return
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
        return
    _remove_identity_tree(path, (info.st_dev, info.st_ino))


def _reject_overlap(store: Path, *others: Path) -> None:
    root = Path(os.path.abspath(store))
    for other in others:
        candidate = Path(os.path.abspath(other))
        if root == candidate or root.is_relative_to(candidate) or candidate.is_relative_to(root):
            raise BackupVerificationError(_ERROR)


def _write_exclusive(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        remaining = memoryview(raw)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise BackupVerificationError(_ERROR)
            remaining = remaining[written:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()
