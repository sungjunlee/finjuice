"""Large-transaction collector for one-shot workflow automation.

Owns large-expense counts and samples at an explicit threshold. The shared
signal-status literal lives in
:mod:`finjuice.pipeline.automation_pending_imports`. Next-step composition
stays in :mod:`finjuice.pipeline.automation_helpers`, which re-exports these
names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]  # optional dependency sentinel

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.automation_pending_imports import SignalStatus
from finjuice.pipeline.config import Config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LargeTransactionSample:
    """Large expense sample mirroring anomaly_large_txn semantics."""

    date: str
    merchant: str | None
    account: str | None
    category: str | None
    amount_krw: float


@dataclass(frozen=True)
class LargeTransactionSignal:
    """Signal summarizing large expense anomalies at an explicit threshold."""

    status: SignalStatus
    threshold: int
    count: int
    samples: list[LargeTransactionSample]


def _collect_large_transactions(
    *,
    config: Config,
    threshold: int,
    sample_limit: int,
) -> tuple[LargeTransactionSignal, str | None]:
    """Collect large-expense counts and samples using explicit threshold input."""
    count_sql = """
        SELECT COUNT(*) AS anomaly_count
        FROM transactions
        WHERE amount < 0
          AND is_transfer_bool = FALSE
          AND abs(amount) >= ?
    """
    sample_sql = """
        SELECT
            CAST(date AS VARCHAR) AS date,
            merchant_raw,
            account,
            category_final,
            abs(amount) AS amount_krw
        FROM transactions
        WHERE amount < 0
          AND is_transfer_bool = FALSE
          AND abs(amount) >= ?
        ORDER BY amount_krw DESC, date DESC, merchant_raw
        LIMIT ?
    """

    try:
        with DuckDBAnalytics(config.data_dir) as analytics:
            count_row = analytics.conn.execute(count_sql, [threshold]).fetchone()
            sample_rows = (
                analytics.conn.execute(sample_sql, [threshold, sample_limit]).pl().to_dicts()
            )
    except FileNotFoundError:
        return (
            LargeTransactionSignal(
                status="clear",
                threshold=threshold,
                count=0,
                samples=[],
            ),
            None,
        )
    except ImportError as exc:
        logger.warning("Large transaction signal unavailable: %s", exc)
        return (
            LargeTransactionSignal(
                status="unavailable",
                threshold=threshold,
                count=0,
                samples=[],
            ),
            "Large-transaction signal unavailable; check DuckDB analytics setup.",
        )
    except duckdb.Error as exc:
        logger.warning("Large transaction collection failed: %s", exc)
        return (
            LargeTransactionSignal(
                status="unavailable",
                threshold=threshold,
                count=0,
                samples=[],
            ),
            "Large-transaction signal unavailable; check transaction data and analytics setup.",
        )

    count = int((count_row or [0])[0] or 0)
    samples = [
        LargeTransactionSample(
            date=str(row.get("date") or ""),
            merchant=_optional_text(row.get("merchant_raw")),
            account=_optional_text(row.get("account")),
            category=_optional_text(row.get("category_final")),
            amount_krw=float(row.get("amount_krw") or 0.0),
        )
        for row in sample_rows
    ]
    status: SignalStatus = "present" if count > 0 else "clear"
    return (
        LargeTransactionSignal(
            status=status,
            threshold=threshold,
            count=count,
            samples=samples,
        ),
        None,
    )


def _optional_text(value: Any) -> str | None:
    """Normalize blank values into None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None
