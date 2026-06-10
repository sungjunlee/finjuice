"""Gap-analysis implementation for rules CLI commands."""

import logging
from pathlib import Path
from typing import Any, Optional

import typer

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config

logger = logging.getLogger(__name__)


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


def analyze_gaps_command(
    ctx: typer.Context,
    top_n: int = typer.Option(
        5,
        "--top",
        "-n",
        help="Number of items to show per category",
    ),
    simulate: bool = typer.Option(
        True,
        "--simulate/--no-simulate",
        help="Show coverage improvement simulation (default: True)",
    ),
    output: Optional[Path] = typer.Option(
        None,
        "--output",
        "-o",
        help="Save report to file",
    ),
    actionable_only: bool = typer.Option(
        False,
        "--actionable-only",
        help="Hide low-signal mismatch noise and show only actionable gaps",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Analyze gaps between tags and Banksalad categories.

    Identifies:
    - 🔴 Untagged transactions (need rules)
    - 🟡 Tagged but mismatched categories (need Banksalad adjustment)
    - 🟢 Fully matched transactions

    Also simulates coverage improvement if top N merchants get rules.

    Examples:
        finjuice rules gaps                  # Show gap analysis
        finjuice rules gaps --top 10         # Show top 10 per category
        finjuice rules gaps --actionable-only # Hide low-signal mismatch noise
        finjuice rules gaps -o gaps.txt      # Save to file
    """
    from finjuice.pipeline.tagging.gap_analyzer import (
        GapType,
        analyze_tag_category_gaps,
        filter_actionable_gaps,
        format_gap_analysis_report,
        simulate_coverage_improvement,
    )

    # Get config from context
    config = get_config(ctx)

    try:
        if json_output:
            result = _compute_rules_gaps_json(config, simulate, json_output, actionable_only)
            emit(result, json_output, lambda _: None, command="rules gaps")
            return

        # Ensure transactions directory exists
        if not config.csv_base_dir.exists():
            typer.echo("❌ No transaction data found.", err=True)
            typer.echo(f"   Expected: {config.csv_base_dir}", err=True)
            # Check if parent data_dir exists to give correct guidance
            if config.data_dir.exists():
                typer.echo("   Run 'finjuice ingest' to import XLSX files.", err=True)
            else:
                typer.echo("   Run 'finjuice init' to set up, then 'finjuice ingest'.", err=True)
            raise typer.Exit(code=1)

        typer.echo("📊 태깅/카테고리 Gap 분석 중...")

        # Analyze gaps
        gaps = analyze_tag_category_gaps(config.csv_base_dir)

        # Count totals
        total_critical = sum(g.transaction_count for g in gaps.get(GapType.CRITICAL, []))
        total_mismatch_all = sum(
            g.transaction_count
            for g in [*gaps.get(GapType.MISMATCH, []), *gaps.get(GapType.PARTIAL, [])]
        )
        total_complete = sum(g.transaction_count for g in gaps.get(GapType.COMPLETE, []))

        if total_critical == 0 and total_mismatch_all == 0 and total_complete == 0:
            typer.echo("📋 분석할 거래 내역이 없습니다.")
            typer.echo("   'finjuice ingest'로 거래 내역을 먼저 가져오세요.")
            return

        report_gaps = filter_actionable_gaps(gaps) if actionable_only else gaps
        total_mismatch = sum(
            g.transaction_count
            for g in [
                *report_gaps.get(GapType.MISMATCH, []),
                *report_gaps.get(GapType.PARTIAL, []),
            ]
        )

        # Simulate coverage improvement
        simulations = []
        if simulate:
            simulations = simulate_coverage_improvement(
                config.csv_base_dir,
                top_n_values=[5, 10, 20],
            )

        # Format report
        report = format_gap_analysis_report(
            gaps=report_gaps,
            simulations=simulations,
            top_n_per_category=top_n,
        )

        # Save or display
        if output:
            try:
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(report, encoding="utf-8")
                typer.echo(f"✅ {output}에 저장되었습니다.")
            except OSError as e:
                typer.echo(f"❌ 파일 저장 실패: {e}", err=True)
                raise typer.Exit(code=1)
        else:
            typer.echo("")  # Blank line before report
            typer.echo(report)

        # Summary and next steps
        typer.echo("")
        typer.echo("─" * 40)
        if total_critical > 0:
            typer.echo(f"💡 다음 단계: finjuice rules suggest --apply --top {min(top_n, 10)}")
        elif total_mismatch > 0:
            typer.echo("💡 다음 단계: 뱅크샐러드 앱에서 카테고리를 조정하세요")
            typer.echo("   finjuice rules export --format banksalad 로 가이드 확인")
        else:
            typer.echo("✅ 모든 거래가 정상적으로 태깅되어 있습니다!")

    except typer.Exit:
        raise
    except Exception as e:  # CLI top-level handler - keep broad
        logger.error(f"Gap analysis failed: {e}", exc_info=True)
        emit_error(
            f"Unexpected error: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="rules gaps",
        )
