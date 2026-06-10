"""Reusable chart components for financial analysis.

This module provides common chart patterns used across multiple analysis templates,
reducing code duplication and ensuring visual consistency.

Note: The canonical Plotly chart functions used by finjuice export live in
``finjuice.pipeline.export.chart_utils``. This module remains available for
AI-skill-facing use with complementary patterns (bar charts, comparison tables).
"""

from typing import List, Optional

import plotly.graph_objects as go
import polars as pl

from .plotly_themes import apply_financial_theme, format_currency


def create_monthly_bar_chart(
    df: pl.DataFrame,
    x_col: str = "month",
    y_col: str = "amount",
    title: str = "Monthly Spending",
    show_trend: bool = True,
) -> go.Figure:
    """Create a bar chart for monthly data with optional trend line.

    Args:
        df: Polars DataFrame with monthly data
        x_col: Column name for x-axis (typically 'month')
        y_col: Column name for y-axis (typically 'amount')
        title: Chart title
        show_trend: Whether to add a trend line (default: True)

    Returns:
        Plotly Figure object

    Example:
        >>> df = pl.DataFrame({
        ...     "month": ["2024-10", "2024-11"],
        ...     "amount": [-1500000, -1750000]
        ... })
        >>> fig = create_monthly_bar_chart(df)
    """
    # Convert to dict for Plotly (avoid pandas conversion)
    data = df.to_dict(as_series=False)

    fig = go.Figure()

    # Add bar chart
    fig.add_trace(
        go.Bar(
            x=data[x_col],
            y=[abs(val) for val in data[y_col]],  # Show positive values
            name="Spending",
            marker_color="#e74c3c",
            text=[format_currency(val) for val in data[y_col]],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>Amount: %{text}<extra></extra>",
        )
    )

    # Add trend line if requested
    if show_trend and len(data[x_col]) > 1:
        # Simple linear trend
        y_values = [abs(val) for val in data[y_col]]
        x_numeric = list(range(len(y_values)))

        # Linear regression (simple)
        n = len(x_numeric)
        sum_x = sum(x_numeric)
        sum_y = sum(y_values)
        sum_xy = sum(x * y for x, y in zip(x_numeric, y_values))
        sum_x2 = sum(x * x for x in x_numeric)

        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        intercept = (sum_y - slope * sum_x) / n

        trend_y = [slope * x + intercept for x in x_numeric]

        fig.add_trace(
            go.Scatter(
                x=data[x_col],
                y=trend_y,
                name="Trend",
                mode="lines",
                line=dict(color="#3498db", width=2, dash="dash"),
                hovertemplate="<b>Trend</b><br>%{y:,.0f}<extra></extra>",
            )
        )

    fig.update_layout(
        title=title,
        xaxis_title="Month",
        yaxis_title="Amount (₩)",
        showlegend=True,
        hovermode="x unified",
    )

    return apply_financial_theme(fig)


def create_pie_chart(
    df: pl.DataFrame,
    names_col: str,
    values_col: str,
    title: str = "Distribution",
    top_n: Optional[int] = None,
) -> go.Figure:
    """Create a pie chart for categorical data.

    Args:
        df: Polars DataFrame with categorical data
        names_col: Column name for categories (labels)
        values_col: Column name for values
        title: Chart title
        top_n: Show only top N categories (optional)

    Returns:
        Plotly Figure object

    Example:
        >>> df = pl.DataFrame({
        ...     "tag": ["식비", "교통", "쇼핑"],
        ...     "amount": [-500000, -200000, -300000]
        ... })
        >>> fig = create_pie_chart(df, "tag", "amount", top_n=10)
    """
    # Sort by value descending and take top N if specified
    df_sorted = df.sort(values_col, descending=False)  # Expenses are negative

    if top_n and len(df_sorted) > top_n:
        df_top = df_sorted.head(top_n)
        # Aggregate remaining into "기타" (Other)
        df_rest = df_sorted.tail(len(df_sorted) - top_n)
        rest_total = df_rest[values_col].sum()

        df_with_other = pl.concat(
            [df_top, pl.DataFrame({names_col: ["기타 (Other)"], values_col: [rest_total]})]
        )
        df_final = df_with_other
    else:
        df_final = df_sorted

    # Convert to dict
    data = df_final.to_dict(as_series=False)

    # Create pie chart
    fig = go.Figure(
        data=[
            go.Pie(
                labels=data[names_col],
                values=[abs(val) for val in data[values_col]],  # Absolute values for pie
                text=[format_currency(val) for val in data[values_col]],
                textposition="auto",
                hovertemplate=(
                    "<b>%{label}</b><br>Amount: %{text}<br>Percentage: %{percent}<extra></extra>"
                ),
                marker=dict(line=dict(color="#ffffff", width=2)),
            )
        ]
    )

    fig.update_layout(
        title=title,
        showlegend=True,
        legend=dict(orientation="v", yanchor="middle", y=0.5, xanchor="left", x=1.05),
    )

    return apply_financial_theme(fig)


def create_comparison_table(
    df: pl.DataFrame, columns: List[str], title: Optional[str] = None
) -> go.Figure:
    """Create a formatted table for data comparison.

    Args:
        df: Polars DataFrame to display
        columns: List of column names to include
        title: Optional table title

    Returns:
        Plotly Figure with table

    Example:
        >>> df = pl.DataFrame({
        ...     "Category": ["식비", "교통"],
        ...     "Oct": [-500000, -200000],
        ...     "Nov": [-550000, -180000]
        ... })
        >>> fig = create_comparison_table(df, ["Category", "Oct", "Nov"])
    """
    # Prepare data
    df_subset = df.select(columns)
    data = df_subset.to_dict(as_series=False)

    # Format values (currency for numeric columns)
    formatted_data = {}
    for col in columns:
        if df_subset[col].dtype in [pl.Float64, pl.Int64]:
            formatted_data[col] = [format_currency(val) for val in data[col]]
        else:
            formatted_data[col] = data[col]

    # Create table
    fig = go.Figure(
        data=[
            go.Table(
                header=dict(
                    values=[f"<b>{col}</b>" for col in columns],
                    fill_color="#3498db",
                    font=dict(color="white", size=13),
                    align="left",
                    height=30,
                ),
                cells=dict(
                    values=[formatted_data[col] for col in columns],
                    fill_color=[["#f8f9fa", "#ffffff"] * (len(df_subset) // 2 + 1)],
                    align="left",
                    height=25,
                ),
            )
        ]
    )

    if title:
        fig.update_layout(title=title)

    return apply_financial_theme(fig)


def export_html(fig: go.Figure, output_path: str, include_plotlyjs: str = "cdn") -> None:
    """Export Plotly figure to standalone HTML file.

    Args:
        fig: Plotly Figure object
        output_path: Path to save HTML file
        include_plotlyjs: How to include Plotly.js ('cdn', 'directory', True, False)

    Example:
        >>> fig = create_monthly_bar_chart(df)
        >>> export_html(fig, "exports/reports/monthly_spend.html")
    """
    fig.write_html(
        output_path,
        include_plotlyjs=include_plotlyjs,
        config={"displayModeBar": True, "responsive": True},
    )
    print(f"✅ Report exported: {output_path}")
