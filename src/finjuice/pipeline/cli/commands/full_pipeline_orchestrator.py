"""Shared full-pipeline orchestrator for CLI commands.

Runs ingest → tag → transfer → export and returns structured step summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

import typer

from finjuice.pipeline.cli.bulk_repository import (
    compute_repository_tag,
    compute_repository_transfer,
)
from finjuice.pipeline.cli.pipeline_failure import FullPipelineError
from finjuice.pipeline.cli.repository_import import (
    identity_from_context,
    ingest_import_directory,
)
from finjuice.pipeline.cli.utils import get_mutation_facade
from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.mutation_facade import MutationIdentity, StorageMutationFacade

logger = logging.getLogger(__name__)

StepStartCallback = Callable[[str, int, int], None]
StepCompleteCallback = Callable[[str, dict[str, Any], int, int], None]


@dataclass(frozen=True)
class PipelineCallbacks:
    """Optional progress renderers for a composed pipeline."""

    on_start: StepStartCallback | None = None
    on_complete: StepCompleteCallback | None = None


class CanonicalExportUnavailableError(RuntimeError):
    """Active canonical export/projection is not wired yet (#436)."""


def compute_full_pipeline_ingest(
    config: Any,
    *,
    facade: StorageMutationFacade | None = None,
    identity: MutationIdentity = MutationIdentity(),
) -> dict[str, Any]:
    """Run the ingest step and normalize its result."""
    selected = facade or StorageMutationFacade(config.data_dir)
    if isinstance(selected.dispatch().authority, RepositoryAuthority):
        return ingest_import_directory(
            selected,
            config,
            identity,
            preview=False,
            archive_requested=False,
        )
    return _legacy_ingest_step(config)


def _legacy_ingest_step(config: Any) -> dict[str, Any]:
    """Run the legacy CSV ingest step and normalize its result."""
    from finjuice.pipeline.ingest.pipeline import ingest_all_files

    logger.info(f"Ingest: {config.import_dir} → {config.csv_base_dir}")
    summary = ingest_all_files(config.import_dir, config.csv_base_dir, archive=False)
    return {
        "command": "ingest",
        "dry_run": False,
        "source": "imports",
        "archive_requested": False,
        "summary": {
            "files_processed": int(summary["files"]),
            "new_transactions": int(summary["inserted"]),
            "updated": int(summary["updated"]),
            "banksalad_overview": summary.get("banksalad_overview", {}),
            "failed": int(summary["failed"]),
            "failed_files": summary.get("failed_files", []),
        },
    }


def compute_full_pipeline_tag(
    config: Any, *, facade: StorageMutationFacade | None = None
) -> dict[str, Any]:
    """Run the tag step, preserving skip-on-missing-rules behavior."""
    from finjuice.pipeline.tagging.pipeline import run_tagging

    selected = facade or StorageMutationFacade(config.data_dir)
    if isinstance(selected.dispatch().authority, RepositoryAuthority):
        if selected.read_config_bytes("rules") is None:
            return {
                "status": "ok",
                "authority": "repository",
                "dry_run": False,
                "total": 0,
                "tagged": 0,
                "untagged": 0,
                "coverage_pct": 0.0,
                "skipped": True,
                "reason": "Canonical rules head is missing.",
            }
        return compute_repository_tag(selected)

    rules_path = config.data_dir / "rules.yaml"
    if not rules_path.exists():
        return {
            "status": "ok",
            "dry_run": False,
            "total": 0,
            "tagged": 0,
            "untagged": 0,
            "coverage_pct": 0.0,
            "skipped": True,
            "reason": f"Rules file not found at {rules_path}",
        }

    logger.info(f"Tag: rules from {rules_path}")
    result = run_tagging(config.csv_base_dir, rules_path, dry_run=False)
    return {
        "status": "ok",
        "dry_run": False,
        "total": int(result["total"]),
        "tagged": int(result["tagged"]),
        "untagged": int(result["untagged"]),
        "coverage_pct": float(result.get("coverage_pct", 0.0)),
    }


def compute_full_pipeline_transfer(
    config: Any, *, facade: StorageMutationFacade | None = None
) -> dict[str, Any]:
    """Run the transfer step and normalize its result."""
    from finjuice.pipeline.transfer.detection import run_transfer_detection

    selected = facade or StorageMutationFacade(config.data_dir)
    if isinstance(selected.dispatch().authority, RepositoryAuthority):
        return compute_repository_transfer(selected)

    logger.info("Transfer detection...")
    result = run_transfer_detection(config.csv_base_dir)
    return {
        "status": "ok",
        "candidate_rows": int(result.get("candidate_rows", result.get("candidates", 0))),
        "candidates_considered": int(result.get("candidates", 0)),
        "pairs_found": int(result.get("pairs", 0)),
        "pairs_linked": int(result.get("paired", 0)),
        "confirmed_transfer_rows": int(result.get("confirmed", result.get("paired", 0))),
        "unconfirmed_candidate_rows": int(result.get("unconfirmed_candidates", 0)),
    }


def compute_full_pipeline_export(
    ctx: typer.Context,
    config: Any,
    *,
    emit_text: bool,
    facade: StorageMutationFacade | None = None,
) -> dict[str, Any]:
    """Run the export step and normalize its result."""
    selected = facade or get_mutation_facade(ctx, config)
    if isinstance(selected.dispatch().authority, RepositoryAuthority):
        raise CanonicalExportUnavailableError(
            "Canonical export/projection is unavailable until issue #436."
        )
    return _legacy_export_step(ctx, config, emit_text=emit_text)


def _legacy_export_step(ctx: typer.Context, config: Any, *, emit_text: bool) -> dict[str, Any]:
    from finjuice.pipeline.export import result as export_result

    return export_result._compute_export_result(
        ctx,
        config,
        format_lower="xlsx",
        period=None,
        auto_open=False,
        dry_run=False,
        emit_text=emit_text,
    )


def run_full_pipeline_orchestrator(
    ctx: typer.Context,
    config: Any,
    *,
    command_name: str,
    export_emit_text: bool = False,
    ingest_result: dict[str, Any] | None = None,
    callbacks: PipelineCallbacks = PipelineCallbacks(),
) -> dict[str, Any]:
    """Run all full-pipeline steps and return a structured summary."""
    facade = get_mutation_facade(ctx, config)
    identity = identity_from_context(ctx)
    step_runners: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("ingest", lambda: _ingest_step(config, facade, identity, ingest_result)),
        ("tag", lambda: compute_full_pipeline_tag(config, facade=facade)),
        ("transfer", lambda: compute_full_pipeline_transfer(config, facade=facade)),
        (
            "export",
            lambda: compute_full_pipeline_export(
                ctx, config, emit_text=export_emit_text, facade=facade
            ),
        ),
    ]
    total_steps = len(step_runners)
    steps: dict[str, dict[str, Any]] = {}

    for index, (step_name, step_runner) in enumerate(step_runners, start=1):
        if callbacks.on_start is not None:
            callbacks.on_start(step_name, index, total_steps)

        try:
            step_result = step_runner()
        except typer.Exit:
            raise
        except Exception as exc:
            raise FullPipelineError.from_exception(step_name, steps, exc) from exc
        steps[step_name] = step_result

        if callbacks.on_complete is not None:
            callbacks.on_complete(step_name, step_result, index, total_steps)

        if step_name == "ingest" and int(step_result["summary"]["failed"]) > 0:
            raise FullPipelineError(step_name, steps, error_type="PartialIngestFailure")

    return {
        "command": command_name,
        "steps": steps,
    }


def _ingest_step(
    config: Any,
    facade: StorageMutationFacade,
    identity: MutationIdentity,
    ingest_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Use a precomputed ingest result, or run the ingest step."""
    if ingest_result is not None:
        return ingest_result
    return compute_full_pipeline_ingest(config, facade=facade, identity=identity)
