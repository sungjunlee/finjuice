"""Month-window parsing helpers for SQL template parameters.

Owns YYYY-MM validation, inclusive month-range expansion, and month-window
lists. Parameter coercion, SQL literal conversion, and template context
resolution stay in
:mod:`finjuice.pipeline.cli.commands.template_cmd.param_coercion`, which
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

import re
from datetime import date

MONTH_PATTERN = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
MONTH_WINDOW_FORMAT = "YYYY-MM:YYYY-MM or YYYY-MM,YYYY-MM,..."


def _parse_month_start(raw: str, *, param_name: str) -> date:
    """Parse a YYYY-MM literal into the first day of that month."""
    if not MONTH_PATTERN.match(raw):
        raise ValueError(f"Invalid month value for '{param_name}': {raw} (expected YYYY-MM)")
    year, month = raw.split("-", 1)
    return date(int(year), int(month), 1)


def _expand_month_range(start_month: str, end_month: str) -> list[str]:
    """Expand an inclusive YYYY-MM month range."""
    months: list[str] = []
    year, month = map(int, start_month.split("-"))
    end_year, end_month_num = map(int, end_month.split("-"))

    while (year, month) <= (end_year, end_month_num):
        months.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1

    return months


def _parse_month_window(raw_value: str, param_name: str) -> list[str]:
    """Parse a month selector that supports inclusive ranges or explicit lists."""
    raw = raw_value.strip()
    if not raw:
        raise ValueError(
            f"Invalid month window value for '{param_name}': {raw_value} "
            f"(expected {MONTH_WINDOW_FORMAT})"
        )

    if ":" in raw and "," in raw:
        raise ValueError(
            f"Invalid month window value for '{param_name}': {raw} (expected {MONTH_WINDOW_FORMAT})"
        )

    if ":" in raw:
        parts = [part.strip() for part in raw.split(":")]
        if len(parts) != 2 or not parts[0] or not parts[1]:
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                f"(expected {MONTH_WINDOW_FORMAT})"
            )
        start_month, end_month = parts
        if not MONTH_PATTERN.match(start_month) or not MONTH_PATTERN.match(end_month):
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                f"(expected {MONTH_WINDOW_FORMAT})"
            )
        if start_month > end_month:
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                "(start month must be <= end month)"
            )
        return _expand_month_range(start_month, end_month)

    month_values = [part.strip() for part in raw.split(",")]
    if not month_values or any(not month for month in month_values):
        raise ValueError(
            f"Invalid month window value for '{param_name}': {raw} (expected {MONTH_WINDOW_FORMAT})"
        )

    deduped_months: list[str] = []
    seen: set[str] = set()
    for month_value in month_values:
        if not MONTH_PATTERN.match(month_value):
            raise ValueError(
                f"Invalid month window value for '{param_name}': {raw} "
                f"(expected {MONTH_WINDOW_FORMAT})"
            )
        if month_value not in seen:
            deduped_months.append(month_value)
            seen.add(month_value)

    return deduped_months
