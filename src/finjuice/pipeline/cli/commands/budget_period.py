"""Budget CLI period and partition-window resolution."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from finjuice.pipeline.goals import validate_month_literal


def parse_budget_period(requested_month: str) -> str:
    """Parse an explicit budget period from ``--month``.

    Args:
        requested_month: User-supplied ``YYYY-MM`` period.

    Returns:
        The validated ``YYYY-MM`` period.

    Raises:
        ValueError: If ``requested_month`` is not a valid ``YYYY-MM`` value.
    """
    return validate_month_literal(requested_month, param_name="month")


def latest_budget_window(csv_base_dir: Path) -> str | None:
    """Return the latest ``YYYY-MM`` partition window with ``transactions.csv``.

    Args:
        csv_base_dir: Root of ``transactions/YYYY/MM/`` partitions.

    Returns:
        The latest partition month, or ``None`` when no window exists.
    """
    if not csv_base_dir.exists():
        return None

    months = [
        f"{path.parent.parent.name}-{path.parent.name}"
        for path in csv_base_dir.glob("*/*/transactions.csv")
        if path.is_file()
    ]
    if not months:
        return None
    return sorted(months)[-1]


def resolve_budget_period(
    requested_month: str | None,
    *,
    csv_base_dir: Path,
    today: date | None = None,
) -> str:
    """Resolve the effective budget period from ``--month`` or the data window.

    Explicit ``--month`` wins. Otherwise the latest transaction partition is
    used. When no partitions exist, the local calendar month is used.

    Args:
        requested_month: Optional user-supplied ``YYYY-MM`` period.
        csv_base_dir: Root of ``transactions/YYYY/MM/`` partitions.
        today: Optional clock override for the empty-window fallback.

    Returns:
        The effective ``YYYY-MM`` period.
    """
    if requested_month is not None:
        return parse_budget_period(requested_month)

    latest_month = latest_budget_window(csv_base_dir)
    if latest_month is not None:
        return latest_month
    clock = today if today is not None else datetime.now().astimezone().date()
    return clock.strftime("%Y-%m")
