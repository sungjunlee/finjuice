"""Read-only checkup composition from one repository revision and staged observations."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any

import polars as pl

from finjuice.pipeline.asset_config import AssetsConfigValidationResult
from finjuice.pipeline.checkup.budget import build_budget_posture
from finjuice.pipeline.checkup.freshness import PipelineFreshnessInputs, build_pipeline_freshness
from finjuice.pipeline.checkup.import_preview import (
    StagedImportSummary,
    capture_staged_imports,
    summarize_staged_imports,
)
from finjuice.pipeline.checkup.models import (
    FAST_SKIP_WARNING,
    CheckupBundle,
    NetWorthPostureSummary,
    ObligationConfirmationSummary,
    skipped_obligation_confirmation_summary,
    skipped_review_pressure_summary,
)
from finjuice.pipeline.checkup.networth import build_networth_posture
from finjuice.pipeline.checkup.next_actions import _build_next_actions
from finjuice.pipeline.checkup.obligations import build_obligation_confirmation
from finjuice.pipeline.checkup.repository_inputs import (
    RepositoryCheckupError,
    checkup_assets,
    checkup_goals,
    checkup_rules,
    scoped_transactions,
)
from finjuice.pipeline.checkup.review import build_review_pressure
from finjuice.pipeline.checkup.warnings import _collect_warnings
from finjuice.pipeline.config import Config
from finjuice.pipeline.goals import GoalsLoadResult
from finjuice.pipeline.insights import (
    RepositoryStatusSnapshotOptions,
    collect_repository_status_snapshot,
)
from finjuice.pipeline.networth import build_networth_position_from_selections
from finjuice.pipeline.portfolio_display import PortfolioDisplay
from finjuice.pipeline.portfolio_networth import _select_partition
from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    LegacyAuthority,
    resolve_storage_authority,
)
from finjuice.pipeline.storage.csv_transactions_read_normalize import _decode_tag_columns
from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite.checkup_reads import CheckupReadSnapshot


@dataclass(frozen=True)
class RepositoryCheckupOptions:
    config: Config
    today: date
    stale_after_days: int
    sample_limit: int
    fast: bool


def collect_repository_checkup(
    options: RepositoryCheckupOptions,
    *,
    evidence_provider: ActivationEvidenceProvider | None,
) -> CheckupBundle | None:
    """Observe staged bytes, then detach all canonical inputs through one reader."""
    config, fast = options.config, options.fast
    try:
        authority = resolve_storage_authority(config.data_dir, evidence_provider).authority
        if isinstance(authority, LegacyAuthority):
            return None
        staged = capture_staged_imports(config.import_dir, fast=fast)
        snapshot = read_checkup_snapshot(config.data_dir, evidence_provider, digests=staged.digests)
        if snapshot is None:
            raise RepositoryCheckupError("Repository authority changed during checkup.")
        preview = summarize_staged_imports(staged, snapshot.imports)
        return _collect(snapshot, options, preview)
    except RepositoryCheckupError:
        raise
    except Exception:
        raise RepositoryCheckupError(
            "Repository checkup could not read validated evidence."
        ) from None


def _collect(
    snapshot: CheckupReadSnapshot, options: RepositoryCheckupOptions, preview: StagedImportSummary
) -> CheckupBundle:
    if snapshot.unmaterialized_months:
        raise RepositoryCheckupError("Canonical transaction evidence is incomplete for checkup.")
    config, today, fast = options.config, options.today, options.fast
    filters, notes = checkup_rules(snapshot.rules)
    goals = checkup_goals(snapshot.portfolio.goals)
    assets = checkup_assets(snapshot.portfolio.assets)
    display = PortfolioDisplay(snapshot.portfolio)
    transactions = snapshot.status.transactions
    frame = scoped_transactions(transactions)
    month = transactions.partition_months[-1] if transactions.partition_months else None
    current = scoped_transactions(transactions, month) if month is not None else frame.head(0)
    # Freshness exposes transaction income/expense/savings only. Goal-dependent
    # structural savings are not part of this domain; validate goals below.
    insights = collect_repository_status_snapshot(
        _decode_tag_columns(frame),
        RepositoryStatusSnapshotOptions(
            goals_content=None,
            goals_parsed_status=None,
            report_filters=filters,
            active_filter_count=filters.total_rules,
        ),
    )
    pipeline = build_pipeline_freshness(
        insights,
        PipelineFreshnessInputs(
            partition_count=len(transactions.partition_months),
            pending_import_files=preview.pending_files,
            failed_import_files=preview.failed_files,
            today=today,
            stale_after_days=options.stale_after_days,
            has_transactions=not frame.is_empty(),
        ),
    )
    if preview.warning:
        pipeline = replace(
            pipeline, warning=" ".join(filter(None, (pipeline.warning, preview.warning)))
        )
    review = (
        skipped_review_pressure_summary()
        if fast
        else build_review_pressure(
            current, month=month, sample_limit=options.sample_limit, rule_notes=notes
        )
    )
    budget = build_budget_posture(
        goals, current, month=month or today.strftime("%Y-%m"), report_filters=filters
    )
    networth = _networth(display, assets, goals)
    obligations = _obligations(frame, goals, fast=fast)
    warnings = _collect_warnings(
        pipeline.warning,
        budget.warning,
        networth.warning,
        obligations.warning,
        FAST_SKIP_WARNING if fast else None,
    )
    next_actions = _build_next_actions(
        pipeline=pipeline, review=review, budget=budget, networth=networth, obligations=obligations
    )
    return CheckupBundle(
        data_dir=str(config.data_dir),
        actionable=any(x.actionable for x in (pipeline, review, budget, networth, obligations)),
        warnings=warnings,
        next_actions=next_actions,
        pipeline=pipeline,
        review=review,
        budget=budget,
        networth=networth,
        obligations=obligations,
        repository=_metadata(snapshot, today, preview),
    )


def _metadata(
    snapshot: CheckupReadSnapshot, today: date, preview: StagedImportSummary
) -> dict[str, Any]:
    return {
        "authority": "repository",
        "dataset_generation": snapshot.info.dataset_generation,
        "dataset_revision": snapshot.info.dataset_revision,
        "sqlite_schema_version": snapshot.info.schema_version,
        "calculation_policy": "legacy_checkup.v1",
        "calculation_as_of": today.isoformat(),
        "rules_selection_state": snapshot.rules.selection_state,
        "goals_selection_state": snapshot.portfolio.goals.selection_state,
        "assets_selection_state": snapshot.portfolio.assets.selection_state,
        "unknown_month_rows": sum(
            s.included and s.month is None for s in snapshot.status.transactions.scopes
        ),
        "staged_observation": preview.metadata,
    }


def _networth(
    display: PortfolioDisplay, assets: AssetsConfigValidationResult, goals: GoalsLoadResult
) -> NetWorthPostureSummary:
    selection = _select_partition(display.snapshot_months, display.snapshot_partition, None)
    position = (
        build_networth_position_from_selections(selection, assets.config)
        if assets.is_valid
        else None
    )
    target = goals.document.net_worth_target if goals.document else None
    result = build_networth_posture(display.snapshot_months, assets, position, target)
    if goals.exists and goals.document is None:
        warning = "Canonical goals are invalid or unselected; the net worth target is unknown."
        return replace(
            result,
            status="target_unknown" if assets.is_valid else result.status,
            actionable=True,
            warning=" ".join(filter(None, (result.warning, warning))),
        )
    return result


def _obligations(
    frame: pl.DataFrame, goals: GoalsLoadResult, *, fast: bool
) -> ObligationConfirmationSummary:
    if fast:
        return skipped_obligation_confirmation_summary()
    if goals.exists and goals.document is None:
        result = build_obligation_confirmation(frame.head(0), goals)
        return replace(
            result,
            status="unavailable",
            actionable=True,
            warning=(
                "Canonical goals are invalid or unselected; obligation confirmation is unavailable."
            ),
        )
    return build_obligation_confirmation(frame, goals)
