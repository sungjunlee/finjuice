"""Compose named checkup collectors into a single read-only bundle.

Next-action builders live in
:mod:`finjuice.pipeline.checkup.next_actions` and are re-exported here so
existing callers can keep importing from this module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date
from typing import Any, TypeVar

from finjuice.pipeline.checkup.budget import collect_budget_posture
from finjuice.pipeline.checkup.freshness import collect_pipeline_freshness
from finjuice.pipeline.checkup.models import CheckupBundle
from finjuice.pipeline.checkup.networth import collect_networth_posture
from finjuice.pipeline.checkup.next_actions import (
    _PRIORITY_ORDER,  # noqa: F401 — re-exported for existing compose imports
    _build_next_actions,
)
from finjuice.pipeline.checkup.obligations import collect_obligation_confirmation
from finjuice.pipeline.checkup.review import collect_review_pressure
from finjuice.pipeline.config import Config

logger = logging.getLogger(__name__)

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
