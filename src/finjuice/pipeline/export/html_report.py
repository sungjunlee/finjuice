"""
HTML report generation with Plotly charts (Issue #117).

This module generates interactive HTML reports with:
- Monthly spending trend (line chart)
- Tag breakdown (pie chart)
- Top merchants (horizontal bar chart)
- Summary statistics tables

Template and fallback HTML rendering live in
:mod:`finjuice.pipeline.export.html_report_render`.
"""

import logging
from pathlib import Path
from typing import Optional

from finjuice.pipeline.export.html_report_render import (
    _get_template_content,
    _plotly_js_tag,
    _render_html_report,
)

logger = logging.getLogger(__name__)

# Check for optional dependencies
try:
    import jinja2  # noqa: F401

    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    import polars as pl

    POLARS_AVAILABLE = True
except ImportError:
    POLARS_AVAILABLE = False
    pl = None  # type: ignore[assignment]  # optional dep fallback; guarded before use


def _check_dependencies() -> None:
    """Check if required dependencies are available."""
    missing = []
    if not POLARS_AVAILABLE:
        missing.append("polars")

    if missing:
        raise ImportError(
            f"Missing required dependencies: {', '.join(missing)}. "
            f"Install with: uv sync --extra templates"
        )


def generate_html_report(
    csv_base_dir: Path,
    output_path: Path,
    period: Optional[str] = None,
    include_charts: bool = True,
    source_df: "pl.DataFrame | None" = None,
    offline: bool = True,
) -> Path:
    """
    Generate interactive HTML report with Plotly charts.

    Defaults to offline mode (privacy-first): Plotly.js is embedded directly
    in the HTML, no external CDN requests are made.

    Args:
        csv_base_dir: Base directory for CSV partitions
        output_path: Path to output HTML file
        period: Optional period filter (YYYY-MM format)
        include_charts: Include interactive Plotly charts (default: True)
        source_df: Optional pre-loaded DataFrame to use instead of loading from disk
        offline: When True (default), inline Plotly.js to avoid CDN requests.
                 When False, load from CDN with SRI integrity hash.

    Returns:
        Path to generated HTML file

    Raises:
        ImportError: If required dependencies are not installed
        RuntimeError: If report generation fails
    """
    _check_dependencies()

    from finjuice.pipeline.export.aggregations import (
        calculate_monthly_spend,
        calculate_summary_stats,
        calculate_tag_breakdown,
        calculate_top_merchants,
        load_transactions,
    )

    logger.info("Generating HTML report (offline=%s)", offline)

    try:
        # Load and process data
        df = load_transactions(csv_base_dir, period, source_df=source_df)
        monthly_spend = calculate_monthly_spend(df)
        tag_breakdown = calculate_tag_breakdown(df, top_n=10)
        top_merchants = calculate_top_merchants(df, limit=20)
        summary = calculate_summary_stats(df, period)

        monthly_spend_rows = monthly_spend.to_dicts()
        tag_breakdown_rows = tag_breakdown.to_dicts()
        top_merchants_rows = top_merchants.to_dicts()

        from finjuice.pipeline.export.chart_utils import (
            create_merchants_bar_chart,
            create_monthly_trend_chart,
            create_tag_pie_chart,
        )

        charts: dict[str, Optional[str]] = {}
        if include_charts:
            charts["monthly_trend"] = create_monthly_trend_chart(
                monthly_spend, include_plotlyjs=offline
            )
            charts["tag_pie"] = create_tag_pie_chart(tag_breakdown)
            charts["merchants_bar"] = create_merchants_bar_chart(top_merchants)
        else:
            charts["monthly_trend"] = None
            charts["tag_pie"] = None
            charts["merchants_bar"] = None

        if JINJA2_AVAILABLE:
            plotly_js = _plotly_js_tag(offline=offline)
            from jinja2 import BaseLoader, Environment

            env = Environment(loader=BaseLoader(), autoescape=True)
            template = env.from_string(_get_template_content())
            html_content = template.render(
                summary=summary,
                charts=charts,
                monthly_spend=monthly_spend_rows,
                tag_breakdown=tag_breakdown_rows,
                top_merchants=top_merchants_rows,
                plotly_js=plotly_js,
            )
        else:
            html_content = _render_html_report(
                summary,
                charts,
                monthly_spend_rows,
                tag_breakdown_rows,
                top_merchants_rows,
                offline=offline,
            )

        # Write to file
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(html_content, encoding="utf-8")

        logger.info("HTML report generated (size: %d bytes)", len(html_content))
        return output_path

    except (OSError, pl.exceptions.PolarsError, RuntimeError) as e:
        logger.error("Failed to generate HTML report (%s)", type(e).__name__)
        raise RuntimeError(f"HTML report generation failed: {e}") from e
