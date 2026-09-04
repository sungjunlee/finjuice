"""JSON payload assembly and text rendering for ``finjuice checkup``.

Human-readable domain summary helpers live in
:mod:`finjuice.pipeline.cli.commands.checkup.rendering_helpers`
and are re-exported here so existing callers can keep importing from this
module.
"""

from __future__ import annotations

from typing import Any, TypedDict, cast

from finjuice.pipeline.checkup import ActionPriority
from finjuice.pipeline.cli.privacy import compact_rule_notes

from .compute import CheckupFacts
from .detector import CheckupDiagnoses
from .rendering_helpers import (
    _format_won,  # noqa: F401 — re-exported for existing rendering imports
    _summarize_budget,
    _summarize_networth,
    _summarize_obligations,
    _summarize_pipeline,
    _summarize_review,
)


class CheckupSummaryPayload(TypedDict):
    """Stable summary block in `checkup --json` output."""

    status: str
    priority: ActionPriority | None
    headline: str
    recommended_command: str | None
    domains_needing_attention: list[str]
    warning_count: int
    next_action_count: int


class CheckupNextActionPayload(TypedDict):
    """Stable next-action block in `checkup --json` output."""

    domain: str
    priority: ActionPriority
    reason: str
    command: str


class CheckupDomainsPayload(TypedDict):
    """Stable top-level domains block; individual domain internals stay command-owned."""

    pipeline: dict[str, Any]
    review: dict[str, Any]
    budget: dict[str, Any]
    networth: dict[str, Any]
    obligations: dict[str, Any]


class CheckupPayloadBase(TypedDict):
    """Common checkup payload contract before the `_meta` envelope is attached."""

    summary: CheckupSummaryPayload
    actionable: bool
    warnings: list[str]
    next_actions: list[CheckupNextActionPayload]
    domains: CheckupDomainsPayload


class CheckupPayload(CheckupPayloadBase):
    """Raw/redacted checkup payload contract before the `_meta` envelope is attached."""

    data_dir: str


class CompactCheckupPayload(CheckupPayloadBase):
    """Compact checkup payload contract before the `_meta` envelope is attached."""

    pass


def serialize_checkup_payload(
    facts: CheckupFacts,
    diagnoses: CheckupDiagnoses,
) -> CheckupPayload:
    """Project checkup facts and diagnoses into the stable CLI JSON surface."""
    bundle = facts.bundle
    bundle_dict = bundle.to_dict()
    domains: CheckupDomainsPayload = {
        "pipeline": cast(dict[str, Any], bundle_dict["pipeline"]),
        "review": cast(dict[str, Any], bundle_dict["review"]),
        "budget": cast(dict[str, Any], bundle_dict["budget"]),
        "networth": cast(dict[str, Any], bundle_dict["networth"]),
        "obligations": cast(dict[str, Any], bundle_dict["obligations"]),
    }
    next_actions = cast(list[dict[str, Any]], bundle_dict["next_actions"])

    return {
        "data_dir": bundle_dict["data_dir"],
        "summary": cast(CheckupSummaryPayload, diagnoses.summary),
        "actionable": bundle.actionable,
        "warnings": bundle_dict["warnings"],
        "next_actions": [
            {
                "domain": action["domain"],
                "priority": action["priority"],
                "reason": action["reason"],
                "command": action["command"],
            }
            for action in next_actions
        ],
        "domains": domains,
    }


def serialize_checkup(
    facts: CheckupFacts,
    diagnoses: CheckupDiagnoses,
) -> dict[str, Any]:
    """Return the legacy dict payload shape expected by emit/apply_privacy_profile."""
    return cast(dict[str, Any], serialize_checkup_payload(facts, diagnoses))


def _compact_checkup_payload(result: CheckupPayload) -> CompactCheckupPayload:
    """Return checkup JSON with orchestration cues and no detailed samples."""
    domains = result["domains"]
    compact_domains: CheckupDomainsPayload = {
        "pipeline": _compact_pipeline_domain(domains["pipeline"]),
        "review": _compact_review_domain(domains["review"]),
        "budget": _compact_budget_domain(domains["budget"]),
        "networth": _compact_networth_domain(domains["networth"]),
        "obligations": _compact_obligations_domain(domains["obligations"]),
    }
    return {
        "summary": result["summary"],
        "actionable": result["actionable"],
        "warnings": result["warnings"],
        "next_actions": result["next_actions"],
        "domains": compact_domains,
    }


def _compact_checkup(result: dict[str, Any]) -> dict[str, Any]:
    """Return the legacy dict payload shape expected by apply_privacy_profile."""
    return cast(dict[str, Any], _compact_checkup_payload(cast(CheckupPayload, result)))


def _compact_pipeline_domain(pipeline: dict[str, Any]) -> dict[str, Any]:
    """Compact pipeline freshness without financial rollups."""
    return {
        key: pipeline.get(key)
        for key in (
            "status",
            "actionable",
            "pending_import_status",
            "pending_import_files",
            "failed_import_files",
            "transaction_partitions",
            "latest_transaction_date",
            "days_since_latest",
            "active_filters",
            "warning",
        )
    }


def _compact_review_domain(review: dict[str, Any]) -> dict[str, Any]:
    """Compact review pressure without row samples."""
    samples = review.get("samples") or []
    return {
        "status": review.get("status"),
        "actionable": review.get("actionable"),
        "month": review.get("month"),
        "total_candidates": review.get("total_candidates"),
        "needs_review_count": review.get("needs_review_count"),
        "untagged_count": review.get("untagged_count"),
        "unclassified_count": review.get("unclassified_count"),
        "low_confidence_count": review.get("low_confidence_count"),
        "sample_count": len(samples) if isinstance(samples, list) else 0,
        "rule_notes": compact_rule_notes(review.get("rule_notes")),
    }


def _compact_budget_domain(budget: dict[str, Any]) -> dict[str, Any]:
    """Compact budget posture without concrete amounts or category names."""
    summary = budget.get("summary") or {}
    return {
        "status": budget.get("status"),
        "actionable": budget.get("actionable"),
        "month": budget.get("month"),
        "goals_file_exists": budget.get("goals_file_exists"),
        "filters_applied": budget.get("filters_applied"),
        "summary": {
            "progress_pct": summary.get("progress_pct"),
            "status": summary.get("status"),
        }
        if isinstance(summary, dict)
        else None,
        "over_budget_category_count": len(budget.get("over_budget_categories") or []),
        "unbudgeted_category_count": len(budget.get("unbudgeted_categories") or []),
        "warning": budget.get("warning"),
    }


def _compact_networth_domain(networth: dict[str, Any]) -> dict[str, Any]:
    """Compact net worth posture without balances."""
    return {
        key: networth.get(key)
        for key in (
            "status",
            "actionable",
            "as_of",
            "snapshot_months",
            "assets_file_exists",
            "asset_count",
            "liability_count",
            "warning",
        )
    }


def _compact_obligations_domain(obligations: dict[str, Any]) -> dict[str, Any]:
    """Compact obligation posture without merchant-like labels or amounts."""
    candidates = obligations.get("candidates") or []
    return {
        "status": obligations.get("status"),
        "actionable": obligations.get("actionable"),
        "candidate_count": obligations.get("candidate_count"),
        "known_obligation_count": obligations.get("known_obligation_count"),
        "sample_count": len(candidates) if isinstance(candidates, list) else 0,
        "warning": obligations.get("warning"),
    }


def render_text(result: dict[str, Any]) -> str:
    """Render a concise plain-text checkup for terminal use."""
    summary = result["summary"]
    domains = result["domains"]
    next_actions = result["next_actions"]
    warnings = result["warnings"]

    fast_mode = any(
        str(domains[name].get("status")) == "skipped" for name in ("review", "obligations")
    )
    lines = ["finjuice checkup --fast" if fast_mode else "finjuice checkup", ""]
    lines.extend(
        [
            "Summary",
            f"- status: {summary['status']}",
            f"- headline: {summary['headline']}",
            (
                f"- recommended: {summary['recommended_command']}"
                if summary["recommended_command"]
                else "- recommended: none"
            ),
        ]
    )

    lines.extend(
        [
            "",
            "Domains",
            f"- pipeline: {_summarize_pipeline(domains['pipeline'])}",
            f"- review: {_summarize_review(domains['review'])}",
            f"- budget: {_summarize_budget(domains['budget'])}",
            f"- networth: {_summarize_networth(domains['networth'])}",
            f"- obligations: {_summarize_obligations(domains['obligations'])}",
        ]
    )

    if warnings:
        lines.extend(["", "Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    if next_actions:
        lines.extend(["", "Next Actions"])
        for action in next_actions:
            lines.append(f"- [{action['priority']}] {action['command']}: {action['reason']}")

    return "\n".join(lines)


def _render_text(result: dict[str, Any]) -> str:
    """Legacy wrapper for plain-text rendering."""
    return render_text(result)
