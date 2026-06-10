"""Export module for generating reports from transaction data."""

# Aggregations are always available (only require polars)
from .aggregations import (
    calculate_monthly_spend,
    calculate_summary_stats,
    calculate_tag_breakdown,
    calculate_top_merchants,
    load_transactions,
)
from .master import export_master_xlsx
from .reports import (
    export_by_account,
    export_by_category,
    export_by_tag,
    export_monthly_spend,
    export_transfers,
    generate_all_reports,
)

# Template-based reports (require jinja2/plotly from templates extra)
try:
    from .html_report import generate_html_report
    from .markdown_report import generate_markdown_report

    _TEMPLATES_AVAILABLE = True
except ImportError:
    _TEMPLATES_AVAILABLE = False
    generate_html_report = None  # type: ignore[assignment]  # optional templates extra fallback
    generate_markdown_report = None  # type: ignore[assignment]  # optional templates extra fallback

__all__ = [
    # Core exports
    "export_monthly_spend",
    "export_by_category",  # NEW in v3: accurate aggregation (no double counting)
    "export_by_tag",
    "export_by_account",
    "export_transfers",
    "generate_all_reports",
    "export_master_xlsx",
    # Aggregations (always available)
    "load_transactions",
    "calculate_monthly_spend",
    "calculate_tag_breakdown",
    "calculate_top_merchants",
    "calculate_summary_stats",
]

# Add template-based exports only if templates extra is available
if _TEMPLATES_AVAILABLE:
    __all__ += [
        "generate_html_report",
        "generate_markdown_report",
    ]
