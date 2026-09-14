"""Exact detached transaction snapshots, independent of CSV projections."""

from __future__ import annotations

import io
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    ConfigRevisionRecord,
    ExactValue,
    GenerationPaths,
    LegacyIdentifierRecord,
    ObservationRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    RepositoryReader,
    SourceOccurrenceRecord,
    TransactionRecord,
)
from finjuice.pipeline.storage.sqlite.exact import UNKNOWN_CURRENCY


def _id() -> str:
    return str(uuid4())


def _seed(tmp_path: Path, *, rules_head: bool = True) -> GenerationPaths:
    paths = GenerationPaths(tmp_path / "generation")
    occurrence, account, config = _id(), _id(), _id()
    with RepositoryBuilder(paths, _id()) as builder:
        artifact = builder.publish_source(io.BytesIO(b"rules: [\n"))
        builder.add_source_occurrence(
            SourceOccurrenceRecord(occurrence, artifact.artifact_id, "csv")
        )
        builder.add_account(AccountRecord(account, "unknown", "account"))
        builder.add_config_revision(
            ConfigRevisionRecord(config, "rules", artifact.artifact_id, occurrence, "invalid")
        )
        if rules_head:
            builder.set_config_head("rules", config, updated_at="2026-09-13")
        for index in range(3):
            provenance, observation, amount, transaction = _id(), _id(), _id(), _id()
            builder.add_provenance(
                ProvenanceRecord(
                    provenance, occurrence, {"row": index}, {"locator_version": 1, "row": index}
                )
            )
            builder.add_observation(
                ObservationRecord(observation, occurrence, None, None, None, "unknown")
            )
            builder.add_exact_value(
                amount,
                ExactValue.from_lexical(
                    "9007199254740993.0100", value_kind="money", currency=UNKNOWN_CURRENCY
                ),
                provenance_id=provenance,
            )
            builder.add_transaction(
                TransactionRecord(
                    transaction,
                    observation,
                    provenance,
                    account,
                    amount,
                    "2026-09-01",
                    "12:34",
                    "literal datetime",
                    "raw",
                    "expense",
                    "account",
                    notes_manual="line1\nline2",
                    category_manual="manual",
                    category_final="persisted final",
                    tags_manual_json='[" x ", " x "]',
                    tags_final_json='["persisted"]',
                )
            )
            if index < 2:
                builder.add_legacy_identifier(
                    LegacyIdentifierRecord(transaction, "row_hash", "same", "a" * 64, provenance)
                )
            if index == 1:
                for alias in ("first", "second"):
                    builder.add_legacy_identifier(
                        LegacyIdentifierRecord(transaction, "file_id", alias, "a" * 64, provenance)
                    )
        builder.finalize()
    return paths


def test_snapshot_preserves_exact_manual_native_and_duplicate_rows(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    before = {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()}
    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        snapshot = reader.transaction_snapshot()
        assert snapshot.info == reader.info
        assert snapshot.rules_content == b"rules: [\n"
        assert snapshot.rules_parsed_status == "invalid"
        assert len(snapshot.rows) == 3
        assert len({row["transaction_id"] for row in snapshot.rows}) == 3
        assert [row["row_hash"] for row in snapshot.rows].count("same") == 2
        assert [row["row_hash"] for row in snapshot.rows].count(None) == 1
        for row in snapshot.rows:
            assert row["amount"] == "9007199254740993.0100"
            assert row["amount_lexical"] == "9007199254740993.0100"
            assert row["amount_coefficient"] == "90071992547409930100"
            assert row["amount_scale"] == 4
            assert row["currency"] is None and row["currency_unknown"] == 1
            assert json.loads(row["tags_manual"]) == [" x ", " x "]
            assert row["tags_final"] == '["persisted"]'
            assert row["category_manual"] == "manual"
            assert row["category_final"] == "persisted final"
            assert row["datetime"] == "literal datetime"
            assert row["notes_manual"] == "line1\nline2"
            assert row["file_id"] is None
        snapshot.rows[0]["notes_manual"] = "detached edit"
        assert reader.transaction_snapshot().rows[0]["notes_manual"] == "line1\nline2"
    assert before == {p: p.read_bytes() for p in paths.root.rglob("*") if p.is_file()}
    with pytest.raises(RuntimeError, match="closed"):
        reader.transaction_snapshot()


def test_reader_remains_pinned_after_live_state_changes(tmp_path: Path) -> None:
    paths = _seed(tmp_path)
    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        first = reader.transaction_snapshot()
        # Simulate a subsequent committed state while the detached reader is open.
        with sqlite3.connect(paths.database) as connection:
            connection.execute("UPDATE transactions SET notes_manual = 'later'")
        second = reader.transaction_snapshot()
        assert first == second
    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        snapshot = reader.transaction_snapshot()
        assert all(row["notes_manual"] == "later" for row in snapshot.rows)
        assert snapshot.rules_content == first.rules_content


@pytest.mark.parametrize(
    ("coefficient", "scale", "expected"),
    [("-1", 4, "-0.0001"), ("0", 4, "0.0000"), ("123", 0, "123"), (None, None, None)],
)
def test_decimal_rendering_avoids_context_precision(
    coefficient: str | None, scale: int | None, expected: str | None
) -> None:
    from finjuice.pipeline.storage.sqlite.transaction_reads import _decimal

    assert _decimal(coefficient, scale) == expected


def test_unselected_rules_do_not_become_canonical(tmp_path: Path) -> None:
    paths = _seed(tmp_path, rules_head=False)
    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        snapshot = reader.transaction_snapshot()
        assert snapshot.rules_content is None
        assert snapshot.rules_parsed_status is None


@pytest.mark.parametrize("status", ["invalid", "opaque", "parsed"])
def test_valid_rules_bytes_keep_independent_parse_status(tmp_path: Path, status: str) -> None:
    from typing import Literal, cast

    paths = GenerationPaths(tmp_path / "generation")
    content = b"rules: []\n"
    occurrence, config = _id(), _id()
    with RepositoryBuilder(paths, _id()) as builder:
        artifact = builder.publish_source(io.BytesIO(content))
        builder.add_source_occurrence(
            SourceOccurrenceRecord(occurrence, artifact.artifact_id, "yaml")
        )
        builder.add_config_revision(
            ConfigRevisionRecord(
                config,
                "rules",
                artifact.artifact_id,
                occurrence,
                cast(Literal["parsed", "invalid", "opaque"], status),
            )
        )
        builder.set_config_head("rules", config, updated_at="2026-09-13")
        builder.finalize()
    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        snapshot = reader.transaction_snapshot()
        assert snapshot.rules_content == content
        assert snapshot.rules_parsed_status == status
