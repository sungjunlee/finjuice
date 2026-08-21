"""Compose named checkup collectors into a single read-only bundle."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from finjuice.pipeline.checkup.budget import collect_budget_posture
from finjuice.pipeline.checkup.freshness import collect_pipeline_freshness
from finjuice.pipeline.checkup.models import (
    ActionPriority,
    BudgetPostureSummary,
    CheckupBundle,
    NetWorthPostureSummary,
    NextAction,
    ObligationConfirmationSummary,
    PipelineFreshnessSummary,
    ReviewPressureSummary,
)
from finjuice.pipeline.checkup.networth import collect_networth_posture
from finjuice.pipeline.checkup.obligations import collect_obligation_confirmation
from finjuice.pipeline.checkup.review import collect_review_pressure
from finjuice.pipeline.config import Config

logger = logging.getLogger(__name__)

_PRIORITY_ORDER: dict[ActionPriority, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
}

T = TypeVar("T")

NAMED_COLLECTORS: dict[str, Callable[..., Any]] = {
    "pipeline": collect_pipeline_freshness,
    "review": collect_review_pressure,
    "budget": collect_budget_posture,
    "networth": collect_networth_posture,
    "obligations": collect_obligation_confirmation,
}


def run_named_collector(
    name: str,
    collector: Callable[..., T],
    /,
    *args: Any,
    **kwargs: Any,
) -> T:
    """Run a named collector fail-closed.

    Exceptions propagate. The composer never substitutes a healthy or empty
    summary for a failed collector, and it does not skip a collector unless a
    future caller adds an explicit skip that remains visible in warnings.
    """
    logger.debug("Running checkup collector %s", name)
    return collector(*args, **kwargs)


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

    pipeline = run_named_collector(
        "pipeline",
        NAMED_COLLECTORS["pipeline"],
        config,
        today=resolved_today,
        stale_after_days=stale_after_days,
    )
    review = run_named_collector(
        "review",
        NAMED_COLLECTORS["review"],
        config,
        sample_limit=review_sample_limit,
    )
    budget = run_named_collector(
        "budget",
        NAMED_COLLECTORS["budget"],
        config,
        today=resolved_today,
    )
    networth = run_named_collector("networth", NAMED_COLLECTORS["networth"], config)
    obligations = run_named_collector(
        "obligations",
        NAMED_COLLECTORS["obligations"],
        config,
    )

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
