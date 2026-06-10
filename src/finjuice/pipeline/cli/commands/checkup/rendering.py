"""JSON payload assembly and text rendering for ``finjuice checkup``."""

from __future__ import annotations

from typing import Any, TypedDict, cast

from finjuice.pipeline.checkup import ActionPriority, CheckupBundle
from finjuice.pipeline.cli.privacy import compact_rule_notes

from .compute import CheckupFacts
from .detector import CheckupDiagnoses, detect_checkup_diagnoses


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


def _serialize_checkup_payload(bundle: CheckupBundle) -> CheckupPayload:
    """Legacy helper preserving the typed checkup payload test surface."""
    facts = CheckupFacts(bundle=bundle)
    diagnoses = detect_checkup_diagnoses(facts)
    return serialize_checkup_payload(facts, diagnoses)


def _serialize_checkup(bundle: CheckupBundle) -> dict[str, Any]:
    """Return the legacy dict payload shape expected by emit/apply_privacy_profile."""
    return cast(dict[str, Any], _serialize_checkup_payload(bundle))


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

    lines = ["finjuice checkup", ""]
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


def _summarize_pipeline(pipeline: dict[str, Any]) -> str:
    """Render a single pipeline summary line."""
    status = str(pipeline["status"])
    if status == "empty":
        return "empty; no transaction partitions"
    if status == "import_failures":
        return (
            "import_failures; "
            f"failed={pipeline['failed_import_files']}, "
            f"pending={pipeline['pending_import_files']}"
        )
    if status == "pending_imports":
        return f"pending_imports; staged={pipeline['pending_import_files']}"
    if status == "stale":
        return f"stale; latest data {pipeline['days_since_latest']}d old"
    latest = pipeline.get("latest_transaction_date") or pipeline.get("data_range") or "-"
    return f"{status}; latest={latest}"


def _summarize_review(review: dict[str, Any]) -> str:
    """Render a single review summary line."""
    status = str(review["status"])
    if status == "empty":
        return "empty; no reviewable transactions"
    return (
        f"{status}; candidates={review['total_candidates']}, "
        f"untagged={review['untagged_count']}, "
        f"low_confidence={review['low_confidence_count']}"
    )


def _summarize_budget(budget: dict[str, Any]) -> str:
    """Render a single budget summary line.

    Uses ``.get`` for both ``actual`` and ``target`` so the privacy-redacted
    and compact-profile shapes (which null out or omit those keys) render as
    "-" instead of raising.
    """
    status = str(budget["status"])
    if status == "missing_config":
        return "missing_config; goals.yaml missing"
    if status == "invalid":
        return "invalid; goals.yaml validation failed"
    summary = budget.get("summary")
    if summary is None:
        return status
    month = budget.get("month")
    actual = summary.get("actual") if isinstance(summary, dict) else None
    target = summary.get("target") if isinstance(summary, dict) else None
    return f"{status}; month={month}, actual={_format_won(actual)}, target={_format_won(target)}"


def _summarize_networth(networth: dict[str, Any]) -> str:
    """Render a single net worth summary line."""
    status = str(networth["status"])
    if status == "missing_data":
        return "missing_data; no asset snapshots or assets.yaml entries"
    if status == "invalid":
        return "invalid; assets.yaml validation failed"
    # Privacy-redacted and compact profiles null out or drop the net_worth value;
    # render those uniformly as "-".
    return f"{status}; net_worth={_format_won(networth.get('net_worth'))}"


def _summarize_obligations(obligations: dict[str, Any]) -> str:
    """Render a single obligation confirmation summary line.

    ``threshold_monthly_krw`` is nulled or omitted under the privacy-redacted
    and compact profiles; ``_format_won`` renders ``None`` as "-".
    """
    status = str(obligations["status"])
    if status == "empty":
        return "empty; no transaction history"
    threshold = obligations.get("threshold_monthly_krw")
    if status == "needs_confirmation":
        return (
            "needs_confirmation; "
            f"candidates={obligations.get('candidate_count')}, "
            f"threshold={_format_won(threshold)}/mo"
        )
    return (
        f"{status}; known={obligations.get('known_obligation_count')}, "
        f"threshold={_format_won(threshold)}/mo"
    )


def _format_won(value: Any) -> str:
    """Format a numeric value as Korean won."""
    if value is None:
        return "-"
    amount = float(value)
    sign = "-" if amount < 0 else ""
    return f"{sign}₩{abs(amount):,.0f}"
