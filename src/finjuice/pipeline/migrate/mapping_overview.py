"""Banksalad overview and asset snapshot mapping."""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.migrate.preserve import legacy_payload
from finjuice.pipeline.migrate.records import (
    _ASSET_KNOWN,
    _BALANCE_KNOWN,
    _CASHFLOW_KNOWN,
    _FACT_KNOWN,
    _INSURANCE_KNOWN,
    _INVESTMENT_KNOWN,
    _LOAN_KNOWN,
    _VALUE_TYPES,
    BuildState,
    RowWork,
    add_identity,
    add_issue,
    add_money,
    add_observation,
    add_provenance,
    add_row_identifiers,
    add_typed_number,
    close_record,
    ensure_account,
    ensure_resource,
    row_locator,
    stable_id,
)
from finjuice.pipeline.storage.sqlite import (
    AssetSnapshotRecord,
    OverviewBalanceRecord,
    OverviewCashflowRecord,
    OverviewFactRecord,
    OverviewInsuranceRecord,
    OverviewInvestmentRecord,
    OverviewLoanRecord,
)


def _begin(
    work: RowWork, known: set[str]
) -> tuple[BuildState, dict[str, Any], str, dict[str, Any]]:
    locator = row_locator(work.entry, work.ordinal, work.row)
    provenance_id = add_provenance(
        work.state,
        work.occurrence_id,
        locator,
        {"relative_path": work.entry.relative_path, "ordinal": work.ordinal},
    )
    payload = legacy_payload(work.row, work.headers, known)
    return work.state, locator, provenance_id, payload


def _opaque(
    state: BuildState,
    provenance_id: str,
    locator: dict[str, Any],
    payload: dict[str, Any],
    extra: dict[str, Any],
) -> None:
    reason = str(extra.get("reason", "preserved_opaque"))
    add_issue(state, provenance_id, reason, extra)
    close_record(state, provenance_id, payload, locator, ("preserved_opaque", reason))


def _insert_projection_fact(work: RowWork, source_key: str) -> str:
    """Create a same-occurrence fact so a projection can satisfy SQLite FKs."""
    fact_locator = {
        "locator_version": 1,
        "relative_path": work.entry.relative_path,
        "logical_role": work.entry.logical_role,
        "source_fact_id": source_key,
        "binding": "projection_source_fact",
    }
    fact_provenance = add_provenance(
        work.state,
        work.occurrence_id,
        fact_locator,
        {"source_fact_id": source_key, "logical_role": work.entry.logical_role},
    )
    fact_id = stable_id(work.state.digest, "overview_fact", fact_locator)
    work.state.builder.add_overview_fact(
        OverviewFactRecord(
            fact_id=fact_id,
            observation_id=add_observation(work.state, work.occurrence_id, fact_locator),
            provenance_id=fact_provenance,
            snapshot_date=work.row.get("snapshot_date") or "",
            sheet_name=work.row.get("sheet_name") or "projection",
            block_id=work.row.get("block_id") or work.entry.logical_role,
            block_title=work.row.get("category") or work.row.get("item_name") or source_key,
            fact_kind="projection_binding",
            value_type="empty",
            row_label=work.row.get("item_name") or work.row.get("category") or None,
        )
    )
    add_identity(work.state, fact_id, "overview_fact", fact_locator)
    work.state.projection_facts[(work.occurrence_id, source_key)] = fact_id
    return fact_id


def _require_fact(
    work: RowWork,
    provenance_id: str,
    locator: dict[str, Any],
    payload: dict[str, Any],
) -> str | None:
    source_fact_id = str(work.row.get("source_fact_id") or "")
    if not source_fact_id:
        _opaque(
            work.state,
            provenance_id,
            locator,
            payload,
            {
                "reason": "missing_source_fact",
                "field_name": "source_fact_id",
                "lexical_value": source_fact_id,
            },
        )
        return None
    cached = work.state.projection_facts.get((work.occurrence_id, source_fact_id))
    if cached is not None:
        return cached
    return _insert_projection_fact(work, source_fact_id)


def map_overview_fact_row(work: RowWork) -> None:
    """Preserve one overview fact without treating it as a transaction."""
    state, locator, provenance_id, payload = _begin(work, _FACT_KNOWN)
    locator["fact_id"] = work.row.get("fact_id")
    value_type = work.row.get("value_type") or "empty"
    if value_type not in _VALUE_TYPES:
        add_issue(
            state,
            provenance_id,
            "unsupported_value_type",
            {"field_name": "value_type", "lexical_value": value_type},
        )
        value_type = "unsupported"
    numeric_id = None
    if value_type == "number" and work.row.get("value_numeric"):
        numeric_id = add_typed_number(
            state,
            provenance_id,
            locator,
            {
                "lexical": work.row["value_numeric"],
                "field_name": "value_numeric",
                "unit": "overview.v1",
            },
        )
        if numeric_id is None:
            _opaque(
                state,
                provenance_id,
                locator,
                payload,
                {
                    "reason": "unparseable_amount",
                    "field_name": "value_numeric",
                    "lexical_value": work.row.get("value_numeric"),
                },
            )
            return
    if value_type == "number" and numeric_id is None:
        _opaque(
            state,
            provenance_id,
            locator,
            payload,
            {"reason": "missing_numeric_value", "field_name": "value_numeric"},
        )
        return
    if value_type not in {"number", "empty"} and not (work.row.get("value_text") or ""):
        _opaque(
            state,
            provenance_id,
            locator,
            payload,
            {"reason": "missing_value_text", "field_name": "value_text"},
        )
        return
    fact_id = stable_id(state.digest, "overview_fact", locator)
    observation_id = add_observation(state, work.occurrence_id, locator)
    state.builder.add_overview_fact(
        OverviewFactRecord(
            fact_id=fact_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            snapshot_date=work.row.get("snapshot_date") or "",
            sheet_name=work.row.get("sheet_name") or "",
            block_id=work.row.get("block_id") or "",
            block_title=work.row.get("block_title") or "",
            fact_kind=work.row.get("fact_kind") or "unknown",
            value_type=value_type,  # type: ignore[arg-type]
            row_label=work.row.get("row_label") or None,
            column_label=work.row.get("column_label") or None,
            numeric_value_id=numeric_id,
            value_text=work.row.get("value_text") or None,
        )
    )
    add_identity(state, fact_id, "overview_fact", locator)
    if work.row.get("fact_id"):
        state.fact_ids[work.row["fact_id"]] = fact_id
    add_row_identifiers(work, fact_id, provenance_id, locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Overview fact preserved distinct from transactions."),
    )


def map_overview_balance_row(work: RowWork) -> None:
    """Preserve a typed balance projection distinct from transaction events."""
    state, locator, provenance_id, payload = _begin(work, _BALANCE_KNOWN)
    fact_id = _require_fact(work, provenance_id, locator, payload)
    if fact_id is None:
        return
    amount_id, amount_issue = add_money(
        state,
        provenance_id,
        locator,
        ("amount", work.row.get("amount") or "", work.row.get("currency")),
    )
    if amount_id is None:
        close_record(
            state,
            provenance_id,
            payload,
            locator,
            ("preserved_opaque", amount_issue or "unparseable_amount"),
        )
        return
    balance_id = stable_id(state.digest, "overview_balance", locator)
    observation_id = add_observation(state, work.occurrence_id, locator)
    state.builder.add_overview_balance(
        OverviewBalanceRecord(
            balance_id=balance_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            source_fact_id=fact_id,
            amount_value_id=amount_id,
            snapshot_date=work.row.get("snapshot_date") or "",
            side=work.row.get("side") or "",
            category=work.row.get("category") or "",
            item_name=work.row.get("item_name") or "",
        )
    )
    add_identity(state, balance_id, "overview_balance", locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Overview balance preserved without interpreting it as a transaction."),
    )


def map_overview_cashflow_row(work: RowWork) -> None:
    """Preserve a typed cashflow projection."""
    state, locator, provenance_id, payload = _begin(work, _CASHFLOW_KNOWN)
    fact_id = _require_fact(work, provenance_id, locator, payload)
    if fact_id is None:
        return
    amount_id, amount_issue = add_money(
        state,
        provenance_id,
        locator,
        ("amount", work.row.get("amount") or "", None),
    )
    if amount_id is None:
        close_record(
            state,
            provenance_id,
            payload,
            locator,
            ("preserved_opaque", amount_issue or "unparseable_amount"),
        )
        return
    cashflow_id = stable_id(state.digest, "overview_cashflow", locator)
    observation_id = add_observation(state, work.occurrence_id, locator)
    state.builder.add_overview_cashflow(
        OverviewCashflowRecord(
            cashflow_id=cashflow_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            source_fact_id=fact_id,
            amount_value_id=amount_id,
            snapshot_date=work.row.get("snapshot_date") or "",
            period_month=work.row.get("period_month") or "",
            category=work.row.get("category") or "",
        )
    )
    add_identity(state, cashflow_id, "overview_cashflow", locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Overview cashflow preserved as a projection."),
    )


def map_overview_insurance_row(work: RowWork) -> None:
    """Preserve a typed insurance projection."""
    state, locator, provenance_id, payload = _begin(work, _INSURANCE_KNOWN)
    fact_id = _require_fact(work, provenance_id, locator, payload)
    if fact_id is None:
        return
    paid_id = None
    if work.row.get("paid_amount"):
        paid_id, paid_issue = add_money(
            state,
            provenance_id,
            locator,
            ("paid_amount", work.row["paid_amount"], work.row.get("currency")),
        )
        if paid_id is None:
            close_record(
                state,
                provenance_id,
                payload,
                locator,
                ("preserved_opaque", paid_issue or "unparseable_amount"),
            )
            return
    insurance_id = stable_id(state.digest, "overview_insurance", locator)
    observation_id = add_observation(state, work.occurrence_id, locator)
    state.builder.add_overview_insurance(
        OverviewInsuranceRecord(
            insurance_id=insurance_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            source_fact_id=fact_id,
            paid_amount_value_id=paid_id,
            snapshot_date=work.row.get("snapshot_date") or "",
            institution=work.row.get("institution") or "",
            policy_name=work.row.get("policy_name") or "",
            contract_status=work.row.get("contract_status") or None,
            contract_date=work.row.get("contract_date") or None,
            maturity_date=work.row.get("maturity_date") or None,
        )
    )
    add_identity(state, insurance_id, "overview_insurance", locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Overview insurance preserved as a projection."),
    )


def _pair_money(
    state: BuildState,
    provenance_id: str,
    locator: dict[str, Any],
    spec: dict[str, Any],
) -> dict[str, str] | None:
    values: dict[str, str] = {}
    row = spec["row"]
    for field_name in spec["fields"]:
        lexical = row.get(field_name) or ""
        if not lexical:
            continue
        value_id, issue = add_money(
            state,
            provenance_id,
            locator,
            (field_name, lexical, row.get("currency")),
        )
        if value_id is None:
            return None if issue else values
        values[field_name] = value_id
    return values


def map_overview_investment_row(work: RowWork) -> None:
    """Preserve a typed investment projection with exact amounts and rate."""
    state, locator, provenance_id, payload = _begin(work, _INVESTMENT_KNOWN)
    fact_id = _require_fact(work, provenance_id, locator, payload)
    if fact_id is None:
        return
    money = _pair_money(
        state,
        provenance_id,
        locator,
        {"row": work.row, "fields": ("principal_amount", "valuation_amount")},
    )
    if money is None:
        close_record(
            state,
            provenance_id,
            payload,
            locator,
            ("preserved_opaque", "unparseable_amount"),
        )
        return
    rate_id = None
    if work.row.get("return_rate"):
        rate_id = add_typed_number(
            state,
            provenance_id,
            locator,
            {
                "lexical": work.row["return_rate"],
                "field_name": "return_rate",
                "unit": "rate.v1",
                "value_kind": "rate",
            },
        )
    investment_id = stable_id(state.digest, "overview_investment", locator)
    observation_id = add_observation(state, work.occurrence_id, locator)
    state.builder.add_overview_investment(
        OverviewInvestmentRecord(
            investment_id=investment_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            source_fact_id=fact_id,
            principal_value_id=money.get("principal_amount"),
            valuation_value_id=money.get("valuation_amount"),
            return_rate_value_id=rate_id,
            snapshot_date=work.row.get("snapshot_date") or "",
            institution=work.row.get("institution") or "",
            product_name=work.row.get("product_name") or "",
            product_type=work.row.get("product_type") or None,
            start_date=work.row.get("start_date") or None,
            maturity_date=work.row.get("maturity_date") or None,
        )
    )
    add_identity(state, investment_id, "overview_investment", locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Overview investment preserved as a projection."),
    )


def map_overview_loan_row(work: RowWork) -> None:
    """Preserve a typed loan projection."""
    state, locator, provenance_id, payload = _begin(work, _LOAN_KNOWN)
    fact_id = _require_fact(work, provenance_id, locator, payload)
    if fact_id is None:
        return
    money = _pair_money(
        state,
        provenance_id,
        locator,
        {"row": work.row, "fields": ("principal_amount", "balance_amount")},
    )
    if money is None:
        close_record(
            state,
            provenance_id,
            payload,
            locator,
            ("preserved_opaque", "unparseable_amount"),
        )
        return
    rate_id = None
    if work.row.get("interest_rate"):
        rate_id = add_typed_number(
            state,
            provenance_id,
            locator,
            {
                "lexical": work.row["interest_rate"],
                "field_name": "interest_rate",
                "unit": "rate.v1",
                "value_kind": "rate",
            },
        )
    loan_id = stable_id(state.digest, "overview_loan", locator)
    observation_id = add_observation(state, work.occurrence_id, locator)
    state.builder.add_overview_loan(
        OverviewLoanRecord(
            loan_id=loan_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            source_fact_id=fact_id,
            principal_value_id=money.get("principal_amount"),
            balance_value_id=money.get("balance_amount"),
            interest_rate_value_id=rate_id,
            snapshot_date=work.row.get("snapshot_date") or "",
            institution=work.row.get("institution") or "",
            product_name=work.row.get("product_name") or "",
            loan_type=work.row.get("loan_type") or None,
            start_date=work.row.get("start_date") or None,
            maturity_date=work.row.get("maturity_date") or None,
        )
    )
    add_identity(state, loan_id, "overview_loan", locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Overview loan preserved as a projection."),
    )


def map_asset_snapshot_row(work: RowWork) -> None:
    """Preserve an asset position without merging accounts or inferring owners."""
    state, locator, provenance_id, payload = _begin(work, _ASSET_KNOWN)
    quantity_id = None
    if work.row.get("quantity"):
        quantity_id = add_typed_number(
            state,
            provenance_id,
            locator,
            {
                "lexical": work.row["quantity"],
                "field_name": "quantity",
                "unit": "share.v1",
                "value_kind": "quantity",
            },
        )
    market_id = None
    if work.row.get("market_value"):
        market_id, market_issue = add_money(
            state,
            provenance_id,
            locator,
            ("market_value", work.row["market_value"], work.row.get("currency")),
        )
        if market_id is None:
            close_record(
                state,
                provenance_id,
                payload,
                locator,
                ("preserved_opaque", market_issue or "unparseable_amount"),
            )
            return
    if quantity_id is None and market_id is None:
        _opaque(state, provenance_id, locator, payload, {"reason": "missing_asset_value"})
        return
    snapshot_id = stable_id(state.digest, "asset_snapshot", locator)
    observation_id = add_observation(state, work.occurrence_id, locator)
    account_key = work.row.get("account_id") or ""
    resource_key = work.row.get("instrument_id") or ""
    state.builder.add_asset_snapshot(
        AssetSnapshotRecord(
            snapshot_id=snapshot_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            account_id=ensure_account(state, "asset_snapshot", account_key, account_key),
            resource_id=ensure_resource(state, resource_key),
            quantity_value_id=quantity_id,
            market_value_id=market_id,
            snapshot_date=work.row.get("snapshot_date") or "",
        )
    )
    add_identity(state, snapshot_id, "asset_snapshot", locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Asset snapshot preserved without ownership inference."),
    )
