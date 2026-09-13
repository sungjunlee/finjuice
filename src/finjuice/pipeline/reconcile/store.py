"""SQLite source/evidence relations for N:M reconcile links.

Occurrence tables preserve the first write of each id. Match decisions are
stored separately so confirm/withdraw never rewrite source amounts or rows.
This sidecar does not alter the authoritative storage schema.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from pathlib import Path

from finjuice.pipeline.reconcile.decisions import confirm_match, withdraw_match
from finjuice.pipeline.reconcile.engine import DEFAULT_WINDOW_DAYS, reconcile
from finjuice.pipeline.reconcile.models import (
    EvidenceItem,
    MatchGroup,
    PaymentItem,
    ReconcileReport,
)
from finjuice.pipeline.reconcile.money import parse_money

_SCHEMA = """
CREATE TABLE IF NOT EXISTS evidence_occurrences (
    evidence_id TEXT PRIMARY KEY NOT NULL,
    occurred_on TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL,
    source_kind TEXT NOT NULL,
    order_id TEXT
);

CREATE TABLE IF NOT EXISTS payment_occurrences (
    payment_id TEXT PRIMARY KEY NOT NULL,
    occurred_on TEXT NOT NULL,
    amount TEXT NOT NULL,
    currency TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS match_groups (
    group_key TEXT PRIMARY KEY NOT NULL,
    evidence_ids_json TEXT NOT NULL,
    payment_ids_json TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK (status IN ('matched', 'partial', 'unmatched')),
    residual TEXT NOT NULL,
    reason TEXT NOT NULL,
    decision TEXT NOT NULL
        CHECK (decision IN ('proposed', 'confirmed', 'withdrawn'))
);
"""


def _group_key(group: MatchGroup) -> str:
    return f"{','.join(group.evidence_ids)}|{','.join(group.payment_ids)}"


class ReconcileStore:
    """Sidecar SQLite file holding evidence/payment occurrences and match links."""

    def __init__(self, path: Path) -> None:
        if path.is_dir():
            raise ValueError("Reconcile store path must be a file.")
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def upsert_evidence(self, items: Sequence[EvidenceItem]) -> None:
        """Insert new evidence occurrences. Existing ids keep their first row."""
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO evidence_occurrences (
                    evidence_id, occurred_on, amount, currency, source_kind, order_id
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        item.evidence_id,
                        item.occurred_on.isoformat(),
                        str(item.amount),
                        item.currency,
                        item.source_kind,
                        item.order_id,
                    )
                    for item in items
                ],
            )

    def upsert_payments(self, items: Sequence[PaymentItem]) -> None:
        """Insert payment snapshots. Existing ids keep their first row."""
        with self._connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO payment_occurrences (
                    payment_id, occurred_on, amount, currency
                ) VALUES (?, ?, ?, ?)
                """,
                [
                    (
                        item.payment_id,
                        item.occurred_on.isoformat(),
                        str(item.amount),
                        item.currency,
                    )
                    for item in items
                ],
            )

    def load_evidence(self) -> list[EvidenceItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT evidence_id, occurred_on, amount, currency, source_kind, order_id
                FROM evidence_occurrences
                ORDER BY occurred_on, evidence_id
                """
            ).fetchall()
        return [
            EvidenceItem(
                evidence_id=str(row["evidence_id"]),
                occurred_on=date.fromisoformat(str(row["occurred_on"])),
                amount=parse_money(row["amount"]),
                currency=str(row["currency"]),
                source_kind=str(row["source_kind"]),  # type: ignore[arg-type]
                order_id=None if row["order_id"] is None else str(row["order_id"]),
            )
            for row in rows
        ]

    def load_payments(self) -> list[PaymentItem]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT payment_id, occurred_on, amount, currency
                FROM payment_occurrences
                ORDER BY occurred_on, payment_id
                """
            ).fetchall()
        return [
            PaymentItem(
                payment_id=str(row["payment_id"]),
                occurred_on=date.fromisoformat(str(row["occurred_on"])),
                amount=parse_money(row["amount"]),
                currency=str(row["currency"]),
            )
            for row in rows
        ]

    def load_groups(self) -> tuple[MatchGroup, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT evidence_ids_json, payment_ids_json, status, residual, reason, decision
                FROM match_groups
                ORDER BY group_key
                """
            ).fetchall()
        return tuple(_row_to_group(row) for row in rows)

    def load_preserved(self) -> tuple[MatchGroup, ...]:
        return tuple(
            group for group in self.load_groups() if group.decision in {"confirmed", "withdrawn"}
        )

    def save_groups(self, groups: Sequence[MatchGroup]) -> None:
        """Replace proposed links only. Confirmed/withdrawn rows stay put."""
        with self._connect() as connection:
            connection.execute("DELETE FROM match_groups WHERE decision = ?", ("proposed",))
            for group in groups:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO match_groups (
                        group_key, evidence_ids_json, payment_ids_json,
                        status, residual, reason, decision
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _group_key(group),
                        json.dumps(list(group.evidence_ids), ensure_ascii=False),
                        json.dumps(list(group.payment_ids), ensure_ascii=False),
                        group.status,
                        str(group.residual),
                        group.reason,
                        group.decision,
                    ),
                )

    def confirm(self, group: MatchGroup) -> MatchGroup:
        """Persist a confirmed decision without rewriting occurrence rows."""
        locked = confirm_match(group)
        self._upsert_decision(locked)
        return locked

    def withdraw(self, group: MatchGroup) -> MatchGroup:
        """Persist a withdrawn decision without rewriting occurrence rows."""
        locked = withdraw_match(group)
        self._upsert_decision(locked)
        return locked

    def record_and_reconcile(
        self,
        evidence: Sequence[EvidenceItem],
        payments: Sequence[PaymentItem],
        *,
        window_days: int = DEFAULT_WINDOW_DAYS,
    ) -> ReconcileReport:
        """Upsert occurrences, match, and save links without duplicating ids."""
        self.upsert_evidence(evidence)
        self.upsert_payments(payments)
        report = reconcile(
            self.load_evidence(),
            self.load_payments(),
            window_days=window_days,
            preserved=self.load_preserved(),
        )
        self.save_groups(report.groups)
        return report

    def _upsert_decision(self, group: MatchGroup) -> None:
        with self._connect() as connection:
            updated = connection.execute(
                "UPDATE match_groups SET decision = ? WHERE group_key = ?",
                (group.decision, _group_key(group)),
            )
            if updated.rowcount:
                return
            connection.execute(
                """
                INSERT INTO match_groups (
                    group_key, evidence_ids_json, payment_ids_json,
                    status, residual, reason, decision
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _group_key(group),
                    json.dumps(list(group.evidence_ids), ensure_ascii=False),
                    json.dumps(list(group.payment_ids), ensure_ascii=False),
                    group.status,
                    str(group.residual),
                    group.reason,
                    group.decision,
                ),
            )


def _row_to_group(row: sqlite3.Row) -> MatchGroup:
    evidence_ids = tuple(str(item) for item in json.loads(str(row["evidence_ids_json"])))
    payment_ids = tuple(str(item) for item in json.loads(str(row["payment_ids_json"])))
    return MatchGroup(
        evidence_ids=evidence_ids,
        payment_ids=payment_ids,
        status=str(row["status"]),  # type: ignore[arg-type]
        residual=Decimal(str(row["residual"])),
        reason=str(row["reason"]),
        decision=str(row["decision"]),  # type: ignore[arg-type]
    )
