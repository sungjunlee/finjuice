"""Retention planning for scheduled backup copies.

The default policy keeps 14 daily, 8 weekly, and 12 monthly copies. Cleanup
never deletes the latest healthy copy or a pinned previous (pre-cutover)
baseline, even when those copies fall outside the numeric windows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from finjuice.pipeline.backup.errors import BackupError

CopyLocation = Literal["local", "off_device"]

DEFAULT_DAILY = 14
DEFAULT_WEEKLY = 8
DEFAULT_MONTHLY = 12


def _require_utc(value: datetime, *, context: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise BackupError(
            f"{context} must be timezone-aware UTC.",
            code="INVALID_ARGS",
        )
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise BackupError(
            f"{context} must be timezone-aware UTC.",
            code="INVALID_ARGS",
        )
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class RetentionPolicy:
    """Numeric GFS windows. Defaults match the published example policy."""

    daily: int = DEFAULT_DAILY
    weekly: int = DEFAULT_WEEKLY
    monthly: int = DEFAULT_MONTHLY

    def __post_init__(self) -> None:
        for name, value in (
            ("daily", self.daily),
            ("weekly", self.weekly),
            ("monthly", self.monthly),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise BackupError(
                    f"Retention {name} window must be a non-negative integer.",
                    code="INVALID_ARGS",
                )


@dataclass(frozen=True)
class BackupCopy:
    """One inventoried backup copy. Paths are omitted from public payloads."""

    copy_id: str
    created_at: datetime
    healthy: bool
    location: CopyLocation = "local"
    pinned: bool = False

    def __post_init__(self) -> None:
        if not self.copy_id:
            raise BackupError("Backup copy_id is required.", code="INVALID_ARGS")
        _require_utc(self.created_at, context="Backup copy created_at")


@dataclass(frozen=True)
class RetentionPlan:
    """Privacy-safe retention decision for one inventory of copies."""

    policy: RetentionPolicy
    keep_ids: tuple[str, ...]
    delete_ids: tuple[str, ...]
    protected_ids: tuple[str, ...]
    latest_healthy_id: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a privacy-safe payload without locations or timestamps."""
        return {
            "delete_count": len(self.delete_ids),
            "keep_count": len(self.keep_ids),
            "latest_healthy_id": self.latest_healthy_id,
            "policy": {
                "daily": self.policy.daily,
                "monthly": self.policy.monthly,
                "weekly": self.policy.weekly,
            },
            "protected_count": len(self.protected_ids),
        }


def _latest_healthy_id(copies: Sequence[BackupCopy]) -> str | None:
    healthy = [copy for copy in copies if copy.healthy]
    if not healthy:
        return None
    newest = max(healthy, key=lambda copy: (copy.created_at, copy.copy_id))
    return newest.copy_id


def _protected_ids(copies: Sequence[BackupCopy], latest_healthy_id: str | None) -> set[str]:
    protected = {copy.copy_id for copy in copies if copy.pinned}
    if latest_healthy_id is not None:
        protected.add(latest_healthy_id)
    return protected


def _slot_keys(created_at: datetime) -> tuple[object, object, object]:
    iso = created_at.isocalendar()
    return created_at.date(), (iso.year, iso.week), (created_at.year, created_at.month)


def _assign_gfs_slots(copies: Sequence[BackupCopy], policy: RetentionPolicy) -> set[str]:
    keep: set[str] = set()
    daily_days: set[object] = set()
    weekly_weeks: set[object] = set()
    monthly_months: set[object] = set()
    ordered = sorted(copies, key=lambda copy: (copy.created_at, copy.copy_id), reverse=True)
    for copy in ordered:
        if not copy.healthy:
            continue
        day, week, month = _slot_keys(copy.created_at)
        assigned = False
        if day not in daily_days and len(daily_days) < policy.daily:
            daily_days.add(day)
            assigned = True
        if week not in weekly_weeks and len(weekly_weeks) < policy.weekly:
            weekly_weeks.add(week)
            assigned = True
        if month not in monthly_months and len(monthly_months) < policy.monthly:
            monthly_months.add(month)
            assigned = True
        if assigned:
            keep.add(copy.copy_id)
    return keep


def plan_retention(
    copies: Sequence[BackupCopy],
    policy: RetentionPolicy | None = None,
) -> RetentionPlan:
    """Return which copies to keep or delete under the GFS policy.

    The latest healthy copy and every pinned previous baseline are always kept.
    Unhealthy copies are eligible for deletion unless they are pinned.
    """
    resolved = policy if policy is not None else RetentionPolicy()
    seen: set[str] = set()
    for copy in copies:
        if copy.copy_id in seen:
            raise BackupError("Duplicate backup copy_id.", code="INVALID_ARGS")
        seen.add(copy.copy_id)
    latest_healthy_id = _latest_healthy_id(copies)
    protected = _protected_ids(copies, latest_healthy_id)
    keep = _assign_gfs_slots(copies, resolved) | protected
    ordered = sorted(copies, key=lambda item: (item.created_at, item.copy_id))
    keep_ids = tuple(copy.copy_id for copy in ordered if copy.copy_id in keep)
    delete_ids = tuple(copy.copy_id for copy in ordered if copy.copy_id not in keep)
    protected_ids = tuple(copy.copy_id for copy in ordered if copy.copy_id in protected)
    return RetentionPlan(
        policy=resolved,
        keep_ids=keep_ids,
        delete_ids=delete_ids,
        protected_ids=protected_ids,
        latest_healthy_id=latest_healthy_id,
    )
