"""Filesystem backup delivery worker, status, and post-commit reporting.

Domain mutation receipts stay immutable. Delivery failures do not rerun
mutations. Local paths are destination_verified evidence, not off-device proof.
"""

from __future__ import annotations

import os
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.backup_coverage import (
    CommitObservation,
    CoverageComparison,
    SourceObservation,
    compare_commit_coverage,
    observe_source_commits,
    recording_from_observation,
    select_covering_copy,
)
from finjuice.pipeline.storage.sqlite.backup_delivery_journal import (
    AttemptRecord,
    DeliveryDescriptor,
    StageUpdate,
    execution_lock,
    initialize_delivery_control,
    publish_attempt_stage,
    read_journal,
    start_attempt,
)
from finjuice.pipeline.storage.sqlite.backup_io import BackupPayloadError
from finjuice.pipeline.storage.sqlite.errors import (
    BackupDeliveryError,
    BackupVerificationError,
    RepositoryBackupError,
)
from finjuice.pipeline.storage.sqlite.mutations import MutationReceipt
from finjuice.pipeline.storage.sqlite.recovery_bundle import (
    ExpectedRecoveryGraph,
    RecoveryCaptureInput,
    RecoveryGraphReceipt,
    verify_recovery_bundle,
)
from finjuice.pipeline.storage.sqlite.recovery_store import (
    capture_into_store,
    enrollment_digest,
    list_recovery_store,
    open_recovery_store,
    receive_graph_into_store,
)
from finjuice.pipeline.storage.sqlite.recovery_store_lock import read_store_identity

BackupLane = Literal["covered", "pending", "verification_failed", "unknown", "transfer_failed"]


@dataclass(frozen=True)
class DeliveryJob:
    """Operator-selected local filesystem delivery job."""

    data_dir: Path
    expected: ExpectedRecoveryGraph
    evidence_provider: ActivationEvidenceProvider
    sender_store: Path
    destination_store: Path
    control_dir: Path
    capture_source: RecoveryCaptureInput | None = None
    timeout_ms: int = 5_000
    recording: MutationReceipt | None = None

    def __post_init__(self) -> None:
        control = Path(os.path.abspath(self.control_dir))
        for selected in (self.data_dir, self.sender_store, self.destination_store):
            root = Path(os.path.abspath(selected))
            if control == root or root in control.parents or control in root.parents:
                raise BackupDeliveryError("control_overlaps_data_or_store")


@dataclass(frozen=True)
class DeliveryReport:
    """Privacy-safe recording plus backup lanes derived from observed facts."""

    kind: str
    job_id: str
    recording: dict[str, Any] | None
    local: BackupLane
    destination: BackupLane
    source_observed_revision: int
    coverage_as_of: str
    pending_commit_count: int | None
    last_verified_at: str | None
    last_attempt_error_code: str | None
    history_unknown: bool
    attempt: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "attempt": self.attempt,
            "backup": {"destination": self.destination, "local": self.local},
            "coverage_as_of": self.coverage_as_of,
            "history_unknown": self.history_unknown,
            "job_id": self.job_id,
            "kind": self.kind,
            "last_attempt_error_code": self.last_attempt_error_code,
            "last_verified_at": self.last_verified_at,
            "pending_commit_count": self.pending_commit_count,
            "recording": self.recording,
            "source_observed_revision": self.source_observed_revision,
        }
        return payload


def _before_journal_write() -> None:
    """Test seam invoked immediately before a durable journal stage write."""
    return None


def _after_destination_publish() -> None:
    """Test seam invoked after receiver publication and before sender journal."""
    return None


def _after_local_graph() -> None:
    """Test seam invoked after a local covering graph exists and before journal."""
    return None


def _lane(comparison: CoverageComparison) -> BackupLane:
    if comparison.status == "transfer_failed":
        return "transfer_failed"
    if comparison.status == "covered":
        return "covered"
    if comparison.status == "pending":
        return "pending"
    if comparison.status == "verification_failed":
        return "verification_failed"
    return "unknown"


def _recording(job: DeliveryJob, source: SourceObservation) -> dict[str, Any] | None:
    receipt = job.recording
    if receipt is None:
        return None
    found = recording_from_observation(
        source,
        changeset_id=receipt.changeset_id,
        committed_revision=receipt.committed_revision,
        replayed=receipt.replayed,
    )
    if found is None:
        return {"status": "unknown", "replayed": receipt.replayed}
    return found


def _inventory_candidates(
    store: Path, expected: ExpectedRecoveryGraph, timeout_ms: int
) -> tuple[Any, Any, tuple[tuple[str, CommitObservation, str, str], ...]]:
    inventory = list_recovery_store(store, expected, timeout_ms=timeout_ms)
    opened = open_recovery_store(store, expected, timeout_ms=timeout_ms)
    candidates: list[tuple[str, CommitObservation, str, str]] = []
    for item in inventory.copies:
        if item.health != "healthy" or item.commit_observation is None:
            continue
        if item.graph_digest is None or item.snapshot_manifest_digest is None:
            continue
        candidates.append(
            (
                item.copy_id,
                item.commit_observation,
                item.graph_digest,
                item.snapshot_manifest_digest,
            )
        )
    return inventory, opened, tuple(candidates)


def _compare_store(
    source: SourceObservation,
    store: Path,
    expected: ExpectedRecoveryGraph,
    timeout_ms: int,
) -> CoverageComparison:
    try:
        _inventory, _opened, candidates = _inventory_candidates(store, expected, timeout_ms)
    except BackupVerificationError:
        unavailable = compare_commit_coverage(source, None)
        return CoverageComparison(
            "unknown",
            None,
            unavailable.source_revision,
            None,
            None,
            None,
            None,
            unavailable.coverage_as_of,
        )
    selected = select_covering_copy(source.commit_set(), candidates)
    if selected is not None:
        return compare_commit_coverage(
            source,
            selected[1],
            graph_digest=selected[2],
            snapshot_manifest_digest=selected[3],
            copy_id=selected[0],
        )
    if not candidates:
        return compare_commit_coverage(source, None)
    failed: CoverageComparison | None = None
    pending: CoverageComparison | None = None
    for copy_id, observation, digest, manifest in candidates:
        compared = compare_commit_coverage(
            source,
            observation,
            graph_digest=digest,
            snapshot_manifest_digest=manifest,
            copy_id=copy_id,
        )
        if compared.status == "verification_failed":
            failed = compared
            break
        if pending is None or len(compared.missing_commits or ()) < len(
            pending.missing_commits or ()
        ):
            pending = compared
    if failed is not None:
        return failed
    assert pending is not None
    return pending


def _pending_count(local: CoverageComparison, destination: CoverageComparison) -> int | None:
    """Count commits absent from either required single-graph lane."""
    if local.missing_commits is None or destination.missing_commits is None:
        return None
    return len(local.missing_commits | destination.missing_commits)


def delivery_status(job: DeliveryJob) -> DeliveryReport:
    """Compute current local/destination coverage and journal history."""
    source = observe_source_commits(
        job.data_dir, job.expected, job.evidence_provider, timeout_ms=job.timeout_ms
    )
    local = _compare_store(source, job.sender_store, job.expected, job.timeout_ms)
    destination = _compare_store(source, job.destination_store, job.expected, job.timeout_ms)
    journal = read_journal(job.control_dir)
    job_id = journal.descriptor.job_id if journal.descriptor is not None else ""
    dest_lane: BackupLane = _lane(destination)
    if journal.latest_failure is not None and dest_lane != "covered":
        dest_lane = "transfer_failed" if journal.latest_failure.error_code else dest_lane
    return DeliveryReport(
        "backup_delivery_status",
        job_id,
        _recording(job, source),
        _lane(local),
        dest_lane,
        source.dataset_revision,
        source.observed_at,
        _pending_count(local, destination),
        journal.last_verified_at(),
        journal.last_attempt_error_code(),
        journal.history_unknown,
    )


def report_committed_delivery(job: DeliveryJob) -> DeliveryReport:
    """Post-commit reporter: confirm the receipt in source facts, then status."""
    if job.recording is None:
        raise BackupDeliveryError("recording_missing")
    report = delivery_status(job)
    if report.recording is None or report.recording.get("status") != "committed":
        return DeliveryReport(
            report.kind,
            report.job_id,
            {"status": "unknown", "replayed": job.recording.replayed},
            report.local,
            report.destination,
            report.source_observed_revision,
            report.coverage_as_of,
            report.pending_commit_count,
            report.last_verified_at,
            report.last_attempt_error_code,
            report.history_unknown,
            report.attempt,
        )
    return report


def run_backup_delivery(job: DeliveryJob) -> DeliveryReport:
    """Capture if needed, copy one covering graph, and journal actual stages."""
    sender_id = read_store_identity(job.sender_store)["store_id"]
    receiver_id = read_store_identity(job.destination_store)["store_id"]
    digest = enrollment_digest(job.expected)
    with execution_lock(job.control_dir, timeout_ms=job.timeout_ms):
        descriptor = initialize_delivery_control(
            job.control_dir,
            enrollment_digest=digest,
            sender_store_id=sender_id,
            receiver_store_id=receiver_id,
            destination_store=job.destination_store,
        )
        _reject_descriptor(descriptor, digest, sender_id, receiver_id)
        source = observe_source_commits(
            job.data_dir, job.expected, job.evidence_provider, timeout_ms=job.timeout_ms
        )
        attempt = start_attempt(
            job.control_dir,
            source_coverage_digest=source.coverage_digest,
            source_generation=source.generation,
            source_schema_version=source.schema_version,
            source_revision=source.dataset_revision,
        )
        try:
            return _run_attempt(job, descriptor, source, attempt)
        except BackupDeliveryError as exc:
            failed = _fail_attempt(job, attempt, exc.reason, source)
            raise BackupDeliveryError(exc.reason, failed.to_dict()) from exc
        except BackupPayloadError as exc:
            failed = _fail_attempt(job, attempt, exc.reason, source)
            raise BackupDeliveryError(exc.reason, failed.to_dict()) from exc
        except BackupVerificationError as exc:
            reason = "verification_failed"
            failed = _fail_attempt(job, attempt, reason, source)
            raise BackupDeliveryError(reason, failed.to_dict()) from exc
        except OSError as exc:
            failed = _fail_attempt(job, attempt, "copy_failed", source)
            raise BackupDeliveryError("copy_failed", failed.to_dict()) from exc
        except RepositoryBackupError as exc:
            reason = getattr(exc, "reason", "delivery_failed")
            failed = _fail_attempt(job, attempt, str(reason), source)
            raise BackupDeliveryError(str(reason), failed.to_dict()) from exc
        except Exception as exc:
            failed = _fail_attempt(job, attempt, "delivery_failed", source)
            raise BackupDeliveryError("delivery_failed", failed.to_dict()) from exc


def _reject_descriptor(
    descriptor: DeliveryDescriptor, digest: str, sender_id: str, receiver_id: str
) -> None:
    if (
        descriptor.enrollment_digest != digest
        or descriptor.sender_store_id != sender_id
        or descriptor.receiver_store_id != receiver_id
        or descriptor.adapter != "filesystem"
    ):
        raise BackupDeliveryError("descriptor_mismatch")


def _run_attempt(
    job: DeliveryJob,
    descriptor: DeliveryDescriptor,
    source: SourceObservation,
    attempt: AttemptRecord,
) -> DeliveryReport:
    del descriptor
    local_copy, graph = _ensure_local_graph(job, source)
    _before_journal_write()
    attempt = publish_attempt_stage(
        job.control_dir,
        attempt,
        "local_verified",
        updates=StageUpdate(
            selected_copy_id=local_copy,
            graph_digest=graph.graph_digest,
            snapshot_manifest_digest=graph.snapshot_manifest_digest,
        ),
    )
    dest = _compare_store(source, job.destination_store, job.expected, job.timeout_ms)
    if dest.status == "covered":
        attempt = publish_attempt_stage(
            job.control_dir,
            attempt,
            "destination_verified",
            updates=StageUpdate(
                receiver_copy_id=dest.copy_id, receiver_graph_digest=dest.graph_digest
            ),
        )
        attempt = publish_attempt_stage(
            job.control_dir, attempt, "finished", updates=StageUpdate(finished=True)
        )
        return _finish_report(job, source, attempt, "covered", "covered")
    attempt = publish_attempt_stage(job.control_dir, attempt, "sending")
    received = _transfer_graph(job, local_copy, graph)
    _after_destination_publish()
    _before_journal_write()
    attempt = publish_attempt_stage(
        job.control_dir,
        attempt,
        "destination_published",
        updates=StageUpdate(
            receiver_copy_id=received.copy_id,
            receiver_graph_digest=received.graph["graph_digest"]
            if isinstance(received.graph, dict)
            else None,
        ),
    )
    later = _compare_store(source, job.destination_store, job.expected, job.timeout_ms)
    if later.status != "covered":
        raise BackupDeliveryError("verification_failed")
    attempt = publish_attempt_stage(
        job.control_dir,
        attempt,
        "destination_verified",
        updates=StageUpdate(
            receiver_copy_id=later.copy_id, receiver_graph_digest=later.graph_digest
        ),
    )
    attempt = publish_attempt_stage(
        job.control_dir, attempt, "finished", updates=StageUpdate(finished=True)
    )
    return _finish_report(job, source, attempt, "covered", "covered")


def _ensure_local_graph(
    job: DeliveryJob, source: SourceObservation
) -> tuple[str, RecoveryGraphReceipt]:
    local = _compare_store(source, job.sender_store, job.expected, job.timeout_ms)
    if local.status == "covered" and local.copy_id is not None:
        opened = open_recovery_store(job.sender_store, job.expected, timeout_ms=job.timeout_ms)
        verified = verify_recovery_bundle(opened.bundles / local.copy_id, job.expected)
        return local.copy_id, verified
    if job.capture_source is None:
        raise BackupDeliveryError("local_pending")
    captured = capture_into_store(
        job.sender_store, job.capture_source, job.expected, timeout_ms=job.timeout_ms
    )
    _after_local_graph()
    later = _compare_store(source, job.sender_store, job.expected, job.timeout_ms)
    if later.status != "covered" or later.copy_id is None:
        raise BackupDeliveryError("local_pending")
    opened = open_recovery_store(job.sender_store, job.expected, timeout_ms=job.timeout_ms)
    verified = verify_recovery_bundle(opened.bundles / later.copy_id, job.expected)
    del captured
    return later.copy_id, verified


def _transfer_graph(job: DeliveryJob, copy_id: str, graph: RecoveryGraphReceipt) -> Any:
    sender = open_recovery_store(job.sender_store, job.expected, timeout_ms=job.timeout_ms)
    destination = open_recovery_store(
        job.destination_store, job.expected, timeout_ms=job.timeout_ms
    )
    sender_id = read_store_identity(sender.root)["store_id"]
    dest_id = read_store_identity(destination.root)["store_id"]
    first, second = (sender, destination) if sender_id <= dest_id else (destination, sender)
    source_bundle = sender.bundles / copy_id
    if not source_bundle.is_dir():
        raise BackupDeliveryError("source_missing")
    with ExitStack() as stack:
        stack.enter_context(first.shared_lease())
        stack.enter_context(second.shared_lease())
        if not source_bundle.is_dir():
            raise BackupDeliveryError("source_missing")
        verified = verify_recovery_bundle(source_bundle, job.expected)
        if verified.graph_digest != graph.graph_digest:
            raise BackupDeliveryError("graph_conflict")
        return receive_graph_into_store(
            job.destination_store,
            source_bundle,
            job.expected,
            expected_graph=graph,
            timeout_ms=job.timeout_ms,
        )


def _fail_attempt(
    job: DeliveryJob, attempt: AttemptRecord, error_code: str, source: SourceObservation
) -> DeliveryReport:
    try:
        _before_journal_write()
        attempt = publish_attempt_stage(
            job.control_dir,
            attempt,
            "finished",
            updates=StageUpdate(error_code=error_code, finished=True),
        )
    except Exception:
        attempt = AttemptRecord(
            attempt.attempt_id,
            attempt.stage,
            attempt.source_coverage_digest,
            attempt.source_generation,
            attempt.source_schema_version,
            attempt.source_revision,
            attempt.selected_copy_id,
            attempt.graph_digest,
            attempt.snapshot_manifest_digest,
            attempt.started_at,
            attempt.finished_at,
            error_code,
            attempt.receiver_copy_id,
            attempt.receiver_graph_digest,
        )
    later = observe_source_commits(
        job.data_dir, job.expected, job.evidence_provider, timeout_ms=job.timeout_ms
    )
    local = _compare_store(later, job.sender_store, job.expected, job.timeout_ms)
    dest = _compare_store(later, job.destination_store, job.expected, job.timeout_ms)
    dest_lane: BackupLane = "transfer_failed"
    if dest.status == "covered":
        dest_lane = "covered"
    elif dest.status == "verification_failed":
        dest_lane = "verification_failed"
    journal = read_journal(job.control_dir)
    return DeliveryReport(
        "backup_delivery_run",
        journal.descriptor.job_id if journal.descriptor else "",
        _recording(job, later),
        _lane(local),
        dest_lane,
        later.dataset_revision,
        later.observed_at,
        _pending_count(local, dest),
        journal.last_verified_at(),
        error_code,
        journal.history_unknown,
        attempt.public_dict(),
    )


def _finish_report(
    job: DeliveryJob,
    selected_source: SourceObservation,
    attempt: AttemptRecord,
    local: BackupLane,
    destination: BackupLane,
) -> DeliveryReport:
    del selected_source, local, destination
    later = observe_source_commits(
        job.data_dir, job.expected, job.evidence_provider, timeout_ms=job.timeout_ms
    )
    local_now = _compare_store(later, job.sender_store, job.expected, job.timeout_ms)
    dest_now = _compare_store(later, job.destination_store, job.expected, job.timeout_ms)
    journal = read_journal(job.control_dir)
    return DeliveryReport(
        "backup_delivery_run",
        journal.descriptor.job_id if journal.descriptor else "",
        _recording(job, later),
        _lane(local_now),
        _lane(dest_now),
        later.dataset_revision,
        later.observed_at,
        _pending_count(local_now, dest_now),
        journal.last_verified_at(),
        journal.last_attempt_error_code(),
        journal.history_unknown,
        attempt.public_dict(),
    )
