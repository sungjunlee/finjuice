"""Close, reopen, retry, restore, and status operations."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from finjuice.pipeline.close.errors import CloseLockedError, CloseStateError
from finjuice.pipeline.close.ledger import (
    CloseStore,
    copy_close_ledger,
    validate_period,
    validate_store_root,
)
from finjuice.pipeline.close.models import (
    CloseAction,
    CloseEvent,
    CloseLine,
    CloseReport,
    CloseRevisionRecord,
    CloseSnapshot,
    CloseStatus,
)
from finjuice.pipeline.close.report import (
    canonical_amount,
    compute_close_report,
    ordered_lines,
    require_source_as_of,
)


def normalize_snapshot(snapshot: CloseSnapshot) -> CloseSnapshot:
    """Canonicalize close inputs so identical meaning compares equal."""
    period = validate_period(snapshot.period)
    if isinstance(snapshot.dataset_revision, bool) or snapshot.dataset_revision < 0:
        raise CloseStateError("Dataset revision must be a non-negative integer.")
    seen: set[str] = set()
    lines: list[CloseLine] = []
    for line in ordered_lines(snapshot.lines):
        if line.line_id in seen:
            raise CloseStateError("Close line ids must be unique.")
        seen.add(line.line_id)
        lines.append(
            CloseLine(
                line_id=line.line_id,
                amount=canonical_amount(line.amount),
                category=line.category,
            )
        )
    unconfirmed = tuple(sorted(snapshot.unconfirmed_item_ids))
    return CloseSnapshot(
        period=period,
        dataset_revision=snapshot.dataset_revision,
        rules_policy=snapshot.rules_policy,
        calculation_policy=snapshot.calculation_policy,
        source_as_of=require_source_as_of(snapshot.source_as_of),
        lines=tuple(lines),
        unconfirmed_item_ids=unconfirmed,
    )


def close_month(
    store: CloseStore,
    snapshot: CloseSnapshot,
    *,
    occurred_at: str | None = None,
) -> CloseRevisionRecord:
    """Freeze a month close without silently replacing a prior revision.

    The same snapshot is idempotent. A different snapshot on a still-closed
    period is rejected so late input or rule changes cannot overwrite history.
    After reopen, a later snapshot becomes the next revision.
    """
    snapshot = normalize_snapshot(snapshot)
    current = store.current(snapshot.period)
    if current is None:
        return _commit_new(store, snapshot, action="closed", occurred_at=occurred_at)
    if current.period_state == "closed" and current.snapshot == snapshot:
        return _record_retry(store, current, occurred_at)
    if current.period_state == "closed":
        raise CloseLockedError(
            "A closed month cannot be overwritten by later input or rule changes."
        )
    if current.period_state == "reopened":
        return _commit_new(store, snapshot, action="reclosed", occurred_at=occurred_at)
    raise CloseStateError("Close period is in an unexpected state.")


def retry_close(
    store: CloseStore,
    snapshot: CloseSnapshot,
    *,
    occurred_at: str | None = None,
) -> CloseRevisionRecord:
    """Retry a close. Matching frozen input keeps the same revision in history."""
    return close_month(store, snapshot, occurred_at=occurred_at)


def reopen_month(
    store: CloseStore,
    period: str,
    *,
    occurred_at: str | None = None,
    reason: str | None = None,
) -> CloseRevisionRecord:
    """Reopen a closed month so a later revision can be written."""
    current = store.current(period)
    if current is None:
        raise CloseStateError("An open month cannot be reopened.")
    if current.period_state != "closed":
        raise CloseStateError("Only a closed month can be reopened.")
    updated = replace(current, period_state="reopened")
    event = _event(
        period=updated.snapshot.period,
        close_revision=updated.close_revision,
        action="reopened",
        occurred_at=occurred_at,
        reason=reason,
    )
    store.update_current(updated, event)
    return updated


def regenerate_close_report(
    store: CloseStore,
    period: str,
    close_revision: int,
) -> CloseReport:
    """Rebuild the report for one frozen close revision from stored inputs."""
    record = store.get_revision(period, close_revision)
    return compute_close_report(record.snapshot, close_revision=close_revision)


def close_status(store: CloseStore, period: str) -> CloseStatus:
    """Return the current close state, including an explicit unconfirmed marker."""
    key = validate_period(period)
    current = store.current(key)
    if current is None:
        return CloseStatus(
            period=key,
            period_state="open",
            current_revision=None,
            result_state=None,
            unconfirmed_item_ids=(),
            has_unconfirmed=False,
            dataset_revision=None,
            rules_policy=None,
            calculation_policy=None,
            source_as_of=None,
            report_digest=None,
        )
    report = current.report
    return CloseStatus(
        period=key,
        period_state=current.period_state,
        current_revision=current.close_revision,
        result_state=report.state,
        unconfirmed_item_ids=report.unconfirmed_item_ids,
        has_unconfirmed=bool(report.unconfirmed_item_ids),
        dataset_revision=report.dataset_revision,
        rules_policy=report.rules_policy,
        calculation_policy=report.calculation_policy,
        source_as_of=report.source_as_of,
        report_digest=report.digest,
    )


def backup_close_ledger(store: CloseStore, destination: Path) -> Path:
    """Copy the close ledger into a backup directory."""
    return copy_close_ledger(store.root, validate_store_root(destination))


def restore_close_ledger(
    backup: Path,
    store: CloseStore,
    *,
    occurred_at: str | None = None,
) -> tuple[CloseEvent, ...]:
    """Restore a close ledger from backup and keep the prior event history."""
    copy_close_ledger(backup, store.root)
    store.reload()
    history = store.events()
    if not history:
        raise CloseStateError("Restored close ledger has no revisions.")
    last = history[-1]
    store.append_event(
        _event(
            period=last.period,
            close_revision=last.close_revision,
            action="restored",
            occurred_at=occurred_at,
            reason="backup_restore",
        )
    )
    return store.events()


def _commit_new(
    store: CloseStore,
    snapshot: CloseSnapshot,
    *,
    action: CloseAction,
    occurred_at: str | None,
) -> CloseRevisionRecord:
    close_revision = store.next_revision(snapshot.period)
    report = compute_close_report(snapshot, close_revision=close_revision)
    record = CloseRevisionRecord(
        close_revision=close_revision,
        snapshot=snapshot,
        report=report,
        period_state="closed",
    )
    store.commit(
        record,
        _event(
            period=snapshot.period,
            close_revision=close_revision,
            action=action,
            occurred_at=occurred_at,
        ),
    )
    return record


def _record_retry(
    store: CloseStore,
    current: CloseRevisionRecord,
    occurred_at: str | None,
) -> CloseRevisionRecord:
    store.append_event(
        _event(
            period=current.snapshot.period,
            close_revision=current.close_revision,
            action="retried",
            occurred_at=occurred_at,
        )
    )
    return current


def _event(
    *,
    period: str,
    close_revision: int,
    action: CloseAction,
    occurred_at: str | None,
    reason: str | None = None,
) -> CloseEvent:
    timestamp = occurred_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return CloseEvent(
        event_id=str(uuid.uuid4()),
        period=period,
        close_revision=close_revision,
        action=action,
        at=timestamp,
        reason=reason,
    )
