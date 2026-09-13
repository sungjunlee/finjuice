"""Compose one-shot automation from pinned data and separately captured files."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from finjuice.pipeline.analysis_source import analysis_frame, analysis_metadata
from finjuice.pipeline.analytics.transaction_frame_registration import register_transaction_frame
from finjuice.pipeline.automation import AutomationSummary
from finjuice.pipeline.automation_helpers import _build_next_steps
from finjuice.pipeline.automation_large_transactions import (
    LargeTransactionSignal,
    large_transactions_from_connection,
)
from finjuice.pipeline.automation_repository_pending import pending_from_evaluation
from finjuice.pipeline.automation_tagging_pressure import tagging_pressure_from_suggestions
from finjuice.pipeline.checkup.import_preview import (
    StagedImportObservation,
    capture_staged_imports,
    evaluate_staged_imports,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    LegacyAuthority,
    resolve_storage_authority,
)
from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite.analysis_reads import AnalysisReadSnapshot
from finjuice.pipeline.storage.sqlite.checkup_reads import CheckupReadSnapshot
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.suggestion_repository import (
    SuggestionReadOptions,
    require_finite_values,
    selected_suggestion_rules,
    suggestions_from_frame,
)


class RepositoryAutomationError(ValueError):
    """Static canonical failure, never converted to a successful empty summary."""


@dataclass(frozen=True)
class RepositoryAutomationOptions:
    large_transaction_threshold: int
    import_sample_limit: int = 3
    merchant_sample_limit: int = 5
    merchant_min_count: int = 2
    large_transaction_sample_limit: int = 5


@dataclass(frozen=True)
class RepositoryAutomationResult:
    summary: AutomationSummary
    metadata: dict[str, Any]


def collect_repository_automation(
    config: Config,
    provider: ActivationEvidenceProvider | None,
    options: RepositoryAutomationOptions,
) -> RepositoryAutomationResult | None:
    """Capture each staged workbook once and read one canonical revision."""
    try:
        authority = resolve_storage_authority(config.data_dir, provider).authority
        if isinstance(authority, LegacyAuthority):
            return None
        if options.large_transaction_threshold < 0:
            raise ValueError("Large-transaction threshold must be nonnegative.")
        staged = capture_staged_imports(config.import_dir)
        snapshot = read_checkup_snapshot(config.data_dir, provider, digests=staged.digests)
        if snapshot is None:
            raise ValueError("Repository authority changed during automation.")
        return automation_from_snapshot(config, snapshot, staged, options)
    except Exception:
        raise RepositoryAutomationError(
            "Canonical automation could not read complete validated evidence."
        ) from None


def automation_from_snapshot(
    config: Config,
    snapshot: CheckupReadSnapshot,
    staged: StagedImportObservation,
    options: RepositoryAutomationOptions,
) -> RepositoryAutomationResult:
    """Calculate from detached inputs; no live file or repository reads."""
    analysis = AnalysisReadSnapshot(
        snapshot.info,
        snapshot.status.transactions,
        snapshot.rules,
        snapshot.portfolio.goals,
        snapshot.unmaterialized_months,
    )
    rules = selected_suggestion_rules(snapshot.rules)
    frame = analysis_frame(analysis, decode_tags=False)
    require_finite_values(frame["amount"].to_list())
    stats, suggestions = suggestions_from_frame(
        frame,
        rules,
        SuggestionReadOptions(options.merchant_sample_limit, options.merchant_min_count),
    )
    tagging = tagging_pressure_from_suggestions(stats, suggestions)
    large = _large_transactions(frame, options)
    evaluation = evaluate_staged_imports(staged, snapshot.imports)
    pending, dispositions = pending_from_evaluation(evaluation, options.import_sample_limit)
    warnings = [evaluation.summary.warning] if evaluation.summary.warning else []
    warnings.append(
        "Staged row estimates sum independent previews against one revision; "
        "they are not sequential batch totals. Canonical validation_skips is unavailable."
    )
    summary = AutomationSummary(
        data_dir=str(config.data_dir),
        actionable=any(signal.status == "present" for signal in (pending, tagging, large)),
        pending_imports=pending,
        tagging_pressure=tagging,
        large_transactions=large,
        next_steps=_build_next_steps(
            pending_imports=pending, tagging_pressure=tagging, large_transactions=large
        ),
        warnings=warnings,
    )
    return RepositoryAutomationResult(
        summary,
        {
            **analysis_metadata(analysis, "legacy_automation_signals.v1"),
            "rules_revision_id": snapshot.rules.head.revision_id if snapshot.rules.head else None,
            "threshold_source": "runtime_config",
            "staged_observation": evaluation.summary.metadata,
            "staged_import_dispositions": dispositions,
        },
    )


def _large_transactions(
    frame: pl.DataFrame, options: RepositoryAutomationOptions
) -> LargeTransactionSignal:
    if options.large_transaction_threshold == 0:
        return LargeTransactionSignal("clear", 0, 0, [])
    import duckdb

    with duckdb.connect(":memory:") as connection:
        register_transaction_frame(connection, frame, ReportFilters())
        return large_transactions_from_connection(
            connection, options.large_transaction_threshold, options.large_transaction_sample_limit
        )
