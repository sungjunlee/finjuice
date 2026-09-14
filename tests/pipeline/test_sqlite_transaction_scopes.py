"""Partition evidence remains separate from raw dates and transaction aliases."""

from __future__ import annotations

import io
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.migration.adapters import FileContext, preserve_file
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    ExactValue,
    GenerationPaths,
    ObservationRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    RepositoryReader,
    SourceOccurrenceRecord,
    TransactionRecord,
)
from finjuice.pipeline.storage.sqlite.transaction_scopes import transaction_scopes

HEADER = (
    "row_hash,date,time,datetime,type_norm,account,amount,"
    "tags_rule,tags_ai,tags_manual,tags_final\n"
)
ROW = "duplicate,not-a-date,12:00,2020-01-02T12:00,expense,account,1.00,[],[],[],[]\n"


def _id() -> str:
    return str(uuid4())


def _migration(tmp_path: Path) -> GenerationPaths:
    paths = GenerationPaths(tmp_path / "generation")
    inputs = [
        ("data", "transactions/2026/01/transactions.csv", HEADER + ROW + ROW),
        ("data", "transactions/2026/12/transactions.csv", HEADER),
        ("supplement", "transactions/2026/11/transactions.csv", HEADER + ROW),
        ("data", "archive/transactions/2026/10/transactions.csv", HEADER + ROW),
    ]
    with RepositoryBuilder(paths, _id()) as builder:
        for index, (root, path, content) in enumerate(inputs):
            source = tmp_path / f"source-{index}.csv"
            source.write_text(content)
            preserve_file(builder, source, FileContext("a" * 64, root, path))
        builder.finalize()
    return paths


def test_migration_scope_uses_exact_primary_path_and_keeps_empty_latest(tmp_path: Path) -> None:
    paths = _migration(tmp_path)
    with RepositoryReader(paths.database) as reader:
        snapshot = reader.transaction_snapshot()
    assert snapshot.partition_months == ("2026-01", "2026-12")
    included = [scope for scope in snapshot.scopes if scope.included]
    assert len(included) == 2
    assert {scope.month for scope in included} == {"2026-01"}
    assert sorted(scope.source_row for scope in included) == [1, 2]
    assert all(scope.source_row is None for scope in snapshot.scopes if not scope.included)
    assert len({scope.transaction_id for scope in snapshot.scopes}) == 4
    assert all(row["row_hash"] == "duplicate" for row in snapshot.rows)
    assert all(row["date"] == "not-a-date" for row in snapshot.rows)
    assert len([scope for scope in snapshot.scopes if not scope.included]) == 2


def _native(tmp_path: Path, values: list[str | None]) -> GenerationPaths:
    paths = GenerationPaths(tmp_path / "generation")
    with RepositoryBuilder(paths, _id()) as builder:
        artifact = builder.publish_source(io.BytesIO(b"synthetic native source"))
        occurrence, account = _id(), _id()
        builder.add_source_occurrence(
            SourceOccurrenceRecord(occurrence, artifact.artifact_id, "exact_xlsx_import")
        )
        builder.add_account(AccountRecord(account, "unknown", "account"))
        for index, effective in enumerate(values):
            provenance, observation, amount = _id(), _id(), _id()
            builder.add_provenance(
                ProvenanceRecord(provenance, occurrence, {"row": index}, {"row": index})
            )
            builder.add_observation(
                ObservationRecord(observation, occurrence, None, effective, None, "unknown")
            )
            builder.add_exact_value(
                amount,
                ExactValue.from_lexical("1", value_kind="money", currency="USD"),
                provenance_id=provenance,
            )
            builder.add_transaction(
                TransactionRecord(
                    _id(),
                    observation,
                    provenance,
                    account,
                    amount,
                    "different raw date",
                    "",
                    "",
                    type_raw=None,
                    type_norm="expense",
                    account_text="account",
                )
            )
        builder.finalize()
    return paths


def test_native_month_uses_validated_effective_date_without_timezone_conversion(
    tmp_path: Path,
) -> None:
    paths = _native(
        tmp_path,
        ["2026-01-31T23:59:00-12:00", "2026-02-01", None, "2026-02-30", "2026-05-01garbage"],
    )
    with RepositoryReader(paths.database) as reader:
        snapshot = reader.transaction_snapshot()
    assert snapshot.partition_months == ("2026-01", "2026-02")
    assert all(scope.included for scope in snapshot.scopes)
    assert all(scope.source_row is None for scope in snapshot.scopes)
    assert [scope.month for scope in snapshot.scopes].count(None) == 3


def test_scope_reader_remains_pinned_after_live_repository_changes(tmp_path: Path) -> None:
    paths = _native(tmp_path, ["2026-01-01"])
    with RepositoryReader(paths.database) as reader:
        with sqlite3.connect(paths.database) as connection:
            # The fixture changes only mutable observation metadata in its synthetic repository.
            connection.execute("UPDATE observations SET effective_at = '2026-02-01'")
        assert reader.transaction_snapshot().partition_months == ("2026-01",)
    with RepositoryReader(paths.database) as reader:
        assert reader.transaction_snapshot().partition_months == ("2026-02",)


@pytest.mark.parametrize("column", ["source_coordinate_json", "legacy_locator_json"])
def test_migration_proof_failure_does_not_fall_back_to_native_date(
    tmp_path: Path, column: str
) -> None:
    paths = _migration(tmp_path)
    with sqlite3.connect(":memory:") as connection, sqlite3.connect(paths.database) as original:
        original.backup(connection)
        for (trigger,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall():
            connection.execute(f'DROP TRIGGER "{trigger}"')
        # Fixed parameterized data in an isolated scratch copy tests defensive scope classification.
        for (provenance,) in connection.execute(
            "SELECT provenance_id FROM record_provenance"
        ).fetchall():
            connection.execute(
                f"UPDATE record_provenance SET {column} = ? WHERE provenance_id = ?",
                ('{"different": "' + provenance + '"}', provenance),
            )
        connection.execute("UPDATE observations SET effective_at = '2026-09-01'")
        ids = tuple(
            row[0]
            for row in connection.execute("SELECT entity_id FROM transactions ORDER BY entity_id")
        )
        scopes, months = transaction_scopes(connection, ids)
    assert months == ()
    assert all(
        not scope.included and scope.month is None and scope.source_row is None for scope in scopes
    )


def test_file_inventory_query_excludes_row_payloads_and_missing_row_key(tmp_path: Path) -> None:
    from finjuice.pipeline.storage.sqlite.transaction_scopes import _SOURCE_SQL

    paths = _migration(tmp_path)
    with sqlite3.connect(":memory:") as connection, sqlite3.connect(paths.database) as original:
        original.backup(connection)
        files = connection.execute(_SOURCE_SQL).fetchall()
        assert len(files) == 4
        assert all('"raw_record"' not in row[-1] for row in files)
        for (trigger,) in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        ).fetchall():
            connection.execute(f'DROP TRIGGER "{trigger}"')
        connection.execute(
            "UPDATE record_provenance "
            "SET source_coordinate_json = json_remove(source_coordinate_json, '$.row') "
            "WHERE json_type(source_coordinate_json, '$.row') = 'null'"
        )
        assert connection.execute(_SOURCE_SQL).fetchall() == []
