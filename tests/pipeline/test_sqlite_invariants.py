"""Application-invariant and builder-lifecycle tests for SQLite preservation storage."""

from __future__ import annotations

import io
import json
import os
import sqlite3
import stat
from decimal import Decimal
from pathlib import Path

import pytest

from finjuice.pipeline.storage.sqlite import (
    UNKNOWN_CURRENCY,
    AccountRecord,
    AssetSnapshotRecord,
    ConfigRevisionRecord,
    ExactValue,
    GenerationPaths,
    LegacyIdentifierRecord,
    MigrationIdentityRecord,
    ObservationRecord,
    OverviewBalanceRecord,
    OverviewFactRecord,
    PartyRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    RepositoryReader,
    ResourceRecord,
    SourceOccurrenceRecord,
    TransactionRecord,
    inspect_repository,
    migration_entity_id,
    new_entity_id,
    upgrade_repository,
    validate_repository,
)
from finjuice.pipeline.storage.sqlite import repository as repository_module
from finjuice.pipeline.storage.sqlite import schema as sqlite_schema
from finjuice.pipeline.storage.sqlite.errors import (
    RepositoryIntegrityError,
    RepositorySnapshotError,
)


def _source_context(
    builder: RepositoryBuilder,
    content: bytes = b"synthetic source",
) -> tuple[str, str]:
    artifact = builder.publish_source(io.BytesIO(content))
    occurrence_id = new_entity_id()
    builder.add_source_occurrence(
        SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact.artifact_id,
            occurrence_kind="synthetic",
        )
    )
    return artifact.artifact_id, occurrence_id


def _add_provenance(
    builder: RepositoryBuilder,
    occurrence_id: str,
    locator: dict[str, object],
) -> str:
    provenance_id = new_entity_id()
    builder.add_provenance(
        ProvenanceRecord(
            provenance_id=provenance_id,
            occurrence_id=occurrence_id,
            source_coordinate={"row": locator["row"]},
            legacy_locator=locator,
        )
    )
    return provenance_id


def test_entity_add_savepoint_rolls_back_failed_subtype_insert(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "atomic-entity")
    party_id = new_entity_id()

    with RepositoryBuilder(paths, new_entity_id()) as builder:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            builder.add_party(PartyRecord(party_id=party_id, party_kind="invalid"))  # type: ignore[arg-type]
        builder.add_party(PartyRecord(party_id=party_id, party_kind="person"))
        builder.finalize()

    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        assert reader.rows("parties") == [
            {
                "entity_id": party_id,
                "entity_kind": "party",
                "party_kind": "person",
                "display_name": None,
            }
        ]


def test_exact_add_savepoint_rolls_back_wrong_subtype_insert(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "atomic-exact")
    value_id = new_entity_id()
    value = ExactValue.from_lexical(
        "1.25",
        value_kind="quantity",
        origin_kind="calculated",
        unit="share.v1",
    )
    original_sql = repository_module._EXACT_SUBTYPE_INSERT_SQL["quantity"]

    with RepositoryBuilder(paths, new_entity_id()) as builder:
        monkeypatch.setitem(
            repository_module._EXACT_SUBTYPE_INSERT_SQL,
            "quantity",
            "INSERT INTO rate_values (value_id, unit) VALUES (?, ?)",
        )
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
            builder.add_exact_value(value_id, value)
        monkeypatch.setitem(
            repository_module._EXACT_SUBTYPE_INSERT_SQL,
            "quantity",
            original_sql,
        )
        builder.add_exact_value(value_id, value)
        builder.finalize()

    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        assert [row["value_id"] for row in reader.rows("exact_values")] == [value_id]
        assert [row["value_id"] for row in reader.rows("quantity_values")] == [value_id]
        assert reader.rows("rate_values") == []


@pytest.mark.parametrize(
    "orphan_sql",
    [
        "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'party')",
        "INSERT INTO exact_values "
        "(value_id, value_kind, coefficient, scale, lexical, origin_kind) "
        "VALUES (?, 'money', '1', 0, '1', 'source')",
    ],
)
def test_finalize_rejects_missing_application_subtype(
    tmp_path: Path,
    orphan_sql: str,
) -> None:
    paths = GenerationPaths(tmp_path / new_entity_id())
    builder = RepositoryBuilder(paths, new_entity_id())
    builder._connection.execute(orphan_sql, (new_entity_id(),))

    with pytest.raises(RepositoryIntegrityError, match="missing its matching"):
        builder.finalize()

    assert not paths.database.exists()


def test_repository_metadata_allows_forward_progress_but_rejects_identity_rewrite(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "protected-metadata")
    generation = new_entity_id()
    with RepositoryBuilder(paths, generation) as builder:
        builder.finalize()

    connection = sqlite3.connect(paths.database)
    try:
        connection.execute("UPDATE repository_meta SET dataset_revision = 2 WHERE singleton = 1")
        connection.commit()
        connection.execute("UPDATE repository_meta SET schema_version = 2 WHERE singleton = 1")
        assert connection.execute(
            "SELECT schema_version FROM repository_meta WHERE singleton = 1"
        ).fetchone() == (2,)
        connection.rollback()

        guarded_statements = (
            (
                "UPDATE repository_meta SET application_id = ? WHERE singleton = 1",
                (1,),
            ),
            (
                "UPDATE repository_meta SET dataset_generation = ? WHERE singleton = 1",
                (new_entity_id(),),
            ),
            (
                "UPDATE repository_meta SET schema_version = 0 WHERE singleton = 1",
                (),
            ),
            (
                "UPDATE repository_meta SET dataset_revision = 1 WHERE singleton = 1",
                (),
            ),
            ("DELETE FROM repository_meta WHERE singleton = 1", ()),
            (
                "INSERT OR REPLACE INTO repository_meta "
                "(singleton, application_id, schema_version, dataset_generation, "
                "dataset_revision) VALUES (1, ?, 1, ?, 3)",
                (sqlite_schema.SQLITE_APPLICATION_ID, new_entity_id()),
            ),
        )
        for statement, parameters in guarded_statements:
            with pytest.raises(sqlite3.IntegrityError, match="protected repository metadata"):
                connection.execute(statement, parameters)
            connection.rollback()
    finally:
        connection.close()

    info = validate_repository(paths.database, scratch_root=tmp_path / "scratch")
    assert info.dataset_generation == generation
    assert info.dataset_revision == 2


def test_schema_migration_ledger_is_immutable_and_must_match_current_version(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "migration-ledger")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        builder.finalize()

    connection = sqlite3.connect(paths.database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
            connection.execute(
                "UPDATE schema_migrations SET migration_name = 'rewritten' WHERE schema_version = 1"
            )
        connection.rollback()
        with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
            connection.execute("DELETE FROM schema_migrations WHERE schema_version = 1")
        connection.rollback()
        connection.execute("DROP TRIGGER schema_migrations_no_delete")
        connection.execute("DELETE FROM schema_migrations WHERE schema_version = 1")
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RepositoryIntegrityError, match="migration ledger"):
        validate_repository(paths.database, scratch_root=tmp_path / "scratch")


def test_source_binding_checks_cover_every_observation_backed_typed_table() -> None:
    assert set(sqlite_schema._OBSERVATION_PROVENANCE_TABLES) == {
        "transactions",
        "overview_facts",
        "overview_balances",
        "overview_cashflows",
        "overview_insurance",
        "overview_investments",
        "overview_loans",
        "asset_snapshots",
    }


def test_typed_record_rejects_observation_and_provenance_from_different_occurrences(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "typed-source-mismatch")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, first_occurrence = _source_context(builder, b"first source")
        _, second_occurrence = _source_context(builder, b"second source")
        observation_id = new_entity_id()
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=first_occurrence,
                observed_at=None,
                effective_at=None,
                collected_at=None,
                scope_state="unknown",
            )
        )
        provenance_id = _add_provenance(
            builder,
            second_occurrence,
            {"locator_version": 1, "row": 1},
        )
        builder.add_overview_fact(
            OverviewFactRecord(
                fact_id=new_entity_id(),
                observation_id=observation_id,
                provenance_id=provenance_id,
                snapshot_date="2026-09-01",
                sheet_name="overview",
                block_id="text",
                block_title="Text",
                fact_kind="text",
                value_type="text",
                value_text="evidence",
            )
        )

        with pytest.raises(RepositoryIntegrityError, match="different source occurrences"):
            builder.finalize()


def test_config_revision_rejects_artifact_from_a_different_occurrence(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "config-source-mismatch")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        first_artifact, _ = _source_context(builder, b"first config")
        _, second_occurrence = _source_context(builder, b"second config")
        builder.add_config_revision(
            ConfigRevisionRecord(
                revision_id=new_entity_id(),
                config_kind="rules",
                artifact_id=first_artifact,
                occurrence_id=second_occurrence,
                parsed_status="parsed",
                canonical_payload={"rules": []},
            )
        )

        with pytest.raises(RepositoryIntegrityError, match="does not match its source"):
            builder.finalize()


def test_source_exact_value_requires_provenance_but_calculated_value_does_not(
    tmp_path: Path,
) -> None:
    calculated_paths = GenerationPaths(tmp_path / "calculated-without-provenance")
    calculated_id = new_entity_id()
    with RepositoryBuilder(calculated_paths, new_entity_id()) as builder:
        builder.add_exact_value(
            calculated_id,
            ExactValue.from_lexical(
                "1",
                value_kind="number",
                origin_kind="calculated",
                unit="count.v1",
            ),
        )
        builder.finalize()

    source_paths = GenerationPaths(tmp_path / "source-without-provenance")
    with RepositoryBuilder(source_paths, new_entity_id()) as builder:
        builder.add_exact_value(
            new_entity_id(),
            ExactValue.from_lexical("1", value_kind="number", unit="count.v1"),
        )
        with pytest.raises(RepositoryIntegrityError, match="missing provenance"):
            builder.finalize()

    with RepositoryReader(
        calculated_paths.database,
        scratch_root=tmp_path / "scratch",
    ) as reader:
        assert reader.rows("exact_values")[0]["provenance_id"] is None


def test_typed_record_rejects_source_exact_value_from_a_different_occurrence(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "exact-source-mismatch")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, first_occurrence = _source_context(builder, b"first values")
        _, second_occurrence = _source_context(builder, b"second values")
        observation_id = new_entity_id()
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=first_occurrence,
                observed_at=None,
                effective_at=None,
                collected_at=None,
                scope_state="unknown",
            )
        )
        fact_provenance = _add_provenance(
            builder,
            first_occurrence,
            {"locator_version": 1, "row": 1},
        )
        value_provenance = _add_provenance(
            builder,
            second_occurrence,
            {"locator_version": 1, "row": 2},
        )
        value_id = new_entity_id()
        builder.add_exact_value(
            value_id,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=value_provenance,
        )
        builder.add_overview_fact(
            OverviewFactRecord(
                fact_id=new_entity_id(),
                observation_id=observation_id,
                provenance_id=fact_provenance,
                snapshot_date="2026-09-01",
                sheet_name="overview",
                block_id="money",
                block_title="Money",
                fact_kind="amount",
                value_type="number",
                numeric_value_id=value_id,
            )
        )

        with pytest.raises(RepositoryIntegrityError, match="exact value.*different"):
            builder.finalize()


def test_overview_projection_rejects_source_fact_from_a_different_occurrence(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "projection-source-mismatch")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, first_occurrence = _source_context(builder, b"first overview")
        _, second_occurrence = _source_context(builder, b"second overview")
        first_observation = new_entity_id()
        second_observation = new_entity_id()
        for observation_id, occurrence_id in (
            (first_observation, first_occurrence),
            (second_observation, second_occurrence),
        ):
            builder.add_observation(
                ObservationRecord(
                    observation_id=observation_id,
                    occurrence_id=occurrence_id,
                    observed_at=None,
                    effective_at=None,
                    collected_at=None,
                    scope_state="unknown",
                )
            )
        fact_provenance = _add_provenance(
            builder,
            first_occurrence,
            {"locator_version": 1, "row": 1},
        )
        projection_provenance = _add_provenance(
            builder,
            second_occurrence,
            {"locator_version": 1, "row": 2},
        )
        value_id = new_entity_id()
        builder.add_exact_value(
            value_id,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=fact_provenance,
        )
        fact_id = new_entity_id()
        builder.add_overview_fact(
            OverviewFactRecord(
                fact_id=fact_id,
                observation_id=first_observation,
                provenance_id=fact_provenance,
                snapshot_date="2026-09-01",
                sheet_name="overview",
                block_id="balance",
                block_title="Balance",
                fact_kind="amount",
                value_type="number",
                numeric_value_id=value_id,
            )
        )
        projection_value_id = new_entity_id()
        builder.add_exact_value(
            projection_value_id,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=projection_provenance,
        )
        builder.add_overview_balance(
            OverviewBalanceRecord(
                balance_id=new_entity_id(),
                observation_id=second_observation,
                provenance_id=projection_provenance,
                source_fact_id=fact_id,
                amount_value_id=projection_value_id,
                snapshot_date="2026-09-01",
                side="asset",
                category="cash",
                item_name="cash",
            )
        )

        with pytest.raises(RepositoryIntegrityError, match="source fact.*different"):
            builder.finalize()


def test_same_occurrence_allows_distinct_overview_observations_and_calculation_sources(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "same-occurrence-distinct-observations")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, occurrence_id = _source_context(builder, b"one overview file")
        observations = [new_entity_id(), new_entity_id()]
        for index, observation_id in enumerate(observations, start=1):
            builder.add_observation(
                ObservationRecord(
                    observation_id=observation_id,
                    occurrence_id=occurrence_id,
                    observed_at=None,
                    effective_at=f"2026-09-0{index}",
                    collected_at=None,
                    scope_state="partial",
                )
            )
        provenances = [
            _add_provenance(
                builder,
                occurrence_id,
                {"locator_version": 1, "row": row},
            )
            for row in (1, 2)
        ]
        fact_value_id = new_entity_id()
        builder.add_exact_value(
            fact_value_id,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=provenances[0],
        )
        fact_id = new_entity_id()
        builder.add_overview_fact(
            OverviewFactRecord(
                fact_id=fact_id,
                observation_id=observations[0],
                provenance_id=provenances[0],
                snapshot_date="2026-09-01",
                sheet_name="overview",
                block_id="balance",
                block_title="Balance",
                fact_kind="amount",
                value_type="number",
                numeric_value_id=fact_value_id,
            )
        )
        calculated_id = new_entity_id()
        builder.add_exact_value(
            calculated_id,
            ExactValue.from_lexical(
                "10",
                value_kind="money",
                origin_kind="calculated",
                currency="KRW",
            ),
            provenance_id=provenances[0],
        )
        builder.add_overview_balance(
            OverviewBalanceRecord(
                balance_id=new_entity_id(),
                observation_id=observations[1],
                provenance_id=provenances[1],
                source_fact_id=fact_id,
                amount_value_id=calculated_id,
                snapshot_date="2026-09-02",
                side="asset",
                category="cash",
                item_name="cash",
            )
        )
        builder.finalize()


def test_overview_non_numeric_fact_requires_lexical_evidence_and_rolls_back(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "overview-evidence")
    fact_id = new_entity_id()
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, occurrence_id = _source_context(builder)
        provenance_id = _add_provenance(
            builder,
            occurrence_id,
            {"locator_version": 1, "row": 1},
        )
        observation_id = new_entity_id()
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=occurrence_id,
                observed_at=None,
                effective_at=None,
                collected_at=None,
                scope_state="unknown",
            )
        )
        missing = OverviewFactRecord(
            fact_id=fact_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            snapshot_date="2026-09-01",
            sheet_name="overview",
            block_id="unsupported",
            block_title="Unsupported",
            fact_kind="formula",
            value_type="unsupported",
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            builder.add_overview_fact(missing)
        builder.add_overview_fact(
            OverviewFactRecord(**{**missing.__dict__, "value_text": "=UNKNOWN()"})
        )
        builder.finalize()


def test_overview_numeric_fact_preserves_money_currency_state_and_generic_number(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "overview-numeric-kinds")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, occurrence_id = _source_context(builder)
        observation_id = new_entity_id()
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=occurrence_id,
                observed_at=None,
                effective_at=None,
                collected_at=None,
                scope_state="unknown",
            )
        )
        cases = (
            ExactValue.from_lexical("1000", value_kind="money", currency="KRW"),
            ExactValue.from_lexical("2000", value_kind="money", currency=UNKNOWN_CURRENCY),
            ExactValue.from_lexical("3", value_kind="number", unit="count.v1"),
        )
        value_ids: list[str] = []
        for row, value in enumerate(cases, start=1):
            provenance_id = _add_provenance(
                builder,
                occurrence_id,
                {"locator_version": 1, "row": row},
            )
            value_id = new_entity_id()
            value_ids.append(value_id)
            builder.add_exact_value(value_id, value, provenance_id=provenance_id)
            builder.add_overview_fact(
                OverviewFactRecord(
                    fact_id=new_entity_id(),
                    observation_id=observation_id,
                    provenance_id=provenance_id,
                    snapshot_date="2026-09-01",
                    sheet_name="overview",
                    block_id="numeric",
                    block_title="Numeric",
                    fact_kind=f"value-{row}",
                    value_type="number",
                    numeric_value_id=value_id,
                )
            )
        builder.finalize()

    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        facts = reader.rows("overview_facts")
        money = reader.rows("money_values")
        numbers = reader.rows("number_values")

    assert [row["numeric_value_id"] for row in facts] == value_ids
    assert [(row["currency_code"], row["currency_unknown"]) for row in money] == [
        ("KRW", 0),
        (None, 1),
    ]
    assert [row["value_id"] for row in numbers] == [value_ids[2]]


def test_asset_snapshot_accepts_one_real_value_and_rejects_both_missing(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "partial-asset-values")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, occurrence_id = _source_context(builder)
        observation_id = new_entity_id()
        account_id = new_entity_id()
        resource_id = new_entity_id()
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=occurrence_id,
                observed_at=None,
                effective_at=None,
                collected_at=None,
                scope_state="partial",
            )
        )
        builder.add_account(AccountRecord(account_id=account_id, account_kind="broker.v1"))
        builder.add_resource(ResourceRecord(resource_id=resource_id, resource_kind="equity.v1"))
        provenances = [
            _add_provenance(
                builder,
                occurrence_id,
                {"locator_version": 1, "row": row},
            )
            for row in range(1, 4)
        ]
        quantity_id = new_entity_id()
        market_value_id = new_entity_id()
        builder.add_exact_value(
            quantity_id,
            ExactValue.from_lexical("1.5", value_kind="quantity", unit="share.v1"),
            provenance_id=provenances[0],
        )
        builder.add_exact_value(
            market_value_id,
            ExactValue.from_lexical("2500", value_kind="money", currency="KRW"),
            provenance_id=provenances[1],
        )
        builder.add_asset_snapshot(
            AssetSnapshotRecord(
                snapshot_id=new_entity_id(),
                observation_id=observation_id,
                provenance_id=provenances[0],
                account_id=account_id,
                resource_id=resource_id,
                quantity_value_id=quantity_id,
                market_value_id=None,
                snapshot_date="2026-09-01",
            )
        )
        builder.add_asset_snapshot(
            AssetSnapshotRecord(
                snapshot_id=new_entity_id(),
                observation_id=observation_id,
                provenance_id=provenances[1],
                account_id=account_id,
                resource_id=resource_id,
                quantity_value_id=None,
                market_value_id=market_value_id,
                snapshot_date="2026-09-01",
            )
        )
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint"):
            builder.add_asset_snapshot(
                AssetSnapshotRecord(
                    snapshot_id=new_entity_id(),
                    observation_id=observation_id,
                    provenance_id=provenances[2],
                    account_id=account_id,
                    resource_id=resource_id,
                    quantity_value_id=None,
                    market_value_id=None,
                    snapshot_date="2026-09-01",
                )
            )
        builder.finalize()

    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        snapshots = reader.rows("asset_snapshots")

    assert [(row["quantity_value_id"], row["market_value_id"]) for row in snapshots] == [
        (quantity_id, None),
        (None, market_value_id),
    ]


def test_immutable_anchor_and_preservation_rows_reject_update_or_delete(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "immutable")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        artifact_id, occurrence_id = _source_context(builder)
        provenance_id = _add_provenance(
            builder,
            occurrence_id,
            {"locator_version": 1, "row": 1},
        )
        party_id = new_entity_id()
        builder.add_party(PartyRecord(party_id=party_id))
        value_id = new_entity_id()
        builder.add_exact_value(
            value_id,
            ExactValue.from_lexical("10", value_kind="money", currency="KRW"),
            provenance_id=provenance_id,
        )
        mapping_id = builder.add_legacy_identifier(
            LegacyIdentifierRecord(
                entity_id=party_id,
                identifier_kind="other",
                identifier_value="legacy-party",
                capture_manifest_digest="a" * 64,
                provenance_id=provenance_id,
            )
        )
        builder.finalize()

    connection = sqlite3.connect(paths.database)
    try:
        statements = [
            ("UPDATE entities SET entity_kind = 'resource' WHERE entity_id = ?", party_id),
            ("DELETE FROM source_artifacts WHERE source_artifact_id = ?", artifact_id),
            ("UPDATE exact_values SET coefficient = '11' WHERE value_id = ?", value_id),
            ("DELETE FROM legacy_identifiers WHERE mapping_id = ?", mapping_id),
        ]
        for statement, value in statements:
            with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
                connection.execute(statement, (value,))
    finally:
        connection.close()


def test_abort_reports_and_preserves_published_objects_and_closed_builder_writes_nothing(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "abort")
    builder = RepositoryBuilder(paths, new_entity_id())
    artifact = builder.publish_source(io.BytesIO(b"retained source"))

    receipts = builder.abort()
    before = list(paths.sha256_objects.rglob("*"))

    assert receipts == (artifact,)
    assert builder.published_artifacts == receipts
    assert (paths.root / artifact.relative_path).read_bytes() == b"retained source"
    assert not paths.database.exists()
    with pytest.raises(RuntimeError, match="closed"):
        builder.publish_source(io.BytesIO(b"must not be written"))
    assert list(paths.sha256_objects.rglob("*")) == before


def test_exact_money_round_trips_as_text_with_lexical_and_currency(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "exact-roundtrip")
    lexical = "123456789012345678901234567890.00100"
    value_id = new_entity_id()
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        builder.add_exact_value(
            value_id,
            ExactValue.from_lexical(
                lexical,
                value_kind="money",
                origin_kind="calculated",
                currency="KRW",
            ),
        )
        builder.finalize()

    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        exact = reader.rows("exact_values")[0]
        money = reader.rows("money_values")[0]

    assert type(exact["coefficient"]) is str
    assert exact["coefficient"] == "12345678901234567890123456789000100"
    assert exact["scale"] == 5
    assert exact["lexical"] == lexical
    coefficient_digits = tuple(int(digit) for digit in exact["coefficient"])
    assert Decimal((0, coefficient_digits, -exact["scale"])) == Decimal(lexical)
    assert money["currency_code"] == "KRW"
    assert money["currency_unknown"] == 0


def test_identical_artifact_keeps_distinct_occurrences_and_locator_uniqueness(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "occurrences")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        first = builder.publish_source(io.BytesIO(b"same bytes"))
        second = builder.publish_source(io.BytesIO(b"same bytes"))
        occurrence_ids = [new_entity_id(), new_entity_id()]
        locator = {"locator_version": 1, "row": 7, "row_hash": "same"}
        for occurrence_id in occurrence_ids:
            builder.add_source_occurrence(
                SourceOccurrenceRecord(
                    occurrence_id=occurrence_id,
                    artifact_id=first.artifact_id,
                    occurrence_kind="synthetic",
                )
            )
            _add_provenance(builder, occurrence_id, locator)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
            _add_provenance(builder, occurrence_ids[0], locator)
        builder.finalize()

    assert first.artifact_id == second.artifact_id
    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        assert len(reader.rows("source_artifacts")) == 1
        assert len(reader.rows("source_occurrences")) == 2
        assert len(reader.rows("record_provenance")) == 2


def test_migrated_transaction_id_can_be_rederived_from_persisted_inputs(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "rederive")
    capture_digest = "a" * 64
    locator = {
        "locator_version": 1,
        "partition_digest": "b" * 64,
        "row": 7,
        "row_hash": "same",
    }
    transaction_id = migration_entity_id(capture_digest, "transaction", locator)
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        _, occurrence_id = _source_context(builder)
        provenance_id = _add_provenance(builder, occurrence_id, locator)
        party_id = new_entity_id()
        account_id = new_entity_id()
        builder.add_party(PartyRecord(party_id=party_id))
        builder.add_account(AccountRecord(account_id=account_id, account_kind="bank.v1"))
        observation_id = new_entity_id()
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=occurrence_id,
                observed_at=None,
                effective_at=None,
                collected_at=None,
                scope_state="unknown",
            )
        )
        amount_id = new_entity_id()
        builder.add_exact_value(
            amount_id,
            ExactValue.from_lexical("-10", value_kind="money", currency="KRW"),
            provenance_id=provenance_id,
        )
        builder.add_transaction(
            TransactionRecord(
                transaction_id=transaction_id,
                observation_id=observation_id,
                provenance_id=provenance_id,
                account_id=account_id,
                amount_value_id=amount_id,
                date_raw="2026-09-01",
                time_raw="00:00:00",
                datetime_raw="2026-09-01 00:00:00",
                type_raw=None,
                type_norm="expense",
                account_text="synthetic",
            )
        )
        builder.add_legacy_identifier(
            LegacyIdentifierRecord(
                entity_id=transaction_id,
                identifier_kind="row_hash",
                identifier_value="same",
                capture_manifest_digest=capture_digest,
                provenance_id=provenance_id,
            )
        )
        builder.add_migration_identity(
            MigrationIdentityRecord(
                entity_id=transaction_id,
                capture_manifest_digest=capture_digest,
                record_kind="transaction",
                legacy_locator=locator,
            )
        )
        builder.finalize()

    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        entity = next(row for row in reader.rows("entities") if row["entity_id"] == transaction_id)
        identity = reader.rows("migration_identities")[0]

    assert entity["entity_kind"] == "transaction"
    assert (
        migration_entity_id(
            identity["capture_manifest_digest"],
            identity["record_kind"],
            json.loads(identity["canonical_locator_json"]),
        )
        == transaction_id
    )


def test_finalize_requires_migration_identity_for_every_uuid5_entity(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "missing-migration-identity")
    locator = {"locator_version": 1, "row": 1}
    party_id = migration_entity_id("a" * 64, "party", locator)
    builder = RepositoryBuilder(paths, new_entity_id())
    builder.add_party(PartyRecord(party_id=party_id))

    with pytest.raises(RepositoryIntegrityError, match="Every UUIDv5 entity"):
        builder.finalize()

    assert not paths.database.exists()


def test_migration_identity_rejects_mismatch_and_conflict(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "migration-identity-conflict")
    locator = {"locator_version": 1, "row": 1}
    capture_digest = "a" * 64
    party_id = migration_entity_id(capture_digest, "party", locator)
    correct = MigrationIdentityRecord(
        entity_id=party_id,
        capture_manifest_digest=capture_digest,
        record_kind="party",
        legacy_locator=locator,
    )

    with RepositoryBuilder(paths, new_entity_id()) as builder:
        builder.add_party(PartyRecord(party_id=party_id))
        with pytest.raises(ValueError, match="do not derive"):
            builder.add_migration_identity(
                MigrationIdentityRecord(
                    entity_id=party_id,
                    capture_manifest_digest="b" * 64,
                    record_kind="party",
                    legacy_locator=locator,
                )
            )
        builder.add_migration_identity(correct)
        with pytest.raises(sqlite3.IntegrityError, match="UNIQUE constraint"):
            builder.add_migration_identity(correct)
        builder.finalize()


def test_later_aliases_do_not_change_migration_identity_and_supersession_is_append_only(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "migration-aliases")
    locator = {"locator_version": 1, "row": 7, "row_hash": "original"}
    capture_digest = "a" * 64
    party_id = migration_entity_id(capture_digest, "party", locator)

    with RepositoryBuilder(paths, new_entity_id()) as builder:
        builder.add_party(PartyRecord(party_id=party_id))
        builder.add_migration_identity(
            MigrationIdentityRecord(
                entity_id=party_id,
                capture_manifest_digest=capture_digest,
                record_kind="party",
                legacy_locator=locator,
            )
        )
        original_mapping_id = builder.add_legacy_identifier(
            LegacyIdentifierRecord(
                entity_id=party_id,
                identifier_kind="row_hash",
                identifier_value="original",
                capture_manifest_digest=capture_digest,
            )
        )
        replacement_mapping_id = builder.add_legacy_identifier(
            LegacyIdentifierRecord(
                entity_id=party_id,
                identifier_kind="old_path",
                identifier_value="corrected/path.csv",
                capture_manifest_digest="b" * 64,
            )
        )
        supersession_id = builder.supersede_legacy_identifier(
            original_mapping_id,
            replacement_mapping_id,
            "corrected alias",
        )
        builder.finalize()

    with RepositoryReader(paths.database, scratch_root=tmp_path / "scratch") as reader:
        identity = reader.rows("migration_identities")[0]
        mappings = reader.rows("legacy_identifiers")
        supersessions = reader.rows("legacy_identifier_supersessions")

    assert identity["capture_manifest_digest"] == capture_digest
    assert identity["canonical_locator_json"] == json.dumps(
        locator,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    assert {row["mapping_id"] for row in mappings} == {
        original_mapping_id,
        replacement_mapping_id,
    }
    assert supersessions == [
        {
            "supersession_id": supersession_id,
            "previous_mapping_id": original_mapping_id,
            "replacement_mapping_id": replacement_mapping_id,
            "reason": "corrected alias",
        }
    ]

    connection = sqlite3.connect(paths.database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
            connection.execute(
                "UPDATE migration_identities SET capture_manifest_digest = ? WHERE entity_id = ?",
                ("c" * 64, party_id),
            )
        with pytest.raises(sqlite3.IntegrityError, match="immutable preservation row"):
            connection.execute(
                "DELETE FROM legacy_identifier_supersessions WHERE supersession_id = ?",
                (supersession_id,),
            )
    finally:
        connection.close()


def test_private_scratch_override_connects_all_read_and_upgrade_apis(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "scratch-source")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        builder.finalize()
    scratch = tmp_path / "private-scratch"

    assert inspect_repository(paths.database, scratch_root=scratch).schema_version == 1
    assert validate_repository(paths.database, scratch_root=scratch).schema_version == 1
    with RepositoryReader(paths.database, scratch_root=scratch) as reader:
        assert reader.info.schema_version == 1
    destination = GenerationPaths(tmp_path / "scratch-destination")
    upgrade_repository(paths.database, destination, scratch_root=scratch)

    assert stat.S_IMODE(scratch.stat().st_mode) == 0o700
    connection = sqlite3.connect(destination.database)
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    finally:
        connection.close()


def test_default_scratch_root_uses_private_application_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "default-scratch-source")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        builder.finalize()
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache_root))

    inspect_repository(paths.database)

    scratch = cache_root / "finjuice" / "sqlite-inspection"
    assert scratch.is_dir()
    assert stat.S_IMODE(scratch.stat().st_mode) == 0o700


def test_scratch_root_rejects_symlink_and_non_private_permissions(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "scratch-policy")
    with RepositoryBuilder(paths, new_entity_id()) as builder:
        builder.finalize()
    real = tmp_path / "real-scratch"
    real.mkdir(mode=0o700)
    alias = tmp_path / "scratch-alias"
    os.symlink(real, alias)
    with pytest.raises(RepositorySnapshotError, match="symlink"):
        inspect_repository(paths.database, scratch_root=alias)

    permissive = tmp_path / "permissive"
    permissive.mkdir(mode=0o755)
    with pytest.raises(RepositorySnapshotError, match="private"):
        inspect_repository(paths.database, scratch_root=permissive)

    with pytest.raises(RepositorySnapshotError, match="outside the generation"):
        inspect_repository(paths.database, scratch_root=paths.root / "scratch")
