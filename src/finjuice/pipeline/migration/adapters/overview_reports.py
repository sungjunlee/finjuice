"""Preserve reported overview values independently of unverified fact aliases."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Literal, cast

from finjuice.pipeline.storage.csv_schema_cluster import (
    BANKSALAD_BALANCE_COLUMNS,
    BANKSALAD_CASHFLOW_COLUMNS,
    BANKSALAD_INSURANCE_COLUMNS,
    BANKSALAD_INVESTMENT_COLUMNS,
    BANKSALAD_LOAN_COLUMNS,
)
from finjuice.pipeline.storage.sqlite.legacy_overview import (
    LegacyOverviewBalanceRecord,
    LegacyOverviewCandidateRecord,
    LegacyOverviewCashflowRecord,
    LegacyOverviewInsuranceRecord,
    LegacyOverviewInvestmentRecord,
    LegacyOverviewLoanRecord,
    LegacyOverviewReferenceRecord,
    LegacyOverviewReportRecord,
)

from .model import Emitter
from .observations import unknown_fields
from .values import emit_exact, parse_exact

_ROLES = {
    "balance": ("balance", BANKSALAD_BALANCE_COLUMNS, LegacyOverviewBalanceRecord),
    "cashflow": ("cashflow", BANKSALAD_CASHFLOW_COLUMNS, LegacyOverviewCashflowRecord),
    "insurance": ("insurance", BANKSALAD_INSURANCE_COLUMNS, LegacyOverviewInsuranceRecord),
    "investments": ("investment", BANKSALAD_INVESTMENT_COLUMNS, LegacyOverviewInvestmentRecord),
    "loans": ("loan", BANKSALAD_LOAN_COLUMNS, LegacyOverviewLoanRecord),
}
_NUMBERS = {
    "balance": {"amount": "amount_value_id"},
    "cashflow": {"amount": "amount_value_id"},
    "insurance": {"paid_amount": "paid_amount_value_id"},
    "investment": {
        "principal_amount": "principal_value_id",
        "valuation_amount": "valuation_value_id",
        "return_rate": "return_rate_value_id",
    },
    "loan": {
        "principal_amount": "principal_value_id",
        "balance_amount": "balance_value_id",
        "interest_rate": "interest_rate_value_id",
    },
}


def report_role(path: str) -> str | None:
    """Recognize only canonical Banksalad partition paths, never arbitrary aliases."""
    parts = PurePosixPath(path).parts
    if len(parts) != 5 or parts[0] != "banksalad" or parts[1] not in _ROLES:
        return None
    if not (len(parts[2]) == 4 and parts[2].isascii() and parts[2].isdigit()):
        return None
    if parts[3] not in {f"{month:02d}" for month in range(1, 13)}:
        return None
    return parts[1] if parts[4] == f"{parts[1]}.csv" else None


def report(
    emitter: Emitter,
    row: dict[str, str | None],
    observation: str,
    role: str,
    pending: list[LegacyOverviewCandidateRecord] | None,
) -> bool:
    """Validate all reported numbers before emitting any typed report detail."""
    kind, columns, record_type = _ROLES[role]
    numbers = _NUMBERS[kind]
    optional = set(numbers) if kind not in {"balance", "cashflow"} else set()
    if not (set(columns) - optional).issubset(row) or row.get("snapshot_date") in (None, ""):
        emitter.issue("incomplete_legacy_overview_report")
        return False
    numeric_row = {**row, "currency": None} if kind == "cashflow" else row
    parsed = {
        field: parse_exact(
            emitter,
            numeric_row,
            field,
            "rate" if field in {"return_rate", "interest_rate"} else "money",
            unit=f"legacy_overview_{field}.v1"
            if field in {"return_rate", "interest_rate"}
            else None,
        )
        for field in numbers
    }
    invalid = any(row.get(field) is not None and value is None for field, value in parsed.items())
    if kind in {"balance", "cashflow"} and parsed["amount"] is None:
        emitter.issue("missing_required_field", "amount", row.get("amount"))
        invalid = True
    if invalid:
        return False
    kwargs: dict[str, Any] = {
        field: row.get(field)
        for field in columns
        if field not in set(numbers) | {"snapshot_date", "source_fact_id", "file_id", "source_row"}
    }
    kwargs.update(
        {name: emit_exact(emitter, field, parsed[field]) for field, name in numbers.items()}
    )
    provenance = emitter.identifier("provenance")
    emitter.call(
        "add_legacy_overview_report",
        LegacyOverviewReportRecord(
            observation,
            provenance,
            cast(Literal["balance", "cashflow", "insurance", "investment", "loan"], kind),
            cast(str, row["snapshot_date"]),
        ),
    )
    emitter.call(f"add_legacy_overview_{kind}", record_type(observation, **kwargs))
    emitter.records["legacy_overview_report"] += 1
    emitter.records[f"legacy_overview_{kind}"] += 1
    for field in ("source_fact_id", "file_id", "source_row"):
        if row.get(field) is not None:
            emitter.legacy(observation, field, row[field] or "")
    reference = row.get("source_fact_id")
    candidates = [
        (obs, prov) for alias, obs, prov in emitter.context.fact_index if alias == reference
    ]
    status: Literal["missing", "unverified", "ambiguous"] = (
        "missing" if not candidates else "unverified" if len(candidates) == 1 else "ambiguous"
    )
    emitter.call(
        "add_legacy_overview_reference",
        LegacyOverviewReferenceRecord(
            observation, emitter.context.capture_digest, reference, status
        ),
    )
    emitter.records["legacy_overview_reference"] += 1
    for obs, prov in candidates:
        emitter.records["legacy_overview_candidate"] += 1
        if pending is not None:
            pending.append(LegacyOverviewCandidateRecord(observation, obs, prov))
    emitter.issue(f"legacy_overview_reference_{status}", "source_fact_id", reference)
    unknown_fields(emitter, row, set(columns))
    return True
