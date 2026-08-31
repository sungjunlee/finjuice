"""Named checkup collector registry and fail-closed runner.

Owns the domain-to-collector map and the fail-closed invocation helper.
Bundle orchestration stays in :mod:`finjuice.pipeline.checkup.compose`,
which re-exports these names so existing callers can keep importing from
that module.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, TypeVar

from finjuice.pipeline.checkup.budget import collect_budget_posture
from finjuice.pipeline.checkup.freshness import collect_pipeline_freshness
from finjuice.pipeline.checkup.networth import collect_networth_posture
from finjuice.pipeline.checkup.obligations import collect_obligation_confirmation
from finjuice.pipeline.checkup.review import collect_review_pressure

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
    skip: bool = False,
    skip_result: T | None = None,
    **kwargs: Any,
) -> T:
    """Run a named collector fail-closed.

    Exceptions propagate. The composer never substitutes a healthy or empty
    summary for a failed collector, and it does not skip a collector unless a
    future caller adds an explicit skip that remains visible in warnings.
    """
    if skip:
        if skip_result is None:
            raise ValueError(f"skip_result is required to skip checkup collector {name}")
        logger.debug("Skipping checkup collector %s", name)
        return skip_result
    logger.debug("Running checkup collector %s", name)
    return collector(*args, **kwargs)
