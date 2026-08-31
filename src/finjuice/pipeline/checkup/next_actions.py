"""Deterministic next-action builders for the checkup composer.

Owns priority ordering and per-domain follow-up actions. Bundle
orchestration stays in :mod:`finjuice.pipeline.checkup.compose`, which
re-exports these helpers so existing callers can keep importing from
that module.
"""

from __future__ import annotations

from finjuice.pipeline.checkup.models import (
    ActionPriority,
    BudgetPostureSummary,
    NetWorthPostureSummary,
    NextAction,
    ObligationConfirmationSummary,
    PipelineFreshnessSummary,
    ReviewPressureSummary,
)

_PRIORITY_ORDER: dict[ActionPriority, int] = {
    "high": 0,
    "medium": 1,
    "low": 2,
}


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
