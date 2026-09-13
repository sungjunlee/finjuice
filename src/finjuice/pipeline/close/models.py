"""Immutable records for revision-based month close."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

CloseAction = Literal["closed", "reopened", "reclosed", "retried", "restored"]
PeriodState = Literal["open", "closed", "reopened"]
CloseResultState = Literal["closed", "closed_with_unconfirmed"]


@dataclass(frozen=True)
class CloseLine:
    """One privacy-safe close line captured at freeze time."""

    line_id: str
    amount: str
    category: str

    def to_dict(self) -> dict[str, str]:
        """Serialize this line without numeric floats."""
        return {
            "line_id": self.line_id,
            "amount": self.amount,
            "category": self.category,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CloseLine:
        """Parse one stored close line."""
        return cls(
            line_id=str(payload["line_id"]),
            amount=str(payload["amount"]),
            category=str(payload["category"]),
        )


@dataclass(frozen=True)
class CloseSnapshot:
    """Inputs frozen at close time. Later live data cannot mutate this."""

    period: str
    dataset_revision: int
    rules_policy: str
    calculation_policy: str
    source_as_of: str
    lines: tuple[CloseLine, ...]
    unconfirmed_item_ids: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """Serialize the frozen close inputs."""
        return {
            "period": self.period,
            "dataset_revision": self.dataset_revision,
            "rules_policy": self.rules_policy,
            "calculation_policy": self.calculation_policy,
            "source_as_of": self.source_as_of,
            "lines": [line.to_dict() for line in self.lines],
            "unconfirmed_item_ids": list(self.unconfirmed_item_ids),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CloseSnapshot:
        """Parse stored close inputs."""
        raw_lines = payload.get("lines") or []
        raw_unconfirmed = payload.get("unconfirmed_item_ids") or []
        return cls(
            period=str(payload["period"]),
            dataset_revision=int(payload["dataset_revision"]),
            rules_policy=str(payload["rules_policy"]),
            calculation_policy=str(payload["calculation_policy"]),
            source_as_of=str(payload["source_as_of"]),
            lines=tuple(CloseLine.from_dict(line) for line in raw_lines),
            unconfirmed_item_ids=tuple(str(item) for item in raw_unconfirmed),
        )


@dataclass(frozen=True)
class CloseReport:
    """Deterministic report produced from one frozen close revision."""

    period: str
    close_revision: int
    dataset_revision: int
    rules_policy: str
    calculation_policy: str
    source_as_of: str
    income: str
    expense: str
    net: str
    line_count: int
    digest: str
    unconfirmed_item_ids: tuple[str, ...]
    state: CloseResultState

    def to_dict(self) -> dict[str, Any]:
        """Serialize the frozen report."""
        return {
            "period": self.period,
            "close_revision": self.close_revision,
            "dataset_revision": self.dataset_revision,
            "rules_policy": self.rules_policy,
            "calculation_policy": self.calculation_policy,
            "source_as_of": self.source_as_of,
            "income": self.income,
            "expense": self.expense,
            "net": self.net,
            "line_count": self.line_count,
            "digest": self.digest,
            "unconfirmed_item_ids": list(self.unconfirmed_item_ids),
            "state": self.state,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CloseReport:
        """Parse a stored close report."""
        return cls(
            period=str(payload["period"]),
            close_revision=int(payload["close_revision"]),
            dataset_revision=int(payload["dataset_revision"]),
            rules_policy=str(payload["rules_policy"]),
            calculation_policy=str(payload["calculation_policy"]),
            source_as_of=str(payload["source_as_of"]),
            income=str(payload["income"]),
            expense=str(payload["expense"]),
            net=str(payload["net"]),
            line_count=int(payload["line_count"]),
            digest=str(payload["digest"]),
            unconfirmed_item_ids=tuple(
                str(item) for item in payload.get("unconfirmed_item_ids") or []
            ),
            state=payload["state"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class CloseRevisionRecord:
    """One immutable close revision plus its current period-state flag."""

    close_revision: int
    snapshot: CloseSnapshot
    report: CloseReport
    period_state: Literal["closed", "reopened"]

    def to_dict(self) -> dict[str, Any]:
        """Serialize one stored revision."""
        return {
            "close_revision": self.close_revision,
            "period_state": self.period_state,
            "snapshot": self.snapshot.to_dict(),
            "report": self.report.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CloseRevisionRecord:
        """Parse one stored revision."""
        return cls(
            close_revision=int(payload["close_revision"]),
            snapshot=CloseSnapshot.from_dict(payload["snapshot"]),
            report=CloseReport.from_dict(payload["report"]),
            period_state=payload["period_state"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class CloseEvent:
    """One append-only close history event."""

    event_id: str
    period: str
    close_revision: int
    action: CloseAction
    at: str
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize one history event without financial payloads."""
        return {
            "event_id": self.event_id,
            "period": self.period,
            "close_revision": self.close_revision,
            "action": self.action,
            "at": self.at,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> CloseEvent:
        """Parse one stored history event."""
        reason = payload.get("reason")
        return cls(
            event_id=str(payload["event_id"]),
            period=str(payload["period"]),
            close_revision=int(payload["close_revision"]),
            action=payload["action"],  # type: ignore[arg-type]
            at=str(payload["at"]),
            reason=None if reason is None else str(reason),
        )


@dataclass(frozen=True)
class CloseStatus:
    """Current close status for a period, including unconfirmed display."""

    period: str
    period_state: PeriodState
    current_revision: int | None
    result_state: CloseResultState | None
    unconfirmed_item_ids: tuple[str, ...]
    has_unconfirmed: bool
    dataset_revision: int | None
    rules_policy: str | None
    calculation_policy: str | None
    source_as_of: str | None
    report_digest: str | None

    @property
    def unconfirmed_label(self) -> str:
        """Return an explicit unconfirmed marker for display."""
        if not self.has_unconfirmed:
            return "none"
        return f"unconfirmed:{len(self.unconfirmed_item_ids)}"


@dataclass(frozen=True)
class CloseDiff:
    """Explainable difference between two close revisions of one period."""

    period: str
    from_revision: int
    to_revision: int
    reasons: tuple[str, ...]
    from_digest: str
    to_digest: str
    from_net: str
    to_net: str
    from_dataset_revision: int
    to_dataset_revision: int
    from_rules_policy: str
    to_rules_policy: str
    from_unconfirmed_count: int
    to_unconfirmed_count: int
