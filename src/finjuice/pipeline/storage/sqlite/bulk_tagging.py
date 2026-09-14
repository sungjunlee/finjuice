"""Pure bulk tagging plan plus MutationContext application.

Rules are read from the pinned canonical config head. Amounts enter the matcher
as non-rounded decimal text. Manual, AI, provenance, and source fields are not
rewritten. Coverage confidence is an integer 0/1 ExactValue allocated only when
derived semantics actually change.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.ids import validate_entity_id
from finjuice.pipeline.storage.sqlite.mutations import MutationContext
from finjuice.pipeline.tagging.manual import merge_final_tags, resolve_category_final
from finjuice.pipeline.tagging.matcher import apply_tagging_rules_v3
from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes

JSONValue = Any


@dataclass(frozen=True)
class BulkTagCommand:
    """Replayable bulk tagging intent without current-head identifiers."""

    transaction_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        _validate_optional_ids(self.transaction_ids)

    def payload(self) -> dict[str, JSONValue]:
        """Return the stable command payload used for idempotent replay."""
        ids = self.transaction_ids
        return {"operation": "recompute", "transaction_ids": None if ids is None else list(ids)}


@dataclass(frozen=True)
class BulkTagChange:
    """One planned derived-tag write for a stable transaction."""

    transaction_id: str
    before: Mapping[str, JSONValue]
    after: Mapping[str, JSONValue]
    confidence: int
    current_matches: bool


@dataclass(frozen=True)
class BulkTagPlan:
    """Shared tagging computation used by dry-run preview and the writer."""

    total: int
    updated: int
    tagged: int
    untagged: int
    changes: tuple[BulkTagChange, ...]

    def result(self) -> dict[str, JSONValue]:
        """Return float-free integer counts shared by preview and write."""
        return {
            "changed": self.updated > 0,
            "tagged": self.tagged,
            "total": self.total,
            "unchanged": self.total - self.updated,
            "untagged": self.untagged,
            "unsupported": 0,
            "updated": self.updated,
        }


def plan_bulk_tagging(context: MutationContext, command: BulkTagCommand) -> BulkTagPlan:
    """Compute derived tagging under the pinned snapshot without writing."""
    rules = load_canonical_rules(context)
    rows = context.load_bulk_transactions(command.transaction_ids)
    changes = tuple(
        change for change in (_planned_tag_change(row, rules) for row in rows) if change is not None
    )
    tagged, untagged = _tag_coverage_counts(rows, changes)
    return BulkTagPlan(len(rows), len(changes), tagged, untagged, changes)


def _planned_tag_change(
    row: Mapping[str, JSONValue],
    rules: Sequence[TagRule],
) -> BulkTagChange | None:
    derived = compute_tag_derived(row, rules)
    if _semantic_state(row) == _semantic_derived(derived):
        return None
    target = int(derived["confidence"])
    return BulkTagChange(
        transaction_id=str(row["transaction_id"]),
        before=tagging_derived_state(row),
        after=tagging_after_state(derived, row["confidence_value_id"]),
        confidence=target,
        current_matches=(
            _coverage_confidence(row) == target and row["confidence_value_id"] is not None
        ),
    )


def apply_bulk_tagging(context: MutationContext, command: BulkTagCommand) -> dict[str, JSONValue]:
    """Write planned tagging changes inside the caller's mutation transaction."""
    plan = plan_bulk_tagging(context, command)
    shared_ids: dict[int, str] = {}
    for change in plan.changes:
        after = dict(change.after)
        after["confidence_value_id"] = _confidence_id(context, change, shared_ids)
        context.update_transaction_derived_state(
            change.transaction_id,
            after,
            before=change.before,
        )
    return plan.result()


def preview_bulk_tagging(context: MutationContext, command: BulkTagCommand) -> dict[str, JSONValue]:
    """Return the write counts without allocating values or updating rows."""
    return plan_bulk_tagging(context, command).result()


def load_canonical_rules(context: MutationContext) -> list[TagRule]:
    """Load enabled-priority rules from the pinned parsed rules head.

    A missing, opaque, or invalid head is rejected. An explicitly parsed empty
    rules document is valid and clears derived rule fields.
    """
    status, content = context.load_rules_head()
    if status is None or content is None:
        raise MutationValidationError("Rules head is missing.")
    if status != "parsed":
        raise MutationValidationError("Rules head is not a parsed canonical document.")
    try:
        return load_rules_bytes(content)
    except ValueError as exc:
        raise MutationValidationError("Rules head is not a parsed canonical document.") from exc


def compute_tag_derived(
    row: Mapping[str, JSONValue], rules: Sequence[TagRule]
) -> dict[str, JSONValue]:
    """Apply canonical tagging semantics to one already-loaded snapshot row."""
    matched = apply_tagging_rules_v3(_matcher_transaction(row), list(rules))
    tags_rule = list(matched.tags)
    tags_final = merge_final_tags(tags_rule, row["tags_ai"], row["tags_manual"])
    category_rule = matched.category_rule or None
    confidence = int(bool(tags_final))
    return {
        "category_final": _category_final(row, category_rule),
        "category_rule": category_rule,
        "confidence": confidence,
        "needs_review": confidence == 0,
        "tags_final": tags_final,
        "tags_rule": tags_rule,
    }


def tagging_derived_state(row: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Return the comparable derived tagging snapshot for one loaded row."""
    return {
        "category_final": row["category_final"],
        "category_rule": row["category_rule"],
        "confidence_value_id": row["confidence_value_id"],
        "needs_review": row["needs_review"],
        "tags_final": list(row["tags_final"]),
        "tags_rule": list(row["tags_rule"]),
    }


def tagging_after_state(
    derived: Mapping[str, JSONValue],
    confidence_value_id: str | None,
) -> dict[str, JSONValue]:
    """Build the derived update mapping, reusing the current confidence id."""
    return {
        "category_final": derived["category_final"],
        "category_rule": derived["category_rule"],
        "confidence_value_id": confidence_value_id,
        "needs_review": derived["needs_review"],
        "tags_final": list(derived["tags_final"]),
        "tags_rule": list(derived["tags_rule"]),
    }


def _matcher_transaction(row: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Supply matcher fields with exact amount text and no KRW/zero coercion."""
    return {
        "account": row.get("account_text") or "",
        "amount": row.get("amount_exact"),
        "major_raw": row.get("major_raw") or "",
        "memo_raw": row.get("memo_raw") or "",
        "merchant_raw": row.get("merchant_raw") or "",
        "minor_raw": row.get("minor_raw") or "",
        "type_norm": row.get("type_norm") or "",
    }


def _category_final(row: Mapping[str, JSONValue], category_rule: str | None) -> str:
    """Prefer the canonical manual column, then sentinel override, then rule fallbacks."""
    manual = row.get("category_manual")
    if isinstance(manual, str) and manual.strip():
        return manual.strip()
    return resolve_category_final(
        category_rule,
        row.get("minor_raw"),
        row.get("major_raw"),
        tags_manual=row.get("tags_manual"),
    )


def _semantic_state(row: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Compare derived tagging without using ExactValue identity."""
    return {
        "category_final": row["category_final"],
        "category_rule": row["category_rule"],
        "confidence": _coverage_confidence(row),
        "needs_review": row["needs_review"],
        "tags_final": list(row["tags_final"]),
        "tags_rule": list(row["tags_rule"]),
    }


def _semantic_derived(derived: Mapping[str, JSONValue]) -> dict[str, JSONValue]:
    """Compare planned tagging using integer coverage rather than value ids."""
    return {
        "category_final": derived["category_final"],
        "category_rule": derived["category_rule"],
        "confidence": derived["confidence"],
        "needs_review": derived["needs_review"],
        "tags_final": list(derived["tags_final"]),
        "tags_rule": list(derived["tags_rule"]),
    }


def _coverage_confidence(row: Mapping[str, JSONValue]) -> int | None:
    """Return stored coverage 0/1, or None when the value is missing or not binary."""
    if row.get("confidence_unit") != "confidence.v1":
        return None
    coefficient = row.get("confidence_coefficient")
    scale = row.get("confidence_scale")
    if not isinstance(coefficient, str) or not isinstance(scale, int):
        return None
    try:
        numeric = int(coefficient)
    except ValueError:
        return None
    for target in (0, 1):
        if numeric == target * 10**scale:
            return target
    return None


def _tag_coverage_counts(
    rows: Sequence[Mapping[str, JSONValue]],
    changes: Sequence[BulkTagChange],
) -> tuple[int, int]:
    """Count planned tagged/untagged rows from after-state, else the loaded row."""
    planned = {change.transaction_id: change.after["tags_final"] for change in changes}
    tagged = 0
    for row in rows:
        tags = planned.get(str(row["transaction_id"]), row["tags_final"])
        if tags:
            tagged += 1
    return tagged, len(rows) - tagged


def _confidence_id(
    context: MutationContext,
    change: BulkTagChange,
    shared_ids: dict[int, str],
) -> str:
    """Keep a matching row id, otherwise reuse or allocate a calculated 0/1 value."""
    if change.current_matches:
        return str(change.before["confidence_value_id"])
    target = change.confidence
    if target not in shared_ids:
        existing = context.find_calculated_confidence(target)
        shared_ids[target] = existing or context.allocate_calculated_confidence(target)
    return shared_ids[target]


def _validate_optional_ids(transaction_ids: tuple[str, ...] | None) -> None:
    """Reject empty, duplicate, or non-entity bulk identifiers."""
    if transaction_ids is None:
        return
    seen: set[str] = set()
    for transaction_id in transaction_ids:
        validate_entity_id(transaction_id)
        if transaction_id in seen:
            raise MutationValidationError("Transaction identifiers must be unique.")
        seen.add(transaction_id)


__all__ = [
    "BulkTagCommand",
    "BulkTagPlan",
    "apply_bulk_tagging",
    "plan_bulk_tagging",
    "preview_bulk_tagging",
]
