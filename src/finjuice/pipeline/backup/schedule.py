"""Scheduled backup jobs, independent key recovery, and ops status."""

from __future__ import annotations

import hashlib
import shutil
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.backup.paths import (
    reject_overlap,
    reject_symlink_chain,
    require_outside_program_repo,
)
from finjuice.pipeline.backup.retention import (
    DEFAULT_DAILY,
    DEFAULT_MONTHLY,
    DEFAULT_WEEKLY,
)
from finjuice.pipeline.storage.sqlite.backup import backup_status

JobName = Literal["local_copy", "off_device_copy", "restore_drill"]
JobStatus = Literal["ok", "failed", "never"]
OpsHealth = Literal["ok", "failed", "stale", "never"]

RPO_TARGET = timedelta(hours=24)
RTO_TARGET = timedelta(hours=1)
RESTORE_DRILL_INTERVAL = timedelta(days=30)
FAILURE_RETRY = timedelta(hours=1)
DEFAULT_INTERVALS: dict[JobName, timedelta] = {
    "local_copy": timedelta(hours=24),
    "off_device_copy": timedelta(hours=24),
    "restore_drill": RESTORE_DRILL_INTERVAL,
}


def _require_utc(value: datetime, *, context: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BackupError(
            f"{context} must be timezone-aware UTC.",
            code="INVALID_ARGS",
        )
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise BackupError(
            f"{context} must be timezone-aware UTC.",
            code="INVALID_ARGS",
        )
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ScheduledJob:
    """One recurring backup operation tracked for the next scheduler tick."""

    name: JobName
    interval: timedelta = timedelta(hours=24)
    last_started_at: datetime | None = None
    last_finished_at: datetime | None = None
    last_status: JobStatus = "never"
    last_error_code: str | None = None
    key_recovery_confirmed: bool = False
    consecutive_failures: int = 0

    def __post_init__(self) -> None:
        if self.interval.total_seconds() < 0:
            raise BackupError("Job interval must be non-negative.", code="INVALID_ARGS")
        if self.consecutive_failures < 0:
            raise BackupError("consecutive_failures must be non-negative.", code="INVALID_ARGS")
        for field_name, stamp in (
            ("last_started_at", self.last_started_at),
            ("last_finished_at", self.last_finished_at),
        ):
            if stamp is not None:
                _require_utc(stamp, context=field_name)


@dataclass(frozen=True)
class JobOutcome:
    """Result of one scheduled attempt. Does not include private paths."""

    status: Literal["ok", "failed"]
    finished_at: datetime
    error_code: str | None = None
    key_recovery_confirmed: bool = False

    def __post_init__(self) -> None:
        _require_utc(self.finished_at, context="JobOutcome.finished_at")
        if self.status == "failed" and not self.error_code:
            raise BackupError("Failed job outcomes require an error_code.", code="INVALID_ARGS")


def next_run_at(job: ScheduledJob, now: datetime) -> datetime:
    """Return the next due time for ``job``.

    A failed job is retried after :data:`FAILURE_RETRY`. A job that has never
    run is due immediately. Successful jobs wait for their interval.
    """
    current = _require_utc(now, context="now")
    if job.last_status == "never" or job.last_finished_at is None:
        return current
    if job.last_status == "failed":
        return job.last_finished_at + FAILURE_RETRY
    return job.last_finished_at + job.interval


def apply_job_outcome(job: ScheduledJob, outcome: JobOutcome) -> ScheduledJob:
    """Record success or failure without mutating the previous healthy copy.

    An off-device copy that reports success without independent key recovery is
    stored as a failure so the last confirmed copy remains the success marker.
    """
    confirmed = outcome.key_recovery_confirmed
    if job.name == "off_device_copy" and outcome.status == "ok" and not confirmed:
        return replace(
            job,
            last_finished_at=outcome.finished_at,
            last_status="failed",
            last_error_code="KEY_RECOVERY_REQUIRED",
            key_recovery_confirmed=False,
            consecutive_failures=job.consecutive_failures + 1,
        )
    if outcome.status == "failed":
        return replace(
            job,
            last_finished_at=outcome.finished_at,
            last_status="failed",
            last_error_code=outcome.error_code,
            consecutive_failures=job.consecutive_failures + 1,
        )
    recovered = confirmed if job.name == "off_device_copy" else job.key_recovery_confirmed
    return replace(
        job,
        last_finished_at=outcome.finished_at,
        last_status="ok",
        last_error_code=None,
        key_recovery_confirmed=recovered,
        consecutive_failures=0,
    )


@dataclass(frozen=True)
class KeyRecoveryRequest:
    """Independent recovery-store check. Source host sessions are rejected."""

    key_store: Path
    source_root: Path
    expected_fingerprint: str


@dataclass(frozen=True)
class KeyRecoveryResult:
    """Privacy-safe confirmation that a sealed copy can be unlocked."""

    confirmed: bool
    store_role: Literal["independent_recovery_store"]
    fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        """Return a payload without paths or key material."""
        return {
            "confirmed": self.confirmed,
            "fingerprint": self.fingerprint,
            "store_role": self.store_role,
        }


def _fingerprint_key(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def confirm_key_recovery(request: KeyRecoveryRequest) -> KeyRecoveryResult:
    """Confirm a recovery key without reading the source workspace.

    The key must live in a store that does not overlap the source tree. Matching
    the sealed fingerprint is required before an off-device restore proceeds.
    """
    expected = request.expected_fingerprint
    if not expected.startswith("sha256:") or len(expected) != 71:
        raise BackupError("Recovery key fingerprint is invalid.", code="INVALID_ARGS")
    source = require_outside_program_repo(request.source_root, context="backup source")
    store = require_outside_program_repo(request.key_store, context="recovery key store")
    reject_overlap(store, source, code="VALIDATION_FAILED")
    key_file = reject_symlink_chain(store)
    if not key_file.is_file() or key_file.is_symlink():
        raise BackupError(
            "Recovery key is missing from the independent store.",
            code="FILE_NOT_FOUND",
            suggestion="Place the recovery key in a store that is not the source host session.",
        )
    fingerprint = _fingerprint_key(key_file)
    if fingerprint != expected:
        raise BackupError(
            "Recovery key does not match the sealed copy.",
            code="VALIDATION_FAILED",
        )
    return KeyRecoveryResult(
        confirmed=True,
        store_role="independent_recovery_store",
        fingerprint=fingerprint,
    )


@dataclass(frozen=True)
class OpsObservation:
    """Inputs for status inspection. Callers pass timestamps, not private paths."""

    now: datetime
    last_success_at: datetime | None
    last_off_device_at: datetime | None
    last_restore_verified_at: datetime | None
    last_job_status: JobStatus
    key_recovery_confirmed: bool
    healthy_off_device: bool


@dataclass(frozen=True)
class OpsStatus:
    """Last success, remote copy, restore verification, and actionable alerts."""

    last_success_at: datetime | None
    last_off_device_at: datetime | None
    last_restore_verified_at: datetime | None
    health: OpsHealth
    actionable: tuple[str, ...]
    retention_policy: dict[str, int]
    rpo_target_seconds: int
    rto_target_seconds: int

    def to_dict(self) -> dict[str, Any]:
        """Return a privacy-safe status payload."""
        off_device = self.last_off_device_at
        restored = self.last_restore_verified_at
        success = self.last_success_at
        return {
            "actionable": list(self.actionable),
            "health": self.health,
            "last_off_device_at": None if off_device is None else off_device.isoformat(),
            "last_restore_verified_at": None if restored is None else restored.isoformat(),
            "last_success_at": None if success is None else success.isoformat(),
            "retention_policy": dict(self.retention_policy),
            "rpo_target_seconds": self.rpo_target_seconds,
            "rto_target_seconds": self.rto_target_seconds,
        }


def _is_stale(stamp: datetime | None, now: datetime, limit: timedelta) -> bool:
    if stamp is None:
        return True
    return now - stamp > limit


def _actionable_alerts(observation: OpsObservation, now: datetime) -> tuple[str, ...]:
    alerts: list[str] = []
    if observation.last_job_status == "failed":
        alerts.append("job_failed")
    if observation.last_success_at is None:
        alerts.append("never_succeeded")
    elif _is_stale(observation.last_success_at, now, RPO_TARGET):
        alerts.append("rpo_stale")
    if not observation.key_recovery_confirmed:
        alerts.append("key_recovery_unconfirmed")
    if not observation.healthy_off_device:
        alerts.append("missing_off_device_copy")
    if _is_stale(observation.last_restore_verified_at, now, RESTORE_DRILL_INTERVAL):
        alerts.append("restore_drill_overdue")
    return tuple(alerts)


def _health_from_alerts(observation: OpsObservation, alerts: tuple[str, ...]) -> OpsHealth:
    if observation.last_job_status == "failed":
        return "failed"
    if "never_succeeded" in alerts:
        return "never"
    if any(code in alerts for code in ("rpo_stale", "restore_drill_overdue")):
        return "stale"
    if alerts:
        return "stale"
    return "ok"


def publish_off_device_copy(local_backup: Path, destination: Path) -> Path:
    """Copy a complete local backup to a new off-device path and re-verify it.

    The source generation is not read. Publication fails closed if the
    destination already exists or the copied tree is incomplete.
    """
    source = require_outside_program_repo(local_backup, context="local backup")
    dest = require_outside_program_repo(destination, context="off-device backup")
    reject_overlap(source, dest)
    status = backup_status(source)
    if not status.complete:
        raise BackupError(
            "Off-device publish requires a complete local backup.",
            code="VALIDATION_FAILED",
        )
    if dest.exists():
        raise BackupError("Off-device destination already exists.", code="VALIDATION_FAILED")
    shutil.copytree(source, dest, symlinks=False)
    copied = backup_status(dest)
    if not copied.complete:
        raise BackupError("Off-device copy is incomplete.", code="VALIDATION_FAILED")
    return dest


def inspect_ops_status(observation: OpsObservation) -> OpsStatus:
    """Report last success/remote/restore times and only actionable alerts.

    A healthy schedule with a recent success, confirmed key recovery, a
    healthy off-device copy, and a current restore drill produces no alerts.
    """
    now = _require_utc(observation.now, context="now")
    for field_name, stamp in (
        ("last_success_at", observation.last_success_at),
        ("last_off_device_at", observation.last_off_device_at),
        ("last_restore_verified_at", observation.last_restore_verified_at),
    ):
        if stamp is not None:
            _require_utc(stamp, context=field_name)
    alerts = _actionable_alerts(observation, now)
    return OpsStatus(
        last_success_at=observation.last_success_at,
        last_off_device_at=observation.last_off_device_at,
        last_restore_verified_at=observation.last_restore_verified_at,
        health=_health_from_alerts(observation, alerts),
        actionable=alerts,
        retention_policy={
            "daily": DEFAULT_DAILY,
            "monthly": DEFAULT_MONTHLY,
            "weekly": DEFAULT_WEEKLY,
        },
        rpo_target_seconds=int(RPO_TARGET.total_seconds()),
        rto_target_seconds=int(RTO_TARGET.total_seconds()),
    )
