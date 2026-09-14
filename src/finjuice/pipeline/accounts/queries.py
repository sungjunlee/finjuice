"""Period membership and ownership-share checks."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from finjuice.pipeline.accounts.models import DateRange, OwnershipShare

_ONE = Decimal("1")
_ZERO = Decimal("0")


def contains(period: DateRange, as_of: date) -> bool:
    """Return True when ``as_of`` is inside the half-open period."""
    if as_of < period.start:
        return False
    return period.end is None or as_of < period.end


def overlaps(left: DateRange, right: DateRange) -> bool:
    """Return True when two half-open periods overlap."""
    left_end = left.end or date.max
    right_end = right.end or date.max
    return left.start < right_end and right.start < left_end


def shares_on_date(
    shares: Sequence[OwnershipShare],
    account_id: str,
    as_of: date,
) -> tuple[OwnershipShare, ...]:
    """Return confirmed shares for one account on ``as_of``."""
    return tuple(
        share
        for share in shares
        if share.account_id == account_id
        and share.confirmation_state == "confirmed"
        and contains(share.period, as_of)
    )


def share_total(shares: Sequence[OwnershipShare]) -> Decimal:
    """Sum exact shares. Empty input is zero, not inferred as 1."""
    total = _ZERO
    for share in shares:
        total += share.share
    return total


def shares_are_complete(shares: Sequence[OwnershipShare]) -> bool:
    """Return True when confirmed shares on a date sum to exactly 1."""
    return bool(shares) and share_total(shares) == _ONE
