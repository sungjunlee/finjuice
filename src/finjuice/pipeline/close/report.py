"""Deterministic report regeneration and close-revision difference."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from decimal import Decimal, InvalidOperation

from finjuice.pipeline.close.errors import CloseError
from finjuice.pipeline.close.models import (
    CloseDiff,
    CloseLine,
    CloseReport,
    CloseResultState,
    CloseSnapshot,
)

_ZERO = Decimal("0")


def parse_close_amount(value: object) -> Decimal:
    """Parse a close amount from int/str/Decimal. Reject floats."""
    if isinstance(value, float):
        raise CloseError("Close amounts must be exact decimals, not float.")
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as error:
        raise CloseError("Invalid close amount.") from error


def canonical_amount(value: object) -> str:
    """Return a stable decimal text form for stored close amounts."""
    return format(parse_close_amount(value), "f")


def ordered_lines(lines: tuple[CloseLine, ...]) -> tuple[CloseLine, ...]:
    """Return close lines ordered by id so reports do not depend on input order."""
    return tuple(sorted(lines, key=lambda line: line.line_id))


def compute_close_report(snapshot: CloseSnapshot, *, close_revision: int) -> CloseReport:
    """Rebuild the close report from frozen inputs only.

    The same snapshot and revision always yield the same digest and totals.
    Live data is never consulted.
    """
    if isinstance(close_revision, bool) or close_revision < 1:
        raise CloseError("Close revision must be a positive integer.")
    income = _ZERO
    expense = _ZERO
    for line in ordered_lines(snapshot.lines):
        amount = parse_close_amount(line.amount)
        if amount >= _ZERO:
            income += amount
        else:
            expense += abs(amount)
    net = income - expense
    unconfirmed = tuple(sorted(snapshot.unconfirmed_item_ids))
    state: CloseResultState = "closed_with_unconfirmed" if unconfirmed else "closed"
    income_text = canonical_amount(income)
    expense_text = canonical_amount(expense)
    net_text = canonical_amount(net)
    payload = {
        "calculation_policy": snapshot.calculation_policy,
        "close_revision": close_revision,
        "dataset_revision": snapshot.dataset_revision,
        "expense": expense_text,
        "income": income_text,
        "line_ids": [line.line_id for line in ordered_lines(snapshot.lines)],
        "line_count": len(snapshot.lines),
        "net": net_text,
        "period": snapshot.period,
        "rules_policy": snapshot.rules_policy,
        "source_as_of": snapshot.source_as_of,
        "state": state,
        "unconfirmed_item_ids": list(unconfirmed),
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return CloseReport(
        period=snapshot.period,
        close_revision=close_revision,
        dataset_revision=snapshot.dataset_revision,
        rules_policy=snapshot.rules_policy,
        calculation_policy=snapshot.calculation_policy,
        source_as_of=snapshot.source_as_of,
        income=income_text,
        expense=expense_text,
        net=net_text,
        line_count=len(snapshot.lines),
        digest=digest,
        unconfirmed_item_ids=unconfirmed,
        state=state,
    )


def explain_close_diff(left: CloseReport, right: CloseReport) -> CloseDiff:
    """Return the reasons a later close revision differs from an earlier one."""
    if left.period != right.period:
        raise CloseError("Close diffs compare revisions of one period.")
    reasons: list[str] = []
    if left.dataset_revision != right.dataset_revision:
        reasons.append("dataset_revision_changed")
    if left.rules_policy != right.rules_policy:
        reasons.append("rules_policy_changed")
    if left.calculation_policy != right.calculation_policy:
        reasons.append("calculation_policy_changed")
    if left.source_as_of != right.source_as_of:
        reasons.append("source_as_of_changed")
    if left.net != right.net or left.income != right.income or left.expense != right.expense:
        reasons.append("totals_changed")
    if left.unconfirmed_item_ids != right.unconfirmed_item_ids:
        reasons.append("unconfirmed_changed")
    if left.digest != right.digest and not reasons:
        reasons.append("report_digest_changed")
    return CloseDiff(
        period=left.period,
        from_revision=left.close_revision,
        to_revision=right.close_revision,
        reasons=tuple(reasons),
        from_digest=left.digest,
        to_digest=right.digest,
        from_net=left.net,
        to_net=right.net,
        from_dataset_revision=left.dataset_revision,
        to_dataset_revision=right.dataset_revision,
        from_rules_policy=left.rules_policy,
        to_rules_policy=right.rules_policy,
        from_unconfirmed_count=len(left.unconfirmed_item_ids),
        to_unconfirmed_count=len(right.unconfirmed_item_ids),
    )


def require_source_as_of(value: str) -> str:
    """Require an ISO calendar date as the source as-of marker."""
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise CloseError("Source as-of must be an ISO calendar date.") from error
    iso = parsed.isoformat()
    if iso != value:
        raise CloseError("Source as-of must be an ISO calendar date.")
    return iso
