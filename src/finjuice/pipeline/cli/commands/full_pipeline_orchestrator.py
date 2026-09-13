"""Shared full-pipeline orchestrator for CLI commands.

Runs ingest → tag → transfer → export and returns structured step summaries.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import typer

from finjuice.pipeline.cli.bulk_repository import (
    compute_repository_tag,
    compute_repository_transfer,
)
from finjuice.pipeline.cli.pipeline_failure import FullPipelineError
from finjuice.pipeline.cli.repository_import import (
    identity_from_context,
    import_xlsx_paths,
    ingest_import_directory,
    present_ingest_step,
)
from finjuice.pipeline.cli.utils import get_mutation_facade
from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.mutation_facade import MutationIdentity, StorageMutationFacade

logger = logging.getLogger(__name__)

StepStartCallback = Callable[[str, int, int], None]
StepCompleteCallback = Callable[[str, dict[str, Any], int, int], None]


@dataclass(frozen=True)
class FullPipelineOptions:
    """Explicit ingest scope, precomputed ingest, and step hooks for one run.

    ``file_paths is None`` means glob ``imports/`` (refresh). An explicit list,
    including empty, ingests only those workbooks and never falls back to glob.
    ``ingest_result`` supplies an already-completed ingest step (active import
    captures its sources before this orchestrator runs) and takes precedence
    over ``file_paths``.
    """

    command_name: str
    export_emit_text: bool = False
    file_paths: list[Any] | None = None
    ingest_result: dict[str, Any] | None = None
    on_step_start: StepStartCallback | None = None
    on_step_complete: StepCompleteCallback | None = None


class CanonicalExportUnavailableError(RuntimeError):
    """Active canonical export/projection is not wired yet (#436)."""


def compute_full_pipeline_ingest(
    config: Any,
    file_paths: list[Any] | None = None,
    *,
    facade: StorageMutationFacade | None = None,
    identity: MutationIdentity = MutationIdentity(),
) -> dict[str, Any]:
    """Run the ingest step and normalize its result.

    ``file_paths is None`` globs ``imports/`` (refresh). An explicit list,
    including empty, ingests only those workbooks and never falls back to glob.
    """
    selected = facade or StorageMutationFacade(config.data_dir)
    if isinstance(selected.dispatch().authority, RepositoryAuthority):
        return _repository_ingest_step(selected, config, identity, file_paths)
    return _legacy_ingest_step(config, file_paths)


def _repository_ingest_step(
    facade: StorageMutationFacade,
    config: Any,
    identity: MutationIdentity,
    file_paths: list[Any] | None,
) -> dict[str, Any]:
    """Import explicit workbooks, or every staged workbook, under canonical authority."""
    if file_paths is None:
        return ingest_import_directory(
            facade,
            config,
            identity,
            preview=False,
            archive_requested=False,
        )
    batch = import_xlsx_paths(facade, [Path(path) for path in file_paths], identity, preview=False)
    return present_ingest_step(batch, source="files", dry_run=False, archive_requested=False)


def _legacy_ingest_step(config: Any, file_paths: list[Any] | None = None) -> dict[str, Any]:
    """Run the legacy CSV ingest step and normalize its result."""
    from finjuice.pipeline.ingest.pipeline import ingest_all_files, ingest_paths

    logger.info(f"Ingest: {config.import_dir} → {config.csv_base_dir}")
    if file_paths is None:
        summary = ingest_all_files(config.import_dir, config.csv_base_dir, archive=False)
    else:
        summary = ingest_paths(
            [Path(path) for path in file_paths],
            config.csv_base_dir,
            archive=False,
        )
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
    options: FullPipelineOptions,
) -> dict[str, Any]:
    """Run all full-pipeline steps and return a structured summary."""
    facade = get_mutation_facade(ctx, config)
    identity = identity_from_context(ctx)
    step_runners: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("ingest", lambda: _ingest_step(config, facade, identity, options)),
        ("tag", lambda: compute_full_pipeline_tag(config, facade=facade)),
        ("transfer", lambda: compute_full_pipeline_transfer(config, facade=facade)),
        (
            "export",
            lambda: compute_full_pipeline_export(
                ctx, config, emit_text=options.export_emit_text, facade=facade
            ),
        ),
    ]
    total_steps = len(step_runners)
    steps: dict[str, dict[str, Any]] = {}

    for index, (step_name, step_runner) in enumerate(step_runners, start=1):
        if options.on_step_start is not None:
            options.on_step_start(step_name, index, total_steps)

        try:
            step_result = step_runner()
        except (typer.Exit, FullPipelineError):
            raise
        except Exception as exc:
            raise FullPipelineError.from_exception(step_name, steps, exc) from exc
        steps[step_name] = step_result

        if options.on_step_complete is not None:
            options.on_step_complete(step_name, step_result, index, total_steps)

        if step_name == "ingest" and int(step_result["summary"]["failed"]) > 0:
            raise FullPipelineError(step_name, steps, error_type="PartialIngestFailure")

    return {
        "command": options.command_name,
        "steps": steps,
    }


def _ingest_step(
    config: Any,
    facade: StorageMutationFacade,
    identity: MutationIdentity,
    options: FullPipelineOptions,
) -> dict[str, Any]:
    """Use a precomputed ingest result, or run the scoped ingest step."""
    if options.ingest_result is not None:
        return options.ingest_result
    return compute_full_pipeline_ingest(
        config, options.file_paths, facade=facade, identity=identity
    )
