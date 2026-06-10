"""Plotly theme configuration for consistent chart styling.

This module provides a standardized theme for all financial analysis charts,
ensuring visual consistency across reports and easy customization.
"""

import plotly.graph_objects as go
import plotly.io as pio

# Custom theme based on Plotly's 'plotly_white' with financial data optimizations
FINANCIAL_THEME = {
    "layout": {
        "font": {
            "family": "Inter, -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif",
            "size": 12,
            "color": "#2c3e50",
        },
        "title": {"font": {"size": 18, "color": "#1a1a1a"}, "x": 0.5, "xanchor": "center"},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#f8f9fa",
        "colorway": [
            "#2ecc71",  # Green (positive/income)
            "#e74c3c",  # Red (negative/expense)
            "#3498db",  # Blue
            "#f39c12",  # Orange
            "#9b59b6",  # Purple
            "#1abc9c",  # Teal
            "#34495e",  # Dark gray
            "#e67e22",  # Dark orange
        ],
        "hovermode": "closest",
        "hoverlabel": {
            "bgcolor": "#ffffff",
            "font": {"size": 12, "family": "monospace"},
            "bordercolor": "#cccccc",
        },
        "xaxis": {
            "showgrid": True,
            "gridcolor": "#e1e4e8",
            "gridwidth": 1,
            "zeroline": False,
            "showline": True,
            "linecolor": "#d1d5db",
            "linewidth": 1,
        },
        "yaxis": {
            "showgrid": True,
            "gridcolor": "#e1e4e8",
            "gridwidth": 1,
            "zeroline": True,
            "zerolinecolor": "#666666",
            "zerolinewidth": 2,
            "showline": True,
            "linecolor": "#d1d5db",
            "linewidth": 1,
        },
        "margin": {"l": 60, "r": 30, "t": 80, "b": 60},
    }
}

# Register custom theme
pio.templates["financial"] = go.layout.Template(layout=FINANCIAL_THEME["layout"])
pio.templates.default = "financial"


def get_color_for_amount(amount: float) -> str:
    """Return color based on transaction amount.

    Args:
        amount: Transaction amount (negative for expenses, positive for income)

    Returns:
        Hex color code (green for income, red for expenses)
    """
    return "#2ecc71" if amount >= 0 else "#e74c3c"


def format_currency(amount: float, currency: str = "KRW") -> str:
    """Format amount as currency string.

    Args:
        amount: Numerical amount
        currency: Currency code (default: KRW)

    Returns:
        Formatted string (e.g., "₩1,234,567" or "-₩1,234,567")
    """
    if currency == "KRW":
        symbol = "₩"
        formatted = f"{abs(amount):,.0f}"
    elif currency == "USD":
        symbol = "$"
        formatted = f"{abs(amount):,.2f}"
    else:
        symbol = currency
        formatted = f"{abs(amount):,.2f}"

    prefix = "-" if amount < 0 else ""
    return f"{prefix}{symbol}{formatted}"


def apply_financial_theme(fig: go.Figure) -> go.Figure:
    """Apply financial theme to a Plotly figure.

    Args:
        fig: Plotly Figure object

    Returns:
        Modified Figure with financial theme applied
    """
    fig.update_layout(template="financial")
    return fig
