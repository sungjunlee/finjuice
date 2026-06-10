"""Reusable one-shot automation signal collection for workflow automation."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

try:
    import duckdb
except ImportError:
    duckdb = None  # type: ignore[assignment]  # optional dependency sentinel

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.config import Config
from finjuice.pipeline.ingest.pipeline import preview_ingest_all_files
from finjuice.pipeline.tagging.suggestions import (
    generate_merchant_context,
    get_suggestion_coverage_stats,
)

logger = logging.getLogger(__name__)

SignalStatus = Literal["present", "clear", "unavailable"]


@dataclass(frozen=True)
class AutomationHint:
    """Existing commands a caller can surface as next-step guidance."""

    signal: str
    message: str
    command: str


@dataclass(frozen=True)
class PendingImportFile:
    """Preview summary for one actionable file in imports/."""

    source_file: str
    estimated_new_rows: int
    estimated_new_asset_rows: int
    validation_skips: int


@dataclass(frozen=True)
class PendingImportFailure:
    """File that could not be previewed cleanly."""

    source_file: str
    error: str


@dataclass(frozen=True)
class PendingImportsSignal:
    """Signal summarizing whether imports/ appears to need attention."""

    status: SignalStatus
    files_found: int
    pending_files: int
    estimated_new_rows: int
    estimated_new_asset_rows: int
    failed_files: list[PendingImportFailure]
    sample_files: list[PendingImportFile]


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


@dataclass(frozen=True)
class AutomationSummary:
    """Stable Python-level summary that later CLI surfaces can render."""

    data_dir: str
    actionable: bool
    pending_imports: PendingImportsSignal
    tagging_pressure: TaggingPressureSignal
    large_transactions: LargeTransactionSignal
    next_steps: list[AutomationHint]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the summary for JSON or text rendering."""
        return asdict(self)


def collect_automation_signals(
    config: Config,
    *,
    large_transaction_threshold: int,
    import_sample_limit: int = 3,
    merchant_sample_limit: int = 5,
    merchant_min_count: int = 2,
    large_transaction_sample_limit: int = 5,
) -> AutomationSummary:
    """Collect a one-shot automation summary from existing pipeline surfaces."""
    if large_transaction_threshold < 0:
        raise ValueError("large_transaction_threshold must be >= 0")

    pending_imports = _collect_pending_imports(
        config=config,
        sample_limit=import_sample_limit,
    )

    warnings: list[str] = []
    tagging_pressure, tagging_warning = _collect_tagging_pressure(
        config=config,
        sample_limit=merchant_sample_limit,
        min_count=merchant_min_count,
    )
    if tagging_warning:
        warnings.append(tagging_warning)

    if large_transaction_threshold == 0:
        large_transactions = LargeTransactionSignal(
            status="clear",
            threshold=0,
            count=0,
            samples=[],
        )
    else:
        large_transactions, anomaly_warning = _collect_large_transactions(
            config=config,
            threshold=large_transaction_threshold,
            sample_limit=large_transaction_sample_limit,
        )
        if anomaly_warning:
            warnings.append(anomaly_warning)

    actionable = any(
        signal.status == "present"
        for signal in (pending_imports, tagging_pressure, large_transactions)
    )

    return AutomationSummary(
        data_dir=str(config.data_dir),
        actionable=actionable,
        pending_imports=pending_imports,
        tagging_pressure=tagging_pressure,
        large_transactions=large_transactions,
        next_steps=_build_next_steps(
            pending_imports=pending_imports,
            tagging_pressure=tagging_pressure,
            large_transactions=large_transactions,
        ),
        warnings=list(dict.fromkeys(warnings)),
    )


def _collect_pending_imports(
    *,
    config: Config,
    sample_limit: int,
) -> PendingImportsSignal:
    """Use ingest preview to identify actionable files still sitting in imports/."""
    preview = preview_ingest_all_files(config.import_dir, config.csv_base_dir, archive=False)

    sample_files: list[PendingImportFile] = []
    pending_file_count = 0
    estimated_new_rows = 0
    estimated_new_asset_rows = 0

    for file_summary in preview.get("files", []):
        transactions = file_summary.get("transactions", {}) or {}
        asset_snapshots = file_summary.get("asset_snapshots", {}) or {}
        tx_rows = int(transactions.get("estimated_new_rows") or 0)
        asset_rows = int(asset_snapshots.get("estimated_new_rows") or 0)
        validation_skips = int(transactions.get("validation_skips") or 0)

        if tx_rows <= 0 and asset_rows <= 0 and validation_skips <= 0:
            continue

        pending_file_count += 1
        estimated_new_rows += tx_rows
        estimated_new_asset_rows += asset_rows

        if len(sample_files) < sample_limit:
            sample_files.append(
                PendingImportFile(
                    source_file=_basename(file_summary.get("source_file")),
                    estimated_new_rows=tx_rows,
                    estimated_new_asset_rows=asset_rows,
                    validation_skips=validation_skips,
                )
            )

    failures = [
        PendingImportFailure(source_file=source_file, error=error)
        for source_file, error in preview.get("failed_files", [])
    ]
    status: SignalStatus = "present" if pending_file_count > 0 or failures else "clear"

    return PendingImportsSignal(
        status=status,
        files_found=int(preview.get("files_found") or 0),
        pending_files=pending_file_count,
        estimated_new_rows=estimated_new_rows,
        estimated_new_asset_rows=estimated_new_asset_rows,
        failed_files=failures,
        sample_files=sample_files,
    )


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


def _build_next_steps(
    *,
    pending_imports: PendingImportsSignal,
    tagging_pressure: TaggingPressureSignal,
    large_transactions: LargeTransactionSignal,
) -> list[AutomationHint]:
    """Build CLI-oriented next-step hints without inventing new commands."""
    next_steps: list[AutomationHint] = []

    if pending_imports.status == "present":
        next_steps.append(
            AutomationHint(
                signal="pending_imports",
                message="New import files look ready for a one-shot pipeline pass.",
                command="finjuice refresh",
            )
        )

    if tagging_pressure.status == "present":
        next_steps.append(
            AutomationHint(
                signal="tagging_pressure",
                message=(
                    "Rule-suggestable untagged transactions are accumulating and need rule review."
                ),
                command="finjuice rules suggest",
            )
        )

    if large_transactions.status == "present":
        next_steps.append(
            AutomationHint(
                signal="large_transactions",
                message="Review large-expense anomalies with the existing template surface.",
                command=(
                    "finjuice template run anomaly_large_txn "
                    f"--param threshold={large_transactions.threshold}"
                ),
            )
        )

    return next_steps


def _basename(value: Any) -> str:
    """Return a CLI-friendly filename for a path-like value."""
    if value is None:
        return ""
    return Path(str(value)).name


def _optional_text(value: Any) -> str | None:
    """Normalize blank values into None."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


__all__ = [
    "AutomationHint",
    "AutomationSummary",
    "LargeTransactionSample",
    "LargeTransactionSignal",
    "MerchantPressureSample",
    "PendingImportFailure",
    "PendingImportFile",
    "PendingImportsSignal",
    "TaggingPressureSignal",
    "collect_automation_signals",
]
