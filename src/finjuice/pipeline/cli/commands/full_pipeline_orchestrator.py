"""Shared full-pipeline orchestrator for CLI commands.

Runs ingest → tag → transfer → export and returns structured step summaries.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import typer

logger = logging.getLogger(__name__)

StepStartCallback = Callable[[str, int, int], None]
StepCompleteCallback = Callable[[str, dict[str, Any], int, int], None]


def compute_full_pipeline_ingest(config: Any) -> dict[str, Any]:
    """Run the ingest step and normalize its result."""
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


def compute_full_pipeline_tag(config: Any) -> dict[str, Any]:
    """Run the tag step, preserving skip-on-missing-rules behavior."""
    from finjuice.pipeline.tagging.pipeline import run_tagging

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


def compute_full_pipeline_transfer(config: Any) -> dict[str, Any]:
    """Run the transfer step and normalize its result."""
    from finjuice.pipeline.transfer.detection import run_transfer_detection

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
) -> dict[str, Any]:
    """Run the export step and normalize its result."""
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
    on_step_start: StepStartCallback | None = None,
    on_step_complete: StepCompleteCallback | None = None,
) -> dict[str, Any]:
    """Run all full-pipeline steps and return a structured summary."""
    step_runners: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("ingest", lambda: compute_full_pipeline_ingest(config)),
        ("tag", lambda: compute_full_pipeline_tag(config)),
        ("transfer", lambda: compute_full_pipeline_transfer(config)),
        ("export", lambda: compute_full_pipeline_export(ctx, config, emit_text=export_emit_text)),
    ]
    total_steps = len(step_runners)
    steps: dict[str, dict[str, Any]] = {}

    for index, (step_name, step_runner) in enumerate(step_runners, start=1):
        if on_step_start is not None:
            on_step_start(step_name, index, total_steps)

        step_result = step_runner()
        steps[step_name] = step_result

        if on_step_complete is not None:
            on_step_complete(step_name, step_result, index, total_steps)

    return {
        "command": command_name,
        "steps": steps,
    }
