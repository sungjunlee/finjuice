"""CLI package for finjuice.

Keep this package init lightweight so non-CLI modules can import shared helpers
without pulling in the full Typer app and its command graph.
"""

__all__: list[str] = []
