"""One-shot workflow automation CLI commands.

Typed JSON payload contracts and raw/compact serializers live in
:mod:`finjuice.pipeline.cli.commands.automation_helpers` and are
re-exported here so existing callers can keep importing from this module.
"""

from __future__ import annotations

import logging
from typing import Any, cast

import typer

from finjuice.pipeline.automation import collect_automation_signals
from finjuice.pipeline.cli.commands.automation_helpers import (  # noqa: F401
    AutomationNextStepPayload,
    AutomationRunPayload,
    AutomationThresholdsPayload,
    CompactAutomationRunPayload,
    CompactLargeTransactionsPayload,
    CompactPendingImportsPayload,
    CompactTaggingPressurePayload,
    LargeTransactionSamplePayload,
    LargeTransactionsPayload,
    MerchantPressurePayload,
    PendingImportFailurePayload,
    PendingImportFilePayload,
    PendingImportsPayload,
    TaggingPressurePayload,
    _compact_automation_run_payload,
    _serialize_automation_run_payload,
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
