"""Isolated restore drills, representative reads, RPO/RTO, and incident runbooks.

A one-shot measured restore that meets the RPO/RTO targets is recorded as
``measured``, not ``guaranteed``. Recurring schedule proof is a separate status.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.backup.paths import (
    reject_overlap,
    require_outside_program_repo,
)
from finjuice.pipeline.backup.schedule import RPO_TARGET, RTO_TARGET
from finjuice.pipeline.storage.sqlite.backup import restore_backup as restore_sqlite_backup
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

CheckStatus = Literal["pass", "fail"]
GoalCoverage = Literal["measured", "not_guaranteed"]
IncidentKind = Literal["source_failure", "post_cutover_records"]

REPRESENTATIVE_CHECKS = ("repository_meta", "source_artifacts", "entities")


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
class RestoreDrillRequest:
    """Inputs for one isolated off-device restore drill."""

    off_device_copy: Path
    isolated_target: Path
    last_successful_copy_at: datetime
    now: datetime
    key_recovery_confirmed: bool


@dataclass(frozen=True)
class QueryCheck:
    """Privacy-safe representative read: counts and pass/fail only."""

    check_id: str
    status: CheckStatus
    checked_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return the public query-check payload."""
        return {
            "check_id": self.check_id,
            "checked_count": self.checked_count,
            "status": self.status,
        }


@dataclass(frozen=True)
class GoalMeasurement:
    """One RPO or RTO measurement with an explicit guarantee distinction."""

    goal: Literal["rpo", "rto"]
    target_seconds: int
    measured_seconds: float
    met: bool
    coverage: GoalCoverage

    def to_dict(self) -> dict[str, Any]:
        """Return the public goal payload."""
        return {
            "coverage": self.coverage,
            "goal": self.goal,
            "measured_seconds": self.measured_seconds,
            "met": self.met,
            "target_seconds": self.target_seconds,
        }


@dataclass(frozen=True)
class RestoreDrillResult:
    """Receipt for one verified isolated restore of an off-device copy."""

    status: Literal["ok"]
    generation_status: Literal["inactive"]
    query_checks: tuple[QueryCheck, ...]
    rpo: GoalMeasurement
    rto: GoalMeasurement
    restore_verified: bool
    file_count: int
    byte_count: int

    def to_dict(self) -> dict[str, Any]:
        """Return a privacy-safe drill payload without paths or financial rows."""
        return {
            "byte_count": self.byte_count,
            "file_count": self.file_count,
            "generation_status": self.generation_status,
            "query_checks": [check.to_dict() for check in self.query_checks],
            "restore_verified": self.restore_verified,
            "rpo": self.rpo.to_dict(),
            "rto": self.rto.to_dict(),
            "status": self.status,
        }


@dataclass(frozen=True)
class RunbookStep:
    """One operator step. Never restores an old baseline over new records."""

    step_id: str
    required: bool
    preserves_post_cutover_records: bool
    overwrites_active_generation: bool


@dataclass(frozen=True)
class IncidentRunbook:
    """Failure or post-cutover preservation procedure with guarantee notes."""

    incident: IncidentKind
    steps: tuple[RunbookStep, ...]
    guaranteed_goals: tuple[str, ...]
    unguaranteed_goals: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return the public runbook payload."""
        return {
            "guaranteed_goals": list(self.guaranteed_goals),
            "incident": self.incident,
            "steps": [
                {
                    "overwrites_active_generation": step.overwrites_active_generation,
                    "preserves_post_cutover_records": step.preserves_post_cutover_records,
                    "required": step.required,
                    "step_id": step.step_id,
                }
                for step in self.steps
            ],
            "unguaranteed_goals": list(self.unguaranteed_goals),
        }


def _query_check(check_id: str, rows: list[Any], *, require_rows: bool) -> QueryCheck:
    count = len(rows)
    passed = count > 0 if require_rows else True
    return QueryCheck(check_id=check_id, status="pass" if passed else "fail", checked_count=count)


def representative_query_checks(database: Path) -> tuple[QueryCheck, ...]:
    """Run representative reads on a restored copy. Returns counts only."""
    with RepositoryReader(database) as reader:
        meta = reader.rows("repository_meta")
        artifacts = reader.rows("source_artifacts")
        entities = reader.rows("entities")
    return (
        _query_check("repository_meta", meta, require_rows=True),
        _query_check("source_artifacts", artifacts, require_rows=True),
        _query_check("entities", entities, require_rows=False),
    )


def _measure_goal(
    goal: Literal["rpo", "rto"],
    *,
    measured_seconds: float,
    target_seconds: int,
) -> GoalMeasurement:
    if measured_seconds < 0:
        raise BackupError("Duration measurements cannot be negative.", code="VALIDATION_FAILED")
    return GoalMeasurement(
        goal=goal,
        target_seconds=target_seconds,
        measured_seconds=measured_seconds,
        met=measured_seconds <= target_seconds,
        coverage="measured",
    )


def run_restore_drill(request: RestoreDrillRequest) -> RestoreDrillResult:
    """Restore an off-device copy into a new isolated path and verify reads.

    The source generation is never opened. A successful drill measures RPO/RTO
    once; that measurement is not a standing guarantee of the 24h/1h objectives.
    """
    if not request.key_recovery_confirmed:
        raise BackupError(
            "Off-device restore requires confirmed independent key recovery.",
            code="VALIDATION_FAILED",
            suggestion="Confirm the recovery key from a store that is not the source host session.",
        )
    now = _require_utc(request.now, context="now")
    last_copy = _require_utc(request.last_successful_copy_at, context="last_successful_copy_at")
    off_device = require_outside_program_repo(request.off_device_copy, context="off-device backup")
    target = require_outside_program_repo(request.isolated_target, context="restore target")
    reject_overlap(target, off_device, code="VALIDATION_FAILED")
    started = time.perf_counter()
    restored = restore_sqlite_backup(off_device, target)
    checks = representative_query_checks(restored.database)
    elapsed = time.perf_counter() - started
    if any(check.status != "pass" for check in checks):
        raise BackupError(
            "Restored copy failed representative query verification.",
            code="VALIDATION_FAILED",
        )
    rpo = _measure_goal(
        "rpo",
        measured_seconds=(now - last_copy).total_seconds(),
        target_seconds=int(RPO_TARGET.total_seconds()),
    )
    rto = _measure_goal(
        "rto",
        measured_seconds=elapsed,
        target_seconds=int(RTO_TARGET.total_seconds()),
    )
    return RestoreDrillResult(
        status="ok",
        generation_status="inactive",
        query_checks=checks,
        rpo=rpo,
        rto=rto,
        restore_verified=restored.verified,
        file_count=restored.file_count,
        byte_count=restored.byte_count,
    )


_SOURCE_FAILURE_STEPS = (
    RunbookStep(
        step_id="recover_key_independent_store",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
    RunbookStep(
        step_id="restore_off_device_copy_isolated_path",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
    RunbookStep(
        step_id="verify_representative_queries",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
    RunbookStep(
        step_id="record_measured_rpo_rto",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
)

_POST_CUTOVER_STEPS = (
    RunbookStep(
        step_id="fence_writers_and_snapshot_active_generation",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
    RunbookStep(
        step_id="keep_pre_cutover_baseline_pinned",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
    RunbookStep(
        step_id="restore_isolated_path_not_active_generation",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
    RunbookStep(
        step_id="fix_forward_or_replay_new_records",
        required=True,
        preserves_post_cutover_records=True,
        overwrites_active_generation=False,
    ),
)

_UNGUARANTEED = ("rpo_24h", "rto_1h")


def incident_runbook(incident: IncidentKind) -> IncidentRunbook:
    """Return the failure or new-record preservation procedure.

    RPO 24h and RTO 1h remain objectives until recurring scheduled success
    proves them. A single drill never lists them as guaranteed.
    """
    if incident == "source_failure":
        steps = _SOURCE_FAILURE_STEPS
    else:
        steps = _POST_CUTOVER_STEPS
    if any(step.overwrites_active_generation for step in steps):
        raise BackupError(
            "Runbook must not overwrite the active generation.",
            code="VALIDATION_FAILED",
        )
    return IncidentRunbook(
        incident=incident,
        steps=steps,
        guaranteed_goals=(),
        unguaranteed_goals=_UNGUARANTEED,
    )
