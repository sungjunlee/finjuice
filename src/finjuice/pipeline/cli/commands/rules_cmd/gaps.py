"""Gap-analysis implementation for rules CLI commands.

JSON payload helpers live in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.gaps_json`.
Those helpers are re-exported here so existing callers can keep
importing from this module.
"""

import logging
from pathlib import Path
from typing import Optional

import typer

from finjuice.pipeline.cli.output import ErrorCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_config

from .gaps_json import (
    _compute_rules_gaps_json,
    _serialize_coverage_simulation,  # noqa: F401 — re-exported for existing gaps imports
    _serialize_gap_analysis,  # noqa: F401 — re-exported for existing gaps imports
)

logger = logging.getLogger(__name__)


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
