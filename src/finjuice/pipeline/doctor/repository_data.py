"""Canonical transaction diagnostics without display floats or report filtering."""

from __future__ import annotations

from datetime import date
from typing import Any

from finjuice.pipeline.doctor.models import CheckResult
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot


def transaction_checks(
    snapshot: TransactionReadSnapshot,
) -> tuple[list[CheckResult], dict[str, Any]]:
    """Separate complete totals from observed typed rows and unknown dates."""
    by_id = {row["transaction_id"]: row for row in snapshot.rows}
    if len(snapshot.scopes) != len(by_id) or {s.transaction_id for s in snapshot.scopes} != set(
        by_id
    ):
        raise ValueError("Canonical transaction scopes are unavailable.")
    rows = [by_id[s.transaction_id] for s in snapshot.scopes if s.included]
    dates = [parsed for row in rows if (parsed := _iso_date(row.get("date"))) is not None]
    complete = not snapshot.unmaterialized_months
    metadata: dict[str, Any] = {
        "transaction_state": "available" if complete else "incomplete",
        "transaction_total": len(rows) if complete else None,
        "observed_typed_rows": len(rows),
        "excluded_typed_rows": len(snapshot.rows) - len(rows),
        "partition_months": list(snapshot.partition_months),
        "unmaterialized_months": list(snapshot.unmaterialized_months),
        "unknown_date_rows": len(rows) - len(dates),
        "unknown_month_rows": sum(s.included and s.month is None for s in snapshot.scopes),
        "date_min": min(dates) if dates and complete else None,
        "date_max": max(dates) if dates and complete else None,
    }
    check = CheckResult(
        "ok" if complete else "error",
        f"{len(rows)} registered transactions."
        if complete
        else "Canonical transaction coverage is incomplete.",
        detail=(
            "Complete total and date range are unavailable."
            if not complete
            else (
                f"Partition months: {len(snapshot.partition_months)}; "
                f"date range: {metadata['date_min'] or 'unavailable'} ~ "
                f"{metadata['date_max'] or 'unavailable'}; "
                f"unknown date rows: {metadata['unknown_date_rows']}."
            )
        ),
        name="repository_transactions",
    )
    return [check], metadata


def _iso_date(value: object) -> str | None:
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
        return value if parsed.isoformat() == value else None
    except ValueError:
        return None
