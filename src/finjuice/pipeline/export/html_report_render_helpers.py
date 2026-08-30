"""Template asset helpers for interactive HTML reports.

Owns the Plotly.js script tag and the Jinja2 HTML template content,
split out of :mod:`finjuice.pipeline.export.html_report_render`.
"""

import plotly.io as pio

try:
    import plotly.graph_objects as go
except ImportError:
    go = None  # type: ignore[assignment]  # optional dep fallback; guarded before use


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
