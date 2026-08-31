"""Pipeline freshness collector for the checkup bundle."""

from __future__ import annotations

from datetime import date

from finjuice.pipeline.checkup.models import PipelineFreshnessSummary
from finjuice.pipeline.config import Config
from finjuice.pipeline.ingest.pipeline import preview_ingest_all_files
from finjuice.pipeline.insights import collect_status_snapshot


def collect_pipeline_freshness(
    config: Config,
    *,
    today: date,
    stale_after_days: int,
    preview_imports: bool = True,
) -> PipelineFreshnessSummary:
    """Summarize transaction freshness from the shared status snapshot surface."""
    snapshot_result = collect_status_snapshot(config)
    snapshot = snapshot_result.snapshot
    partition_count = len(list(config.csv_base_dir.glob("*/*/transactions.csv")))
    pending_import_files, failed_import_files = _collect_import_preview_counts(
        config,
        preview_imports=preview_imports,
    )
    pending_import_status = "present" if pending_import_files > 0 else "clear"
    latest_date = _extract_latest_date(snapshot.data_range)
    days_since_latest = (today - latest_date).days if latest_date is not None else None

    if failed_import_files > 0:
        warning = f"{failed_import_files} staged import file(s) failed preview validation."
        if pending_import_files > 0:
            warning = (
                f"{warning} {pending_import_files} additional staged import file(s) are ready "
                "for refresh."
            )

        return PipelineFreshnessSummary(
            status="import_failures",
            actionable=True,
            pending_import_status=pending_import_status,
            pending_import_files=pending_import_files,
            failed_import_files=failed_import_files,
            transaction_partitions=partition_count,
            data_range=snapshot.data_range,
            latest_transaction_date=latest_date.isoformat() if latest_date is not None else None,
            days_since_latest=days_since_latest,
            monthly_avg_income=snapshot.monthly_avg_income,
            monthly_avg_expense=snapshot.monthly_avg_expense,
            savings_rate_3mo=snapshot.savings_rate_3mo,
            active_filters=snapshot.active_filters,
            warning=warning,
        )

    if pending_import_files > 0:
        return PipelineFreshnessSummary(
            status="pending_imports",
            actionable=True,
            pending_import_status=pending_import_status,
            pending_import_files=pending_import_files,
            failed_import_files=failed_import_files,
            transaction_partitions=partition_count,
            data_range=snapshot.data_range,
            latest_transaction_date=latest_date.isoformat() if latest_date is not None else None,
            days_since_latest=days_since_latest,
            monthly_avg_income=snapshot.monthly_avg_income,
            monthly_avg_expense=snapshot.monthly_avg_expense,
            savings_rate_3mo=snapshot.savings_rate_3mo,
            active_filters=snapshot.active_filters,
            warning=f"{pending_import_files} staged import file(s) are waiting in imports/.",
        )

    if partition_count == 0:
        return PipelineFreshnessSummary(
            status="empty",
            actionable=True,
            pending_import_status=pending_import_status,
            pending_import_files=pending_import_files,
            failed_import_files=failed_import_files,
            transaction_partitions=0,
            data_range=None,
            latest_transaction_date=None,
            days_since_latest=None,
            monthly_avg_income=None,
            monthly_avg_expense=None,
            savings_rate_3mo=None,
            active_filters=snapshot.active_filters,
            warning=(
                "No transaction partitions found. Import data before running the pipeline loop."
            ),
        )

    if latest_date is None:
        return PipelineFreshnessSummary(
            status="unknown",
            actionable=True,
            pending_import_status=pending_import_status,
            pending_import_files=pending_import_files,
            failed_import_files=failed_import_files,
            transaction_partitions=partition_count,
            data_range=snapshot.data_range,
            latest_transaction_date=None,
            days_since_latest=None,
            monthly_avg_income=snapshot.monthly_avg_income,
            monthly_avg_expense=snapshot.monthly_avg_expense,
            savings_rate_3mo=snapshot.savings_rate_3mo,
            active_filters=snapshot.active_filters,
            warning=snapshot_result.warning or "Could not resolve the latest transaction date.",
        )

    status = "healthy"
    actionable = False
    if days_since_latest is not None and days_since_latest > stale_after_days:
        status = "stale"
        actionable = True
    elif snapshot_result.warning is not None:
        status = "degraded"
        actionable = True

    return PipelineFreshnessSummary(
        status=status,
        actionable=actionable,
        pending_import_status=pending_import_status,
        pending_import_files=pending_import_files,
        failed_import_files=failed_import_files,
        transaction_partitions=partition_count,
        data_range=snapshot.data_range,
        latest_transaction_date=latest_date.isoformat(),
        days_since_latest=days_since_latest,
        monthly_avg_income=snapshot.monthly_avg_income,
        monthly_avg_expense=snapshot.monthly_avg_expense,
        savings_rate_3mo=snapshot.savings_rate_3mo,
        active_filters=snapshot.active_filters,
        warning=snapshot_result.warning,
    )


def _extract_latest_date(data_range: str | None) -> date | None:
    """Parse the max date from the status snapshot data-range label."""
    if not data_range:
        return None
    _, _, latest = data_range.partition(" ~ ")
    raw_date = latest or data_range
    try:
        return date.fromisoformat(raw_date.strip())
    except ValueError:
        return None


def _collect_import_preview_counts(
    config: Config,
    *,
    preview_imports: bool = True,
) -> tuple[int, int]:
    """Count staged imports that are actionable vs preview failures.

    When ``preview_imports`` is false, count staged ``*.xlsx`` files without
    opening them. Failures are not distinguished on that cheap path.
    """
    if not preview_imports:
        if not config.import_dir.is_dir():
            return 0, 0
        return len(list(config.import_dir.glob("*.xlsx"))), 0

    preview = preview_ingest_all_files(config.import_dir, config.csv_base_dir, archive=False)
    pending_files = 0

    for file_summary in preview.get("files", []):
        transactions = file_summary.get("transactions", {}) or {}
        asset_snapshots = file_summary.get("asset_snapshots", {}) or {}
        tx_rows = int(transactions.get("estimated_new_rows") or 0)
        asset_rows = int(asset_snapshots.get("estimated_new_rows") or 0)
        validation_skips = int(transactions.get("validation_skips") or 0)
        if tx_rows > 0 or asset_rows > 0 or validation_skips > 0:
            pending_files += 1

    return pending_files, len(preview.get("failed_files", []))
