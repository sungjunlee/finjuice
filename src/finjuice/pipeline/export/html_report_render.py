"""HTML template and fallback render helpers for interactive reports.

``generate_html_report`` stays in ``html_report.py``. This module owns the
non-Jinja2 HTML fallback; the Plotly.js script tag and Jinja2 template live
in :mod:`finjuice.pipeline.export.html_report_render_helpers`.
"""

import html
from typing import Optional

from finjuice.pipeline.export.html_report_render_helpers import (
    _get_template_content,
    _plotly_js_tag,
)

__all__ = [
    "_get_template_content",
    "_plotly_js_tag",
    "_format_currency",
    "_render_html_report",
    "_render_table_rows",
]


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
