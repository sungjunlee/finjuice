"""Parity and atomicity tests for the shared typed-row SQLite writer."""

from __future__ import annotations

import io
import sqlite3
import uuid
from pathlib import Path
from typing import Any, Final

import pytest

from finjuice.pipeline.storage.sqlite import (
    UNKNOWN_CURRENCY,
    AccountRecord,
    AssetSnapshotRecord,
    ExactValue,
    GenerationPaths,
    ObservationRecord,
    OverviewBalanceRecord,
    OverviewCashflowRecord,
    OverviewFactRecord,
    OverviewInsuranceRecord,
    OverviewInvestmentRecord,
    OverviewLoanRecord,
    PartyRecord,
    PreservationIssueRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    RepositoryReader,
    ResourceRecord,
    SourceOccurrenceRecord,
    TransactionRecord,
)
from finjuice.pipeline.storage.sqlite import schema as sqlite_schema
from finjuice.pipeline.storage.sqlite.writes import TypedRowWriter, TypedWriteError

_NAMESPACE: Final = uuid.UUID("2f0c1a7e-3c7b-4a1d-9c3a-6a6a9f1e0d21")
_SOURCE_BYTES: Final = b"synthetic xlsx bytes for typed writer parity"
_ROW_HASH: Final = "same-legacy-row-hash"
_COMPARED_TABLES: Final = (
    "entities",
    "source_artifacts",
    "source_occurrences",
    "record_provenance",
    "exact_values",
    "money_values",
    "quantity_values",
    "rate_values",
    "number_values",
    "parties",
    "accounts",
    "resources",
    "observations",
    "transactions",
    "overview_facts",
    "overview_balances",
    "overview_cashflows",
    "overview_insurance",
    "overview_investments",
    "overview_loans",
    "asset_snapshots",
    "legacy_payloads",
    "preservation_issues",
)


def _sid(name: str) -> str:
    """Return a stable v4-shaped UUID so builder and writer rows are directly comparable.

    UUIDv5 entities would require migration identities, which this writer never publishes.
    """
    return str(uuid.UUID(bytes=uuid.uuid5(_NAMESPACE, name).bytes, version=4))


def _provenance(row: int, *, row_hash: str = _ROW_HASH) -> ProvenanceRecord:
    return ProvenanceRecord(
        provenance_id=_sid(f"provenance:{row}"),
        occurrence_id=_sid("occurrence"),
        source_coordinate={"sheet": "synthetic", "row": row, "col": "B"},
        legacy_locator={
            "locator_version": 1,
            "sheet": "synthetic",
            "row": row,
            "row_hash": row_hash,
        },
        parser_version="test-v1",
        source_schema_version="banksalad-2026",
    )


def _transaction(index: int, amount_id: str, **overrides: Any) -> TransactionRecord:
    fields: dict[str, Any] = {
        "transaction_id": _sid(f"transaction:{index}"),
        "observation_id": _sid("observation"),
        "provenance_id": _sid(f"provenance:{index}"),
        "account_id": _sid("account"),
        "amount_value_id": amount_id,
        "date_raw": "2026-09-01",
        "time_raw": "12:00:00",
        "datetime_raw": "2026-09-01 12:00:00",
        "type_raw": "지출",
        "type_norm": "expense",
        "account_text": "synthetic account",
    }
    fields.update(overrides)
    return TransactionRecord(**fields)


def _exact_values() -> dict[str, ExactValue]:
    """Representative exact shapes: sign, unknown currency, tiny, large, subtypes, calculated."""
    return {
        "amount:1": ExactValue.from_lexical("-1000.00", value_kind="money", currency="KRW"),
        "amount:2": ExactValue.from_lexical(
            "0.000001", value_kind="money", currency=UNKNOWN_CURRENCY
        ),
        "large": ExactValue.from_lexical(
            "123456789012345678901234567890.5", value_kind="money", currency="KRW"
        ),
        "count": ExactValue.from_lexical("42", value_kind="number", unit="count.v1"),
        "rate": ExactValue.from_lexical("3.25", value_kind="rate", unit="percent.v1"),
        "quantity": ExactValue.from_lexical("1.250", value_kind="quantity", unit="share.v1"),
        "calculated": ExactValue(
            coefficient="-10",
            scale=0,
            lexical=None,
            value_kind="money",
            origin_kind="calculated",
            currency="KRW",
        ),
    }


def _populate_foundation(target: TypedRowWriter | RepositoryBuilder, artifact_id: str) -> None:
    target.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=_sid("occurrence"),
            artifact_id=artifact_id,
            occurrence_kind="banksalad_xlsx",
            original_filename="synthetic.xlsx",
            imported_at="2026-09-02T00:00:00Z",
            parser_version="test-v1",
        )
    )
    for row in (1, 2, 3, 4, 5, 6, 7, 8, 9):
        target.add_provenance(_provenance(row))
    target.add_party(PartyRecord(party_id=_sid("party"), party_kind="person", display_name="P"))
    target.add_account(
        AccountRecord(
            account_id=_sid("account"),
            account_kind="bank.v1",
            display_name="synthetic account",
            ownership_state="asserted",
            owner_party_id=_sid("party"),
        )
    )
    target.add_resource(ResourceRecord(resource_id=_sid("resource"), resource_kind="equity.v1"))
    target.add_observation(
        ObservationRecord(
            observation_id=_sid("observation"),
            occurrence_id=_sid("occurrence"),
            observed_at=None,
            effective_at="2026-09-01",
            collected_at="2026-09-02T00:00:00Z",
            scope_state="partial",
        )
    )
    for name, value in _exact_values().items():
        target.add_exact_value(_sid(f"value:{name}"), value, provenance_id=_value_provenance(name))


def _value_provenance(name: str) -> str | None:
    """Source values bind to occurrence provenance; calculated values carry none."""
    if name == "calculated":
        return None
    return _sid(
        "provenance:" + name.removeprefix("amount:")
        if name.startswith("amount:")
        else "provenance:3"
    )


def _populate_transactions(target: TypedRowWriter | RepositoryBuilder) -> None:
    target.add_transaction(
        _transaction(
            1,
            _sid("value:amount:1"),
            major_raw="식비",
            minor_raw="카페",
            merchant_raw="synthetic cafe",
            memo_raw="memo",
            notes_manual="note",
            counterparty="cafe",
            category_rule="food",
            category_manual=None,
            category_final="food",
            tags_rule_json='["food", "cafe"]',
            tags_final_json='[ "food" ]',
            confidence_value_id=_sid("value:count"),
            needs_review=True,
            is_transfer_candidate=False,
            is_transfer=None,
            timezone_state="known",
        )
    )
    target.add_transaction(_transaction(2, _sid("value:amount:2")))
    target.add_legacy_payload(
        _sid("provenance:1"),
        {"raw_amount": "-1000.00", "row_hash": _ROW_HASH, "nested": {"z": 1, "a": [1, "x"]}},
        payload_id=_sid("payload"),
    )
    target.add_preservation_issue(
        PreservationIssueRecord(
            provenance_id=_sid("provenance:2"),
            issue_kind="unsupported_currency",
            detail={"column": "currency", "seen": "?"},
            field_name="currency",
            lexical_value="?",
            issue_id=_sid("issue"),
        )
    )


def _populate_overview_and_assets(target: TypedRowWriter | RepositoryBuilder) -> None:
    common = {"observation_id": _sid("observation"), "snapshot_date": "2026-09-01"}
    target.add_overview_fact(
        OverviewFactRecord(
            fact_id=_sid("fact"),
            provenance_id=_sid("provenance:3"),
            sheet_name="overview",
            block_id="assets",
            block_title="Assets",
            fact_kind="synthetic_count",
            value_type="number",
            row_label="row",
            column_label="col",
            numeric_value_id=_sid("value:count"),
            **common,
        )
    )
    fact = {"source_fact_id": _sid("fact"), **common}
    target.add_overview_balance(
        OverviewBalanceRecord(
            balance_id=_sid("balance"),
            provenance_id=_sid("provenance:4"),
            amount_value_id=_sid("value:large"),
            side="asset",
            category="cash",
            item_name="synthetic balance",
            **fact,
        )
    )
    target.add_overview_cashflow(
        OverviewCashflowRecord(
            cashflow_id=_sid("cashflow"),
            provenance_id=_sid("provenance:5"),
            amount_value_id=_sid("value:calculated"),
            period_month="2026-09",
            category="income",
            **fact,
        )
    )
    target.add_overview_insurance(
        OverviewInsuranceRecord(
            insurance_id=_sid("insurance"),
            provenance_id=_sid("provenance:6"),
            paid_amount_value_id=None,
            institution="insurer",
            policy_name="policy",
            contract_status="active",
            **fact,
        )
    )
    target.add_overview_investment(
        OverviewInvestmentRecord(
            investment_id=_sid("investment"),
            provenance_id=_sid("provenance:7"),
            principal_value_id=_sid("value:large"),
            valuation_value_id=None,
            return_rate_value_id=_sid("value:rate"),
            institution="broker",
            product_name="fund",
            product_type="fund",
            start_date="2026-01-01",
            **fact,
        )
    )
    target.add_overview_loan(
        OverviewLoanRecord(
            loan_id=_sid("loan"),
            provenance_id=_sid("provenance:8"),
            principal_value_id=None,
            balance_value_id=_sid("value:amount:1"),
            interest_rate_value_id=_sid("value:rate"),
            institution="bank",
            product_name="loan",
            maturity_date="2030-01-01",
            **fact,
        )
    )
    target.add_asset_snapshot(
        AssetSnapshotRecord(
            snapshot_id=_sid("asset"),
            provenance_id=_sid("provenance:9"),
            account_id=_sid("account"),
            resource_id=_sid("resource"),
            quantity_value_id=_sid("value:quantity"),
            market_value_id=_sid("value:large"),
            **common,
        )
    )


def _populate(target: TypedRowWriter | RepositoryBuilder, artifact_id: str) -> None:
    _populate_foundation(target, artifact_id)
    _populate_transactions(target)
    _populate_overview_and_assets(target)


def _rows(connection: sqlite3.Connection, table: str) -> list[dict[str, Any]]:
    assert table in _COMPARED_TABLES
    cursor = connection.execute(f"SELECT * FROM {table}")
    names = [description[0] for description in cursor.description]
    return sorted(
        (dict(zip(names, row, strict=True)) for row in cursor.fetchall()),
        key=lambda row: str(row[names[0]]),
    )


def _open_writer_database(path: Path) -> sqlite3.Connection:
    """Create a synthetic current-schema database with the caller in autocommit control."""
    connection = sqlite3.connect(path, isolation_level=None)
    connection.execute("PRAGMA foreign_keys = ON")
    sqlite_schema._apply_schema_v1(connection, _sid("generation"))
    sqlite_schema._apply_schema_v2(connection)
    sqlite_schema._apply_schema_v3(connection)
    sqlite_schema._apply_schema_v4(connection)
    return connection


def _build_reference(tmp_path: Path) -> tuple[GenerationPaths, tuple[Any, ...]]:
    paths = GenerationPaths(tmp_path / "reference")
    with RepositoryBuilder(paths, _sid("generation")) as builder:
        artifact = builder.publish_source(io.BytesIO(_SOURCE_BYTES))
        _populate(builder, artifact.artifact_id)
        builder.finalize()
    artifact_row = (
        artifact.artifact_id,
        artifact.digest_hex,
        artifact.byte_length,
        artifact.relative_path,
    )
    return paths, artifact_row


@pytest.fixture
def writer_connection(tmp_path: Path) -> sqlite3.Connection:
    connection = _open_writer_database(tmp_path / "writer.db")
    yield connection
    connection.close()


def test_writer_rows_match_builder_rows_for_all_typed_shapes(
    tmp_path: Path, writer_connection: sqlite3.Connection
) -> None:
    reference_paths, artifact_row = _build_reference(tmp_path)

    writer_connection.execute("BEGIN")
    writer_connection.execute(
        "INSERT INTO source_artifacts (source_artifact_id, digest_hex, byte_length, object_path) "
        "VALUES (?, ?, ?, ?)",
        artifact_row,
    )
    _populate(TypedRowWriter(writer_connection), artifact_row[0])
    writer_connection.execute("COMMIT")

    with RepositoryReader(reference_paths.database) as reader:
        for table in _COMPARED_TABLES:
            expected = sorted(reader.rows(table), key=lambda row: str(next(iter(row.values()))))
            assert _rows(writer_connection, table) == expected, table
    assert len(_rows(writer_connection, "transactions")) == 2
    assert writer_connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_writer_preserves_exact_sign_lexical_and_unknown_currency(
    writer_connection: sqlite3.Connection,
) -> None:
    writer = TypedRowWriter(writer_connection)
    writer_connection.execute("BEGIN")
    for name, value in _exact_values().items():
        writer.add_exact_value(_sid(f"value:{name}"), value)

    exact = {row["value_id"]: row for row in _rows(writer_connection, "exact_values")}
    money = {row["value_id"]: row for row in _rows(writer_connection, "money_values")}
    negative = exact[_sid("value:amount:1")]
    assert (negative["coefficient"], negative["scale"], negative["lexical"]) == (
        "-100000",
        2,
        "-1000.00",
    )
    tiny = exact[_sid("value:amount:2")]
    assert (tiny["coefficient"], tiny["scale"], tiny["lexical"]) == ("1", 6, "0.000001")
    assert money[_sid("value:amount:2")]["currency_code"] is None
    assert money[_sid("value:amount:2")]["currency_unknown"] == 1
    large = exact[_sid("value:large")]
    assert (large["coefficient"], large["scale"]) == ("1234567890123456789012345678905", 1)
    calculated = exact[_sid("value:calculated")]
    assert (calculated["lexical"], calculated["origin_kind"]) == (None, "calculated")
    assert {row["value_id"] for row in _rows(writer_connection, "rate_values")} == {
        _sid("value:rate")
    }


def test_same_row_hash_with_different_provenance_stays_distinct(
    writer_connection: sqlite3.Connection,
) -> None:
    writer = TypedRowWriter(writer_connection)
    writer_connection.execute("BEGIN")
    writer.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=_sid("occurrence"),
            artifact_id=_register_artifact(writer_connection),
            occurrence_kind="banksalad_xlsx",
        )
    )
    writer.add_provenance(_provenance(7))
    writer.add_provenance(_provenance(8))

    hashes = writer_connection.execute(
        "SELECT provenance_id, json_extract(legacy_locator_json, '$.row_hash') "
        "FROM record_provenance ORDER BY provenance_id"
    ).fetchall()
    assert [row[1] for row in hashes] == [_ROW_HASH, _ROW_HASH]
    assert len({row[0] for row in hashes}) == 2
    with pytest.raises(sqlite3.IntegrityError):
        writer.add_provenance(_provenance(7))
    assert len(_rows(writer_connection, "record_provenance")) == 2


def test_writer_rejects_writes_outside_a_caller_transaction(
    writer_connection: sqlite3.Connection,
) -> None:
    writer = TypedRowWriter(writer_connection)
    assert not writer_connection.in_transaction

    with pytest.raises(TypedWriteError):
        writer.add_party(PartyRecord(party_id=_sid("party")))
    with pytest.raises(TypedWriteError):
        writer.add_exact_value(_sid("value:count"), _exact_values()["count"])

    assert _rows(writer_connection, "entities") == []
    assert _rows(writer_connection, "exact_values") == []
    assert not writer_connection.in_transaction


def test_failed_second_step_leaves_no_orphan_and_keeps_caller_state(
    writer_connection: sqlite3.Connection,
) -> None:
    writer = TypedRowWriter(writer_connection)
    writer_connection.execute("BEGIN")
    writer.add_party(PartyRecord(party_id=_sid("party")))
    writer_connection.execute("SAVEPOINT caller_scope")
    writer.add_resource(ResourceRecord(resource_id=_sid("resource"), resource_kind="equity.v1"))
    writer_connection.execute(
        "CREATE TEMP TRIGGER reject_synthetic_money BEFORE INSERT ON money_values "
        "WHEN NEW.currency_code = 'XTS' BEGIN SELECT RAISE(ABORT, 'synthetic fault'); END"
    )

    with pytest.raises(sqlite3.IntegrityError):
        writer.add_transaction(_transaction(1, _sid("value:amount:1")))
    with pytest.raises(sqlite3.IntegrityError):
        writer.add_exact_value(
            _sid("value:fault"),
            ExactValue.from_lexical("1", value_kind="money", currency="XTS"),
        )

    assert {row["entity_kind"] for row in _rows(writer_connection, "entities")} == {
        "party",
        "resource",
    }
    assert _rows(writer_connection, "transactions") == []
    assert _rows(writer_connection, "exact_values") == []
    assert writer_connection.in_transaction
    writer_connection.execute("ROLLBACK TO caller_scope")
    writer_connection.execute("RELEASE caller_scope")
    assert [row["entity_kind"] for row in _rows(writer_connection, "entities")] == ["party"]
    writer.add_exact_value(_sid("value:count"), _exact_values()["count"])
    writer_connection.execute("COMMIT")
    assert len(_rows(writer_connection, "number_values")) == 1


def test_outer_rollback_removes_every_writer_row_and_writer_never_commits(
    tmp_path: Path, writer_connection: sqlite3.Connection
) -> None:
    database = tmp_path / "writer.db"
    writer_connection.execute("BEGIN")
    artifact_id = _register_artifact(writer_connection)
    _populate(TypedRowWriter(writer_connection), artifact_id)
    assert writer_connection.in_transaction

    observer = sqlite3.connect(database, isolation_level=None)
    try:
        assert observer.execute("SELECT count(*) FROM entities").fetchone()[0] == 0
    finally:
        observer.close()
    writer_connection.execute("ROLLBACK")

    for table in _COMPARED_TABLES:
        assert _rows(writer_connection, table) == [], table


def test_writer_validates_ids_and_json_before_touching_tables(
    writer_connection: sqlite3.Connection,
) -> None:
    writer = TypedRowWriter(writer_connection)
    writer_connection.execute("BEGIN")

    with pytest.raises(ValueError):
        writer.add_party(PartyRecord(party_id="not-a-uuid"))
    with pytest.raises(ValueError):
        writer.add_legacy_payload(_sid("provenance:1"), {"nan": float("nan")})
    with pytest.raises(ValueError):
        writer.add_transaction(_transaction(1, _sid("value:amount:1"), tags_rule_json='{"a":1}'))

    assert _rows(writer_connection, "entities") == []
    assert writer_connection.in_transaction


def _register_artifact(connection: sqlite3.Connection) -> str:
    digest = "ab" * 32
    connection.execute(
        "INSERT INTO source_artifacts (source_artifact_id, digest_hex, byte_length, object_path) "
        "VALUES (?, ?, ?, ?)",
        (f"sha256:{digest}", digest, len(_SOURCE_BYTES), f"objects/sha256/ab/{digest}"),
    )
    return f"sha256:{digest}"
