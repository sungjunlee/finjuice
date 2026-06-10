"""
Analysis templates for finjuice.

This package contains reusable Python analysis scripts that AI agents
(Claude Code, ChatGPT, Cursor) can easily customize and execute.

Templates:
    - analysis/monthly_spend.py: Monthly spending trends with charts
    - analysis/tag_breakdown.py: Spending breakdown by tag
    - analysis/subscriptions.py: Recurring payment detection
    - analysis/card_rewards.py: Card rewards optimization

Usage:
    Each template is a standalone script with rich docstrings.
    AI agents can read the docstring to understand usage and
    execute with minimal modification.

Example:
    # AI agent workflow
    python templates/analysis/monthly_spend.py --months 2024-10,2024-11

See templates/README_TEMPLATES.md for detailed usage guide.
"""

__version__ = "0.1.0"
