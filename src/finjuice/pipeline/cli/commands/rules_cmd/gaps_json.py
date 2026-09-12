"""JSON payload helpers for ``finjuice rules gaps``.

Owns gap/simulation serialization and the JSON payload wrapper around
tagging gap analysis. The Typer command stays in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.gaps`, which re-exports
these helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.config import Config


def _serialize_gap_analysis(gap: Any) -> dict[str, Any]:
    """Convert a GapAnalysis dataclass into a JSON-safe payload."""
    return {
        "merchant": gap.merchant,
        "transaction_count": gap.transaction_count,
        "total_amount": float(gap.total_amount),
        "banksalad_category": gap.current_category,
        "current_tags": list(gap.current_tags),
        "gap_type": gap.gap_type.name.lower(),
        "suggested_action": gap.suggested_action,
        "expected_category": gap.expected_category,
        "mismatch_type": gap.mismatch_type,
        "mismatch_severity": gap.mismatch_severity,
        "actionable": bool(gap.actionable),
    }


def _serialize_coverage_simulation(simulation: Any) -> dict[str, Any]:
    """Convert a CoverageSimulation dataclass into a JSON-safe payload."""
    return {
        "top_n": simulation.top_n,
        "expected_tagged": simulation.expected_tagged,
        "expected_coverage_pct": round(float(simulation.expected_coverage_pct), 2),
        "coverage_improvement_pct": round(float(simulation.improvement_pct), 2),
    }


def _compute_rules_gaps_json(
    config: Config,
    simulate: bool,
    json_output: bool,
    actionable_only: bool = False,
) -> dict[str, Any]:
    """Compute JSON payload for `rules gaps`."""
    from finjuice.pipeline.tagging.gap_analyzer import (
        GapType,
        analyze_tag_category_gaps,
        simulate_coverage_improvement,
        sort_mismatch_gaps,
    )

    if not config.csv_base_dir.exists():
        if config.data_dir.exists():
            emit_error(
                f"No transaction data found at {config.csv_base_dir}. "
                "Run 'finjuice ingest' to import XLSX files.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                suggestion="finjuice ingest",
                json_output=json_output,
                command="rules gaps",
            )
        else:
            emit_error(
                f"No transaction data found at {config.csv_base_dir}. "
                "Run 'finjuice init' to set up, then 'finjuice ingest'.",
                error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
                exit_code=ExitCode.USAGE_ERROR,
                suggestion="finjuice init",
                json_output=json_output,
                command="rules gaps",
            )

    gaps = analyze_tag_category_gaps(config.csv_base_dir)

    critical_gaps = gaps.get(GapType.CRITICAL, [])
    all_mismatch_gaps = sort_mismatch_gaps(
        [
            *gaps.get(GapType.MISMATCH, []),
            *gaps.get(GapType.PARTIAL, []),
        ]
    )
    mismatch_gaps = [gap for gap in all_mismatch_gaps if gap.actionable or not actionable_only]
    complete_matches = gaps.get(GapType.COMPLETE, [])

    total_mismatch_count = sum(gap.transaction_count for gap in all_mismatch_gaps)
    filtered_mismatch_count = sum(gap.transaction_count for gap in mismatch_gaps)
    actionable_mismatch_count = sum(
        gap.transaction_count for gap in all_mismatch_gaps if gap.actionable
    )

    def _count_mismatch_type(mismatch_type: str) -> int:
        return sum(
            gap.transaction_count for gap in all_mismatch_gaps if gap.mismatch_type == mismatch_type
        )

    simulations = []
    if simulate:
        simulations = simulate_coverage_improvement(
            config.csv_base_dir,
            top_n_values=[5, 10, 20],
        )

    return {
        "summary": {
            "critical_count": sum(gap.transaction_count for gap in critical_gaps),
            "mismatch_count": filtered_mismatch_count,
            "complete_count": sum(gap.transaction_count for gap in complete_matches),
            "total_mismatch_count": total_mismatch_count,
            "filtered_mismatch_count": filtered_mismatch_count,
            "filtered_out_mismatch_count": total_mismatch_count - filtered_mismatch_count,
            "actionable_mismatch_count": actionable_mismatch_count,
            "conflict_count": _count_mismatch_type("conflict"),
            "category_mismatch_count": _count_mismatch_type("category_mismatch"),
            "multi_tag_noise_count": _count_mismatch_type("multi_tag_noise"),
            "actionable_only": actionable_only,
        },
        "critical_gaps": [_serialize_gap_analysis(gap) for gap in critical_gaps],
        "mismatches": [_serialize_gap_analysis(gap) for gap in mismatch_gaps],
        "simulations": [_serialize_coverage_simulation(simulation) for simulation in simulations],
    }
