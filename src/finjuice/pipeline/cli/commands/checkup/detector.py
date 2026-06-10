"""Decision logic for the ``finjuice checkup`` command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from .compute import CheckupFacts


@dataclass(frozen=True)
class CheckupDiagnoses:
    """Summary decisions derived from the checkup bundle."""

    summary: dict[str, Any]


def detect_checkup_diagnoses(facts: CheckupFacts) -> CheckupDiagnoses:
    """Build the stable summary block from collected checkup facts."""
    bundle = facts.bundle
    bundle_dict = bundle.to_dict()
    domains = cast(dict[str, dict[str, Any]], _domain_payloads(bundle_dict))
    next_actions = cast(list[dict[str, Any]], bundle_dict["next_actions"])
    recommended_action = next_actions[0] if next_actions else None
    domains_needing_attention = [
        domain_name for domain_name, payload in domains.items() if bool(payload.get("actionable"))
    ]

    return CheckupDiagnoses(
        summary={
            "status": "needs_attention" if bundle.actionable else "ok",
            "priority": recommended_action["priority"] if recommended_action else None,
            "headline": (
                recommended_action["reason"]
                if recommended_action
                else "No immediate action required."
            ),
            "recommended_command": recommended_action["command"] if recommended_action else None,
            "domains_needing_attention": domains_needing_attention,
            "warning_count": len(bundle.warnings),
            "next_action_count": len(next_actions),
        }
    )


def _domain_payloads(bundle_dict: dict[str, Any]) -> dict[str, Any]:
    """Return domain payloads in the public summary order."""
    return {
        "pipeline": bundle_dict["pipeline"],
        "review": bundle_dict["review"],
        "budget": bundle_dict["budget"],
        "networth": bundle_dict["networth"],
        "obligations": bundle_dict["obligations"],
    }
