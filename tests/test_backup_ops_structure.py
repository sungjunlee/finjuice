"""Scheduled backup ops: retention, next run, restore drill, and runbook."""

from __future__ import annotations

import hashlib
import importlib
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.backup.drill import (
    RestoreDrillRequest,
    incident_runbook,
    run_restore_drill,
)
from finjuice.pipeline.backup.errors import BackupError
from finjuice.pipeline.backup.retention import (
    DEFAULT_DAILY,
    DEFAULT_MONTHLY,
    DEFAULT_WEEKLY,
    BackupCopy,
    RetentionPolicy,
    plan_retention,
)
from finjuice.pipeline.backup.schedule import (
    DEFAULT_INTERVALS,
    FAILURE_RETRY,
    JobOutcome,
    KeyRecoveryRequest,
    OpsObservation,
    ScheduledJob,
    apply_job_outcome,
    confirm_key_recovery,
    inspect_ops_status,
    next_run_at,
    publish_off_device_copy,
)
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryBuilder
from finjuice.pipeline.storage.sqlite.backup import create_backup
from finjuice.pipeline.storage.sqlite.records import SourceOccurrenceRecord

UTC = timezone.utc


def _stamp(days: int = 0, hours: int = 0) -> datetime:
    return datetime(2026, 9, 13, 12, 0, tzinfo=UTC) - timedelta(days=days, hours=hours)


def _copy(
    copy_id: str,
    *,
    days: int = 0,
    healthy: bool = True,
    pinned: bool = False,
    location: str = "off_device",
) -> BackupCopy:
    return BackupCopy(
        copy_id=copy_id,
        created_at=_stamp(days=days),
        healthy=healthy,
        location=location,  # type: ignore[arg-type]
        pinned=pinned,
    )


def _fingerprint(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _post_cutover_generation(root: Path) -> GenerationPaths:
    paths = GenerationPaths(root)
    with RepositoryBuilder(paths, str(uuid4())) as builder:
        artifact = builder.publish_source(io.BytesIO(b"synthetic post-cutover source bytes"))
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=str(uuid4()),
                artifact_id=artifact.artifact_id,
                occurrence_kind="banksalad_xlsx",
                original_filename="synthetic.xlsx",
            )
        )
        builder.finalize()
    return paths


def test_retention_defaults_match_published_example_policy() -> None:
    policy = RetentionPolicy()

    assert (policy.daily, policy.weekly, policy.monthly) == (
        DEFAULT_DAILY,
        DEFAULT_WEEKLY,
        DEFAULT_MONTHLY,
    )
    assert (policy.daily, policy.weekly, policy.monthly) == (14, 8, 12)


def test_retention_keeps_latest_healthy_and_pinned_baseline() -> None:
    # Arrange: a tight window would otherwise drop the newest healthy copy and
    # the pinned pre-cutover baseline.
    copies = (
        _copy("pinned-baseline", days=400, pinned=True),
        _copy("old-healthy", days=30),
        _copy("mid-unhealthy", days=10, healthy=False),
        _copy("latest-healthy", days=0),
        _copy("newer-unhealthy", days=0, healthy=False),
    )
    policy = RetentionPolicy(daily=1, weekly=0, monthly=0)

    # Act
    plan = plan_retention(copies, policy)

    # Assert
    assert plan.latest_healthy_id == "latest-healthy"
    assert "latest-healthy" in plan.keep_ids
    assert "pinned-baseline" in plan.keep_ids
    assert "latest-healthy" not in plan.delete_ids
    assert "pinned-baseline" not in plan.delete_ids
    assert "mid-unhealthy" in plan.delete_ids
    assert "newer-unhealthy" in plan.delete_ids
    assert "old-healthy" in plan.delete_ids


def test_schedule_next_run_failure_handling_and_key_recovery(tmp_path: Path) -> None:
    # Arrange
    now = _stamp()
    job = ScheduledJob(name="off_device_copy", interval=timedelta(hours=24))
    source = tmp_path / "source"
    source.mkdir()
    key_store = tmp_path / "recovery-key"
    key_store.write_bytes(b"synthetic-recovery-key")
    overlapping = source / "session-key"
    overlapping.write_bytes(b"synthetic-recovery-key")

    # Act
    due_immediately = next_run_at(job, now)
    failed = apply_job_outcome(
        job,
        JobOutcome(status="failed", finished_at=now, error_code="TRANSFER_FAILED"),
    )
    retry_at = next_run_at(failed, now)
    recovered = confirm_key_recovery(
        KeyRecoveryRequest(
            key_store=key_store,
            source_root=source,
            expected_fingerprint=_fingerprint(key_store),
        )
    )
    succeeded = apply_job_outcome(
        failed,
        JobOutcome(
            status="ok",
            finished_at=now,
            key_recovery_confirmed=True,
        ),
    )
    next_success = next_run_at(succeeded, now)
    missing_key = apply_job_outcome(
        succeeded,
        JobOutcome(status="ok", finished_at=now + timedelta(hours=1)),
    )

    # Assert
    assert due_immediately == now
    assert DEFAULT_INTERVALS["off_device_copy"] == timedelta(hours=24)
    assert DEFAULT_INTERVALS["restore_drill"].days == 30
    assert failed.last_status == "failed"
    assert failed.last_error_code == "TRANSFER_FAILED"
    assert retry_at == now + FAILURE_RETRY
    assert recovered.confirmed is True
    assert recovered.store_role == "independent_recovery_store"
    assert succeeded.last_status == "ok"
    assert succeeded.key_recovery_confirmed is True
    assert next_success == now + timedelta(hours=24)
    assert missing_key.last_status == "failed"
    assert missing_key.last_error_code == "KEY_RECOVERY_REQUIRED"
    with pytest.raises(BackupError, match="overlap"):
        confirm_key_recovery(
            KeyRecoveryRequest(
                key_store=overlapping,
                source_root=source,
                expected_fingerprint=_fingerprint(overlapping),
            )
        )


def test_ops_status_alerts_only_actionable_changes() -> None:
    # Arrange
    now = _stamp()
    healthy = OpsObservation(
        now=now,
        last_success_at=now - timedelta(hours=2),
        last_off_device_at=now - timedelta(hours=2),
        last_restore_verified_at=now - timedelta(days=7),
        last_job_status="ok",
        key_recovery_confirmed=True,
        healthy_off_device=True,
    )
    stale = OpsObservation(
        now=now,
        last_success_at=now - timedelta(hours=25),
        last_off_device_at=now - timedelta(hours=25),
        last_restore_verified_at=now - timedelta(days=7),
        last_job_status="ok",
        key_recovery_confirmed=True,
        healthy_off_device=True,
    )
    failed = OpsObservation(
        now=now,
        last_success_at=now - timedelta(hours=2),
        last_off_device_at=now - timedelta(hours=2),
        last_restore_verified_at=now - timedelta(days=7),
        last_job_status="failed",
        key_recovery_confirmed=True,
        healthy_off_device=True,
    )

    # Act
    healthy_status = inspect_ops_status(healthy)
    stale_status = inspect_ops_status(stale)
    failed_status = inspect_ops_status(failed)

    # Assert
    assert healthy_status.health == "ok"
    assert healthy_status.actionable == ()
    assert healthy_status.retention_policy == {"daily": 14, "weekly": 8, "monthly": 12}
    assert stale_status.health == "stale"
    assert stale_status.actionable == ("rpo_stale",)
    assert failed_status.health == "failed"
    assert "job_failed" in failed_status.actionable
    assert "rpo_stale" not in failed_status.actionable


def test_restore_drill_restores_off_device_copy_and_verifies_queries(tmp_path: Path) -> None:
    # Arrange
    generation = _post_cutover_generation(tmp_path / "generation")
    local_backup = tmp_path / "local-backup"
    created = create_backup(generation.database, local_backup)
    off_device = publish_off_device_copy(local_backup, tmp_path / "off-device")
    target = tmp_path / "isolated-restore"
    copied_at = _stamp(hours=3)
    now = _stamp()

    # Act
    result = run_restore_drill(
        RestoreDrillRequest(
            off_device_copy=off_device,
            isolated_target=target,
            last_successful_copy_at=copied_at,
            now=now,
            key_recovery_confirmed=True,
        )
    )

    # Assert
    assert created.complete
    assert result.status == "ok"
    assert result.generation_status == "inactive"
    assert result.restore_verified is True
    check_ids = {check.check_id: check for check in result.query_checks}
    assert check_ids["repository_meta"].status == "pass"
    assert check_ids["source_artifacts"].checked_count >= 1
    assert check_ids["entities"].checked_count >= 1
    assert (target / "finjuice.sqlite3").is_file()
    assert result.rpo.goal == "rpo"
    assert result.rpo.met is True
    assert result.rpo.coverage == "measured"
    assert result.rto.goal == "rto"
    assert result.rto.met is True
    assert result.rto.coverage == "measured"
    assert result.rpo.target_seconds == 24 * 60 * 60
    assert result.rto.target_seconds == 60 * 60
    payload = result.to_dict()
    assert str(generation.root) not in str(payload)
    assert "synthetic" not in str(payload)


def test_restore_drill_rejects_unconfirmed_key_recovery(tmp_path: Path) -> None:
    request = RestoreDrillRequest(
        off_device_copy=tmp_path / "off-device",
        isolated_target=tmp_path / "target",
        last_successful_copy_at=_stamp(hours=1),
        now=_stamp(),
        key_recovery_confirmed=False,
    )

    with pytest.raises(BackupError, match="key recovery"):
        run_restore_drill(request)


def test_rpo_rto_runbook_distinguishes_unguaranteed_goals() -> None:
    # Arrange / Act
    source_failure = incident_runbook("source_failure")
    post_cutover = incident_runbook("post_cutover_records")

    # Assert
    assert source_failure.guaranteed_goals == ()
    assert source_failure.unguaranteed_goals == ("rpo_24h", "rto_1h")
    assert post_cutover.guaranteed_goals == ()
    assert post_cutover.unguaranteed_goals == ("rpo_24h", "rto_1h")
    assert all(not step.overwrites_active_generation for step in post_cutover.steps)
    assert all(step.preserves_post_cutover_records for step in post_cutover.steps)
    step_ids = {step.step_id for step in post_cutover.steps}
    assert "keep_pre_cutover_baseline_pinned" in step_ids
    assert "fix_forward_or_replay_new_records" in step_ids
    payload = post_cutover.to_dict()
    assert payload["unguaranteed_goals"] == ["rpo_24h", "rto_1h"]
    assert payload["guaranteed_goals"] == []


def test_backup_ops_public_names_live_outside_legacy_ops_module() -> None:
    """New scheduled-ops APIs stay in dedicated modules, not legacy ops.py."""
    retention = importlib.import_module("finjuice.pipeline.backup.retention")
    schedule = importlib.import_module("finjuice.pipeline.backup.schedule")
    drill = importlib.import_module("finjuice.pipeline.backup.drill")
    ops = importlib.import_module("finjuice.pipeline.backup.ops")

    assert retention.plan_retention is plan_retention
    assert schedule.next_run_at is next_run_at
    assert schedule.confirm_key_recovery is confirm_key_recovery
    assert drill.run_restore_drill is run_restore_drill
    assert drill.incident_runbook is incident_runbook
    assert not hasattr(ops, "plan_retention")
    assert not hasattr(ops, "run_restore_drill")
    assert not hasattr(ops, "incident_runbook")
