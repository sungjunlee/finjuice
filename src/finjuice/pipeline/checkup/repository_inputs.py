"""Detached display and configuration inputs for repository checkups."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

import polars as pl

from finjuice.pipeline.asset_config import (
    AssetsConfig,
    AssetsConfigIssue,
    AssetsConfigValidationResult,
    validate_assets_config_bytes,
)
from finjuice.pipeline.goals import (
    GoalsLoadResult,
    GoalsValidationProblem,
    load_goals_roundtrip_bytes,
    validate_goals_payload,
)
from finjuice.pipeline.storage.read_facade import transaction_frame
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters_bytes, load_rules_bytes


class RepositoryCheckupError(ValueError):
    """Static failure when authoritative checkup evidence cannot be interpreted."""


def scoped_transactions(
    snapshot: TransactionReadSnapshot, month: str | None = None
) -> pl.DataFrame:
    """Keep primary/native scope and original partition/row order before calculations."""
    by_id = {row["transaction_id"]: row for row in snapshot.rows}
    if len(snapshot.scopes) != len(by_id) or {s.transaction_id for s in snapshot.scopes} != set(
        by_id
    ):
        raise RepositoryCheckupError("Repository transaction scope evidence is incomplete.")
    scopes = sorted(
        snapshot.scopes,
        key=lambda s: (s.month or "", s.source_row is None, s.source_row or 0, s.transaction_id),
    )
    rows = tuple(
        by_id[s.transaction_id]
        for s in scopes
        if s.included and (month is None or s.month == month)
    )
    return transaction_frame(replace(snapshot, rows=rows))


def _absent(selection: PortfolioConfigSnapshot) -> bool:
    return selection.selection_state == "absent" and not selection.revisions


def _content(selection: PortfolioConfigSnapshot) -> bytes:
    head = selection.head
    if selection.selection_state != "selected" or head is None or head.parsed_status != "parsed":
        raise RepositoryCheckupError("Canonical configuration requires a valid selection.")
    return head.content


def checkup_goals(selection: PortfolioConfigSnapshot) -> GoalsLoadResult:
    """Represent invalid/unselected goals as unavailable, never as absent targets."""
    if _absent(selection):
        return GoalsLoadResult(False, None, [])
    try:
        _, raw = load_goals_roundtrip_bytes(_content(selection))
        document, problems = validate_goals_payload(raw)
        if document is not None and not problems:
            return GoalsLoadResult(True, document, [])
    except Exception:
        pass
    return GoalsLoadResult(
        True,
        None,
        [
            GoalsValidationProblem(
                "goals.yaml", "Canonical goals require a valid selection and content."
            )
        ],
    )


def checkup_assets(selection: PortfolioConfigSnapshot) -> AssetsConfigValidationResult:
    """Validate canonical manual assets while preserving explicit absence semantics."""
    if _absent(selection):
        return AssetsConfigValidationResult(Path("assets.yaml"), False, AssetsConfig())
    try:
        result = validate_assets_config_bytes(_content(selection))
        if result.is_valid:
            return result
    except Exception:
        pass
    return AssetsConfigValidationResult(
        Path("assets.yaml"),
        True,
        AssetsConfig(),
        [
            AssetsConfigIssue(
                "assets.yaml", "Canonical assets require a valid selection and content."
            )
        ],
    )


def checkup_rules(selection: PortfolioConfigSnapshot) -> tuple[ReportFilters, list[dict[str, Any]]]:
    """Validate canonical filters and derive enabled notes from those same bytes."""
    if _absent(selection):
        return ReportFilters(), []
    try:
        content = _content(selection)
        filters = load_report_filters_bytes(content)
        notes = []
        for rule in load_rules_bytes(content):
            if rule.enabled and rule.notes.strip():
                item: dict[str, Any] = {
                    "rule_name": rule.name,
                    "notes": rule.notes.strip(),
                    "tags": list(rule.tags),
                }
                if rule.category:
                    item["category"] = rule.category
                notes.append(item)
                if len(notes) == 5:
                    break
        return filters, notes
    except Exception:
        raise RepositoryCheckupError(
            "Canonical rules cannot supply checkup filters and notes."
        ) from None
