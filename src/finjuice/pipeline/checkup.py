"""Unified read-only checkup bundle for AI-oriented runtime orchestration."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Literal

import polars as pl
import yaml

from finjuice.pipeline.config import Config
from finjuice.pipeline.filters import exclude_transfers_for
from finjuice.pipeline.goals import MonthlyBudget, known_obligation_labels, load_goals_file
from finjuice.pipeline.ingest.pipeline import preview_ingest_all_files
from finjuice.pipeline.insights import collect_status_snapshot
from finjuice.pipeline.networth import (
    build_networth_position,
    discover_snapshot_months,
    validate_assets_config_file,
)
from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.storage.csv_schema import POLARS_SCHEMA, get_partition_path
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters, summarize_rule_notes

ActionPriority = Literal["high", "medium", "low"]

_PRIORITY_ORDER: dict[ActionPriority, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
}
DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD = 300_000
_RECURRING_OBLIGATION_MIN_MONTHS = 6
_RECURRING_OBLIGATION_MAX_RELATIVE_RANGE = 0.4
_SENSITIVE_DIGIT_PATTERN = re.compile(r"\d[\d\s-]{3,}\d")


@dataclass(frozen=True)
class NextAction:
    """One explicit follow-up command suitable for future CLI rendering."""

    domain: str
    priority: ActionPriority
    reason: str
    command: str


@dataclass(frozen=True)
class ReviewSample:
    """Compact review candidate sample."""

    date: str | None
    merchant: str | None
    amount: float | None
    reasons: list[str]


@dataclass(frozen=True)
class BudgetSummary:
    """Budget summary row reused in the checkup bundle."""

    target: int
    actual: int
    remaining: int
    progress_pct: float | None
    status: str


@dataclass(frozen=True)
class RecurringOutflowCandidate:
    """One large recurring outflow that may need user confirmation."""

    label: str
    cadence: str
    amount_range: dict[str, int]
    average_monthly_amount: int
    active_months: list[str]
    active_month_count: int
    transaction_count: int
    suggested_confirmation_question: str


@dataclass(frozen=True)
class PipelineFreshnessSummary:
    """Pipeline freshness summary derived from existing status insights."""

    status: str
    actionable: bool
    pending_import_status: str
    pending_import_files: int
    failed_import_files: int
    transaction_partitions: int
    data_range: str | None
    latest_transaction_date: str | None
    days_since_latest: int | None
    monthly_avg_income: int | None
    monthly_avg_expense: int | None
    savings_rate_3mo: float | None
    active_filters: int
    warning: str | None = None


@dataclass(frozen=True)
class ReviewPressureSummary:
    """Manual-review pressure summary for the latest transaction month."""

    status: str
    actionable: bool
    month: str | None
    total_candidates: int
    needs_review_count: int
    untagged_count: int
    unclassified_count: int
    low_confidence_count: int
    samples: list[ReviewSample] = field(default_factory=list)
    rule_notes: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class BudgetPostureSummary:
    """Budget posture for the effective month."""

    status: str
    actionable: bool
    month: str
    goals_file_exists: bool
    filters_applied: int
    summary: BudgetSummary | None
    over_budget_categories: list[str] = field(default_factory=list)
    unbudgeted_categories: list[str] = field(default_factory=list)
    warning: str | None = None


@dataclass(frozen=True)
class NetWorthPostureSummary:
    """Net worth posture from snapshots, assets.yaml, and optional goal target."""

    status: str
    actionable: bool
    as_of: str | None
    snapshot_months: int
    assets_file_exists: bool
    asset_count: int
    liability_count: int
    total_assets: float
    total_liabilities: float
    net_worth: float
    target: int | None
    gap_to_target: float | None
    warning: str | None = None


@dataclass(frozen=True)
class ObligationConfirmationSummary:
    """Large recurring outflow candidates for user confirmation."""

    status: str
    actionable: bool
    threshold_monthly_krw: int
    candidate_count: int
    known_obligation_count: int
    candidates: list[RecurringOutflowCandidate] = field(default_factory=list)
    warning: str | None = None


def _empty_obligation_confirmation_summary() -> ObligationConfirmationSummary:
    """Return the default quiet obligation confirmation summary."""
    return ObligationConfirmationSummary(
        status="empty",
        actionable=False,
        threshold_monthly_krw=DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD,
        candidate_count=0,
        known_obligation_count=0,
        candidates=[],
    )


@dataclass(frozen=True)
class CheckupBundle:
    """Stable Python-level bundle for a future `finjuice checkup` surface."""

    data_dir: str
    actionable: bool
    warnings: list[str]
    next_actions: list[NextAction]
    pipeline: PipelineFreshnessSummary
    review: ReviewPressureSummary
    budget: BudgetPostureSummary
    networth: NetWorthPostureSummary
    obligations: ObligationConfirmationSummary = field(
        default_factory=_empty_obligation_confirmation_summary
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize the bundle for downstream JSON rendering."""
        return asdict(self)


def collect_checkup_bundle(
    config: Config,
    *,
    today: date | None = None,
    stale_after_days: int = 35,
    review_sample_limit: int = 3,
) -> CheckupBundle:
    """Collect a unified read-only bundle across the main orchestration domains."""
    if stale_after_days < 0:
        raise ValueError("stale_after_days must be >= 0")

    resolved_today = today or date.today()

    pipeline = _collect_pipeline_freshness(
        config,
        today=resolved_today,
        stale_after_days=stale_after_days,
    )
    review = _collect_review_pressure(config, sample_limit=review_sample_limit)
    budget = _collect_budget_posture(config, today=resolved_today)
    networth = _collect_networth_posture(config)
    obligations = _collect_obligation_confirmation(config)

    warnings = _collect_warnings(
        pipeline.warning,
        budget.warning,
        networth.warning,
        obligations.warning,
    )
    next_actions = _build_next_actions(
        pipeline=pipeline,
        review=review,
        budget=budget,
        networth=networth,
        obligations=obligations,
    )

    actionable = (
        pipeline.actionable
        or review.actionable
        or budget.actionable
        or networth.actionable
        or obligations.actionable
    )

    return CheckupBundle(
        data_dir=str(config.data_dir),
        actionable=actionable,
        warnings=warnings,
        next_actions=next_actions,
        pipeline=pipeline,
        review=review,
        budget=budget,
        networth=networth,
        obligations=obligations,
    )


def _collect_pipeline_freshness(
    config: Config,
    *,
    today: date,
    stale_after_days: int,
) -> PipelineFreshnessSummary:
    """Summarize transaction freshness from the shared status snapshot surface."""
    snapshot_result = collect_status_snapshot(config)
    snapshot = snapshot_result.snapshot
    partition_count = len(list(config.csv_base_dir.glob("*/*/transactions.csv")))
    pending_import_files, failed_import_files = _collect_import_preview_counts(config)
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


def _collect_review_pressure(
    config: Config,
    *,
    sample_limit: int,
) -> ReviewPressureSummary:
    """Summarize latest-month transactions that need human attention."""
    latest_month = _latest_partition_month(config.csv_base_dir)
    if latest_month is None:
        return ReviewPressureSummary(
            status="empty",
            actionable=False,
            month=None,
            total_candidates=0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
            samples=[],
        )

    df = _read_month_partition(config.csv_base_dir, latest_month)
    if df is None or df.is_empty():
        return ReviewPressureSummary(
            status="empty",
            actionable=False,
            month=latest_month,
            total_candidates=0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
            samples=[],
        )

    review_expr = _review_pressure_expr(df)
    matching_review_df = df.filter(review_expr)
    review_df = _sort_review_candidates(matching_review_df, sample_limit=sample_limit)
    needs_review_count = (
        int(df.filter(pl.col("needs_review") == 1).height) if "needs_review" in df.columns else 0
    )
    untagged_count = int(df.filter(_untagged_expr(df)).height)
    unclassified_count = (
        int(df.filter(pl.col("category_final") == "미분류").height)
        if "category_final" in df.columns
        else 0
    )
    low_confidence_count = int(df.filter(_low_confidence_expr()).height)

    return ReviewPressureSummary(
        status="needs_attention" if matching_review_df.height > 0 else "healthy",
        actionable=matching_review_df.height > 0,
        month=latest_month,
        total_candidates=int(matching_review_df.height),
        needs_review_count=needs_review_count,
        untagged_count=untagged_count,
        unclassified_count=unclassified_count,
        low_confidence_count=low_confidence_count,
        samples=[
            ReviewSample(
                date=_string_or_none(row.get("date")),
                merchant=_string_or_none(row.get("merchant_raw")),
                amount=_float_or_none(row.get("amount")),
                reasons=_review_reasons(row),
            )
            for row in review_df.to_dicts()
        ],
        rule_notes=(
            _load_checkup_rule_notes(config.rules_file) if matching_review_df.height > 0 else []
        ),
    )


def _collect_budget_posture(
    config: Config,
    *,
    today: date,
) -> BudgetPostureSummary:
    """Summarize monthly budget posture without routing through the CLI command."""
    month = _latest_partition_month(config.csv_base_dir) or today.strftime("%Y-%m")
    goals_result = load_goals_file(config.goals_file)
    actuals, filters_applied, filter_warning = _load_budget_actuals(config, month=month)

    if not goals_result.exists:
        warning = "goals.yaml not found. Budget posture is unconfigured."
        return BudgetPostureSummary(
            status="missing_config",
            actionable=True,
            month=month,
            goals_file_exists=False,
            filters_applied=filters_applied,
            summary=None,
            over_budget_categories=[],
            unbudgeted_categories=[],
            warning=_merge_warning(filter_warning, warning),
        )

    if goals_result.document is None:
        formatted = "; ".join(problem.format() for problem in goals_result.problems)
        warning = f"goals.yaml is invalid. {formatted}" if formatted else "goals.yaml is invalid."
        return BudgetPostureSummary(
            status="invalid",
            actionable=True,
            month=month,
            goals_file_exists=True,
            filters_applied=filters_applied,
            summary=None,
            over_budget_categories=[],
            unbudgeted_categories=[],
            warning=_merge_warning(filter_warning, warning),
        )

    summary = _build_budget_summary(goals_result.document.monthly_budget, actuals)
    category_rows = _build_budget_categories(goals_result.document.monthly_budget, actuals)
    over_budget_categories = [
        row["name"] for row in category_rows if row["status"] == "over" and row["target"] > 0
    ]
    unbudgeted_categories = [
        row["name"] for row in category_rows if row["target"] == 0 and row["actual"]
    ]

    status = "healthy" if summary.status in {"under", "on-track"} else "needs_attention"
    actionable = status == "needs_attention"

    return BudgetPostureSummary(
        status=status,
        actionable=actionable,
        month=month,
        goals_file_exists=True,
        filters_applied=filters_applied,
        summary=summary,
        over_budget_categories=over_budget_categories,
        unbudgeted_categories=unbudgeted_categories,
        warning=filter_warning,
    )


def _collect_networth_posture(config: Config) -> NetWorthPostureSummary:
    """Summarize aggregated net worth from snapshots, assets.yaml, and goals.yaml."""
    snapshots_dir = config.data_dir / "assets" / "snapshots"
    snapshot_months = discover_snapshot_months(snapshots_dir)
    assets_validation = validate_assets_config_file(config.assets_file, allow_missing_file=True)
    assets_warning: str | None = None

    if not assets_validation.is_valid:
        formatted = "; ".join(issue.format() for issue in assets_validation.issues)
        assets_warning = (
            f"assets.yaml is invalid. {formatted}" if formatted else "assets.yaml is invalid."
        )
        return NetWorthPostureSummary(
            status="invalid",
            actionable=True,
            as_of=None,
            snapshot_months=len(snapshot_months),
            assets_file_exists=assets_validation.exists,
            asset_count=0,
            liability_count=0,
            total_assets=0.0,
            total_liabilities=0.0,
            net_worth=0.0,
            target=_load_networth_target(config.goals_file),
            gap_to_target=None,
            warning=assets_warning,
        )

    position = build_networth_position(snapshots_dir, config.assets_file)
    target = _load_networth_target(config.goals_file)
    gap_to_target = float(target - position.net_worth) if target is not None else None

    warning: str | None = None
    if (
        not snapshot_months
        and not assets_validation.config.manual_assets
        and not assets_validation.config.liabilities
    ):
        warning = "No asset snapshots or assets.yaml entries found for net worth posture."
        status = "missing_data"
        actionable = True
    elif position.net_worth < 0:
        status = "negative"
        actionable = True
    elif target is not None and position.net_worth >= target:
        status = "on_target"
        actionable = False
    elif target is not None:
        status = "tracking"
        actionable = False
    else:
        status = "healthy"
        actionable = False

    return NetWorthPostureSummary(
        status=status,
        actionable=actionable,
        as_of=position.as_of.isoformat() if position.as_of is not None else None,
        snapshot_months=len(snapshot_months),
        assets_file_exists=assets_validation.exists,
        asset_count=len(position.assets),
        liability_count=len(position.liabilities),
        total_assets=position.total_assets,
        total_liabilities=position.total_liabilities,
        net_worth=position.net_worth,
        target=target,
        gap_to_target=gap_to_target,
        warning=warning,
    )


def _collect_obligation_confirmation(
    config: Config,
    *,
    threshold_monthly_krw: int = DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD,
) -> ObligationConfirmationSummary:
    """Collect high-level recurring outflow candidates without raw row details."""
    goals_result = load_goals_file(config.goals_file)
    known_labels = known_obligation_labels(goals_result.document)
    known_count = len(goals_result.document.known_obligations or []) if goals_result.document else 0

    source_df = _read_all_partitions(config.csv_base_dir)
    if source_df is None or source_df.is_empty():
        return ObligationConfirmationSummary(
            status="empty",
            actionable=False,
            threshold_monthly_krw=threshold_monthly_krw,
            candidate_count=0,
            known_obligation_count=known_count,
            candidates=[],
        )

    candidates = _detect_large_recurring_outflow_candidates(
        source_df,
        threshold_monthly_krw=threshold_monthly_krw,
        known_labels=known_labels,
    )

    return ObligationConfirmationSummary(
        status="needs_confirmation" if candidates else "healthy",
        actionable=bool(candidates),
        threshold_monthly_krw=threshold_monthly_krw,
        candidate_count=len(candidates),
        known_obligation_count=known_count,
        candidates=candidates,
    )


def _build_next_actions(
    *,
    pipeline: PipelineFreshnessSummary,
    review: ReviewPressureSummary,
    budget: BudgetPostureSummary,
    networth: NetWorthPostureSummary,
    obligations: ObligationConfirmationSummary,
) -> list[NextAction]:
    """Build a deterministic, priority-ordered next-action list."""
    actions: list[NextAction] = []

    if pipeline.status == "empty":
        actions.append(
            NextAction(
                domain="pipeline",
                priority="high",
                reason="거래 파티션이 없어 파이프라인 기반 점검을 시작할 수 없습니다.",
                command="finjuice import <banksalad.xlsx>",
            )
        )
    elif pipeline.status == "import_failures":
        actions.append(
            NextAction(
                domain="pipeline",
                priority="high",
                reason=(
                    f"imports/의 파일 {pipeline.failed_import_files}개가 preview 검증에 실패해 "
                    "원인 확인이 필요합니다."
                ),
                command="finjuice doctor",
            )
        )
        if pipeline.pending_import_status == "present":
            actions.append(
                NextAction(
                    domain="pipeline",
                    priority="high",
                    reason=(
                        f"preview에 성공한 대기 파일 {pipeline.pending_import_files}개는 "
                        "원인 확인 후 갱신할 수 있습니다."
                    ),
                    command="finjuice refresh",
                )
            )
    elif pipeline.pending_import_status == "present":
        actions.append(
            NextAction(
                domain="pipeline",
                priority="high",
                reason=(
                    "imports/에 대기 중인 파일 "
                    f"{pipeline.pending_import_files}개가 있어 최신 상태를 반영하려면 "
                    "갱신이 필요합니다."
                ),
                command="finjuice refresh",
            )
        )
    elif pipeline.status == "stale":
        days = pipeline.days_since_latest or 0
        actions.append(
            NextAction(
                domain="pipeline",
                priority="medium",
                reason=f"최신 거래일이 {days}일 전이라 파이프라인 상태가 오래됐습니다.",
                command="finjuice refresh",
            )
        )
    elif pipeline.warning is not None:
        actions.append(
            NextAction(
                domain="pipeline",
                priority="low",
                reason="상세 상태 분석이 저하돼 환경 점검이 필요합니다.",
                command="finjuice doctor",
            )
        )

    if review.actionable:
        actions.append(
            NextAction(
                domain="review",
                priority="high",
                reason=f"최신 월에 수동 검토 후보 {review.total_candidates}건이 남아 있습니다.",
                command="finjuice review --json",
            )
        )

    if budget.status == "missing_config":
        actions.append(
            NextAction(
                domain="budget",
                priority="medium",
                reason="예산 기준이 없어 지출 posture를 판단할 수 없습니다.",
                command="finjuice budget edit --set total=<monthly_budget> --yes",
            )
        )
    elif budget.status == "invalid":
        actions.append(
            NextAction(
                domain="budget",
                priority="high",
                reason="goals.yaml 검증 오류 때문에 budget posture가 깨졌습니다.",
                command="finjuice budget validate",
            )
        )
    elif budget.actionable and budget.summary is not None:
        actions.append(
            NextAction(
                domain="budget",
                priority="high",
                reason=f"{budget.month} 예산이 초과 상태입니다.",
                command="finjuice budget status --json",
            )
        )

    if networth.status == "missing_data":
        actions.append(
            NextAction(
                domain="networth",
                priority="medium",
                reason="자산 스냅샷이나 수동 자산 정보가 없어 순자산 posture를 계산할 수 없습니다.",
                command="finjuice networth init",
            )
        )
    elif networth.status == "invalid":
        actions.append(
            NextAction(
                domain="networth",
                priority="high",
                reason="assets.yaml 검증 오류 때문에 net worth posture가 깨졌습니다.",
                command="finjuice networth validate",
            )
        )
    elif networth.status == "negative":
        actions.append(
            NextAction(
                domain="networth",
                priority="medium",
                reason="순자산이 음수라 liabilities 구성이 우선 점검 대상입니다.",
                command="finjuice networth --json",
            )
        )

    if obligations.actionable:
        actions.append(
            NextAction(
                domain="obligations",
                priority="medium",
                reason=(
                    f"고액 반복 지출 후보 {obligations.candidate_count}개를 "
                    "known_obligations에 기록할지 확인해야 합니다."
                ),
                command="finjuice checkup --json",
            )
        )

    return sorted(
        actions,
        key=lambda action: (_PRIORITY_ORDER[action.priority], action.domain, action.command),
    )


def _collect_warnings(*messages: str | None) -> list[str]:
    """Return de-duplicated warnings in stable order."""
    warnings: list[str] = []
    seen: set[str] = set()
    for message in messages:
        if not message or message in seen:
            continue
        warnings.append(message)
        seen.add(message)
    return warnings


def _latest_partition_month(csv_base_dir: Path) -> str | None:
    """Return the latest YYYY-MM partition containing transactions.csv."""
    months = [
        f"{path.parent.parent.name}-{path.parent.name}"
        for path in csv_base_dir.glob("*/*/transactions.csv")
        if path.is_file()
    ]
    if not months:
        return None
    return sorted(months)[-1]


def _read_month_partition(csv_base_dir: Path, month: str) -> pl.DataFrame | None:
    """Read one month partition using the canonical Polars schema."""
    year, mon = month.split("-", 1)
    partition_path = get_partition_path(csv_base_dir, int(year), int(mon))
    if not partition_path.exists():
        return None

    return pl.read_csv(
        partition_path,
        schema_overrides=POLARS_SCHEMA,
        null_values=["", "NA", "NULL"],
    )


def _read_all_partitions(csv_base_dir: Path) -> pl.DataFrame | None:
    """Read all transaction partitions into one DataFrame."""
    partition_paths = sorted(
        path for path in csv_base_dir.glob("*/*/transactions.csv") if path.is_file()
    )
    if not partition_paths:
        return None

    frames = [
        pl.read_csv(
            path,
            schema_overrides=POLARS_SCHEMA,
            null_values=["", "NA", "NULL"],
        )
        for path in partition_paths
    ]
    return pl.concat(frames, how="diagonal_relaxed") if frames else None


def _detect_large_recurring_outflow_candidates(
    df: pl.DataFrame,
    *,
    threshold_monthly_krw: int,
    known_labels: set[str],
) -> list[RecurringOutflowCandidate]:
    """Return sanitized monthly recurring outflow confirmation candidates."""
    if df.is_empty() or "amount" not in df.columns or "date" not in df.columns:
        return []

    expense_df = _expense_rows(df)
    if expense_df.is_empty():
        return []

    groups: dict[str, dict[str, Any]] = {}
    for row in expense_df.to_dicts():
        month = _transaction_month(row.get("date"))
        amount = _float_or_none(row.get("amount"))
        label = _recurring_outflow_label(row)
        if month is None or amount is None or amount >= 0 or label is None:
            continue

        key = label.casefold()
        if key in known_labels:
            continue

        group = groups.setdefault(
            key,
            {
                "label": label,
                "month_totals": {},
                "transaction_count": 0,
            },
        )
        month_totals = group["month_totals"]
        month_totals[month] = int(month_totals.get(month, 0) + abs(round(amount)))
        group["transaction_count"] = int(group["transaction_count"]) + 1

    candidates: list[RecurringOutflowCandidate] = []
    for group in groups.values():
        month_totals = group["month_totals"]
        active_months = sorted(month_totals)
        if len(active_months) < _RECURRING_OBLIGATION_MIN_MONTHS:
            continue
        if not _months_are_consecutive(active_months):
            continue

        amounts = [int(month_totals[month]) for month in active_months]
        average_monthly_amount = int(round(sum(amounts) / len(amounts)))
        if average_monthly_amount < threshold_monthly_krw:
            continue

        min_amount = min(amounts)
        max_amount = max(amounts)
        relative_range = (max_amount - min_amount) / max_amount if max_amount else 0
        if relative_range > _RECURRING_OBLIGATION_MAX_RELATIVE_RANGE:
            continue

        label = str(group["label"])
        question = (
            f"{label} 지출이 {len(active_months)}개월 동안 월 "
            f"{_format_won(min_amount)}~{_format_won(max_amount)} 수준으로 반복됩니다. "
            "대출, 월세, 보험료 같은 확정 의무로 known_obligations에 기록할까요?"
        )
        candidates.append(
            RecurringOutflowCandidate(
                label=label,
                cadence="monthly",
                amount_range={"min": min_amount, "max": max_amount},
                average_monthly_amount=average_monthly_amount,
                active_months=active_months,
                active_month_count=len(active_months),
                transaction_count=int(group["transaction_count"]),
                suggested_confirmation_question=question,
            )
        )

    return sorted(
        candidates,
        key=lambda item: (-item.average_monthly_amount, item.label.casefold()),
    )


def _transaction_month(value: Any) -> str | None:
    """Return YYYY-MM from a transaction date-like value."""
    if value is None:
        return None
    raw = str(value)
    if len(raw) < 7:
        return None
    month = raw[:7]
    return month if len(month) == 7 and month[4] == "-" else None


def _recurring_outflow_label(row: dict[str, Any]) -> str | None:
    """Build a sanitized recurring-outflow label without memo/account fields."""
    for column_name in (
        "merchant_raw",
        "category_final",
        "category_rule",
        "minor_raw",
        "major_raw",
    ):
        value = row.get(column_name)
        if value is None:
            continue
        label = _sanitize_recurring_label(str(value))
        if label:
            return label
    return None


def _sanitize_recurring_label(raw_value: str) -> str | None:
    """Remove obvious account-like digit runs and cap labels for JSON surfaces."""
    label = " ".join(raw_value.strip().split())
    if not label:
        return None
    label = _SENSITIVE_DIGIT_PATTERN.sub("#", label)
    label = re.sub(r"\d{4,}", "#", label)
    return label[:40]


def _months_are_consecutive(months: list[str]) -> bool:
    """Return True when month labels form a gapless sequence."""
    ordinals = [_month_ordinal(month) for month in months]
    if any(ordinal is None for ordinal in ordinals):
        return False

    typed_ordinals = [ordinal for ordinal in ordinals if ordinal is not None]
    return typed_ordinals == list(range(typed_ordinals[0], typed_ordinals[0] + len(months)))


def _month_ordinal(month: str) -> int | None:
    """Convert YYYY-MM into a monotonic month ordinal."""
    try:
        year_raw, month_raw = month.split("-", 1)
        year = int(year_raw)
        month_number = int(month_raw)
    except ValueError:
        return None
    if not 1 <= month_number <= 12:
        return None
    return year * 12 + month_number


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


def _is_list_dtype(dtype: pl.DataType | None) -> bool:
    """Return True when the column is a Polars list type."""
    return dtype == pl.List(pl.Utf8) or (dtype is not None and str(dtype).startswith("List"))


def _untagged_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the default untagged predicate used by review surfaces."""
    dtype = df.schema.get("tags_final")
    if _is_list_dtype(dtype):
        return (pl.col("tags_final").list.len() == 0) | pl.col("tags_final").is_null()
    return pl.col("tags_final").str.strip_chars().is_in(["[]", ""]) | pl.col("tags_final").is_null()


def _default_review_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the default review predicate from the latest-month review flow."""
    return (
        (pl.col("needs_review") == 1) | _untagged_expr(df) | (pl.col("category_final") == "미분류")
    )


def _low_confidence_expr() -> pl.Expr:
    """Return the low-confidence predicate used by review surfaces."""
    return pl.col("confidence").is_null() | (pl.col("confidence") < 0.7)


def _review_pressure_expr(df: pl.DataFrame) -> pl.Expr:
    """Return the broader review-pressure predicate for checkup bundles."""
    return _default_review_expr(df) | _low_confidence_expr()


def _sort_review_candidates(df: pl.DataFrame, *, sample_limit: int) -> pl.DataFrame:
    """Sort review candidates newest-first with schema fallback."""
    if df.is_empty():
        return df
    if "datetime" in df.columns:
        return df.sort("datetime", descending=True).head(sample_limit)
    if "date" in df.columns:
        return df.sort("date", descending=True).head(sample_limit)
    return df.head(sample_limit)


def _review_reasons(row: dict[str, Any]) -> list[str]:
    """Derive stable reason labels for one review row."""
    reasons: list[str] = []
    if row.get("needs_review") == 1:
        reasons.append("needs_review")

    tags_value = row.get("tags_final")
    if tags_value is None or tags_value == "[]" or tags_value == [] or tags_value == "":
        reasons.append("untagged")

    if row.get("category_final") == "미분류":
        reasons.append("unclassified")
    confidence = row.get("confidence")
    if confidence is None or float(confidence) < 0.7:
        reasons.append("low_confidence")
    return reasons


def _load_budget_actuals(
    config: Config,
    *,
    month: str,
) -> tuple[dict[str, int], int, str | None]:
    """Load one month's filtered expense actuals by category."""
    df = _read_month_partition(config.csv_base_dir, month)
    if df is None or df.is_empty():
        return {}, 0, None

    report_filters, warning = _load_budget_report_filters(config)
    filtered_df, filters_applied = apply_report_filters(df, report_filters)
    expense_df = _expense_rows(filtered_df)
    if expense_df.is_empty():
        return {}, filters_applied, warning

    grouped = (
        expense_df.with_columns(_budget_category_expr(expense_df).alias("budget_category"))
        .group_by("budget_category")
        .agg(pl.col("amount").abs().sum().alias("actual_amount"))
        .sort("actual_amount", descending=True)
    )
    actuals = {str(row[0]): int(round(float(row[1]))) for row in grouped.iter_rows()}
    return actuals, filters_applied, warning


def _load_budget_report_filters(config: Config) -> tuple[ReportFilters, str | None]:
    """Best-effort report-filter loader for runtime budget posture collection."""
    try:
        return load_report_filters(config.rules_file), None
    except (OSError, yaml.YAMLError) as exc:
        return ReportFilters(), f"Could not load report filters for budget posture: {exc}"


def _load_checkup_rule_notes(rules_file: Path) -> list[dict[str, Any]]:
    """Best-effort rule notes for review/checkup consumers."""
    try:
        return summarize_rule_notes(rules_file, limit=5)
    except (OSError, yaml.YAMLError):
        return []


def _expense_rows(df: pl.DataFrame) -> pl.DataFrame:
    """Return expense rows with transfers excluded."""
    if df.is_empty() or "amount" not in df.columns:
        return df.head(0)

    expr = pl.col("amount") < 0
    if "type_norm" in df.columns:
        expr = expr & (pl.col("type_norm").cast(pl.Utf8, strict=False) == "expense")
    expr = expr & exclude_transfers_for(df)
    return df.filter(expr)


def _budget_category_expr(df: pl.DataFrame) -> pl.Expr:
    """Build the category fallback chain used for budget rollups."""
    exprs: list[pl.Expr] = []
    for column_name in ("category_final", "category_rule", "minor_raw", "major_raw"):
        if column_name in df.columns:
            exprs.append(pl.col(column_name).cast(pl.Utf8, strict=False))
    if not exprs:
        return pl.lit("미분류")
    return pl.coalesce([*exprs, pl.lit("미분류")])


def _build_budget_categories(
    monthly_budget: MonthlyBudget,
    actuals: dict[str, int],
) -> list[dict[str, Any]]:
    """Build per-category rows from configured budgets plus unbudgeted spend."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for name, target in monthly_budget.categories.items():
        rows.append(_budget_row(name, target, actuals.get(name, 0)))
        seen.add(name)

    unbudgeted = [
        (name, actual) for name, actual in actuals.items() if name not in seen and actual > 0
    ]
    for name, actual in sorted(unbudgeted, key=lambda item: (-item[1], item[0])):
        rows.append(_budget_row(name, 0, actual))

    return rows


def _build_budget_summary(monthly_budget: MonthlyBudget, actuals: dict[str, int]) -> BudgetSummary:
    """Build the overall budget summary row."""
    row = _budget_row("Total", monthly_budget.total, sum(actuals.values()))
    return BudgetSummary(
        target=row["target"],
        actual=row["actual"],
        remaining=row["remaining"],
        progress_pct=row["progress_pct"],
        status=row["status"],
    )


def _budget_row(name: str, target: int, actual: int) -> dict[str, Any]:
    """Return one normalized budget-status row."""
    progress_pct = round((actual / target) * 100, 2) if target > 0 else None
    return {
        "name": name,
        "target": target,
        "actual": actual,
        "remaining": target - actual,
        "progress_pct": progress_pct,
        "status": _budget_status(progress_pct=progress_pct, target=target, actual=actual),
    }


def _budget_status(*, progress_pct: float | None, target: int, actual: int) -> str:
    """Return the normalized budget posture enum."""
    if target <= 0:
        return "over" if actual > 0 else "on-track"
    if progress_pct is None:
        return "under"
    if progress_pct > 100.0:
        return "over"
    if progress_pct >= 90.0:
        return "on-track"
    return "under"


def _load_networth_target(goals_file: Path) -> int | None:
    """Return the optional net worth target from goals.yaml when valid."""
    result = load_goals_file(goals_file)
    if result.document is None:
        return None
    return result.document.net_worth_target


def _merge_warning(left: str | None, right: str | None) -> str | None:
    """Merge two warning strings into one stable sentence."""
    if left and right:
        return f"{left} {right}"
    return left or right


def _collect_import_preview_counts(config: Config) -> tuple[int, int]:
    """Count staged imports that are actionable vs preview failures."""
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


def _format_won(value: int) -> str:
    """Format a KRW integer for internal question text."""
    return f"₩{value:,}"


def _string_or_none(value: Any) -> str | None:
    """Return a string value or None."""
    if value is None:
        return None
    return str(value)


def _float_or_none(value: Any) -> float | None:
    """Return a float value or None."""
    if value is None:
        return None
    return float(value)


__all__ = [
    "BudgetPostureSummary",
    "CheckupBundle",
    "DEFAULT_LARGE_RECURRING_OBLIGATION_THRESHOLD",
    "NetWorthPostureSummary",
    "NextAction",
    "ObligationConfirmationSummary",
    "PipelineFreshnessSummary",
    "RecurringOutflowCandidate",
    "ReviewPressureSummary",
    "ReviewSample",
    "collect_checkup_bundle",
]
