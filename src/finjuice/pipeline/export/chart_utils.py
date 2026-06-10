"""Shared Plotly chart utilities for HTML reports.

This module is the canonical source for Plotly chart generation functions
used by the HTML report pipeline. Related chart components also live in
``templates/visualizations/chart_helpers.py`` (AI-skill-facing helpers).
"""

import polars as pl

try:
    import plotly.graph_objects as go
except ImportError:
    go = None  # type: ignore[assignment]  # optional dep; guarded by _check_dependencies


def create_monthly_trend_chart(
    df: pl.DataFrame,
    include_plotlyjs: bool = False,
) -> str:
    """Create monthly spending trend line chart.

    Args:
        df: DataFrame with columns [month, transaction_count, total_amount]
        include_plotlyjs: Whether to include Plotly.js in this fragment.

    Returns:
        HTML string with Plotly line chart, or placeholder if unavailable.
    """
    if go is None:
        return "<p>Plotly not available</p>"
    if df.is_empty():
        return "<p>No data available for chart</p>"

    df_sorted = df.sort("month")
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=df_sorted["month"].to_list(),
            y=[abs(v) for v in df_sorted["total_amount"].to_list()],
            mode="lines+markers",
            name="월별 지출",
            line=dict(color="rgb(255, 99, 132)", width=3),
            marker=dict(size=8),
            hovertemplate="<b>%{x}</b><br>지출: ₩%{y:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text="월별 지출 추이", font=dict(size=18)),
        xaxis_title="월",
        yaxis_title="지출 (원)",
        yaxis=dict(tickformat=",.0f", tickprefix="₩"),
        hovermode="x unified",
        template="plotly_white",
        margin=dict(l=60, r=40, t=60, b=40),
        height=400,
    )
    return str(fig.to_html(full_html=False, include_plotlyjs=include_plotlyjs))


def create_tag_pie_chart(
    df: pl.DataFrame,
    include_plotlyjs: bool = False,
) -> str:
    """Create tag breakdown pie chart.

    Args:
        df: DataFrame with columns [tag, transaction_count, total_amount, percentage]
        include_plotlyjs: Whether to include Plotly.js in this fragment.

    Returns:
        HTML string with Plotly pie chart, or placeholder if unavailable.
    """
    if go is None:
        return "<p>Plotly not available</p>"
    if df.is_empty():
        return "<p>No tag data available</p>"

    colors = [
        "rgb(255, 99, 132)",
        "rgb(54, 162, 235)",
        "rgb(255, 206, 86)",
        "rgb(75, 192, 192)",
        "rgb(153, 102, 255)",
        "rgb(255, 159, 64)",
        "rgb(199, 199, 199)",
        "rgb(83, 102, 255)",
        "rgb(255, 99, 255)",
        "rgb(99, 255, 132)",
    ]

    fig = go.Figure()
    fig.add_trace(
        go.Pie(
            labels=df["tag"].to_list(),
            values=[abs(v) for v in df["total_amount"].to_list()],
            textinfo="label+percent",
            textposition="outside",
            hovertemplate=(
                "<b>%{label}</b><br>지출: ₩%{value:,.0f}<br>비율: %{percent}<extra></extra>"
            ),
            marker=dict(colors=colors),
        )
    )
    fig.update_layout(
        title=dict(text="태그별 지출 분포", font=dict(size=18)),
        template="plotly_white",
        margin=dict(l=40, r=40, t=60, b=40),
        height=450,
        showlegend=True,
        legend=dict(orientation="v", x=1.02, y=0.5),
    )
    return str(fig.to_html(full_html=False, include_plotlyjs=include_plotlyjs))


def create_merchants_bar_chart(
    df: pl.DataFrame,
    include_plotlyjs: bool = False,
) -> str:
    """Create top merchants horizontal bar chart.

    Args:
        df: DataFrame with columns [merchant, transaction_count, total_amount]
        include_plotlyjs: Whether to include Plotly.js in this fragment.

    Returns:
        HTML string with Plotly horizontal bar chart, or placeholder.
    """
    if go is None:
        return "<p>Plotly not available</p>"
    if df.is_empty():
        return "<p>No merchant data available</p>"

    df_reversed = df.reverse()
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=[abs(v) for v in df_reversed["total_amount"].to_list()],
            y=df_reversed["merchant"].to_list(),
            orientation="h",
            marker=dict(color="rgb(54, 162, 235)"),
            hovertemplate="<b>%{y}</b><br>지출: ₩%{x:,.0f}<extra></extra>",
        )
    )
    fig.update_layout(
        title=dict(text=f"주요 가맹점 (Top {len(df)})", font=dict(size=18)),
        xaxis_title="지출 (원)",
        xaxis=dict(tickformat=",.0f", tickprefix="₩"),
        yaxis_title="",
        template="plotly_white",
        margin=dict(l=150, r=40, t=60, b=40),
        height=max(400, len(df) * 25 + 100),
    )
    return str(fig.to_html(full_html=False, include_plotlyjs=include_plotlyjs))
