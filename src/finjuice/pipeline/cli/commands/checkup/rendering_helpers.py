"""Human-readable domain summary helpers for ``finjuice checkup``.

Owns one-line pipeline/review/budget/networth/obligation summaries and KRW
formatting. JSON payload assembly, compact privacy projection, and text
orchestration stay in :mod:`finjuice.pipeline.cli.commands.checkup.rendering`.
"""

from __future__ import annotations

from typing import Any


def _summarize_pipeline(pipeline: dict[str, Any]) -> str:
    """Render a single pipeline summary line."""
    status = str(pipeline["status"])
    if status == "empty":
        return "empty; no transaction partitions"
    if status == "import_failures":
        return (
            "import_failures; "
            f"failed={pipeline['failed_import_files']}, "
            f"pending={pipeline['pending_import_files']}"
        )
    if status == "pending_imports":
        return f"pending_imports; staged={pipeline['pending_import_files']}"
    if status == "stale":
        return f"stale; latest data {pipeline['days_since_latest']}d old"
    latest = pipeline.get("latest_transaction_date") or pipeline.get("data_range") or "-"
    return f"{status}; latest={latest}"


def _summarize_review(review: dict[str, Any]) -> str:
    """Render a single review summary line."""
    status = str(review["status"])
    if status == "empty":
        return "empty; no reviewable transactions"
    if status == "skipped":
        return "skipped; run finjuice checkup for full detectors"
    return (
        f"{status}; candidates={review['total_candidates']}, "
        f"untagged={review['untagged_count']}, "
        f"low_confidence={review['low_confidence_count']}"
    )


def _summarize_budget(budget: dict[str, Any]) -> str:
    """Render a single budget summary line.

    Uses ``.get`` for both ``actual`` and ``target`` so the privacy-redacted
    and compact-profile shapes (which null out or omit those keys) render as
    "-" instead of raising.
    """
    status = str(budget["status"])
    if status == "missing_config":
        return "missing_config; goals.yaml missing"
    if status == "invalid":
        return "invalid; goals.yaml validation failed"
    summary = budget.get("summary")
    if summary is None:
        return status
    month = budget.get("month")
    actual = summary.get("actual") if isinstance(summary, dict) else None
    target = summary.get("target") if isinstance(summary, dict) else None
    return f"{status}; month={month}, actual={_format_won(actual)}, target={_format_won(target)}"


def _summarize_networth(networth: dict[str, Any]) -> str:
    """Render a single net worth summary line."""
    status = str(networth["status"])
    if status == "missing_data":
        return "missing_data; no asset snapshots or assets.yaml entries"
    if status == "invalid":
        return "invalid; assets.yaml validation failed"
    # Privacy-redacted and compact profiles null out or drop the net_worth value;
    # render those uniformly as "-".
    return f"{status}; net_worth={_format_won(networth.get('net_worth'))}"


def _summarize_obligations(obligations: dict[str, Any]) -> str:
    """Render a single obligation confirmation summary line.

    ``threshold_monthly_krw`` is nulled or omitted under the privacy-redacted
    and compact profiles; ``_format_won`` renders ``None`` as "-".
    """
    status = str(obligations["status"])
    if status == "empty":
        return "empty; no transaction history"
    if status == "skipped":
        return "skipped; run finjuice checkup for full detectors"
    threshold = obligations.get("threshold_monthly_krw")
    if status == "needs_confirmation":
        return (
            "needs_confirmation; "
            f"candidates={obligations.get('candidate_count')}, "
            f"threshold={_format_won(threshold)}/mo"
        )
    return (
        f"{status}; known={obligations.get('known_obligation_count')}, "
        f"threshold={_format_won(threshold)}/mo"
    )


def _format_won(value: Any) -> str:
    """Format a numeric value as Korean won."""
    if value is None:
        return "-"
    amount = float(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}₩{abs(amount):,.0f}"
