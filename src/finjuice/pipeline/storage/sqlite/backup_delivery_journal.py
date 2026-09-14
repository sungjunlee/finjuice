"""Append-only backup delivery journal outside the financial database.

Stage records are exclusive-create files. A lost or corrupt journal cannot
invent success. Domain COMMIT does not write here.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.storage.authority import CoordinationLease, CoordinationPaths
from finjuice.pipeline.storage.sqlite.backup_io import checked_directories, read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError
from finjuice.pipeline.storage.sqlite.objects import _mkdir_checked

_ERROR = "Backup delivery journal could not be verified."
_KIND = "finjuice.sqlite.backup-delivery-job"
_ATTEMPT_KIND = "finjuice.sqlite.backup-delivery-attempt"
_STAGE_KIND = "finjuice.sqlite.backup-delivery-stage"
_CACHE_KIND = "finjuice.sqlite.backup-delivery-success-cache"
DescriptorAdapter = Literal["filesystem"]
AttemptStage = Literal[
    "started",
    "local_verified",
    "sending",
    "destination_published",
    "destination_verified",
    "finished",
]
_STAGES: tuple[AttemptStage, ...] = (
    "started",
    "local_verified",
    "sending",
    "destination_published",
    "destination_verified",
    "finished",
)
_STAGE_INDEX = {name: index for index, name in enumerate(_STAGES)}
_DESCRIPTOR_KEYS = {
    "adapter",
    "enrollment_digest",
    "job_id",
    "kind",
    "receiver_store_id",
    "schema_version",
    "sender_store_id",
}


@dataclass(frozen=True)
class DeliveryDescriptor:
    """Versioned job identity. Private paths stay on disk only."""

    job_id: str
    enrollment_digest: str
    sender_store_id: str
    receiver_store_id: str
    adapter: DescriptorAdapter
    destination_store: str | None = None

    def public_dict(self) -> dict[str, Any]:
        return {
            "adapter": self.adapter,
            "enrollment_digest": self.enrollment_digest,
            "job_id": self.job_id,
            "receiver_store_id": self.receiver_store_id,
            "sender_store_id": self.sender_store_id,
        }


@dataclass(frozen=True)
class AttemptRecord:
    """Reconstructed attempt from immutable stage files."""

    attempt_id: str
    stage: AttemptStage
    source_coverage_digest: str
    source_generation: str
    source_schema_version: int
    source_revision: int
    selected_copy_id: str | None
    graph_digest: str | None
    snapshot_manifest_digest: str | None
    started_at: str
    finished_at: str | None
    error_code: str | None
    receiver_copy_id: str | None
    receiver_graph_digest: str | None
    history_unknown: bool = False

    def public_dict(self) -> dict[str, Any]:
        return {
            "attempt_id": self.attempt_id,
            "error_code": self.error_code,
            "finished_at": self.finished_at,
            "graph_digest": self.graph_digest,
            "receiver_copy_id": self.receiver_copy_id,
            "receiver_graph_digest": self.receiver_graph_digest,
            "selected_copy_id": self.selected_copy_id,
            "snapshot_manifest_digest": self.snapshot_manifest_digest,
            "source_coverage_digest": self.source_coverage_digest,
            "source_revision": self.source_revision,
            "stage": self.stage,
            "started_at": self.started_at,
        }


@dataclass(frozen=True)
class JournalView:
    """History projection. Missing or corrupt files make history unknown."""

    descriptor: DeliveryDescriptor | None
    attempts: tuple[AttemptRecord, ...]
    last_success: AttemptRecord | None
    latest_failure: AttemptRecord | None
    history_unknown: bool

    def last_verified_at(self) -> str | None:
        if self.history_unknown or self.last_success is None:
            return None
        return self.last_success.finished_at

    def last_attempt_error_code(self) -> str | None:
        if self.history_unknown:
            return None
        if self.latest_failure is None:
            return None
        return self.latest_failure.error_code


def control_lock(control: Path) -> CoordinationPaths:
    """Return the execution lock namespace outside deletable graph bundles."""
    return CoordinationPaths(Path(os.path.abspath(control)) / "lock")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


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


def _replace_atomic(path: Path, raw: bytes) -> None:
    staged = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    _write_exclusive(staged, raw)
    os.replace(staged, path)
    _fsync_directory(path.parent)


def initialize_delivery_control(
    control: Path,
    *,
    enrollment_digest: str,
    sender_store_id: str,
    receiver_store_id: str,
    destination_store: Path,
) -> DeliveryDescriptor:
    """Create a private control directory with one versioned descriptor."""
    root = Path(os.path.abspath(control))
    checked_directories(root.parent)
    _mkdir_checked(root)
    _mkdir_checked(root / "attempts", boundary=root)
    _mkdir_checked(root / "lock", boundary=root)
    if os.path.lexists(root / "descriptor.json"):
        return load_descriptor(root)
    job_id = str(uuid.uuid4())
    document = {
        "adapter": "filesystem",
        "destination_store": str(Path(os.path.abspath(destination_store))),
        "enrollment_digest": enrollment_digest,
        "job_id": job_id,
        "kind": _KIND,
        "receiver_store_id": receiver_store_id,
        "schema_version": 1,
        "sender_store_id": sender_store_id,
    }
    _write_exclusive(root / "descriptor.json", _canonical(document))
    _fsync_directory(root)
    return DeliveryDescriptor(
        job_id,
        enrollment_digest,
        sender_store_id,
        receiver_store_id,
        "filesystem",
        str(document["destination_store"]),
    )


def load_descriptor(control: Path) -> DeliveryDescriptor:
    """Read the durable descriptor; corrupt files do not invent a job."""
    try:
        payload = json.loads(read_regular_bytes(Path(control) / "descriptor.json").decode("utf-8"))
    except Exception:
        raise BackupVerificationError(_ERROR) from None
    if not isinstance(payload, dict):
        raise BackupVerificationError(_ERROR)
    public = {key: payload[key] for key in _DESCRIPTOR_KEYS if key in payload}
    if (
        not isinstance(payload, dict)
        or payload.get("kind") != _KIND
        or payload.get("schema_version") != 1
        or public.keys() != _DESCRIPTOR_KEYS
    ):
        raise BackupVerificationError(_ERROR)
    destination = payload.get("destination_store")
    if destination is not None and (type(destination) is not str or not destination):
        raise BackupVerificationError(_ERROR)
    return DeliveryDescriptor(
        str(payload["job_id"]),
        str(payload["enrollment_digest"]),
        str(payload["sender_store_id"]),
        str(payload["receiver_store_id"]),
        "filesystem",
        destination if isinstance(destination, str) else None,
    )


def start_attempt(
    control: Path,
    *,
    source_coverage_digest: str,
    source_generation: str,
    source_schema_version: int,
    source_revision: int,
) -> AttemptRecord:
    """Publish the started stage. Failure here is not a success receipt."""
    attempt_id = str(uuid.uuid4())
    started = _utc_now()
    body = {
        "attempt_id": attempt_id,
        "error_code": None,
        "finished_at": None,
        "graph_digest": None,
        "kind": _STAGE_KIND,
        "receiver_copy_id": None,
        "receiver_graph_digest": None,
        "schema_version": 1,
        "selected_copy_id": None,
        "snapshot_manifest_digest": None,
        "source_coverage_digest": source_coverage_digest,
        "source_generation": source_generation,
        "source_revision": source_revision,
        "source_schema_version": source_schema_version,
        "stage": "started",
        "started_at": started,
    }
    folder = Path(control) / "attempts" / attempt_id
    _mkdir_checked(folder, boundary=Path(control))
    _write_exclusive(folder / "00-started.json", _canonical(body))
    _fsync_directory(folder)
    _fsync_directory(folder.parent)
    return AttemptRecord(
        attempt_id,
        "started",
        source_coverage_digest,
        source_generation,
        source_schema_version,
        source_revision,
        None,
        None,
        None,
        started,
        None,
        None,
        None,
        None,
    )


@dataclass(frozen=True)
class StageUpdate:
    """Facts produced by one completed delivery stage."""

    selected_copy_id: str | None = None
    graph_digest: str | None = None
    snapshot_manifest_digest: str | None = None
    error_code: str | None = None
    receiver_copy_id: str | None = None
    receiver_graph_digest: str | None = None
    finished: bool = False


def publish_attempt_stage(
    control: Path,
    current: AttemptRecord,
    stage: AttemptStage,
    updates: StageUpdate = StageUpdate(),
) -> AttemptRecord:
    """Append one later stage. Callers must have completed the real work."""
    if _STAGE_INDEX[stage] <= _STAGE_INDEX[current.stage]:
        raise BackupVerificationError(_ERROR)
    finished_at = _utc_now() if updates.finished or updates.error_code is not None else None
    record = AttemptRecord(
        current.attempt_id,
        stage,
        current.source_coverage_digest,
        current.source_generation,
        current.source_schema_version,
        current.source_revision,
        current.selected_copy_id if updates.selected_copy_id is None else updates.selected_copy_id,
        current.graph_digest if updates.graph_digest is None else updates.graph_digest,
        current.snapshot_manifest_digest
        if updates.snapshot_manifest_digest is None
        else updates.snapshot_manifest_digest,
        current.started_at,
        finished_at if finished_at is not None else current.finished_at,
        updates.error_code,
        current.receiver_copy_id if updates.receiver_copy_id is None else updates.receiver_copy_id,
        current.receiver_graph_digest
        if updates.receiver_graph_digest is None
        else updates.receiver_graph_digest,
    )
    body = {
        "attempt_id": record.attempt_id,
        "error_code": record.error_code,
        "finished_at": record.finished_at,
        "graph_digest": record.graph_digest,
        "kind": _STAGE_KIND,
        "receiver_copy_id": record.receiver_copy_id,
        "receiver_graph_digest": record.receiver_graph_digest,
        "schema_version": 1,
        "selected_copy_id": record.selected_copy_id,
        "snapshot_manifest_digest": record.snapshot_manifest_digest,
        "source_coverage_digest": record.source_coverage_digest,
        "source_generation": record.source_generation,
        "source_revision": record.source_revision,
        "source_schema_version": record.source_schema_version,
        "stage": record.stage,
        "started_at": record.started_at,
    }
    folder = Path(control) / "attempts" / record.attempt_id
    name = f"{_STAGE_INDEX[stage]:02d}-{stage}.json"
    _write_exclusive(folder / name, _canonical(body))
    _fsync_directory(folder)
    if record.stage == "finished" and record.error_code is None:
        _write_success_cache(control, record)
    return record


def _write_success_cache(control: Path, record: AttemptRecord) -> None:
    cache = {
        "attempt_id": record.attempt_id,
        "finished_at": record.finished_at,
        "kind": _CACHE_KIND,
        "receiver_graph_digest": record.receiver_graph_digest,
        "schema_version": 1,
        "source_coverage_digest": record.source_coverage_digest,
    }
    _replace_atomic(Path(control) / "latest-success.json", _canonical(cache))


def read_journal(control: Path) -> JournalView:
    """Reconstruct history. Corrupt or missing files yield unknown history."""
    root = Path(os.path.abspath(control))
    if not os.path.lexists(root):
        return JournalView(None, (), None, None, True)
    try:
        descriptor = load_descriptor(root)
    except BackupVerificationError:
        return JournalView(None, (), None, None, True)
    attempts_root = root / "attempts"
    if not os.path.lexists(attempts_root):
        return JournalView(descriptor, (), None, None, True)
    attempts: list[AttemptRecord] = []
    unknown = False
    try:
        children = sorted(attempts_root.iterdir(), key=lambda path: path.name)
    except OSError:
        return JournalView(descriptor, (), None, None, True)
    for child in children:
        if child.name.startswith("."):
            continue
        record = _read_attempt(child)
        if record is None:
            unknown = True
            continue
        attempts.append(record)
    successes = [
        item
        for item in attempts
        if item.stage == "finished" and item.error_code is None and not item.history_unknown
    ]
    failures = [item for item in attempts if item.error_code is not None]
    last_success = max(
        successes, key=lambda item: item.finished_at or item.started_at, default=None
    )
    latest_failure = max(
        failures, key=lambda item: item.finished_at or item.started_at, default=None
    )
    if _invalid_success_cache(root, last_success):
        unknown = True
        last_success = None
    return JournalView(descriptor, tuple(attempts), last_success, latest_failure, unknown)


def _invalid_success_cache(control: Path, success: AttemptRecord | None) -> bool:
    if success is None:
        return os.path.lexists(control / "latest-success.json")
    return not _cache_matches(control, success)


def _cache_matches(control: Path, success: AttemptRecord) -> bool:
    path = control / "latest-success.json"
    if not os.path.lexists(path):
        return False
    try:
        payload = json.loads(read_regular_bytes(path).decode("utf-8"))
    except Exception:
        return False
    return (
        isinstance(payload, dict)
        and payload.get("schema_version") == 1
        and payload.get("finished_at") == success.finished_at
        and payload.get("kind") == _CACHE_KIND
        and payload.get("attempt_id") == success.attempt_id
        and payload.get("source_coverage_digest") == success.source_coverage_digest
        and payload.get("receiver_graph_digest") == success.receiver_graph_digest
    )


def _read_attempt(folder: Path) -> AttemptRecord | None:
    try:
        files = sorted(path for path in folder.iterdir() if path.suffix == ".json")
    except OSError:
        return None
    if not files:
        return None
    parsed: list[dict[str, Any]] = []
    for path in files:
        try:
            payload = json.loads(read_regular_bytes(path).decode("utf-8"))
        except Exception:
            return None
        if not isinstance(payload, dict) or payload.get("kind") != _STAGE_KIND:
            return None
        parsed.append(payload)
    latest = parsed[-1]
    stage = latest.get("stage")
    if not _valid_stage_history(folder, files, parsed) or stage not in _STAGE_INDEX:
        return None
    return AttemptRecord(
        str(latest["attempt_id"]),
        stage,  # type: ignore[arg-type]
        str(latest["source_coverage_digest"]),
        str(latest["source_generation"]),
        int(latest["source_schema_version"]),
        int(latest["source_revision"]),
        latest.get("selected_copy_id"),
        latest.get("graph_digest"),
        latest.get("snapshot_manifest_digest"),
        str(latest["started_at"]),
        latest.get("finished_at"),
        latest.get("error_code"),
        latest.get("receiver_copy_id"),
        latest.get("receiver_graph_digest"),
    )


def _valid_stage_history(folder: Path, files: list[Path], records: list[dict[str, Any]]) -> bool:
    required = {
        "attempt_id",
        "source_coverage_digest",
        "source_generation",
        "source_schema_version",
        "source_revision",
        "started_at",
        "stage",
    }
    fixed = required - {"stage"}
    if not records or records[0].get("stage") != "started":
        return False
    for path, record in zip(files, records, strict=True):
        stage = record.get("stage")
        if (
            not required <= record.keys()
            or stage not in _STAGE_INDEX
            or record.get("schema_version") != 1
            or record["attempt_id"] != folder.name
            or path.name != f"{_STAGE_INDEX[stage]:02d}-{stage}.json"
            or any(record[key] != records[0][key] for key in fixed)
        ):
            return False
        if (
            type(record["source_revision"]) is not int
            or type(record["source_schema_version"]) is not int
        ):
            return False
    latest = records[-1]
    if latest["stage"] == "finished" and latest.get("error_code") is None:
        stages = {record["stage"] for record in records}
        if not {"local_verified", "destination_verified"} <= stages:
            return False
        if not all(
            latest.get(key)
            for key in (
                "finished_at",
                "selected_copy_id",
                "graph_digest",
                "snapshot_manifest_digest",
                "receiver_copy_id",
                "receiver_graph_digest",
            )
        ):
            return False
    return True


def execution_lock(control: Path, *, timeout_ms: int = 5_000) -> CoordinationLease:
    """Exclusive lock for one delivery worker on this control directory."""
    return CoordinationLease(control_lock(control), exclusive=True, timeout_ms=timeout_ms)
