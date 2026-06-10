"""One-shot workflow automation CLI commands."""

from __future__ import annotations

import logging
from typing import Any, TypedDict, cast

import typer

from finjuice.pipeline.automation import (
    AutomationHint,
    AutomationSummary,
    collect_automation_signals,
)
from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    bullet_list,
    emit,
    emit_error,
    section,
    success,
    table_summary,
    warning,
)
from finjuice.pipeline.cli.privacy import (
    PrivacyProfile,
    apply_privacy_profile,
    privacy_meta,
)
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)

automation_app = typer.Typer(
    name="automation",
    help="Run one-shot workflow automation checks for external schedulers.",
    no_args_is_help=True,
)


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


def _format_krw(amount: float) -> str:
    """Format a numeric threshold or amount as Korean won."""
    return f"₩{abs(amount):,.0f}"


def _build_automation_run_payload(ctx: typer.Context) -> AutomationRunPayload:
    """Build a threshold-aware, CLI-friendly automation summary."""
    config = get_config(ctx)
    thresholds = config.automation.thresholds

    summary = collect_automation_signals(
        config,
        large_transaction_threshold=thresholds.large_transaction,
    )

    return _serialize_automation_run_payload(
        summary,
        enabled=config.automation.enabled,
        untagged_threshold=thresholds.untagged_count,
        large_transaction_threshold=thresholds.large_transaction,
    )


def _build_automation_run_result(ctx: typer.Context) -> dict[str, Any]:
    """Build the legacy dict payload shape expected by emit/apply_privacy_profile."""
    return cast(dict[str, Any], _build_automation_run_payload(ctx))


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


def _compact_automation_run_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return the legacy dict payload shape expected by apply_privacy_profile."""
    return cast(
        dict[str, Any],
        _compact_automation_run_payload(cast(AutomationRunPayload, result)),
    )


def _render_automation_run(result: dict[str, Any]) -> None:
    """Render the automation summary in concise human-oriented text."""
    pending_imports = result["pending_imports"]
    tagging_pressure = result["tagging_pressure"]
    large_transactions = result["large_transactions"]

    section("Automation Run")
    untagged_summary = (
        f"{tagging_pressure['untagged_transactions']} total untagged; "
        f"{tagging_pressure['suggestable_untagged_transactions']} rule-suggestable"
    )
    if tagging_pressure["transfer_excluded_untagged_transactions"] > 0:
        untagged_summary += (
            f" ({tagging_pressure['transfer_excluded_untagged_transactions']} transfer-excluded)"
        )

    table_summary(
        "One-Shot Summary",
        [
            ("Automation Enabled", "yes" if result["enabled"] else "no"),
            ("Actionable Signals", "yes" if result["actionable"] else "no"),
            (
                "Pending Imports",
                (
                    f"{pending_imports['pending_files']} file(s), "
                    f"{pending_imports['estimated_new_rows']} row(s)"
                    if pending_imports["status"] == "present"
                    else "clear"
                ),
            ),
            (
                "Tagging Pressure",
                (
                    f"{untagged_summary} (disabled; threshold 0)"
                    if tagging_pressure["threshold"] == 0
                    else f"{untagged_summary} (threshold {tagging_pressure['threshold']})"
                ),
            ),
            (
                "Large Transactions",
                (
                    "disabled (threshold 0)"
                    if large_transactions["threshold"] == 0
                    else (
                        f"{large_transactions['count']} >= "
                        f"{_format_krw(large_transactions['threshold'])}"
                        if large_transactions["status"] == "present"
                        else f"clear (< {_format_krw(large_transactions['threshold'])})"
                    )
                ),
            ),
        ],
    )

    for message in result["warnings"]:
        warning(message)

    details: list[str] = []
    if pending_imports["sample_files"]:
        sample = pending_imports["sample_files"][0]
        details.append(
            "Pending import sample: "
            f"{sample['source_file']} (+{sample['estimated_new_rows']} tx rows, "
            f"+{sample['estimated_new_asset_rows']} asset rows)"
        )
    if tagging_pressure["merchant_pressure"]:
        merchant = tagging_pressure["merchant_pressure"][0]
        details.append(
            "Top suggestable untagged merchant: "
            f"{merchant['merchant']} ({merchant['transaction_count']} txn)"
        )
    if large_transactions["samples"]:
        sample = large_transactions["samples"][0]
        merchant = sample["merchant"] or "Unknown merchant"
        details.append(
            f"Large transaction sample: {sample['date']} {merchant} "
            f"{_format_krw(sample['amount_krw'])}"
        )

    if details:
        bullet_list(details, style="cyan")

    if result["next_steps"]:
        bullet_list(
            [f"{step['message']} -> {step['command']}" for step in result["next_steps"]],
            style="green",
        )

    success(
        "One-shot automation pass found actionable signals."
        if result["actionable"]
        else "One-shot automation pass found no actionable signals."
    )


@automation_app.command("run")
def automation_run_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    privacy: PrivacyProfile = typer.Option(
        PrivacyProfile.RAW,
        "--privacy",
        help="Privacy profile for JSON output: raw, redacted, or compact",
    ),
) -> None:
    """Run one one-shot automation pass using config-backed thresholds."""
    try:
        result = _build_automation_run_result(ctx)
        output_result = (
            apply_privacy_profile(result, privacy, compact=_compact_automation_run_result)
            if json_output
            else result
        )
        emit(
            output_result,
            json_output,
            _render_automation_run,
            command="automation run",
            meta_extras=privacy_meta(privacy),
        )
    except ValueError as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="automation run",
            privacy=privacy,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # intended catch-all for CLI robustness
        logger.error("Failed to run automation summary: %s", exc, exc_info=True)
        emit_error(
            f"Failed to run automation summary: {exc}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command="automation run",
            privacy=privacy,
        )
