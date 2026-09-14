"""Persist overview facts and typed projections from exact mapping."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from finjuice.pipeline.ingest.exact_overview.models import (
    ExactBalanceObservation,
    ExactCashflowObservation,
    ExactInsuranceRow,
    ExactInvestmentRow,
    ExactLoanRow,
    ExactOverviewFact,
    ExactOverviewMapping,
    MappedField,
    SnapshotDateEvidence,
)
from finjuice.pipeline.storage.sqlite.exact import ExactValue
from finjuice.pipeline.storage.sqlite.exact_import.evidence import (
    PersistSession,
    SourcePlace,
    add_cell_provenance,
    add_issues,
    add_mapper_issues,
    as_issue,
)
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.records import (
    ObservationRecord,
    OverviewBalanceRecord,
    OverviewCashflowRecord,
    OverviewFactRecord,
    OverviewInsuranceRecord,
    OverviewInvestmentRecord,
    OverviewLoanRecord,
    PreservationIssueRecord,
)

FactKey = tuple[str, int, str]


def persist_overview(
    session: PersistSession,
    mapping: ExactOverviewMapping,
) -> dict[str, list[str]]:
    """Write overview facts and supported projections. Skip invented dates."""
    snapshot = mapping.snapshot
    if mapping.status != "mapped" or snapshot.parsed_date is None:
        _persist_mapping_only(session, mapping)
        return {"facts": [], "projections": []}
    observation_id = _add_snapshot_observation(session, snapshot)
    parsed = snapshot.parsed_date
    facts = _persist_facts(session, mapping, observation_id, parsed)
    projections = _persist_projections(session, mapping, observation_id, facts, parsed)
    return {"facts": list(facts.values()), "projections": projections}


def _persist_mapping_only(session: PersistSession, mapping: ExactOverviewMapping) -> None:
    if not mapping.facts:
        return
    for fact in mapping.facts:
        provenance_id = _fact_provenance(session, fact, extra={"typed": False})
        add_mapper_issues(session, provenance_id, fact.issues, sheet_name=fact.sheet_name)


def _add_snapshot_observation(session: PersistSession, snapshot: SnapshotDateEvidence) -> str:
    observation_id = new_entity_id()
    reliable = snapshot.reliable and snapshot.origin in {"explicit", "source_label"}
    effective = snapshot.parsed_date.isoformat() if reliable and snapshot.parsed_date else None
    session.context.add_observation(
        ObservationRecord(
            observation_id=observation_id,
            occurrence_id=session.occurrence_id,
            observed_at=None,
            effective_at=effective,
            collected_at=session.collected_at,
            scope_state="partial",
            confirmation_state="unconfirmed",
        )
    )
    return observation_id


def _persist_facts(
    session: PersistSession,
    mapping: ExactOverviewMapping,
    observation_id: str,
    snapshot_date: date,
) -> dict[FactKey, str]:
    stored: dict[FactKey, str] = {}
    for fact in mapping.facts:
        fact_id = _insert_fact(session, fact, observation_id, snapshot_date)
        stored[(fact.sheet_name, fact.source_row, fact.column)] = fact_id
    return stored


def _insert_fact(
    session: PersistSession,
    fact: ExactOverviewFact,
    observation_id: str,
    snapshot_date: date,
) -> str:
    provenance_id = _fact_provenance(session, fact, extra={"typed": True})
    add_mapper_issues(session, provenance_id, fact.issues, sheet_name=fact.sheet_name)
    numeric_id = _add_number(session, provenance_id, fact.number_value)
    fact_id = new_entity_id()
    value_text, placeholder = _fact_text(fact)
    session.context.add_overview_fact(
        OverviewFactRecord(
            fact_id=fact_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            snapshot_date=snapshot_date.isoformat(),
            sheet_name=fact.sheet_name,
            block_id=fact.block_id or "",
            block_title=fact.block_title or "",
            fact_kind=fact.fact_kind,
            value_type=fact.value_type,
            row_label=fact.row_label,
            column_label=fact.column_label,
            numeric_value_id=numeric_id,
            value_text=value_text,
        )
    )
    if placeholder:
        _placeholder_issue(session, provenance_id, fact)
    return fact_id


def _persist_projections(
    session: PersistSession,
    mapping: ExactOverviewMapping,
    observation_id: str,
    facts: dict[FactKey, str],
    snapshot_date: date,
) -> list[str]:
    ids: list[str] = []
    ids.extend(_persist_balances(session, mapping.balances, observation_id, facts, snapshot_date))
    ids.extend(_persist_cashflows(session, mapping.cashflows, observation_id, facts, snapshot_date))
    ids.extend(_persist_insurance(session, mapping.insurance, observation_id, facts, snapshot_date))
    ids.extend(
        _persist_investments(session, mapping.investments, observation_id, facts, snapshot_date)
    )
    ids.extend(_persist_loans(session, mapping.loans, observation_id, facts, snapshot_date))
    return ids


def _persist_balances(
    session: PersistSession,
    rows: Sequence[ExactBalanceObservation],
    observation_id: str,
    facts: dict[FactKey, str],
    snapshot_date: date,
) -> list[str]:
    ids: list[str] = []
    for row in rows:
        if not row.supported or row.amount.exact_value is None:
            _projection_evidence(session, row, "overview_balance")
            continue
        provenance_id = _projection_provenance(session, row, "overview_balance")
        source_fact_id = _source_fact(facts, row.sheet_name, row.source_row, row.source_column)
        amount_id = _required_value_id(session, provenance_id, row.amount.exact_value)
        balance_id = new_entity_id()
        session.context.add_overview_balance(
            OverviewBalanceRecord(
                balance_id=balance_id,
                observation_id=observation_id,
                provenance_id=provenance_id,
                source_fact_id=source_fact_id,
                amount_value_id=amount_id,
                snapshot_date=snapshot_date.isoformat(),
                side=row.side,
                category=_required_text(row.category),
                item_name=_required_text(row.item_name),
            )
        )
        ids.append(balance_id)
    return ids


def _persist_cashflows(
    session: PersistSession,
    rows: Sequence[ExactCashflowObservation],
    observation_id: str,
    facts: dict[FactKey, str],
    snapshot_date: date,
) -> list[str]:
    ids: list[str] = []
    for row in rows:
        if not row.supported or row.amount.exact_value is None or row.period_month.text is None:
            _projection_evidence(session, row, "overview_cashflow")
            continue
        provenance_id = _projection_provenance(session, row, "overview_cashflow")
        source_fact_id = _source_fact(facts, row.sheet_name, row.source_row, row.source_column)
        amount_id = _required_value_id(session, provenance_id, row.amount.exact_value)
        cashflow_id = new_entity_id()
        session.context.add_overview_cashflow(
            OverviewCashflowRecord(
                cashflow_id=cashflow_id,
                observation_id=observation_id,
                provenance_id=provenance_id,
                source_fact_id=source_fact_id,
                amount_value_id=amount_id,
                snapshot_date=snapshot_date.isoformat(),
                period_month=row.period_month.text,
                category=_required_text(row.category),
            )
        )
        ids.append(cashflow_id)
    return ids


def _persist_insurance(
    session: PersistSession,
    rows: Sequence[ExactInsuranceRow],
    observation_id: str,
    facts: dict[FactKey, str],
    snapshot_date: date,
) -> list[str]:
    ids: list[str] = []
    for row in rows:
        if not row.supported:
            _projection_evidence(session, row, "overview_insurance")
            continue
        provenance_id = _projection_provenance(session, row, "overview_insurance")
        source_fact_id = _source_fact(facts, row.sheet_name, row.source_row, row.source_column)
        paid_id = _add_number(session, provenance_id, row.paid_amount.exact_value)
        insurance_id = new_entity_id()
        session.context.add_overview_insurance(
            OverviewInsuranceRecord(
                insurance_id=insurance_id,
                observation_id=observation_id,
                provenance_id=provenance_id,
                source_fact_id=source_fact_id,
                paid_amount_value_id=paid_id,
                snapshot_date=snapshot_date.isoformat(),
                institution=_required_text(row.institution),
                policy_name=_required_text(row.policy_name),
                contract_status=row.contract_status.text,
                contract_date=_date_text(row.contract_date),
                maturity_date=_date_text(row.maturity_date),
            )
        )
        ids.append(insurance_id)
    return ids


def _persist_investments(
    session: PersistSession,
    rows: Sequence[ExactInvestmentRow],
    observation_id: str,
    facts: dict[FactKey, str],
    snapshot_date: date,
) -> list[str]:
    ids: list[str] = []
    for row in rows:
        if not row.supported:
            _projection_evidence(session, row, "overview_investment")
            continue
        provenance_id = _projection_provenance(session, row, "overview_investment")
        source_fact_id = _source_fact(facts, row.sheet_name, row.source_row, row.source_column)
        investment_id = new_entity_id()
        principal_id = _add_number(session, provenance_id, row.principal_amount.exact_value)
        valuation_id = _add_number(session, provenance_id, row.valuation_amount.exact_value)
        rate_id = _add_number(session, provenance_id, row.return_rate.exact_value)
        session.context.add_overview_investment(
            OverviewInvestmentRecord(
                investment_id=investment_id,
                observation_id=observation_id,
                provenance_id=provenance_id,
                source_fact_id=source_fact_id,
                principal_value_id=principal_id,
                valuation_value_id=valuation_id,
                return_rate_value_id=rate_id,
                snapshot_date=snapshot_date.isoformat(),
                institution=_required_text(row.institution),
                product_name=_required_text(row.product_name),
                product_type=row.product_type.text,
                start_date=_date_text(row.start_date),
                maturity_date=_date_text(row.maturity_date),
            )
        )
        ids.append(investment_id)
    return ids


def _persist_loans(
    session: PersistSession,
    rows: Sequence[ExactLoanRow],
    observation_id: str,
    facts: dict[FactKey, str],
    snapshot_date: date,
) -> list[str]:
    ids: list[str] = []
    for row in rows:
        if not row.supported:
            _projection_evidence(session, row, "overview_loan")
            continue
        provenance_id = _projection_provenance(session, row, "overview_loan")
        source_fact_id = _source_fact(facts, row.sheet_name, row.source_row, row.source_column)
        loan_id = new_entity_id()
        principal_id = _add_number(session, provenance_id, row.principal_amount.exact_value)
        balance_id = _add_number(session, provenance_id, row.balance_amount.exact_value)
        rate_id = _add_number(session, provenance_id, row.interest_rate.exact_value)
        session.context.add_overview_loan(
            OverviewLoanRecord(
                loan_id=loan_id,
                observation_id=observation_id,
                provenance_id=provenance_id,
                source_fact_id=source_fact_id,
                principal_value_id=principal_id,
                balance_value_id=balance_id,
                interest_rate_value_id=rate_id,
                snapshot_date=snapshot_date.isoformat(),
                institution=_required_text(row.institution),
                product_name=_required_text(row.product_name),
                loan_type=row.loan_type.text,
                start_date=_date_text(row.start_date),
                maturity_date=_date_text(row.maturity_date),
            )
        )
        ids.append(loan_id)
    return ids


def _fact_provenance(
    session: PersistSession,
    fact: ExactOverviewFact,
    *,
    extra: dict[str, object],
) -> str:
    place = SourcePlace("overview_fact", fact.sheet_name, fact.source_row, fact.column)
    return add_cell_provenance(session, place, (fact.cell,), extra)


def _projection_provenance(session: PersistSession, row: object, family: str) -> str:
    sheet_name = str(getattr(row, "sheet_name"))
    source_row = int(getattr(row, "source_row"))
    column = str(getattr(row, "source_column"))
    cell = getattr(getattr(row, "amount", None), "cell", None)
    cells = () if cell is None else (cell,)
    place = SourcePlace(family, sheet_name, source_row, column)
    provenance_id = add_cell_provenance(session, place, cells, {"typed": True})
    issues = tuple(as_issue(item) for item in getattr(row, "issues", ()))
    add_issues(session, provenance_id, issues, sheet_name=sheet_name)
    return provenance_id


def _projection_evidence(session: PersistSession, row: object, family: str) -> None:
    _projection_provenance(session, row, family)


def _source_fact(facts: dict[FactKey, str], sheet: str, row: int, column: str) -> str:
    direct = facts.get((sheet, row, column))
    if direct is not None:
        return direct
    for (fact_sheet, fact_row, _column), fact_id in facts.items():
        if fact_sheet == sheet and fact_row == row:
            return fact_id
    raise RuntimeError("Overview projection is missing its source fact.")


def _add_number(
    session: PersistSession,
    provenance_id: str,
    value: ExactValue | None,
) -> str | None:
    if value is None:
        return None
    value_id = new_entity_id()
    session.context.add_exact_value(value_id, value, provenance_id=provenance_id)
    return value_id


def _required_value_id(
    session: PersistSession,
    provenance_id: str,
    value: ExactValue,
) -> str:
    value_id = _add_number(session, provenance_id, value)
    if value_id is None:
        raise RuntimeError("Required exact value was not stored.")
    return value_id


def _fact_text(fact: ExactOverviewFact) -> tuple[str | None, bool]:
    if fact.value_type in {"number", "empty"}:
        return fact.text_value, False
    if fact.text_value:
        return fact.text_value, False
    if fact.parsed_date is not None:
        return fact.parsed_date.isoformat(), False
    return "", True


def _placeholder_issue(
    session: PersistSession,
    provenance_id: str,
    fact: ExactOverviewFact,
) -> None:
    session.context.add_preservation_issue(
        PreservationIssueRecord(
            provenance_id=provenance_id,
            issue_kind="EMPTY_REQUIRED_TEXT_PLACEHOLDER",
            detail={"code": "EMPTY_REQUIRED_TEXT_PLACEHOLDER", "column": fact.column},
            field_name="value_text",
        )
    )


def _required_text(field: MappedField) -> str:
    return field.text or ""


def _date_text(field: MappedField) -> str | None:
    if field.parsed_date is not None:
        return field.parsed_date.isoformat()
    return field.date_raw or field.text
