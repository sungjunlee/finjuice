"""Inventory and GFS-plan helpers for an initialized recovery-graph store.

Owns copy inspection, baseline validation, verified inventory receipts, and
recomputed retention plans. Public names stay importable from
:mod:`finjuice.pipeline.storage.sqlite.recovery_store`, which re-exports them
so existing callers keep the original module path.
"""

from __future__ import annotations

import stat
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from finjuice.pipeline.backup.retention import (
    BackupCopy,
    RetentionPlan,
    RetentionPolicy,
    plan_retention,
)
from finjuice.pipeline.storage.sqlite.backup_coverage import (
    CommitObservation,
    read_graph_commits,
    select_retention_latest,
)
from finjuice.pipeline.storage.sqlite.backup_io import checked_directories
from finjuice.pipeline.storage.sqlite.backup_verify import resolve_backup_input
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.recovery_bundle import verify_recovery_bundle
from finjuice.pipeline.storage.sqlite.recovery_store_lock import is_copy_id, read_store_identity

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.recovery_store import RecoveryGraphStore

_ERROR = "Local recovery store operation could not be verified."
_TOMBSTONE = ".tombstone-"
_RECEIVE_PREFIX = ".recv-"
Health = Literal["healthy", "held"]


@dataclass(frozen=True)
class StoreCopyRecord:
    """One inventoried graph copy without filesystem paths."""

    copy_id: str
    health: Health
    protected: bool
    created_at: str | None
    graph_digest: str | None
    hold_reason: str | None
    snapshot_manifest_digest: str | None = None
    snapshot_revision: int = -1
    directory_identity: tuple[int, int] | None = None
    commit_observation: CommitObservation | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        del payload["snapshot_manifest_digest"]
        del payload["snapshot_revision"]
        del payload["directory_identity"]
        del payload["commit_observation"]
        return payload


@dataclass(frozen=True)
class StoreInventoryReceipt:
    """Verified inventory of one local recovery-graph store."""

    kind: str
    store_id: str
    healthy_count: int
    held_count: int
    baseline_copy_ids: tuple[str, ...]
    latest_healthy_id: str | None
    copies: tuple[StoreCopyRecord, ...]
    plan_digest: str | None = None
    unresolved_copy_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["baseline_copy_ids"] = list(self.baseline_copy_ids)
        payload["copies"] = [item.to_dict() for item in self.copies]
        del payload["unresolved_copy_ids"]
        return payload


@dataclass(frozen=True)
class StorePlanReceipt:
    """Recomputed GFS plan plus a digest for later stale-plan rejection."""

    kind: str
    plan_digest: str
    delete_count: int
    keep_count: int
    protected_count: int
    latest_healthy_id: str | None
    policy: dict[str, int]
    keep_ids: tuple[str, ...]
    delete_ids: tuple[str, ...]
    protected_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["keep_ids"] = list(self.keep_ids)
        payload["delete_ids"] = list(self.delete_ids)
        payload["protected_ids"] = list(self.protected_ids)
        return payload


def _inventory(store: RecoveryGraphStore) -> StoreInventoryReceipt:
    from finjuice.pipeline.storage.sqlite.recovery_store import _read_registration

    identity = read_store_identity(store.root)
    records: list[StoreCopyRecord] = []
    for child in _bundle_children(store.bundles):
        records.append(_inspect_copy(store, child))
    healthy = [item for item in records if item.health == "healthy"]
    latest = None
    unresolved: tuple[str, ...] = ()
    if healthy:
        latest, unresolved_ids = select_retention_latest(
            tuple(
                (
                    item.copy_id,
                    _parse_created(item.created_at),
                    item.commit_observation,
                )
                for item in healthy
            )
        )
        unresolved = tuple(sorted(unresolved_ids))
    registered = _read_registration(store) or ()
    _validate_baselines(registered, records)
    protected_ids = {item["copy_id"] for item in registered}
    copies = tuple(
        replace(item, protected=item.copy_id in protected_ids or item.copy_id == latest)
        for item in records
    )
    return StoreInventoryReceipt(
        "local_recovery_store_inventory",
        identity["store_id"],
        len(healthy),
        sum(1 for item in copies if item.health == "held"),
        tuple(item["copy_id"] for item in registered),
        latest,
        copies,
        None,
        unresolved,
    )


def _validate_baselines(
    registered: tuple[dict[str, str], ...], records: list[StoreCopyRecord]
) -> None:
    by_id = {item.copy_id: item for item in records}
    for baseline in registered:
        item = by_id.get(baseline["copy_id"])
        if (
            item is None
            or item.health != "healthy"
            or item.graph_digest != baseline["graph_digest"]
            or item.snapshot_manifest_digest != baseline["snapshot_manifest_digest"]
            or item.created_at != baseline["created_at"]
        ):
            raise BackupVerificationError(_ERROR)


def _inspect_copy(store: RecoveryGraphStore, path: Path) -> StoreCopyRecord:
    name = path.name
    if name.startswith(_TOMBSTONE):
        raise BackupVerificationError(_ERROR)
    if not is_copy_id(name):
        return StoreCopyRecord(name, "held", False, None, None, "unknown")
    try:
        info = path.lstat()
        if not stat.S_ISDIR(info.st_mode) or path.is_symlink():
            return StoreCopyRecord(name, "held", False, None, None, "unreadable")
        verified = verify_recovery_bundle(path, store.expected)
        created_at = _snapshot_created_at(path)
        observation = None
        try:
            observation = read_graph_commits(
                path,
                snapshot_generation=verified.snapshot_generation,
                snapshot_schema_version=verified.snapshot_schema_version,
                snapshot_revision=verified.snapshot_revision,
            )
        except (BackupVerificationError, OSError, ValueError):
            observation = None
        return StoreCopyRecord(
            name,
            "healthy",
            False,
            created_at,
            verified.graph_digest,
            None,
            verified.snapshot_manifest_digest,
            verified.snapshot_revision,
            (info.st_dev, info.st_ino),
            observation,
        )
    except BackupVerificationError:
        return StoreCopyRecord(name, "held", False, None, None, "unverified")
    except (OSError, ValueError):
        return StoreCopyRecord(name, "held", False, None, None, "unreadable")


def _plan_from_inventory(
    inventory: StoreInventoryReceipt, policy: RetentionPolicy | None
) -> RetentionPlan:
    if inventory.healthy_count <= 0:
        raise BackupVerificationError(_ERROR)
    registered = inventory.baseline_copy_ids
    if not registered:
        raise BackupVerificationError(_ERROR)
    healthy = {item.copy_id: item for item in inventory.copies if item.health == "healthy"}
    pinned: list[BackupCopy] = []
    for copy_id in registered:
        item = healthy.get(copy_id)
        if item is None or item.graph_digest is None or item.created_at is None:
            raise BackupVerificationError(_ERROR)
        pinned.append(
            BackupCopy(
                copy_id=copy_id,
                created_at=_parse_created(item.created_at),
                healthy=True,
                location="local",
                pinned=True,
            )
        )
    copies = []
    seen = set()
    for item in inventory.copies:
        if item.health != "healthy" or item.created_at is None:
            continue
        copies.append(
            BackupCopy(
                copy_id=item.copy_id,
                created_at=_parse_created(item.created_at),
                healthy=True,
                location="local",
                pinned=item.copy_id in registered,
            )
        )
        seen.add(item.copy_id)
    for extra in pinned:
        if extra.copy_id not in seen:
            raise BackupVerificationError(_ERROR)
    planned = plan_retention(copies, policy if policy is not None else RetentionPolicy())
    ours = set(registered) | set(inventory.unresolved_copy_ids)
    if inventory.latest_healthy_id is not None:
        ours.add(inventory.latest_healthy_id)
    keep = (set(planned.keep_ids) - set(planned.protected_ids)) | ours
    ordered = tuple(item.copy_id for item in inventory.copies if item.copy_id in keep)
    delete = tuple(
        item.copy_id
        for item in inventory.copies
        if item.health == "healthy" and item.copy_id not in keep
    )
    protected = tuple(
        item.copy_id
        for item in inventory.copies
        if item.copy_id in registered or item.copy_id == inventory.latest_healthy_id
    )
    return replace(
        planned,
        latest_healthy_id=inventory.latest_healthy_id,
        keep_ids=ordered,
        delete_ids=delete,
        protected_ids=protected,
    )


def _plan_receipt(planned: RetentionPlan, inventory: StoreInventoryReceipt) -> StorePlanReceipt:
    from finjuice.pipeline.storage.sqlite.recovery_store import _canonical, _sha

    policy = {
        "daily": planned.policy.daily,
        "monthly": planned.policy.monthly,
        "weekly": planned.policy.weekly,
    }
    payload = {
        "store_id": inventory.store_id,
        "baselines": inventory.baseline_copy_ids,
        "copies": [
            {key: value for key, value in asdict(item).items() if key != "commit_observation"}
            for item in inventory.copies
        ],
        "delete_ids": list(planned.delete_ids),
        "keep_ids": list(planned.keep_ids),
        "latest_healthy_id": planned.latest_healthy_id,
        "policy": policy,
        "protected_ids": list(planned.protected_ids),
    }
    return StorePlanReceipt(
        "local_recovery_store_plan",
        _sha(_canonical(payload)),
        len(planned.delete_ids),
        len(planned.keep_ids),
        len(planned.protected_ids),
        planned.latest_healthy_id,
        policy,
        planned.keep_ids,
        planned.delete_ids,
        planned.protected_ids,
    )


def _snapshot_created_at(bundle: Path) -> str:
    _, manifest, _ = resolve_backup_input(bundle / "snapshot")
    created = datetime.fromisoformat(manifest.created_at)
    if created.tzinfo is None or created.utcoffset() is None:
        raise BackupVerificationError(_ERROR)
    return created.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_created(value: str | None) -> datetime:
    if value is None:
        raise BackupVerificationError(_ERROR)
    created = datetime.fromisoformat(value)
    if created.tzinfo is None or created.utcoffset() is None:
        raise BackupVerificationError(_ERROR)
    return created.astimezone(timezone.utc)


def _bundle_children(bundles: Path) -> list[Path]:
    checked_directories(bundles)
    children: list[Path] = []
    for child in sorted(bundles.iterdir(), key=lambda path: path.name):
        if child.name.startswith(_TOMBSTONE) or child.name.startswith(_RECEIVE_PREFIX):
            continue
        children.append(child)
    return children
