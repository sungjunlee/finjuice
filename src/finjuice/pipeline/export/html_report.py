"""
HTML report generation with Plotly charts (Issue #117).

This module generates interactive HTML reports with:
- Monthly spending trend (line chart)
- Tag breakdown (pie chart)
- Top merchants (horizontal bar chart)
- Summary statistics tables
"""

import html
import logging
from pathlib import Path
from typing import Optional

import plotly.io as pio

logger = logging.getLogger(__name__)

# Check for optional dependencies
try:
    import jinja2  # noqa: F401

    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

try:
    import plotly.graph_objects as go
except ImportError:
    go = None  # type: ignore[assignment]  # optional dep fallback; guarded before use

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


def _plotly_js_tag(offline: bool = True) -> str:
    """Return the Plotly.js script tag for the HTML report head.

    Args:
        offline: When True, inline the full Plotly.js library.
                 When False, load from CDN with SRI integrity hash.
    """
    if not offline:
        return (
            '<script charset="utf-8" '
            'src="https://cdn.plot.ly/plotly-3.5.0.min.js" '
            'integrity="sha256-fHbNLP+GlIXN+efbQec78UkemUz3NJp7UmfGxC1tNxs=" '
            'crossorigin="anonymous"></script>'
        )
    fake_fig = go.Figure() if go is not None else None
    if fake_fig is not None:
        embedded = str(
            pio.to_html(
                {"data": [], "layout": {"template": {}}},
                include_plotlyjs=True,
                full_html=False,
            )
        )
        return embedded
    return ""


def _get_template_content() -> str:  # noqa: E501
    """Get embedded HTML template content."""
    return """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>재무 분석 리포트 - {{ summary.period }}</title>
    {{ plotly_js | safe }}
    <style>
        * {
            box-sizing: border-box;
        }
        body {
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans KR", sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }
        .header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 30px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.1);
        }
        .header h1 {
            margin: 0 0 10px 0;
            font-size: 28px;
        }
        .header p {
            margin: 5px 0;
            opacity: 0.9;
        }
        .summary-cards {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }
        .summary-card {
            background: white;
            padding: 20px;
            border-radius: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
            text-align: center;
        }
        .summary-card .label {
            font-size: 14px;
            color: #666;
            margin-bottom: 5px;
        }
        .summary-card .value {
            font-size: 24px;
            font-weight: 600;
            color: #333;
        }
        .summary-card .value.expense {
            color: #e53e3e;
        }
        .summary-card .value.income {
            color: #38a169;
        }
        .chart-container {
            background: white;
            padding: 20px;
            border-radius: 10px;
            margin-bottom: 20px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        }
        .chart-container h2 {
            margin: 0 0 15px 0;
            font-size: 18px;
            color: #333;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }
        th, td {
            padding: 12px 15px;
            text-align: left;
            border-bottom: 1px solid #eee;
        }
        th {
            background: #f8f9fa;
            font-weight: 600;
            color: #555;
        }
        tr:hover {
            background: #f8f9fa;
        }
        .amount {
            font-family: "Roboto Mono", monospace;
            text-align: right;
        }
        .amount.negative {
            color: #e53e3e;
        }
        .footer {
            text-align: center;
            padding: 20px;
            color: #888;
            font-size: 12px;
        }
        @media print {
            body {
                background: white;
                padding: 0;
            }
            .chart-container {
                page-break-inside: avoid;
                box-shadow: none;
                border: 1px solid #ddd;
            }
        }
        @media (max-width: 600px) {
            body {
                padding: 10px;
            }
            .header {
                padding: 20px;
            }
            .header h1 {
                font-size: 22px;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <h1>💰 재무 분석 리포트</h1>
        <p>📅 기간: {{ summary.period }}</p>
        <p>🕐 생성일: {{ summary.generated_at }}</p>
    </div>

    <div class="summary-cards">
        <div class="summary-card">
            <div class="label">총 거래 건수</div>
            <div class="value">{{ "{:,}".format(summary.total_transactions) }}건</div>
        </div>
        <div class="summary-card">
            <div class="label">총 지출</div>
            <div class="value expense">₩{{ "{:,.0f}".format(summary.total_expenses) }}</div>
        </div>
        <div class="summary-card">
            <div class="label">총 수입</div>
            <div class="value income">₩{{ "{:,.0f}".format(summary.total_income) }}</div>
        </div>
    </div>

    {% if charts.monthly_trend %}
    <div class="chart-container">
        <h2>📈 월별 지출 추이</h2>
        {{ charts.monthly_trend | safe }}
    </div>
    {% endif %}

    {% if charts.tag_pie %}
    <div class="chart-container">
        <h2>🏷️ 태그별 지출 분포</h2>
        {{ charts.tag_pie | safe }}
    </div>
    {% endif %}

    {% if charts.merchants_bar %}
    <div class="chart-container">
        <h2>🏪 주요 가맹점</h2>
        {{ charts.merchants_bar | safe }}
    </div>
    {% endif %}

    <div class="chart-container">
        <h2>📊 월별 지출 상세</h2>
        <table>
            <thead>
                <tr>
                    <th>월</th>
                    <th>거래 건수</th>
                    <th class="amount">총 지출</th>
                </tr>
            </thead>
            <tbody>
                {% for row in monthly_spend %}
                <tr>
                    <td>{{ row.month }}</td>
                    <td>{{ row.transaction_count }}건</td>
                    <td class="amount negative">₩{{ "{:,.0f}".format(row.total_amount | abs) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="chart-container">
        <h2>🏷️ 태그별 지출 상세</h2>
        <table>
            <thead>
                <tr>
                    <th>태그</th>
                    <th>거래 건수</th>
                    <th class="amount">총 지출</th>
                    <th class="amount">비율</th>
                </tr>
            </thead>
            <tbody>
                {% for row in tag_breakdown %}
                <tr>
                    <td>{{ row.tag }}</td>
                    <td>{{ row.transaction_count }}건</td>
                    <td class="amount negative">₩{{ "{:,.0f}".format(row.total_amount | abs) }}</td>
                    <td class="amount">{{ "%.1f" | format(row.percentage | abs) }}%</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="chart-container">
        <h2>🏪 가맹점별 지출 상세</h2>
        <table>
            <thead>
                <tr>
                    <th>순위</th>
                    <th>가맹점</th>
                    <th>거래 건수</th>
                    <th class="amount">총 지출</th>
                </tr>
            </thead>
            <tbody>
                {% for row in top_merchants %}
                <tr>
                    <td>{{ loop.index }}</td>
                    <td>{{ row.merchant }}</td>
                    <td>{{ row.transaction_count }}건</td>
                    <td class="amount negative">₩{{ "{:,.0f}".format(row.total_amount | abs) }}</td>
                </tr>
                {% endfor %}
            </tbody>
        </table>
    </div>

    <div class="footer">
        <p>Generated by finjuice | Local-first Personal Finance Tools</p>
    </div>
</body>
</html>"""


def _format_currency(amount: float | int) -> str:
    """Format a numeric amount as KRW."""
    return f"₩{abs(amount):,.0f}"


def _render_table_rows(rows: list[dict], columns: list[tuple[str, str, bool]]) -> str:
    """Render HTML table rows from row dictionaries."""
    rendered_rows: list[str] = []
    for row in rows:
        cells: list[str] = []
        for key, label, is_amount in columns:
            if key == "_index":
                value = row[label]
            else:
                value = row.get(key, "")
            text = _format_currency(value) if is_amount else html.escape(str(value))
            class_name = ' class="amount negative"' if is_amount else ""
            cells.append(f"<td{class_name}>{text}</td>")
        rendered_rows.append(f"<tr>{''.join(cells)}</tr>")
    return "\n".join(rendered_rows)


def _render_html_report(
    summary: dict,
    charts: dict[str, Optional[str]],
    monthly_spend_rows: list[dict],
    tag_breakdown_rows: list[dict],
    top_merchants_rows: list[dict],
    offline: bool = True,
) -> str:
    """Render HTML without requiring Jinja2."""
    plotly_tag = _plotly_js_tag(offline=offline)
    monthly_table_rows = _render_table_rows(
        monthly_spend_rows,
        [
            ("month", "month", False),
            ("transaction_count", "transaction_count", False),
            ("total_amount", "total_amount", True),
        ],
    )
    tag_table_rows = _render_table_rows(
        tag_breakdown_rows,
        [
            ("tag", "tag", False),
            ("transaction_count", "transaction_count", False),
            ("total_amount", "total_amount", True),
            ("percentage", "percentage", False),
        ],
    ).replace("</td></tr>", "%</td></tr>")
    merchant_rows = [{"_index": index, **row} for index, row in enumerate(top_merchants_rows, 1)]
    merchant_table_rows = _render_table_rows(
        merchant_rows,
        [
            ("_index", "_index", False),
            ("merchant", "merchant", False),
            ("transaction_count", "transaction_count", False),
            ("total_amount", "total_amount", True),
        ],
    )

    chart_sections: list[str] = []
    chart_titles = {
        "monthly_trend": "📈 월별 지출 추이",
        "tag_pie": "🏷️ 태그별 지출 분포",
        "merchants_bar": "🏪 주요 가맹점",
    }
    for chart_key, title in chart_titles.items():
        if charts.get(chart_key):
            chart_sections.append(
                f"""
    <div class="chart-container">
        <h2>{title}</h2>
        {charts[chart_key]}
    </div>"""
            )

    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>재무 분석 리포트 - {html.escape(str(summary["period"]))}</title>
    {plotly_tag}
    <style>
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans KR", sans-serif;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
            line-height: 1.6;
        }}
        .header, .chart-container, .summary-card {{
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
        }}
        .header {{
            padding: 24px;
            margin-bottom: 20px;
        }}
        .summary-cards {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 20px;
        }}
        .summary-card {{
            padding: 20px;
            text-align: center;
        }}
        .summary-card .label {{
            color: #666;
            font-size: 14px;
        }}
        .summary-card .value {{
            font-size: 24px;
            font-weight: 600;
        }}
        .chart-container {{
            padding: 20px;
            margin-bottom: 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-top: 15px;
        }}
        th, td {{
            padding: 12px 15px;
            border-bottom: 1px solid #eee;
            text-align: left;
        }}
        .amount {{
            text-align: right;
            font-family: "Roboto Mono", monospace;
        }}
        .negative {{
            color: #e53e3e;
        }}
    </style>
</head>
<body>
    <div class="header">
        <h1>💰 재무 분석 리포트</h1>
        <p>📅 기간: {html.escape(str(summary["period"]))}</p>
        <p>🕐 생성일: {html.escape(str(summary["generated_at"]))}</p>
    </div>

    <div class="summary-cards">
        <div class="summary-card">
            <div class="label">총 거래 건수</div>
            <div class="value">{summary["total_transactions"]:,}건</div>
        </div>
        <div class="summary-card">
            <div class="label">총 지출</div>
            <div class="value negative">{_format_currency(summary["total_expenses"])}</div>
        </div>
        <div class="summary-card">
            <div class="label">총 수입</div>
            <div class="value">{_format_currency(summary["total_income"])}</div>
        </div>
    </div>
    {"".join(chart_sections)}
    <div class="chart-container">
        <h2>📊 월별 지출 상세</h2>
        <table>
            <thead>
                <tr><th>월</th><th>거래 건수</th><th class="amount">총 지출</th></tr>
            </thead>
            <tbody>
                {monthly_table_rows}
            </tbody>
        </table>
    </div>
    <div class="chart-container">
        <h2>🏷️ 태그별 지출 상세</h2>
        <table>
            <thead>
                <tr><th>태그</th><th>거래 건수</th><th class="amount">총 지출</th><th class="amount">비율</th></tr>
            </thead>
            <tbody>
                {tag_table_rows}
            </tbody>
        </table>
    </div>
    <div class="chart-container">
        <h2>🏪 가맹점별 지출 상세</h2>
        <table>
            <thead>
                <tr><th>순위</th><th>가맹점</th><th>거래 건수</th><th class="amount">총 지출</th></tr>
            </thead>
            <tbody>
                {merchant_table_rows}
            </tbody>
        </table>
    </div>
</body>
</html>"""


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
