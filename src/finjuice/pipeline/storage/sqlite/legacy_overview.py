"""Records and explicit inserts for legacy reports with unverified references."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class LegacyOverviewReportRecord:
    """Preserve a legacy report without asserting a verified fact derivation."""

    observation_id: str
    provenance_id: str
    report_kind: Literal["balance", "cashflow", "insurance", "investment", "loan"]
    snapshot_date: str


@dataclass(frozen=True)
class LegacyOverviewBalanceRecord:
    """Preserve a legacy balance without asserting a verified fact derivation."""

    observation_id: str
    amount_value_id: str
    side: str | None
    category: str | None
    item_name: str | None
    currency: str | None = None


@dataclass(frozen=True)
class LegacyOverviewCashflowRecord:
    """Preserve a legacy cashflow without asserting a verified fact derivation."""

    observation_id: str
    amount_value_id: str
    period_month: str | None
    category: str | None
    currency: str | None = None


@dataclass(frozen=True)
class LegacyOverviewInsuranceRecord:
    """Preserve a legacy insurance without asserting a verified fact derivation."""

    observation_id: str
    institution: str | None
    policy_name: str | None
    contract_status: str | None
    contract_date: str | None
    maturity_date: str | None
    paid_amount_value_id: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class LegacyOverviewInvestmentRecord:
    """Preserve a legacy investment without asserting a verified fact derivation."""

    observation_id: str
    product_type: str | None
    institution: str | None
    product_name: str | None
    start_date: str | None
    maturity_date: str | None
    principal_value_id: str | None = None
    valuation_value_id: str | None = None
    return_rate_value_id: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class LegacyOverviewLoanRecord:
    """Preserve a legacy loan without asserting a verified fact derivation."""

    observation_id: str
    loan_type: str | None
    institution: str | None
    product_name: str | None
    start_date: str | None
    maturity_date: str | None
    principal_value_id: str | None = None
    balance_value_id: str | None = None
    interest_rate_value_id: str | None = None
    currency: str | None = None


@dataclass(frozen=True)
class LegacyOverviewReferenceRecord:
    """Preserve a legacy reference without asserting a verified fact derivation."""

    report_observation_id: str
    capture_digest: str
    source_fact_id: str | None
    status: Literal["missing", "unverified", "ambiguous"]
    assessment_policy: str = "legacy_overview_reference.v1"


@dataclass(frozen=True)
class LegacyOverviewCandidateRecord:
    """Preserve a legacy candidate without asserting a verified fact derivation."""

    report_observation_id: str
    candidate_observation_id: str
    candidate_provenance_id: str


class LegacyOverviewWriter:
    """Insert single rows into the caller-owned staging transaction."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def add_report(self, record: LegacyOverviewReportRecord) -> None:
        """Append immutable legacy report evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_reports (observation_id, provenance_id, "
            "report_kind, snapshot_date)"
            "VALUES (?, ?, ?, ?)",
            (
                record.observation_id,
                record.provenance_id,
                record.report_kind,
                record.snapshot_date,
            ),
        )

    def add_balance(self, record: LegacyOverviewBalanceRecord) -> None:
        """Append immutable legacy balance evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_balances (observation_id, amount_value_id, side, "
            "category, item_name, currency)"
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                record.observation_id,
                record.amount_value_id,
                record.side,
                record.category,
                record.item_name,
                record.currency,
            ),
        )

    def add_cashflow(self, record: LegacyOverviewCashflowRecord) -> None:
        """Append immutable legacy cashflow evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_cashflows (observation_id, amount_value_id, "
            "period_month, category, currency)"
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.observation_id,
                record.amount_value_id,
                record.period_month,
                record.category,
                record.currency,
            ),
        )

    def add_insurance(self, record: LegacyOverviewInsuranceRecord) -> None:
        """Append immutable legacy insurance evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_insurance (observation_id, institution, "
            "policy_name, contract_status, contract_date, maturity_date, "
            "paid_amount_value_id, currency)"
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.observation_id,
                record.institution,
                record.policy_name,
                record.contract_status,
                record.contract_date,
                record.maturity_date,
                record.paid_amount_value_id,
                record.currency,
            ),
        )

    def add_investment(self, record: LegacyOverviewInvestmentRecord) -> None:
        """Append immutable legacy investment evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_investments (observation_id, product_type, "
            "institution, product_name, start_date, maturity_date, principal_value_id, "
            "valuation_value_id, return_rate_value_id, currency)"
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.observation_id,
                record.product_type,
                record.institution,
                record.product_name,
                record.start_date,
                record.maturity_date,
                record.principal_value_id,
                record.valuation_value_id,
                record.return_rate_value_id,
                record.currency,
            ),
        )

    def add_loan(self, record: LegacyOverviewLoanRecord) -> None:
        """Append immutable legacy loan evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_loans (observation_id, loan_type, institution, "
            "product_name, start_date, maturity_date, principal_value_id, "
            "balance_value_id, interest_rate_value_id, currency)"
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.observation_id,
                record.loan_type,
                record.institution,
                record.product_name,
                record.start_date,
                record.maturity_date,
                record.principal_value_id,
                record.balance_value_id,
                record.interest_rate_value_id,
                record.currency,
            ),
        )

    def add_reference(self, record: LegacyOverviewReferenceRecord) -> None:
        """Append immutable legacy reference evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_reference_assessments (report_observation_id, "
            "capture_digest, source_fact_id, status, assessment_policy)"
            "VALUES (?, ?, ?, ?, ?)",
            (
                record.report_observation_id,
                record.capture_digest,
                record.source_fact_id,
                record.status,
                record.assessment_policy,
            ),
        )

    def add_candidate(self, record: LegacyOverviewCandidateRecord) -> None:
        """Append immutable legacy candidate evidence."""
        self._connection.execute(
            "INSERT INTO legacy_overview_reference_candidates (report_observation_id, "
            "candidate_observation_id, candidate_provenance_id)"
            "VALUES (?, ?, ?)",
            (
                record.report_observation_id,
                record.candidate_observation_id,
                record.candidate_provenance_id,
            ),
        )
