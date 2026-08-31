"""Compose named checkup collectors into a single read-only bundle.

Next-action builders live in
:mod:`finjuice.pipeline.checkup.next_actions` and are re-exported here so
existing callers can keep importing from this module.

The named collector registry lives in
:mod:`finjuice.pipeline.checkup.named_collectors` and is re-exported here
so existing callers can keep importing from this module.

Warning aggregation helpers live in
:mod:`finjuice.pipeline.checkup.warnings` and are re-exported here so
existing callers can keep importing from this module.
"""

from __future__ import annotations

from datetime import date

from finjuice.pipeline.checkup.models import CheckupBundle
from finjuice.pipeline.checkup.named_collectors import (
    NAMED_COLLECTORS,
    run_named_collector,
)
from finjuice.pipeline.checkup.next_actions import (
    _PRIORITY_ORDER,  # noqa: F401 — re-exported for existing compose imports
    _build_next_actions,
)
from finjuice.pipeline.checkup.warnings import _collect_warnings
from finjuice.pipeline.config import Config


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
