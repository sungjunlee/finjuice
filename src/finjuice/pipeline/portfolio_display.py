"""Legacy portfolio display partitions derived only from detached repository evidence."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import date
from decimal import Decimal
from typing import Any

import polars as pl

from finjuice.pipeline.storage.csv_schema import (
    ASSET_SNAPSHOT_POLARS_SCHEMA,
    BANKSALAD_BALANCE_POLARS_SCHEMA,
    BANKSALAD_INVESTMENT_POLARS_SCHEMA,
    BANKSALAD_LOAN_POLARS_SCHEMA,
)
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioReadSnapshot

_SCHEMAS = {
    "snapshot": ASSET_SNAPSHOT_POLARS_SCHEMA,
    "balance": BANKSALAD_BALANCE_POLARS_SCHEMA,
    "investment": BANKSALAD_INVESTMENT_POLARS_SCHEMA,
    "loan": BANKSALAD_LOAN_POLARS_SCHEMA,
}


class PortfolioDisplayError(ValueError):
    """Static public error for incomplete or unrepresentable portfolio evidence."""


def _object(value: str) -> dict[str, Any]:
    try:
        result = json.loads(value)
    except (ValueError, TypeError):
        raise PortfolioDisplayError("Portfolio source evidence is invalid.") from None
    if not isinstance(result, dict):
        raise PortfolioDisplayError("Portfolio source evidence is invalid.")
    return result


def _month(value: str) -> str:
    try:
        if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value) is None:
            raise ValueError
        return date.fromisoformat(value).isoformat()[:7]
    except (ValueError, TypeError):
        raise PortfolioDisplayError("Portfolio date cannot be displayed.") from None


class PortfolioDisplay:
    """Display floats coexist with exact sidecars; no identity or ownership merging.

    Primary capture partitions retain path months and source row order. Native
    rows follow primary rows in UUID order and use explicit native-* labels when
    legacy aliases do not exist. Auxiliary captures never enter display totals.
    """

    def __init__(self, snapshot: PortfolioReadSnapshot) -> None:
        self.snapshot = snapshot
        self._provenance = {
            row["provenance_id"]: row for row in snapshot.evidence["record_provenance"]
        }
        self._payloads = {row["provenance_id"]: row for row in snapshot.evidence["legacy_payloads"]}
        self._values = {row["value_id"]: row for row in snapshot.evidence["exact_values"]}
        self._money = {row["value_id"]: row for row in snapshot.evidence["money_values"]}
        self._rates = {row["value_id"]: row for row in snapshot.evidence["rate_values"]}
        self._occurrences = {
            row["entity_id"]: row for row in snapshot.evidence["source_occurrences"]
        }
        self._scopes = {row["source_occurrence_id"]: row for row in snapshot.source_scopes}
        self._cache: dict[str, dict[str, pl.DataFrame]] = {}

    @property
    def snapshot_months(self) -> tuple[str, ...]:
        """Primary empty partitions and native valid-date months, sorted ascending."""
        return tuple(sorted(self._partitions("snapshot")))

    @property
    def balance_months(self) -> tuple[str, ...]:
        """Available primary/native balance months, preserving empty partitions."""
        return tuple(sorted(self._partitions("balance")))

    def snapshot_partition(self, month: str) -> pl.DataFrame | None:
        """Return a detached asset display frame; absent month remains None."""
        frame = self._partitions("snapshot").get(month)
        return frame.clone() if frame is not None else None

    def balance_partition(self, month: str) -> pl.DataFrame | None:
        """Return reported balances without promoting source-fact references."""
        frame = self._partitions("balance").get(month)
        return frame.clone() if frame is not None else None

    @property
    def investment_months(self) -> tuple[str, ...]:
        """Available primary/native investment months, including empty partitions."""
        return tuple(sorted(self._partitions("investment")))

    @property
    def loan_months(self) -> tuple[str, ...]:
        """Available primary/native loan months, including empty partitions."""
        return tuple(sorted(self._partitions("loan")))

    def investment_partition(self, month: str) -> pl.DataFrame | None:
        """Return investment amounts with exact values and unconverted rate units."""
        frame = self._partitions("investment").get(month)
        return frame.clone() if frame is not None else None

    def loan_partition(self, month: str) -> pl.DataFrame | None:
        """Return loan amounts with exact values and unconverted rate units."""
        frame = self._partitions("loan").get(month)
        return frame.clone() if frame is not None else None

    def metadata(self) -> dict[str, object]:
        """Report the pinned source and display policy, not materialization completeness."""
        references = self.snapshot.legacy_overview_reports.get(
            "legacy_overview_reference_assessments", ()
        )
        return {
            "authority": "repository",
            "dataset_generation": self.snapshot.info.dataset_generation,
            "dataset_revision": self.snapshot.info.dataset_revision,
            "sqlite_schema_version": self.snapshot.info.schema_version,
            "read_policy": "legacy_portfolio_display.v1",
            "calculation_policy": "legacy_portfolio_display.v1",
            "native_identity_display_policy": "explicit_native_uuid_labels.v1",
            "source_counts": dict(
                Counter(row["occurrence_kind"] for row in self._occurrences.values())
            ),
            "preserved_reference_counts": dict(Counter(row["status"] for row in references)),
            "legacy_reports_support": self.snapshot.legacy_reports_support,
        }

    def _scope_month(self, scope: dict[str, Any], kind: str) -> str | None:
        prefix, filename = {
            "snapshot": ("assets/snapshots", "snapshots.csv"),
            "balance": ("banksalad/balance", "balance.csv"),
            "investment": ("banksalad/investments", "investments.csv"),
            "loan": ("banksalad/loans", "loans.csv"),
        }[kind]
        match = re.fullmatch(
            rf"{prefix}/([0-9]{{4}})/(0[1-9]|1[0-2])/{re.escape(filename)}", scope["path"]
        )
        if scope["root"] != "data" or match is None:
            return None
        return f"{match[1]}-{match[2]}"

    def _location(self, row: dict[str, Any], kind: str) -> tuple[str, int, int] | None:
        provenance = self._provenance[row["provenance_id"]]
        occurrence = provenance["source_occurrence_id"]
        if self._occurrences[occurrence]["occurrence_kind"] == "legacy_capture":
            scope = self._scopes.get(occurrence)
            if scope is None or (month := self._scope_month(scope, kind)) is None:
                return None
            coordinate = _object(provenance["source_coordinate_json"])
            locator = _object(provenance["legacy_locator_json"])
            if (
                coordinate != locator
                or coordinate.get("root") != scope["root"]
                or coordinate.get("path") != scope["path"]
                or type(coordinate.get("row")) is not int
                or coordinate["row"] < 1
            ):
                raise PortfolioDisplayError("Portfolio row provenance is incomplete.")
            return month, 0, coordinate["row"]
        return _month(row["snapshot_date"]), 1, 0

    def _guard(self, kind: str, represented: set[str]) -> None:
        for provenance in self._provenance.values():
            scope = self._scopes.get(provenance["source_occurrence_id"])
            if scope is None or self._scope_month(scope, kind) is None:
                continue
            coordinate = _object(provenance["source_coordinate_json"])
            if coordinate.get("row") is not None and provenance["provenance_id"] not in represented:
                raise PortfolioDisplayError("Preserved portfolio rows lack typed display values.")

    def _partitions(self, kind: str) -> dict[str, pl.DataFrame]:
        if kind in self._cache:
            return self._cache[kind]
        rows = self._domain(kind)
        self._guard(kind, {row["provenance_id"] for row in rows})
        grouped: dict[str, list[dict[str, Any]]] = {}
        for scope in self._scopes.values():
            month = self._scope_month(scope, kind)
            if month is not None:
                grouped.setdefault(month, [])
        ordered = []
        for row in rows:
            location = self._location(row, kind)
            if location is not None:
                identifier = row.get("entity_id", row["observation_id"])
                ordered.append((*location, identifier, row))
        for month, _, _, _, row in sorted(ordered, key=lambda item: item[:4]):
            grouped.setdefault(month, []).append(self._display(row, kind))
        schema = _SCHEMAS[kind]
        self._cache[kind] = {
            month: pl.DataFrame(values, schema_overrides=schema, infer_schema_length=None)
            if values
            else pl.DataFrame(schema=schema)
            for month, values in grouped.items()
        }
        return self._cache[kind]

    def _domain(self, kind: str) -> tuple[dict[str, Any], ...]:
        if kind == "snapshot":
            return self.snapshot.asset_snapshots
        legacy = self.snapshot.legacy_overview_reports
        reports = {row["observation_id"]: row for row in legacy.get("legacy_overview_reports", ())}
        table = {"balance": "balances", "investment": "investments", "loan": "loans"}[kind]
        reported = []
        for row in legacy.get(f"legacy_overview_{table}", ()):
            header = reports.get(row["observation_id"])
            if header is None or header["report_kind"] != kind:
                raise PortfolioDisplayError("Portfolio report header is incomplete.")
            reported.append({**header, **row, "reported": True})
        return self.snapshot.native_overview_reports[f"overview_{table}"] + tuple(reported)

    def _raw(self, row: dict[str, Any]) -> dict[str, Any]:
        payload = self._payloads.get(row["provenance_id"])
        if payload is None:
            return {}
        parsed = _object(payload["payload_json"])
        columns, values = parsed.get("columns"), parsed.get("values")
        if not isinstance(columns, list) or not isinstance(values, list):
            return {}
        if len(columns) != len(values) or len(set(columns)) != len(columns):
            raise PortfolioDisplayError("Portfolio raw row is ambiguous.")
        return dict(zip(columns, values, strict=True))

    def _alias(self, entity: str, name: str, provenance: str) -> str | None:
        superseded = {
            row["previous_mapping_id"]
            for row in self.snapshot.evidence["legacy_identifier_supersessions"]
        }
        values = set()
        for row in self.snapshot.evidence["legacy_identifiers"]:
            if (
                row["entity_id"] != entity
                or row["provenance_id"] != provenance
                or row["mapping_id"] in superseded
            ):
                continue
            if row["identifier_kind"] == name:
                values.add(row["identifier_value"])
            elif row["identifier_kind"] == "other" and row["identifier_value"].startswith(
                name + ":"
            ):
                values.add(row["identifier_value"][len(name) + 1 :])
        if len(values) > 1:
            raise PortfolioDisplayError("Portfolio legacy alias is ambiguous.")
        return next(iter(values), None)

    def _number(self, value_id: str | None, field: str) -> dict[str, Any]:
        value = self._values.get(value_id) if value_id is not None else None
        if value is None:
            return {
                field: None,
                f"{field}_coefficient": None,
                f"{field}_scale": None,
                f"{field}_lexical": None,
            }
        exact = Decimal(
            (
                int(value["coefficient"].startswith("-")),
                tuple(int(c) for c in value["coefficient"].lstrip("-")),
                -value["scale"],
            )
        )
        if value["coefficient"] == "0" and (value["lexical"] or "").lstrip().startswith("-"):
            exact = exact.copy_negate()
        displayed = float(exact)
        if not math.isfinite(displayed):
            raise PortfolioDisplayError("Portfolio value exceeds the finite display range.")
        return {
            field: displayed,
            **{f"{field}_{key}": value[key] for key in ("coefficient", "scale", "lexical")},
        }

    def _display(self, row: dict[str, Any], kind: str) -> dict[str, Any]:
        raw = self._raw(row)
        provenance = row["provenance_id"]
        identifier = row.get("entity_id", row["observation_id"])
        result = {
            "snapshot_date": row["snapshot_date"],
            "authoritative_id": identifier,
            "observation_id": row["observation_id"],
            "provenance_id": provenance,
            "file_id": self._alias(identifier, "file_id", provenance),
            "source_row": raw.get("source_row"),
        }
        if result["source_row"] is not None:
            try:
                result["source_row"] = (
                    int(result["source_row"]) if result["source_row"] != "" else None
                )
            except (ValueError, TypeError):
                raise PortfolioDisplayError("Portfolio source row cannot be displayed.") from None
        if kind == "snapshot":
            account = self._alias(row["account_id"], "account_id", provenance)
            resource = self._alias(row["resource_id"], "instrument_id", provenance)
            occurrence = self._provenance[provenance]["source_occurrence_id"]
            if self._occurrences[occurrence]["occurrence_kind"] == "legacy_capture" and (
                account is None or resource is None
            ):
                raise PortfolioDisplayError("Portfolio legacy identity evidence is incomplete.")
            result.update(
                account_id=account
                if account is not None
                else f"native-account:{row['account_id']}",
                instrument_id=resource
                if resource is not None
                else f"native-instrument:{row['resource_id']}",
                asset_snapshot_id=row["entity_id"],
                account_entity_id=row["account_id"],
                resource_entity_id=row["resource_id"],
            )
            result.update(self._number(row["quantity_value_id"], "quantity"))
            result.update(self._number(row["market_value_id"], "market_value"))
            value_id = row["market_value_id"]
        elif kind in {"investment", "loan"}:
            result.update(self._financial_report(row, kind, raw))
            value_id = row["valuation_value_id" if kind == "investment" else "balance_value_id"]
        else:
            result.update({key: row[key] for key in ("side", "category", "item_name")})
            result.update(self._number(row["amount_value_id"], "amount"))
            result["source_fact_id"] = raw.get("source_fact_id")
            result["source_fact_uuid"] = None if row.get("reported") else row["source_fact_id"]
            result["source_basis"] = "reported" if row.get("reported") else "native"
            value_id = row["amount_value_id"]
        money = self._money.get(value_id, {})
        result["currency"] = raw.get("currency", row.get("currency", money.get("currency_code")))
        result["currency_unknown"] = money.get("currency_unknown")
        result["currency_source"] = result["currency"]
        result["snapshot_date_raw"] = result["snapshot_date"]
        schema = _SCHEMAS[kind]
        for name, dtype in schema.items():
            if dtype == pl.Utf8 and result.get(name) in {"", "NA", "NULL"}:
                result[name] = None
        return result

    def _financial_report(
        self, row: dict[str, Any], kind: str, raw: dict[str, Any]
    ) -> dict[str, Any]:
        """Preserve nullable values and per-field currencies; never convert or infer."""
        type_field = "product_type" if kind == "investment" else "loan_type"
        amount_field = "valuation_amount" if kind == "investment" else "balance_amount"
        amount_key = "valuation_value_id" if kind == "investment" else "balance_value_id"
        rate_field = "return_rate" if kind == "investment" else "interest_rate"
        fields = (type_field, "institution", "product_name", "start_date", "maturity_date")
        result = {key: row[key] for key in fields}
        result.update(
            source_fact_id=raw.get("source_fact_id"),
            source_fact_uuid=None if row.get("reported") else row["source_fact_id"],
            source_basis="reported" if row.get("reported") else "native",
        )
        for field, key, subtype in (
            ("principal_amount", "principal_value_id", self._money),
            (amount_field, amount_key, self._money),
            (rate_field, f"{rate_field}_value_id", self._rates),
        ):
            value_id = row[key]
            if value_id is not None and (value_id not in self._values or value_id not in subtype):
                raise PortfolioDisplayError("Portfolio numeric evidence is incomplete.")
            try:
                result.update(self._number(value_id, field))
            except (KeyError, TypeError, ValueError, ArithmeticError):
                raise PortfolioDisplayError("Portfolio numeric evidence is invalid.") from None
            detail = subtype.get(value_id, {})
            if field == rate_field:
                unit = detail.get("unit")
                if value_id is not None and (not isinstance(unit, str) or ".v" not in unit):
                    raise PortfolioDisplayError("Portfolio rate unit is invalid.")
                result[f"{field}_unit"] = unit
            else:
                result[f"{field}_currency"] = detail.get("currency_code")
                result[f"{field}_currency_unknown"] = detail.get("currency_unknown")
        return result
