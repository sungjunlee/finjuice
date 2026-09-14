"""Append-only JSON ledger for frozen month-close revisions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from finjuice.pipeline.close.errors import CloseNotFoundError, ClosePathError
from finjuice.pipeline.close.models import CloseEvent, CloseRevisionRecord
from finjuice.pipeline.storage.atomic_files import replace_with_owned_temp

LEDGER_FILENAME = "close-ledger.json"
LEDGER_SCHEMA_VERSION = 1
PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def validate_period(period: str) -> str:
    """Return a YYYY-MM period or raise a path error."""
    if PERIOD_RE.fullmatch(period) is None:
        raise ClosePathError("Close period must be YYYY-MM.")
    return period


def validate_store_root(root: Path) -> Path:
    """Return an absolute close-store root, rejecting symlinks."""
    if root.exists() and root.is_symlink():
        raise ClosePathError("Close store root must not be a symlink.")
    resolved = root.expanduser().absolute()
    if ".." in Path(root).parts:
        raise ClosePathError("Close store root must not contain parent segments.")
    return resolved


def copy_close_ledger(source_root: Path, destination_root: Path) -> Path:
    """Copy the ledger file between store roots without interpreting rows."""
    source = CloseStore(source_root)
    if not source.path.is_file():
        raise CloseNotFoundError("Close ledger backup is missing.")
    destination = CloseStore(destination_root)
    destination.root.mkdir(mode=0o700, parents=True, exist_ok=True)
    _atomic_write(destination.path, source.path.read_bytes())
    return destination.path


class CloseStore:
    """File-backed store for closed month revisions and history events."""

    def __init__(self, root: Path) -> None:
        self.root = validate_store_root(root)
        self.path = self.root / LEDGER_FILENAME
        self._periods: dict[str, dict[int, CloseRevisionRecord]] = {}
        self._current: dict[str, int] = {}
        self._events: list[CloseEvent] = []
        self.reload()

    def reload(self) -> None:
        """Reload revisions and events from disk."""
        self._periods = {}
        self._current = {}
        self._events = []
        if not self.path.exists():
            return
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if int(payload.get("schema_version", 0)) != LEDGER_SCHEMA_VERSION:
            raise ClosePathError("Close ledger schema version is unsupported.")
        for period, body in (payload.get("periods") or {}).items():
            validate_period(period)
            revisions: dict[int, CloseRevisionRecord] = {}
            for raw in body.get("revisions") or []:
                record = CloseRevisionRecord.from_dict(raw)
                revisions[record.close_revision] = record
            self._periods[period] = revisions
            current = body.get("current_revision")
            if current is not None:
                self._current[period] = int(current)
        self._events = [CloseEvent.from_dict(raw) for raw in payload.get("events") or []]

    def current(self, period: str) -> CloseRevisionRecord | None:
        """Return the current revision record for a period, if any."""
        key = validate_period(period)
        revision = self._current.get(key)
        if revision is None:
            return None
        return self.get_revision(key, revision)

    def get_revision(self, period: str, close_revision: int) -> CloseRevisionRecord:
        """Return one frozen revision or raise if missing."""
        key = validate_period(period)
        record = self._periods.get(key, {}).get(close_revision)
        if record is None:
            raise CloseNotFoundError("Close revision was not found.")
        return record

    def next_revision(self, period: str) -> int:
        """Return the next unused close revision for a period."""
        key = validate_period(period)
        existing = self._periods.get(key) or {}
        if not existing:
            return 1
        return max(existing) + 1

    def events(self, period: str | None = None) -> tuple[CloseEvent, ...]:
        """Return history events, optionally filtered to one period."""
        if period is None:
            return tuple(self._events)
        key = validate_period(period)
        return tuple(event for event in self._events if event.period == key)

    def commit(self, record: CloseRevisionRecord, event: CloseEvent) -> None:
        """Persist one revision and history event together."""
        period = validate_period(record.snapshot.period)
        revisions = self._periods.setdefault(period, {})
        revisions[record.close_revision] = record
        self._current[period] = record.close_revision
        self._events.append(event)
        self._save()

    def update_current(self, record: CloseRevisionRecord, event: CloseEvent) -> None:
        """Replace the current revision flag and append a history event."""
        period = validate_period(record.snapshot.period)
        revisions = self._periods.setdefault(period, {})
        revisions[record.close_revision] = record
        self._current[period] = record.close_revision
        self._events.append(event)
        self._save()

    def append_event(self, event: CloseEvent) -> None:
        """Append a history event and persist the ledger."""
        validate_period(event.period)
        self._events.append(event)
        self._save()

    def _save(self) -> None:
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        periods: dict[str, Any] = {}
        for period, revisions in sorted(self._periods.items()):
            periods[period] = {
                "current_revision": self._current.get(period),
                "revisions": [revisions[key].to_dict() for key in sorted(revisions)],
            }
        payload = {
            "schema_version": LEDGER_SCHEMA_VERSION,
            "periods": periods,
            "events": [event.to_dict() for event in self._events],
        }
        encoded = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        _atomic_write(self.path, encoded.encode("utf-8"))


def _atomic_write(path: Path, payload: bytes) -> None:
    replace_with_owned_temp(path, payload)
