"""Schema v5 preserves reported values without weakening native fact bindings."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryBuilder, RepositoryReader
from finjuice.pipeline.storage.sqlite.errors import RepositoryIntegrityError
from finjuice.pipeline.storage.sqlite.exact import UNKNOWN_CURRENCY, ExactValue
from finjuice.pipeline.storage.sqlite.ids import migration_entity_id
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
from finjuice.pipeline.storage.sqlite.records import (
    MigrationIdentityRecord,
    ObservationRecord,
    OverviewBalanceRecord,
    OverviewFactRecord,
    ProvenanceRecord,
    SourceOccurrenceRecord,
)
from finjuice.pipeline.storage.sqlite.schema import upgrade_repository

CAPTURE = "a" * 64


def _source(
    builder: RepositoryBuilder, path: str, raw: dict[str, str | None], *, capture: str = CAPTURE
) -> tuple[str, str]:
    locator = {"root": "data", "path": path, "row": None}
    occurrence = migration_entity_id(capture, "source_occurrence", locator)
    artifact = builder.publish_source(io.BytesIO(b"synthetic source bytes"))
    builder.add_source_occurrence(
        SourceOccurrenceRecord(occurrence, artifact.artifact_id, "legacy")
    )
    builder.add_migration_identity(
        MigrationIdentityRecord(occurrence, capture, "source_occurrence", locator)
    )
    locator = {**locator, "row": 1}
    observation = migration_entity_id(capture, "observation", locator)
    provenance = str(uuid4())
    builder.add_provenance(ProvenanceRecord(provenance, occurrence, locator, locator))
    builder.add_legacy_payload(
        provenance,
        {
            "columns": list(raw),
            "values": list(raw.values()),
            "cells": [
                {
                    "column": field,
                    "column_ordinal": index,
                    "state": "null" if value is None else "blank" if value == "" else "value",
                    "value": value,
                }
                for index, (field, value) in enumerate(raw.items())
            ],
        },
    )
    builder.add_observation(ObservationRecord(observation, occurrence, None, None, None, "unknown"))
    builder.add_migration_identity(
        MigrationIdentityRecord(observation, capture, "observation", locator)
    )
    return observation, provenance


def _amount(builder: RepositoryBuilder, provenance: str, lexical: str = "12.3400") -> str:
    value = str(uuid4())
    builder.add_exact_value(
        value,
        ExactValue.from_lexical(
            lexical, value_kind="money", origin_kind="migration", currency=UNKNOWN_CURRENCY
        ),
        provenance_id=provenance,
    )
    return value


def _balance(builder: RepositoryBuilder) -> tuple[str, str, str]:
    observation, provenance = _source(
        builder,
        "banksalad/balance/2026/09/balance.csv",
        {
            "snapshot_date": "2026-09-13",
            "source_fact_id": "fact",
            "amount": "12.3400",
            "side": "asset",
            "category": "",
            "item_name": "synthetic",
            "currency": None,
        },
    )
    amount = _amount(builder, provenance)
    builder.add_legacy_overview_report(
        LegacyOverviewReportRecord(observation, provenance, "balance", "2026-09-13")
    )
    builder.add_legacy_overview_balance(
        LegacyOverviewBalanceRecord(observation, amount, "asset", "", "synthetic")
    )
    return observation, provenance, amount


def test_v4_upgrade_adds_empty_v5_tables_without_mutating_source(tmp_path: Path) -> None:
    source, target = GenerationPaths(tmp_path / "old"), GenerationPaths(tmp_path / "new")
    with RepositoryBuilder(source, str(uuid4()), expected_schema_version=4) as builder:
        builder.finalize()
    before = source.database.read_bytes()
    info = upgrade_repository(source.database, target)
    assert info.schema_version == 5
    assert source.database.read_bytes() == before
    with RepositoryReader(source.database, expected_schema_version=4) as reader:
        assert reader.info.schema_version == 4
    with RepositoryReader(target.database) as reader:
        assert reader.rows("legacy_overview_reports") == []
    assert not (target.root / "migration-manifest.json").exists()


@pytest.mark.parametrize("count", [0, 1, 2])
def test_complete_candidate_set_keeps_unverified_and_distinct_occurrences(
    tmp_path: Path, count: int
) -> None:
    paths = GenerationPaths(tmp_path / "candidate")
    with RepositoryBuilder(paths, str(uuid4())) as builder:
        observation, _, _ = _balance(builder)
        candidates = [
            _source(
                builder,
                f"facts-{index}.csv",
                {"fact_id": "fact", "fact_kind": "invalid-but-preserved"},
            )
            for index in range(count)
        ]
        status = ("missing", "unverified", "ambiguous")[count]
        builder.add_legacy_overview_reference(
            LegacyOverviewReferenceRecord(observation, CAPTURE, "fact", status)
        )
        for candidate, provenance in candidates:
            builder.add_legacy_overview_candidate(
                LegacyOverviewCandidateRecord(observation, candidate, provenance)
            )
        builder.finalize()
    with RepositoryReader(paths.database) as reader:
        assert len(reader.rows("legacy_overview_reference_candidates")) == count
        assert reader.rows("overview_facts") == []
        assert reader.rows("legacy_overview_balances")[0]["amount_value_id"]


@pytest.mark.parametrize(
    "fault",
    [
        "missing_detail",
        "extra_detail",
        "missing_assessment",
        "omitted_candidate",
        "cross_capture",
        "wrong_provenance",
        "wrong_value",
        "status",
    ],
)
def test_report_closure_and_reference_forgery_rejected(tmp_path: Path, fault: str) -> None:
    with RepositoryBuilder(GenerationPaths(tmp_path / "candidate"), str(uuid4())) as builder:
        observation, provenance, amount = _balance(builder)
        if fault == "missing_detail":
            builder._connection.execute("DROP TRIGGER legacy_overview_balances_no_delete")
            builder._connection.execute("DELETE FROM legacy_overview_balances")
        if fault == "extra_detail":
            builder.add_legacy_overview_cashflow(
                LegacyOverviewCashflowRecord(observation, amount, "2026-09", "")
            )
        if fault == "wrong_value":
            wrong = _amount(builder, provenance, "99")
            builder._connection.execute("DROP TRIGGER legacy_overview_balances_no_update")
            builder._connection.execute(
                "UPDATE legacy_overview_balances SET amount_value_id = ?", (wrong,)
            )
        candidates = []
        if fault in {"omitted_candidate", "cross_capture", "wrong_provenance"}:
            candidates.append(
                _source(
                    builder,
                    "facts.csv",
                    {"fact_id": "fact", "fact_kind": "x"},
                    capture="b" * 64 if fault == "cross_capture" else CAPTURE,
                )
            )
        if fault != "missing_assessment":
            status = "unverified" if candidates or fault == "status" else "missing"
            builder.add_legacy_overview_reference(
                LegacyOverviewReferenceRecord(observation, CAPTURE, "fact", status)
            )
        if candidates and fault != "omitted_candidate":
            candidate, candidate_provenance = candidates[0]
            builder.add_legacy_overview_candidate(
                LegacyOverviewCandidateRecord(
                    observation,
                    candidate,
                    provenance if fault == "wrong_provenance" else candidate_provenance,
                )
            )
        with pytest.raises(RepositoryIntegrityError):
            builder.finalize()


@pytest.mark.parametrize(
    "table",
    [
        "reports",
        "balances",
        "cashflows",
        "insurance",
        "investments",
        "loans",
        "reference_assessments",
        "reference_candidates",
    ],
)
def test_new_evidence_tables_have_append_only_guards(tmp_path: Path, table: str) -> None:
    with RepositoryBuilder(GenerationPaths(tmp_path / "candidate"), str(uuid4())) as builder:
        triggers = {
            row[0]
            for row in builder._connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }
        assert f"legacy_overview_{table}_no_update" in triggers
        assert f"legacy_overview_{table}_no_delete" in triggers
        assert f"legacy_overview_{table}_no_replace" in triggers
        observation, _, amount = _balance(builder)
        builder.add_legacy_overview_cashflow(
            LegacyOverviewCashflowRecord(observation, amount, None, None)
        )
        builder.add_legacy_overview_insurance(
            LegacyOverviewInsuranceRecord(observation, None, None, None, None, None)
        )
        builder.add_legacy_overview_investment(
            LegacyOverviewInvestmentRecord(observation, None, None, None, None, None)
        )
        builder.add_legacy_overview_loan(
            LegacyOverviewLoanRecord(observation, None, None, None, None, None)
        )
        builder.add_legacy_overview_reference(
            LegacyOverviewReferenceRecord(observation, CAPTURE, "fact", "unverified")
        )
        candidate, provenance = _source(builder, "fact.csv", {"fact_id": "fact", "fact_kind": "x"})
        builder.add_legacy_overview_candidate(
            LegacyOverviewCandidateRecord(observation, candidate, provenance)
        )
        builder._connection.execute("PRAGMA recursive_triggers = OFF")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            builder._connection.execute(
                f"INSERT OR REPLACE INTO legacy_overview_{table} "
                f"SELECT * FROM legacy_overview_{table}"
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            builder._connection.execute(f"DELETE FROM legacy_overview_{table}")


@pytest.mark.parametrize("kind", ["cashflow", "insurance", "investment", "loan"])
def test_other_report_kinds_preserve_empty_text_and_absent_amounts(
    tmp_path: Path, kind: str
) -> None:
    with RepositoryBuilder(GenerationPaths(tmp_path / "candidate"), str(uuid4())) as builder:
        raw = {"snapshot_date": "2026-09-13", "source_fact_id": None}
        if kind == "cashflow":
            raw.update({"amount": "12.3400", "period_month": "2026-09", "category": ""})
        role = {"investment": "investments", "loan": "loans"}.get(kind, kind)
        observation, provenance = _source(builder, f"banksalad/{role}/2026/09/{role}.csv", raw)
        builder.add_legacy_overview_report(
            LegacyOverviewReportRecord(observation, provenance, kind, "2026-09-13")
        )
        if kind == "cashflow":
            builder.add_legacy_overview_cashflow(
                LegacyOverviewCashflowRecord(
                    observation, _amount(builder, provenance), "2026-09", ""
                )
            )
        elif kind == "insurance":
            builder.add_legacy_overview_insurance(
                LegacyOverviewInsuranceRecord(observation, None, None, None, None, None)
            )
        elif kind == "investment":
            builder.add_legacy_overview_investment(
                LegacyOverviewInvestmentRecord(observation, None, None, None, None, None)
            )
        else:
            builder.add_legacy_overview_loan(
                LegacyOverviewLoanRecord(observation, None, None, None, None, None)
            )
        builder.add_legacy_overview_reference(
            LegacyOverviewReferenceRecord(observation, CAPTURE, None, "missing")
        )
        builder.finalize()


def test_native_fact_occurrence_invariant_remains_enforced(tmp_path: Path) -> None:
    with RepositoryBuilder(GenerationPaths(tmp_path / "candidate"), str(uuid4())) as builder:
        observation, provenance, amount = _balance(builder)
        candidate, candidate_provenance = _source(
            builder, "fact.csv", {"fact_id": "fact", "fact_kind": "label"}
        )
        fact_id = str(uuid4())
        builder.add_overview_fact(
            OverviewFactRecord(
                fact_id,
                candidate,
                candidate_provenance,
                "2026-09-13",
                "sheet",
                "block",
                "title",
                "label",
                "text",
                value_text="synthetic",
            )
        )
        builder.add_overview_balance(
            OverviewBalanceRecord(
                str(uuid4()),
                observation,
                provenance,
                fact_id,
                amount,
                "2026-09-13",
                "asset",
                "",
                "synthetic",
            )
        )
        builder.add_legacy_overview_reference(
            LegacyOverviewReferenceRecord(observation, CAPTURE, "fact", "unverified")
        )
        builder.add_legacy_overview_candidate(
            LegacyOverviewCandidateRecord(observation, candidate, candidate_provenance)
        )
        with pytest.raises(RepositoryIntegrityError, match="different occurrences"):
            builder.finalize()


@pytest.mark.parametrize("unit", ["legacy_overview_return_rate.v1", "wrong_rate.v1"])
def test_rate_unit_is_fixed_by_report_role(tmp_path: Path, unit: str) -> None:
    with RepositoryBuilder(GenerationPaths(tmp_path / "candidate"), str(uuid4())) as builder:
        observation, provenance = _source(
            builder,
            "banksalad/investments/2026/09/investments.csv",
            {"snapshot_date": "2026-09-13", "source_fact_id": None, "return_rate": "0.0300"},
        )
        rate_id = str(uuid4())
        builder.add_exact_value(
            rate_id,
            ExactValue.from_lexical(
                "0.0300", value_kind="rate", origin_kind="migration", unit=unit
            ),
            provenance_id=provenance,
        )
        builder.add_legacy_overview_report(
            LegacyOverviewReportRecord(observation, provenance, "investment", "2026-09-13")
        )
        builder.add_legacy_overview_investment(
            LegacyOverviewInvestmentRecord(
                observation, None, None, None, None, None, return_rate_value_id=rate_id
            )
        )
        builder.add_legacy_overview_reference(
            LegacyOverviewReferenceRecord(observation, CAPTURE, None, "missing")
        )
        if unit == "wrong_rate.v1":
            with pytest.raises(RepositoryIntegrityError):
                builder.finalize()
        else:
            builder.finalize()


def test_report_kind_cannot_reinterpret_another_partition(tmp_path: Path) -> None:
    with RepositoryBuilder(GenerationPaths(tmp_path / "candidate"), str(uuid4())) as builder:
        observation, provenance = _source(
            builder,
            "banksalad/balance/2026/09/balance.csv",
            {
                "snapshot_date": "2026-09-13",
                "source_fact_id": None,
                "amount": "12.3400",
                "period_month": None,
                "category": None,
            },
        )
        builder.add_legacy_overview_report(
            LegacyOverviewReportRecord(observation, provenance, "cashflow", "2026-09-13")
        )
        builder.add_legacy_overview_cashflow(
            LegacyOverviewCashflowRecord(observation, _amount(builder, provenance), None, None)
        )
        builder.add_legacy_overview_reference(
            LegacyOverviewReferenceRecord(observation, CAPTURE, None, "missing")
        )
        with pytest.raises(RepositoryIntegrityError):
            builder.finalize()


def test_replace_cannot_steal_another_report_provenance(tmp_path: Path) -> None:
    with RepositoryBuilder(GenerationPaths(tmp_path / "candidate"), str(uuid4())) as builder:
        _, provenance, _ = _balance(builder)
        other, _ = _source(builder, "other.csv", {"untyped": None})
        builder._connection.execute("PRAGMA recursive_triggers = OFF")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            builder._connection.execute(
                "INSERT OR REPLACE INTO legacy_overview_reports VALUES (?, ?, ?, ?)",
                (other, provenance, "balance", "2026-09-13"),
            )


@pytest.mark.parametrize(
    "path",
    [
        "transactions/2026/09/transactions.csv",
        "banksalad/balance/2026/09/balance.csv",
        "banksalad/cashflow/2026/09/cashflow.csv",
        "banksalad/insurance/2026/09/insurance.csv",
        "banksalad/investments/2026/09/investments.csv",
        "banksalad/loans/2026/09/loans.csv",
    ],
)
def test_fact_index_skips_payload_decoding_for_other_dispatch_roles(
    monkeypatch: pytest.MonkeyPatch,
    path: str,
) -> None:
    from finjuice.pipeline.storage.sqlite import schema_v5

    def unexpected_decode(payload: str) -> dict[str, str | None]:
        pytest.fail("Excluded dispatch roles must not decode their CSV payload for fact indexing.")

    monkeypatch.setattr(schema_v5, "_payload_row", unexpected_decode)
    source = {"canonical_locator_json": json.dumps({"path": path}), "payload_json": "not decoded"}
    assert schema_v5._fact_index({"observation": source}) == {}
