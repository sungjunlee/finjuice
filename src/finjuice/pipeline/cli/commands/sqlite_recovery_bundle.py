"""Operator CLI for local recovery-graph capture, verify, and inactive restore."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.recovery_expected import load_expected_recovery_graph
from finjuice.pipeline.cli.commands.sqlite_backup import (
    _active_data_dir,
    _fail,
    _reject_active_restore,
    _render_restore,
    _unexpected,
    ssot_backup_app,
)
from finjuice.pipeline.cli.output import emit
from finjuice.pipeline.storage.authority import StaticActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.errors import (
    BackupVerificationError,
    RepositoryBackupError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.inactive_restore import restore_workspace
from finjuice.pipeline.storage.sqlite.recovery_bundle import (
    RecoveryCaptureInput,
    RecoveryGraphReceipt,
    capture_recovery_bundle,
    verify_recovery_bundle,
)
from finjuice.pipeline.storage.sqlite.recovery_release_evidence import ReleaseArtifactPaths


def _render_graph(result: dict[str, Any]) -> None:
    output.success("Local recovery graph verified")
    output.info(f"  kind: {result['kind']}")
    output.info(f"  digest: {result['graph_digest']}")
    output.info(f"  generation: {result['snapshot_generation']}")
    output.info(f"  snapshot revision: {result['snapshot_revision']}")
    output.info(f"  activation revision: {result['activation_revision']}")
    output.info(f"  files: {result['file_count']}")
    output.info("Keep independently enrolled expectations; this receipt is not a pointer copy.")


def _run(command: str, json_output: bool, action: Callable[[], RecoveryGraphReceipt]) -> None:
    try:
        result = action()
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render_graph, command=command)


@ssot_backup_app.command("capture-bundle")
def sqlite_backup_capture_bundle(  # noqa: PLR0913 - explicit Typer operator options
    source_data_dir: Path = typer.Option(
        ...,
        "--source-data-dir",
        help="Explicit live data directory to snapshot; not read from the host pointer.",
    ),
    output_dir: Path = typer.Option(
        ..., "--output", help="Fresh directory for the published graph."
    ),
    expected: Path = typer.Option(
        ...,
        "--expected",
        help="Independently retained expectation JSON; never derived from the live tree.",
    ),
    wheel: Path = typer.Option(..., "--wheel", help="Operator-selected release wheel."),
    dependency_lock: Path = typer.Option(
        ..., "--dependency-lock", help="Operator-selected dependency lock file."
    ),
    binding: Path = typer.Option(..., "--binding", help="Operator-selected trusted binding file."),
    migration_candidate: Path = typer.Option(
        ...,
        "--migration-candidate",
        help="Immutable migration candidate directory.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Capture one local recovery graph from explicit operator paths."""
    command = "ssot backup capture-bundle"

    def action() -> RecoveryGraphReceipt:
        enrolled = load_expected_recovery_graph(expected)
        return capture_recovery_bundle(
            RecoveryCaptureInput(
                source_data_dir,
                output_dir,
                StaticActivationEvidenceProvider(enrolled.activation_evidence),
                ReleaseArtifactPaths(wheel, dependency_lock, binding),
                migration_candidate,
            ),
            enrolled,
        )

    _run(command, json_output, action)


@ssot_backup_app.command("verify-bundle")
def sqlite_backup_verify_bundle(
    bundle: Path = typer.Argument(..., help="Published local recovery graph directory."),
    expected: Path = typer.Option(
        ...,
        "--expected",
        help="Independently retained expectation JSON; never derived from the bundle.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Verify one published recovery graph against independently enrolled evidence."""
    command = "ssot backup verify-bundle"
    _run(
        command,
        json_output,
        lambda: verify_recovery_bundle(bundle, load_expected_recovery_graph(expected)),
    )


@ssot_backup_app.command("restore-bundle")
def sqlite_backup_restore_bundle(
    ctx: typer.Context,
    bundle: Path = typer.Argument(..., help="Published local recovery graph directory."),
    target: Path = typer.Option(
        ..., "--target", help="Fresh isolated workspace directory; parent must exist."
    ),
    expected: Path = typer.Option(
        ...,
        "--expected",
        help="Independently retained expectation JSON; never derived from the bundle.",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Verify the graph, then restore its snapshot into an inactive workspace."""
    command = "ssot backup restore-bundle"
    try:
        enrolled = load_expected_recovery_graph(expected)
        _reject_active_restore(target, _active_data_dir(ctx))
        from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

        with managed_read_lease(bundle):
            verified = verify_recovery_bundle(bundle, enrolled)
            result = restore_workspace(bundle / "snapshot", target)
            if (
                result.source_manifest_digest != verified.snapshot_manifest_digest
                or result.dataset_generation != verified.snapshot_generation
                or result.sqlite_schema_version != verified.snapshot_schema_version
                or result.initial_dataset_revision != verified.snapshot_revision
            ):
                raise BackupVerificationError(
                    "Restored snapshot does not match the verified graph."
                )
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render_restore, command=command)
