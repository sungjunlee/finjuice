"""Tagging-pressure collector for one-shot workflow automation.

Owns untagged coverage stats and merchant-pressure samples. The shared
signal-status literal lives in
:mod:`finjuice.pipeline.automation_pending_imports`. Next-step composition
stays in :mod:`finjuice.pipeline.automation_helpers`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]  # optional dependency sentinel

from finjuice.pipeline.automation_pending_imports import SignalStatus
from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.suggestions import (
    generate_merchant_context,
    get_suggestion_coverage_stats,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MerchantPressureSample:
    """Compact merchant-level sample for untagged pressure."""

    merchant: str
    transaction_count: int
    total_amount: float
    avg_amount: float
    sample_memos: list[str]


@dataclass(frozen=True)
class TaggingPressureSignal:
    """Signal summarizing untagged transaction and merchant pressure."""

    status: SignalStatus
    total_transactions: int
    untagged_transactions: int
    coverage_pct: float
    suggestable_untagged_transactions: int
    suggestable_coverage_pct: float
    transfer_excluded_untagged_transactions: int
    merchant_pressure: list[MerchantPressureSample]


def _collect_tagging_pressure(
    *,
    config: Config,
    sample_limit: int,
    min_count: int,
) -> tuple[TaggingPressureSignal, str | None]:
    """Reuse rules-suggest surfaces to summarize untagged pressure."""
    try:
        stats = get_suggestion_coverage_stats(config.data_dir)
        suggestions = generate_merchant_context(
            config.data_dir,
            rules_file=config.rules_file,
            top_n=sample_limit,
            min_count=min_count,
        )
    except FileNotFoundError:
        stats = {
            "total_count": 0,
            "untagged_count": 0,
            "suggestable_untagged_count": 0,
            "transfer_excluded_untagged_count": 0,
            "coverage_before_pct": 0.0,
            "suggestable_coverage_before_pct": 0.0,
        }
        suggestions = []
    except ImportError as exc:
        logger.warning("Tagging pressure unavailable: %s", exc)
        return (
            TaggingPressureSignal(
                status="unavailable",
                total_transactions=0,
                untagged_transactions=0,
                coverage_pct=0.0,
                suggestable_untagged_transactions=0,
                suggestable_coverage_pct=0.0,
                transfer_excluded_untagged_transactions=0,
                merchant_pressure=[],
            ),
            "Tagging pressure unavailable; check DuckDB analytics setup.",
        )
    except duckdb.Error as exc:
        logger.warning("Tagging pressure collection failed: %s", exc)
        return (
            TaggingPressureSignal(
                status="unavailable",
                total_transactions=0,
                untagged_transactions=0,
                coverage_pct=0.0,
                suggestable_untagged_transactions=0,
                suggestable_coverage_pct=0.0,
                transfer_excluded_untagged_transactions=0,
                merchant_pressure=[],
            ),
            "Tagging pressure unavailable; check DuckDB analytics setup.",
        )

    merchant_pressure = [
        MerchantPressureSample(
            merchant=str(suggestion["merchant"]),
            transaction_count=int(suggestion.get("transaction_count") or 0),
            total_amount=float(suggestion.get("total_amount") or 0.0),
            avg_amount=float(suggestion.get("avg_amount") or 0.0),
            sample_memos=list(suggestion.get("sample_memos") or []),
        )
        for suggestion in suggestions
    ]

    untagged_transactions = int(stats.get("untagged_count") or 0)
    suggestable_untagged_transactions = int(
        stats.get("suggestable_untagged_count", untagged_transactions) or 0
    )
    transfer_excluded_untagged_transactions = int(
        stats.get(
            "transfer_excluded_untagged_count",
            max(untagged_transactions - suggestable_untagged_transactions, 0),
        )
        or 0
    )
    coverage_pct = float(stats.get("coverage_before_pct") or 0.0)
    suggestable_coverage_pct = float(
        stats.get("suggestable_coverage_before_pct", coverage_pct) or 0.0
    )
    status: SignalStatus = "present" if suggestable_untagged_transactions > 0 else "clear"
    return (
        TaggingPressureSignal(
            status=status,
            total_transactions=int(stats.get("total_count") or 0),
            untagged_transactions=untagged_transactions,
            coverage_pct=coverage_pct,
            suggestable_untagged_transactions=suggestable_untagged_transactions,
            suggestable_coverage_pct=suggestable_coverage_pct,
            transfer_excluded_untagged_transactions=transfer_excluded_untagged_transactions,
            merchant_pressure=merchant_pressure,
        ),
        None,
    )
