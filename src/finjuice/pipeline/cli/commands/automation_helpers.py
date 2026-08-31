"""JSON payload projection for ``finjuice automation run``.

Owns typed payload contracts, raw/compact serializers, and next-step
filtering. The Typer command, config-backed build, and human rendering
stay in :mod:`finjuice.pipeline.cli.commands.automation`.
"""

from __future__ import annotations

from typing import TypedDict

from finjuice.pipeline.automation import AutomationHint, AutomationSummary


class AutomationThresholdsPayload(TypedDict):
    """Stable threshold block in `automation run --json` output."""

    untagged_count: int
    large_transaction: int


class AutomationNextStepPayload(TypedDict):
    """Stable next-step hint emitted by agent-facing JSON commands."""

    signal: str
    message: str
    command: str


class PendingImportFailurePayload(TypedDict):
    """Stable pending-import failure sample."""

    source_file: str
    error: str


class PendingImportFilePayload(TypedDict):
    """Stable pending-import sample."""

    source_file: str
    estimated_new_rows: int
    estimated_new_asset_rows: int
    validation_skips: int


class PendingImportsPayload(TypedDict):
    """Stable pending-imports block for raw automation JSON."""

    status: str
    files_found: int
    pending_files: int
    estimated_new_rows: int
    estimated_new_asset_rows: int
    failed_files: list[PendingImportFailurePayload]
    sample_files: list[PendingImportFilePayload]


class CompactPendingImportsPayload(TypedDict):
    """Compact pending-imports block without filenames or samples."""

    status: str
    files_found: int
    pending_files: int
    estimated_new_rows: int
    estimated_new_asset_rows: int
    failed_file_count: int
    sample_file_count: int


class MerchantPressurePayload(TypedDict):
    """Stable merchant-pressure sample for raw automation JSON."""

    merchant: str
    transaction_count: int
    total_amount: float
    avg_amount: float
    sample_memos: list[str]


class TaggingPressurePayload(TypedDict):
    """Stable tagging-pressure block for raw automation JSON."""

    status: str
    total_transactions: int
    untagged_transactions: int
    coverage_pct: float
    suggestable_untagged_transactions: int
    suggestable_coverage_pct: float
    transfer_excluded_untagged_transactions: int
    merchant_pressure: list[MerchantPressurePayload]
    threshold: int
    threshold_basis: str
    threshold_exceeded: bool


class CompactTaggingPressurePayload(TypedDict):
    """Compact tagging-pressure block without merchant samples."""

    status: str
    total_transactions: int
    untagged_transactions: int
    coverage_pct: float
    suggestable_untagged_transactions: int
    suggestable_coverage_pct: float
    transfer_excluded_untagged_transactions: int
    threshold: int
    threshold_basis: str
    threshold_exceeded: bool
    merchant_pressure_count: int


class LargeTransactionSamplePayload(TypedDict):
    """Stable large-transaction sample for raw automation JSON."""

    date: str
    merchant: str | None
    account: str | None
    category: str | None
    amount_krw: float


class LargeTransactionsPayload(TypedDict):
    """Stable large-transactions block for raw automation JSON."""

    status: str
    threshold: int
    count: int
    samples: list[LargeTransactionSamplePayload]


class CompactLargeTransactionsPayload(TypedDict):
    """Compact large-transactions block without samples."""

    status: str
    threshold: int
    count: int
    sample_count: int


class AutomationRunPayload(TypedDict):
    """Internal contract for raw `automation run --json` payload before `_meta`."""

    enabled: bool
    data_dir: str
    actionable: bool
    thresholds: AutomationThresholdsPayload
    pending_imports: PendingImportsPayload
    tagging_pressure: TaggingPressurePayload
    large_transactions: LargeTransactionsPayload
    next_steps: list[AutomationNextStepPayload]
    warnings: list[str]


class CompactAutomationRunPayload(TypedDict):
    """Internal contract for compact `automation run --json` payload before `_meta`."""

    enabled: bool
    actionable: bool
    thresholds: AutomationThresholdsPayload
    pending_imports: CompactPendingImportsPayload
    tagging_pressure: CompactTaggingPressurePayload
    large_transactions: CompactLargeTransactionsPayload
    next_steps: list[AutomationNextStepPayload]
    warnings: list[str]


def _serialize_automation_run_payload(
    summary: AutomationSummary,
    *,
    enabled: bool,
    untagged_threshold: int,
    large_transaction_threshold: int,
) -> AutomationRunPayload:
    """Project collected automation signals into the stable CLI JSON contract."""
    pending_imports = summary.pending_imports
    tagging_pressure = summary.tagging_pressure
    large_transactions = summary.large_transactions
    tagging_threshold_enabled = untagged_threshold > 0
    suggestable_untagged = tagging_pressure.suggestable_untagged_transactions

    threshold_exceeded = tagging_threshold_enabled and (suggestable_untagged >= untagged_threshold)

    next_steps = _serialize_automation_next_steps(
        summary.next_steps,
        include_tagging_pressure=threshold_exceeded,
    )

    warnings = list(summary.warnings)
    if not enabled:
        warnings.insert(0, "Automation is disabled in config; showing a preview-only summary.")
    if not tagging_threshold_enabled:
        warnings.append(
            "Tagging-pressure automation is disabled because "
            "automation.thresholds.untagged_count is 0."
        )
    if large_transaction_threshold == 0:
        warnings.append(
            "Large-transaction automation is disabled because "
            "automation.thresholds.large_transaction is 0."
        )

    actionable = (
        pending_imports.status == "present"
        or threshold_exceeded
        or large_transactions.status == "present"
    )

    return {
        "enabled": enabled,
        "data_dir": summary.data_dir,
        "actionable": actionable,
        "thresholds": {
            "untagged_count": untagged_threshold,
            "large_transaction": large_transaction_threshold,
        },
        "pending_imports": {
            "status": pending_imports.status,
            "files_found": pending_imports.files_found,
            "pending_files": pending_imports.pending_files,
            "estimated_new_rows": pending_imports.estimated_new_rows,
            "estimated_new_asset_rows": pending_imports.estimated_new_asset_rows,
            "failed_files": [
                {"source_file": failure.source_file, "error": failure.error}
                for failure in pending_imports.failed_files
            ],
            "sample_files": [
                {
                    "source_file": sample.source_file,
                    "estimated_new_rows": sample.estimated_new_rows,
                    "estimated_new_asset_rows": sample.estimated_new_asset_rows,
                    "validation_skips": sample.validation_skips,
                }
                for sample in pending_imports.sample_files
            ],
        },
        "tagging_pressure": {
            "status": tagging_pressure.status,
            "total_transactions": tagging_pressure.total_transactions,
            "untagged_transactions": tagging_pressure.untagged_transactions,
            "coverage_pct": tagging_pressure.coverage_pct,
            "suggestable_untagged_transactions": suggestable_untagged,
            "suggestable_coverage_pct": tagging_pressure.suggestable_coverage_pct,
            "transfer_excluded_untagged_transactions": (
                tagging_pressure.transfer_excluded_untagged_transactions
            ),
            "merchant_pressure": [
                {
                    "merchant": sample.merchant,
                    "transaction_count": sample.transaction_count,
                    "total_amount": sample.total_amount,
                    "avg_amount": sample.avg_amount,
                    "sample_memos": sample.sample_memos,
                }
                for sample in tagging_pressure.merchant_pressure
            ],
            "threshold": untagged_threshold,
            "threshold_basis": "suggestable_untagged_transactions",
            "threshold_exceeded": threshold_exceeded,
        },
        "large_transactions": {
            "status": large_transactions.status,
            "threshold": large_transactions.threshold,
            "count": large_transactions.count,
            "samples": [
                {
                    "date": sample.date,
                    "merchant": sample.merchant,
                    "account": sample.account,
                    "category": sample.category,
                    "amount_krw": sample.amount_krw,
                }
                for sample in large_transactions.samples
            ],
        },
        "next_steps": next_steps,
        "warnings": warnings,
    }


def _serialize_automation_next_steps(
    next_steps: list[AutomationHint],
    *,
    include_tagging_pressure: bool,
) -> list[AutomationNextStepPayload]:
    """Return JSON next-step hints after threshold-aware filtering."""
    return [
        {
            "signal": hint.signal,
            "message": hint.message,
            "command": hint.command,
        }
        for hint in next_steps
        if hint.signal != "tagging_pressure" or include_tagging_pressure
    ]


def _compact_automation_run_payload(
    result: AutomationRunPayload,
) -> CompactAutomationRunPayload:
    """Return typed compact automation JSON with counts and workflow cues."""
    pending_imports = result["pending_imports"]
    tagging_pressure = result["tagging_pressure"]
    large_transactions = result["large_transactions"]

    return {
        "enabled": result["enabled"],
        "actionable": result["actionable"],
        "thresholds": result["thresholds"],
        "pending_imports": {
            "status": pending_imports["status"],
            "files_found": pending_imports["files_found"],
            "pending_files": pending_imports["pending_files"],
            "estimated_new_rows": pending_imports["estimated_new_rows"],
            "estimated_new_asset_rows": pending_imports["estimated_new_asset_rows"],
            "failed_file_count": len(pending_imports["failed_files"]),
            "sample_file_count": len(pending_imports["sample_files"]),
        },
        "tagging_pressure": {
            "status": tagging_pressure["status"],
            "total_transactions": tagging_pressure["total_transactions"],
            "untagged_transactions": tagging_pressure["untagged_transactions"],
            "coverage_pct": tagging_pressure["coverage_pct"],
            "suggestable_untagged_transactions": tagging_pressure[
                "suggestable_untagged_transactions"
            ],
            "suggestable_coverage_pct": tagging_pressure["suggestable_coverage_pct"],
            "transfer_excluded_untagged_transactions": tagging_pressure[
                "transfer_excluded_untagged_transactions"
            ],
            "threshold": tagging_pressure["threshold"],
            "threshold_basis": tagging_pressure["threshold_basis"],
            "threshold_exceeded": tagging_pressure["threshold_exceeded"],
            "merchant_pressure_count": len(tagging_pressure["merchant_pressure"]),
        },
        "large_transactions": {
            "status": large_transactions["status"],
            "threshold": large_transactions["threshold"],
            "count": large_transactions["count"],
            "sample_count": len(large_transactions["samples"]),
        },
        "next_steps": result["next_steps"],
        "warnings": result["warnings"],
    }
