"""Canonical automation rendering with explicit data and observation provenance."""

from __future__ import annotations

from typing import Any, cast

import typer

from finjuice.pipeline.automation_repository import (
    RepositoryAutomationOptions,
    collect_repository_automation,
)
from finjuice.pipeline.cli.commands.automation_helpers import _serialize_automation_run_payload
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error, info
from finjuice.pipeline.cli.privacy import PrivacyProfile, apply_privacy_profile, privacy_meta
from finjuice.pipeline.cli.utils import get_activation_evidence_provider, get_config


def try_repository_automation(
    ctx: typer.Context, *, json_output: bool, privacy: PrivacyProfile
) -> bool:
    """Render canonical automation; False means verified legacy authority only."""
    from finjuice.pipeline.cli.commands.automation import (
        _compact_automation_run_result,
        _render_automation_run,
    )

    config = get_config(ctx)
    thresholds = config.automation.thresholds
    try:
        result = collect_repository_automation(
            config,
            get_activation_evidence_provider(ctx),
            RepositoryAutomationOptions(thresholds.large_transaction),
        )
        if result is None:
            return False
        payload = cast(
            dict[str, Any],
            _serialize_automation_run_payload(
                result.summary,
                enabled=config.automation.enabled,
                untagged_threshold=thresholds.untagged_count,
                large_transaction_threshold=thresholds.large_transaction,
            ),
        )
        if not json_output:
            info(
                f"Repository revision {result.metadata['dataset_revision']} "
                f"({result.metadata['dataset_generation']}); thresholds: runtime config"
            )
        emit(
            apply_privacy_profile(payload, privacy, compact=_compact_automation_run_result)
            if json_output
            else payload,
            json_output,
            _render_automation_run,
            command="automation run",
            meta_extras={**result.metadata, **privacy_meta(privacy)},
        )
        return True
    except typer.Exit:
        raise
    except Exception:
        emit_error(
            "Canonical automation could not read complete validated evidence.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="automation run",
            privacy=privacy,
        )
        raise AssertionError("emit_error must exit") from None
