"""One-shot backup delivery worker and privacy-safe status CLI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.recovery_expected import load_expected_recovery_graph
from finjuice.pipeline.cli.commands.sqlite_backup import (
    _fail,
    _unexpected,
    ssot_backup_app,
)
from finjuice.pipeline.cli.output import ExitCode, emit
from finjuice.pipeline.storage.authority import StaticActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.backup_delivery import (
    DeliveryJob,
    DeliveryReport,
    delivery_status,
    report_committed_delivery,
    run_backup_delivery,
)
from finjuice.pipeline.storage.sqlite.errors import (
    BackupDeliveryError,
    RepositoryBackupError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.recovery_bundle import RecoveryCaptureInput
from finjuice.pipeline.storage.sqlite.recovery_release_evidence import ReleaseArtifactPaths

deliver_app = typer.Typer(
    name="deliver",
    help="Run one filesystem backup delivery or report committed vs pending coverage.",
    no_args_is_help=True,
)
ssot_backup_app.add_typer(deliver_app, name="deliver")

_EXPECTED_HELP = "Independently retained expectation JSON; never derived from the store."


def _job(  # noqa: PLR0913 - operator CLI must name every independent input
    source_data_dir: Path,
    expected: Path,
    sender_store: Path,
    destination_store: Path,
    control_dir: Path,
    wheel: Path | None,
    dependency_lock: Path | None,
    binding: Path | None,
    migration_candidate: Path | None,
) -> DeliveryJob:
    enrolled = load_expected_recovery_graph(expected)
    evidence = StaticActivationEvidenceProvider(enrolled.activation_evidence)
    capture_source = None
    artifacts = (wheel, dependency_lock, binding, migration_candidate)
    if any(item is not None for item in artifacts) and any(item is None for item in artifacts):
        raise ValueError("Capture requires all four release and migration artifacts.")
    if None not in (wheel, dependency_lock, binding, migration_candidate):
        assert wheel is not None and dependency_lock is not None
        assert binding is not None and migration_candidate is not None
        capture_source = RecoveryCaptureInput(
            source_data_dir,
            source_data_dir / "unused-delivery-capture-destination",
            evidence,
            ReleaseArtifactPaths(wheel, dependency_lock, binding),
            migration_candidate,
        )
    return DeliveryJob(
        source_data_dir,
        enrolled,
        evidence,
        sender_store,
        destination_store,
        control_dir,
        capture_source,
    )


def _render_status(result: dict[str, Any]) -> None:
    recording = result.get("recording") or {}
    revision = result["source_observed_revision"]
    local = result["backup"]["local"]
    destination = result["backup"]["destination"]
    if recording.get("status") == "committed":
        output.success(f"기록은 저장되었습니다(리비전 {recording['committed_revision']}).")
    elif recording.get("status") == "unknown":
        output.warning("기록 확정 상태를 확인하지 못했습니다.")
    else:
        output.info(f"소스 관측 리비전 {revision}")
    output.info(f"  로컬 백업: {local}")
    output.info(f"  대상 사본: {destination}")
    if destination in {"pending", "transfer_failed"}:
        output.warning("대상 사본 전송은 대기 중입니다. 원래 기록을 다시 입력할 필요는 없습니다.")
    if result.get("last_attempt_error_code"):
        output.warning(f"  last attempt: {result['last_attempt_error_code']}")
    if result.get("history_unknown"):
        output.warning("  delivery history: unknown")


def _emit_report(report: DeliveryReport, *, json_output: bool, command: str, failed: bool) -> None:
    payload = report.to_dict()
    emit(payload, json_output, _render_status, command=command)
    if failed:
        raise typer.Exit(int(ExitCode.GENERAL_ERROR))


@deliver_app.command("status")
def sqlite_backup_deliver_status(  # noqa: PLR0913 - explicit Typer operator options
    source_data_dir: Path = typer.Option(..., "--source-data-dir"),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    sender_store: Path = typer.Option(..., "--sender-store"),
    destination_store: Path = typer.Option(..., "--destination-store"),
    control_dir: Path = typer.Option(..., "--control-dir"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Report committed-record coverage and delivery history without transferring."""
    command = "ssot backup deliver status"
    try:
        job = _job(
            source_data_dir,
            expected,
            sender_store,
            destination_store,
            control_dir,
            None,
            None,
            None,
            None,
        )
        report = delivery_status(job)
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    _emit_report(report, json_output=json_output, command=command, failed=False)


@deliver_app.command("run")
def sqlite_backup_deliver_run(  # noqa: PLR0913 - explicit Typer operator options
    source_data_dir: Path = typer.Option(..., "--source-data-dir"),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    sender_store: Path = typer.Option(..., "--sender-store"),
    destination_store: Path = typer.Option(..., "--destination-store"),
    control_dir: Path = typer.Option(..., "--control-dir"),
    wheel: Optional[Path] = typer.Option(None, "--wheel"),
    dependency_lock: Optional[Path] = typer.Option(None, "--dependency-lock"),
    binding: Optional[Path] = typer.Option(None, "--binding"),
    migration_candidate: Optional[Path] = typer.Option(None, "--migration-candidate"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """Run one filesystem delivery. Nonzero exit is backup failure, not a domain rollback."""
    command = "ssot backup deliver run"
    try:
        job = _job(
            source_data_dir,
            expected,
            sender_store,
            destination_store,
            control_dir,
            wheel,
            dependency_lock,
            binding,
            migration_candidate,
        )
        report = run_backup_delivery(job)
    except BackupDeliveryError as exc:
        payload: dict[str, Any] = dict(exc.report)
        if not payload:
            _fail(exc, command=command, json_output=json_output)
            return
        emit(payload, json_output, _render_status, command=command)
        raise typer.Exit(int(ExitCode.GENERAL_ERROR))
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    failed = bool(report.attempt and report.attempt.get("error_code"))
    _emit_report(report, json_output=json_output, command=command, failed=failed)


def report_after_commit(job: DeliveryJob) -> DeliveryReport:
    """Public post-commit boundary used by tests and callers with a real receipt."""
    return report_committed_delivery(job)
