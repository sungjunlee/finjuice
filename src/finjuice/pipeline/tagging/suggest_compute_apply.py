"""Headless auto-apply helpers for `finjuice rules suggest`.

Owns the `--apply --yes` suggestion application loop used by JSON compute.
JSON compute stays in :mod:`finjuice.pipeline.tagging.suggest_compute`,
which re-exports these names so existing callers can keep importing from
that module. Coverage-stat shaping lives in
:mod:`finjuice.pipeline.tagging.suggest_compute_stats`, compact privacy
projection lives in
:mod:`finjuice.pipeline.tagging.suggest_compute_compact`, and the domain
error lives in :mod:`finjuice.pipeline.tagging.suggest_compute_error`.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _apply_auto_apply_suggestions(
    suggestions: Sequence[dict[str, Any]],
    *,
    rules_file: Path,
    audit_applied: Callable[[str], None],
) -> tuple[int, int]:
    """Apply auto-apply eligible suggestions headlessly.

    Returns ``(applied_count, skipped_count)``; ``audit_applied`` is called
    with each applied rule name. Ineligible, failing, and erroring
    suggestions are counted as skipped instead of raising.
    """
    from finjuice.pipeline.tagging.suggestions import (
        apply_suggestion_to_rules,
        is_auto_apply_eligible,
    )

    applied_count = 0
    skipped_count = 0

    for suggestion_idx, suggestion in enumerate(suggestions, start=1):
        if not is_auto_apply_eligible(suggestion):
            skipped_count += 1
            continue
        try:
            applied_rule = apply_suggestion_to_rules(suggestion, rules_file)
            audit_applied(applied_rule.name)
            applied_count += 1
        except (OSError, ValueError) as exc:
            logger.warning(
                "Failed to auto-apply suggestion %s/%s (%s)",
                suggestion_idx,
                len(suggestions),
                type(exc).__name__,
            )
            skipped_count += 1

    return applied_count, skipped_count
