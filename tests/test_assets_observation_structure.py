"""Synthetic tests for asset observation structure (issue #443 M1)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from finjuice.pipeline.assets import (
    CorrectionOp,
    EvaluationQuery,
    FxBasis,
    InclusionAssertion,
    MeaningChangeset,
    Measure,
    MoneyAmount,
    Observation,
    ObservationBundle,
    ObservationLifecycle,
    ObservationReport,
    ObservationSubject,
    ObservationTime,
    RevisionConflictError,
    Source,
    apply_changeset,
    evaluate_observations,
)
from finjuice.pipeline.assets.models import MeasureKind, ScopeState, SourceKind
from finjuice.pipeline.assets.money import parse_decimal


@dataclass(frozen=True)
class _Spec:
    observation_id: str
    account_id: str
    kind: MeasureKind
    amount: str
    as_of: str
    collected_at: str
    scope: ScopeState = "complete"
    source: SourceKind = "institution_export"
    resource_id: str | None = None
    currency: str = "KRW"
    confirmation: str = "unconfirmed"
    supersedes_id: str | None = None
    quantity: str | None = None
    fx: FxBasis | None = None


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def _obs(spec: _Spec) -> Observation:
    quantity = parse_decimal(spec.quantity) if spec.quantity is not None else None
    amount = None
    if spec.kind != "holding_quantity":
        amount = MoneyAmount(amount=parse_decimal(spec.amount), currency=spec.currency)
    return Observation(
        observation_id=spec.observation_id,
        subject=ObservationSubject(account_id=spec.account_id, resource_id=spec.resource_id),
        measure=Measure(kind=spec.kind, amount=amount, quantity=quantity, fx=spec.fx),
        source=Source(kind=spec.source, artifact_id=spec.observation_id),
        time=ObservationTime(
            as_of=date.fromisoformat(spec.as_of),
            collected_at=_dt(spec.collected_at),
        ),
        lifecycle=ObservationLifecycle(
            scope_state=spec.scope,
            confirmation_state=spec.confirmation,  # type: ignore[arg-type]
            supersedes_id=spec.supersedes_id,
        ),
    )


def _query(as_of: str, currency: str = "KRW") -> EvaluationQuery:
    return EvaluationQuery(as_of=date.fromisoformat(as_of), valuation_currency=currency)


def _report(observations: list[Observation], as_of: str, **kwargs: object) -> ObservationReport:
    bundle = ObservationBundle(observations=tuple(observations), **kwargs)  # type: ignore[arg-type]
    return evaluate_observations(bundle, _query(as_of))


def test_partial_screenshot_does_not_replace_newer_complete() -> None:
    complete = _obs(
        _Spec("c1", "acct-broker", "balance", "1000000", "2026-09-01", "2026-09-02T00:00:00")
    )
    partial = _obs(
        _Spec(
            "p1",
            "acct-broker",
            "balance",
            "800000",
            "2026-08-15",
            "2026-09-10T00:00:00",
            scope="partial",
            source="screenshot",
        )
    )

    report = _report([complete, partial], "2026-09-10")

    assert report.current_ids == ("c1",)
    assert "p1" in report.evidence_ids
    assert report.confirmed_total == Decimal("1000000")
    assert any(issue.kind == "partial_does_not_supersede" for issue in report.issues)


def test_later_partial_same_as_of_does_not_overwrite_complete() -> None:
    complete = _obs(
        _Spec("c1", "acct-broker", "balance", "500000", "2026-09-01", "2026-09-01T09:00:00")
    )
    partial = _obs(
        _Spec(
            "p1",
            "acct-broker",
            "balance",
            "1",
            "2026-09-01",
            "2026-09-01T18:00:00",
            scope="partial",
            source="screenshot",
        )
    )

    report = _report([complete, partial], "2026-09-01")

    assert report.current_ids == ("c1",)
    assert report.confirmed_total == Decimal("500000")


def test_unconfirmed_supersession_does_not_replace_current_view() -> None:
    original = _obs(
        _Spec("c1", "acct-bank", "balance", "200000", "2026-09-01", "2026-09-01T00:00:00")
    )
    newer = _obs(
        _Spec(
            "c2",
            "acct-bank",
            "balance",
            "250000",
            "2026-09-10",
            "2026-09-10T00:00:00",
            supersedes_id="c1",
        )
    )

    report = _report([original, newer], "2026-09-10")

    assert report.current_ids == ("c1",)
    assert any(issue.kind == "unconfirmed_supersession" for issue in report.issues)


def test_confirmed_supersession_changeset_replaces_current_view() -> None:
    original = _obs(
        _Spec("c1", "acct-bank", "balance", "200000", "2026-09-01", "2026-09-01T00:00:00")
    )
    newer = _obs(
        _Spec(
            "c2",
            "acct-bank",
            "balance",
            "250000",
            "2026-09-10",
            "2026-09-10T00:00:00",
            supersedes_id="c1",
        )
    )
    bundle = ObservationBundle(observations=(original, newer))
    updated = apply_changeset(
        bundle,
        MeaningChangeset(
            changeset_id="cs-1",
            expected_revision=0,
            reason="user confirmed later complete export",
            operations=(CorrectionOp(kind="confirm_supersession", observation_id="c2"),),
        ),
    )

    assert original.lifecycle.confirmation_state == "unconfirmed"
    assert newer.lifecycle.confirmation_state == "unconfirmed"
    report = evaluate_observations(updated, _query("2026-09-10"))
    assert report.current_ids == ("c2",)
    assert report.revision == 1
    assert report.confirmed_total == Decimal("250000")


def test_summary_holdings_are_not_double_counted() -> None:
    summary = _obs(
        _Spec("s1", "acct-broker", "balance", "3000000", "2026-09-01", "2026-09-01T00:00:00")
    )
    holding = _obs(
        _Spec(
            "h1",
            "acct-broker",
            "valuation",
            "3000000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            resource_id="res-spy",
        )
    )
    assertion = InclusionAssertion(
        assertion_id="inc-1",
        kind="summary_contains_holdings",
        container_id="s1",
        member_id="h1",
        review_state="confirmed",
        reason="account summary already includes holdings",
    )

    report = evaluate_observations(
        ObservationBundle(observations=(summary, holding), inclusions=(assertion,)),
        _query("2026-09-01"),
    )
    exclusion = report.exclusion_for("h1")

    assert report.confirmed_total == Decimal("3000000")
    assert exclusion is not None
    assert exclusion.reason == "included_in_summary"
    assert exclusion.assertion_id == "inc-1"


def test_unreviewed_inclusion_excludes_member_and_reports_issue() -> None:
    summary = _obs(
        _Spec("s1", "acct-broker", "balance", "2000000", "2026-09-01", "2026-09-01T00:00:00")
    )
    holding = _obs(
        _Spec(
            "h1",
            "acct-broker",
            "valuation",
            "2000000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            resource_id="res-spy",
        )
    )
    assertion = InclusionAssertion(
        assertion_id="inc-pending",
        kind="summary_contains_holdings",
        container_id="s1",
        member_id="h1",
    )

    report = evaluate_observations(
        ObservationBundle(observations=(summary, holding), inclusions=(assertion,)),
        _query("2026-09-01"),
    )
    exclusion = report.exclusion_for("h1")

    assert report.confirmed_total == Decimal("2000000")
    assert exclusion is not None
    assert exclusion.reason == "unreviewed_inclusion"
    assert any(issue.kind == "unreviewed_inclusion" for issue in report.issues)


def test_unresolved_summary_holdings_overlap_is_excluded_with_reason() -> None:
    summary = _obs(
        _Spec("s1", "acct-broker", "balance", "1500000", "2026-09-01", "2026-09-01T00:00:00")
    )
    holding = _obs(
        _Spec(
            "h1",
            "acct-broker",
            "valuation",
            "1500000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            resource_id="res-qqq",
        )
    )

    report = _report([summary, holding], "2026-09-01")
    exclusion = report.exclusion_for("h1")

    assert report.confirmed_total == Decimal("1500000")
    assert exclusion is not None
    assert exclusion.reason == "unresolved_summary_holdings_overlap"
    assert any(issue.kind == "unresolved_overlap" for issue in report.issues)


def test_manual_and_institution_balances_are_not_double_counted() -> None:
    bank = _obs(_Spec("b1", "acct-bank", "balance", "400000", "2026-09-01", "2026-09-01T00:00:00"))
    manual = _obs(
        _Spec(
            "m1",
            "acct-bank",
            "balance",
            "400000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            source="manual",
        )
    )

    report = _report([bank, manual], "2026-09-01")
    exclusion = report.exclusion_for("m1")

    assert "b1" in report.current_ids
    assert "m1" in report.current_ids
    assert report.confirmed_total == Decimal("400000")
    assert exclusion is not None
    assert exclusion.reason == "unresolved_manual_institution_overlap"


def test_rejected_overlap_counts_both_independent_balances() -> None:
    bank = _obs(_Spec("b1", "acct-bank", "balance", "100000", "2026-09-01", "2026-09-01T00:00:00"))
    cash = _obs(
        _Spec(
            "m1",
            "acct-cash",
            "balance",
            "50000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            source="manual",
        )
    )
    assertion = InclusionAssertion(
        assertion_id="inc-2",
        kind="manual_overlaps_institution",
        container_id="b1",
        member_id="m1",
        review_state="rejected",
        reason="manual cash is a different envelope",
    )

    report = evaluate_observations(
        ObservationBundle(observations=(bank, cash), inclusions=(assertion,)),
        _query("2026-09-01"),
    )

    assert report.exclusion_for("m1") is None
    assert report.confirmed_total == Decimal("150000")


def test_valuation_change_is_not_cash_flow() -> None:
    first = _obs(
        _Spec(
            "v1",
            "acct-broker",
            "valuation",
            "1000000",
            "2026-08-01",
            "2026-08-01T00:00:00",
            resource_id="res-spy",
        )
    )
    second = _obs(
        _Spec(
            "v2",
            "acct-broker",
            "valuation",
            "1200000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            resource_id="res-spy",
        )
    )
    inflow = _obs(
        _Spec(
            "c1",
            "acct-bank",
            "cash_movement",
            "50000",
            "2026-09-01",
            "2026-09-01T00:00:00",
        )
    )

    report = _report([first, second, inflow], "2026-09-01")

    assert report.cash_flow_total == Decimal("50000")
    assert report.valuation_change_total == Decimal("200000")
    assert report.confirmed_total == Decimal("1200000")
    assert report.cash_flow_total != report.valuation_change_total


def test_expected_inflow_and_quantity_are_not_net_worth_or_cash() -> None:
    expected = _obs(
        _Spec(
            "e1",
            "acct-bank",
            "expected_inflow",
            "90000",
            "2026-09-30",
            "2026-09-01T00:00:00",
        )
    )
    quantity = _obs(
        _Spec(
            "q1",
            "acct-broker",
            "holding_quantity",
            "0",
            "2026-09-01",
            "2026-09-01T00:00:00",
            resource_id="res-spy",
            quantity="10",
        )
    )

    report = _report([expected, quantity], "2026-09-30")
    kinds = {line.observation_id: line.contribution for line in report.lines}

    assert kinds["e1"] == "expected"
    assert kinds["q1"] == "quantity_only"
    assert report.confirmed_total == Decimal("0")
    assert report.cash_flow_total == Decimal("0")


def test_conflicts_gaps_and_stale_observations_are_reported() -> None:
    first = _obs(_Spec("c1", "acct-bank", "balance", "100000", "2026-09-01", "2026-09-01T09:00:00"))
    second = _obs(
        _Spec("c2", "acct-bank", "balance", "180000", "2026-09-01", "2026-09-01T10:00:00")
    )
    older = _obs(
        _Spec("c0", "acct-broker", "balance", "900000", "2026-08-01", "2026-08-01T00:00:00")
    )
    newer = _obs(
        _Spec("c3", "acct-broker", "balance", "950000", "2026-09-01", "2026-09-01T00:00:00")
    )

    report = evaluate_observations(
        ObservationBundle(
            observations=(first, second, older, newer),
            known_targets=("acct-bank", "acct-broker", "acct-missing"),
        ),
        _query("2026-09-01"),
    )
    kinds = {issue.kind for issue in report.issues}

    assert "conflict" in kinds
    assert "gap" in kinds
    assert "stale" in kinds
    assert report.confirmed_total == Decimal("950000")


def test_reclassify_measure_requires_new_observation_id() -> None:
    cashish = _obs(
        _Spec(
            "v1",
            "acct-broker",
            "cash_movement",
            "1000000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            resource_id="res-spy",
        )
    )
    replacement = _obs(
        _Spec(
            "v1-fix",
            "acct-broker",
            "valuation",
            "1000000",
            "2026-09-01",
            "2026-09-01T00:00:00",
            resource_id="res-spy",
            confirmation="confirmed",
            supersedes_id="v1",
        )
    )
    bundle = ObservationBundle(observations=(cashish,))

    with pytest.raises(ValueError, match="new observation id"):
        apply_changeset(
            bundle,
            MeaningChangeset(
                changeset_id="cs-bad",
                expected_revision=0,
                reason="cannot rewrite the original row",
                operations=(
                    CorrectionOp(
                        kind="reclassify_measure",
                        observation_id="v1",
                        replacement=cashish,
                    ),
                ),
            ),
        )

    updated = apply_changeset(
        bundle,
        MeaningChangeset(
            changeset_id="cs-2",
            expected_revision=0,
            reason="valuation was not a cash movement",
            operations=(
                CorrectionOp(
                    kind="reclassify_measure",
                    observation_id="v1",
                    replacement=replacement,
                ),
            ),
        ),
    )
    report = evaluate_observations(updated, _query("2026-09-01"))

    assert cashish.measure.kind == "cash_movement"
    assert "v1" in report.evidence_ids
    assert report.current_ids == ("v1-fix",)
    assert report.cash_flow_total == Decimal("0")
    assert report.confirmed_total == Decimal("1000000")


def test_stale_expected_revision_is_rejected() -> None:
    item = _obs(_Spec("c1", "acct-bank", "balance", "1", "2026-09-01", "2026-09-01T00:00:00"))
    bundle = ObservationBundle(observations=(item,), revision=2)

    with pytest.raises(RevisionConflictError):
        apply_changeset(
            bundle,
            MeaningChangeset(
                changeset_id="cs-3",
                expected_revision=0,
                reason="stale",
                operations=(CorrectionOp(kind="reject_observation", observation_id="c1"),),
            ),
        )


def test_revision_explanation_keeps_original_currency_and_fx_policy() -> None:
    fx = FxBasis(
        quote_currency="KRW",
        rate=parse_decimal("1300"),
        rate_as_of=date(2026, 9, 1),
        policy_id="fx.v1",
    )
    usd = _obs(
        _Spec(
            "u1",
            "acct-usd",
            "balance",
            "10",
            "2026-09-01",
            "2026-09-01T00:00:00",
            currency="USD",
            fx=fx,
        )
    )

    report = evaluate_observations(
        ObservationBundle(observations=(usd,)),
        _query("2026-09-01"),
    )
    line = report.lines[0]

    assert line.original == MoneyAmount(amount=Decimal("10"), currency="USD")
    assert line.valued == MoneyAmount(amount=Decimal("13000"), currency="KRW")
    assert line.fx_policy_id == "fx.v1"
    assert report.confirmed_total == Decimal("13000")


def test_unlike_currency_without_fx_is_not_summed() -> None:
    usd = _obs(
        _Spec(
            "u1",
            "acct-usd",
            "balance",
            "10",
            "2026-09-01",
            "2026-09-01T00:00:00",
            currency="USD",
        )
    )

    report = _report([usd], "2026-09-01")

    assert report.confirmed_total is None
    assert any(issue.kind == "missing_fx_basis" for issue in report.issues)


def test_parse_decimal_rejects_float() -> None:
    with pytest.raises(ValueError, match="exact decimals"):
        parse_decimal(1.25)
