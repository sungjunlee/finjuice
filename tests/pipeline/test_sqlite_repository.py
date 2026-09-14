"""Synthetic integration tests for repository staging, reading, and upgrades."""

from __future__ import annotations

import io
import os
import sqlite3
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.storage.sqlite import (
    SQLITE_APPLICATION_ID,
    AccountRecord,
    AssetSnapshotRecord,
    ConfigRevisionRecord,
    ExactValue,
    GenerationPaths,
    LegacyIdentifierRecord,
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
    initialize_repository,
    inspect_repository,
    upgrade_repository,
    validate_repository,
)
from finjuice.pipeline.storage.sqlite import schema as sqlite_schema
from finjuice.pipeline.storage.sqlite import snapshot as sqlite_snapshot
from finjuice.pipeline.storage.sqlite.errors import (
    RepositoryIntegrityError,
    RepositoryPathError,
    RepositorySnapshotError,
    RepositoryVersionError,
)


def _id() -> str:
    return str(uuid4())


def _tree_state(root: Path) -> dict[str, tuple[int, bytes | None]]:
    state: dict[str, tuple[int, bytes | None]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        relative_path = "." if path == root else path.relative_to(root).as_posix()
        entry = path.lstat()
        contents = path.read_bytes() if stat.S_ISREG(entry.st_mode) else None
        state[relative_path] = (stat.S_IMODE(entry.st_mode), contents)
    return state


def _provenance(occurrence_id: str, row: int) -> ProvenanceRecord:
    return ProvenanceRecord(
        provenance_id=_id(),
        occurrence_id=occurrence_id,
        source_coordinate={"sheet": "synthetic", "row": row},
        legacy_locator={
            "locator_version": 1,
            "sheet": "synthetic",
            "row": row,
            "row_hash": "same-legacy-row-hash",
        },
        parser_version="test-v1",
    )


def _assert_typed_domain_rows(paths: GenerationPaths, transaction_ids: list[str]) -> None:
    with RepositoryReader(paths.database) as reader:
        assert len(reader.rows("transactions")) == 2
        assert {row["entity_id"] for row in reader.rows("transactions")} == set(transaction_ids)
        assert [row["identifier_value"] for row in reader.rows("legacy_identifiers")] == [
            "same-legacy-row-hash",
            "same-legacy-row-hash",
        ]
        assert len(reader.rows("overview_balances")) == 1
        assert len(reader.rows("asset_snapshots")) == 1
        assert len(reader.rows("config_revisions")) == 1


def test_builder_publishes_typed_domains_and_preserves_duplicate_occurrences(
    tmp_path: Path,
) -> None:
    paths = GenerationPaths(tmp_path / "generation")
    generation = _id()
    occurrence_id = _id()
    party_id = _id()
    account_id = _id()
    resource_id = _id()
    observation_id = _id()
    transaction_provenances = [_provenance(occurrence_id, row) for row in (7, 8)]
    fact_provenance = _provenance(occurrence_id, 20)
    balance_provenance = _provenance(occurrence_id, 21)
    asset_provenance = _provenance(occurrence_id, 30)

    with RepositoryBuilder(paths, generation) as builder:
        artifact = builder.publish_source(io.BytesIO(b"synthetic xlsx bytes"))
        assert not paths.database.exists()
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=occurrence_id,
                artifact_id=artifact.artifact_id,
                occurrence_kind="banksalad_xlsx",
                original_filename="synthetic.xlsx",
            )
        )
        for provenance in (
            *transaction_provenances,
            fact_provenance,
            balance_provenance,
            asset_provenance,
        ):
            builder.add_provenance(provenance)

        builder.add_party(PartyRecord(party_id=party_id, party_kind="person"))
        builder.add_account(
            AccountRecord(
                account_id=account_id,
                account_kind="bank.v1",
                ownership_state="asserted",
                owner_party_id=party_id,
            )
        )
        builder.add_resource(ResourceRecord(resource_id=resource_id, resource_kind="equity.v1"))
        builder.add_observation(
            ObservationRecord(
                observation_id=observation_id,
                occurrence_id=occurrence_id,
                observed_at=None,
                effective_at="2026-09-01",
                collected_at="2026-09-02T00:00:00Z",
                scope_state="partial",
            )
        )
        builder.add_config_revision(
            ConfigRevisionRecord(
                revision_id=_id(),
                config_kind="rules",
                artifact_id=artifact.artifact_id,
                occurrence_id=occurrence_id,
                parsed_status="parsed",
                canonical_payload={"rules": []},
            )
        )

        transaction_ids: list[str] = []
        for index, provenance in enumerate(transaction_provenances, start=1):
            amount_id = _id()
            transaction_id = _id()
            transaction_ids.append(transaction_id)
            builder.add_exact_value(
                amount_id,
                ExactValue.from_lexical(
                    f"-{index}000.00",
                    value_kind="money",
                    currency="KRW",
                ),
                provenance_id=provenance.provenance_id,
            )
            builder.add_transaction(
                TransactionRecord(
                    transaction_id=transaction_id,
                    observation_id=observation_id,
                    provenance_id=provenance.provenance_id,
                    account_id=account_id,
                    amount_value_id=amount_id,
                    date_raw="2026-09-01",
                    time_raw="12:00:00",
                    datetime_raw="2026-09-01 12:00:00",
                    type_raw="지출",
                    type_norm="expense",
                    account_text="synthetic account",
                    tags_rule_json='["food"]',
                    tags_final_json='["food"]',
                )
            )
            builder.add_legacy_identifier(
                LegacyIdentifierRecord(
                    entity_id=transaction_id,
                    identifier_kind="row_hash",
                    identifier_value="same-legacy-row-hash",
                    capture_manifest_digest="a" * 64,
                    provenance_id=provenance.provenance_id,
                )
            )

        builder.add_legacy_payload(
            transaction_provenances[0].provenance_id,
            {"raw_amount": "-1000.00", "row_hash": "same-legacy-row-hash"},
        )
        builder.add_migration_disposition(
            transaction_provenances[0].provenance_id,
            "migrated",
            "typed without loss",
        )

        fact_value_id = _id()
        builder.add_exact_value(
            fact_value_id,
            ExactValue.from_lexical("42.00", value_kind="number", unit="count.v1"),
            provenance_id=fact_provenance.provenance_id,
        )
        fact_id = _id()
        builder.add_overview_fact(
            OverviewFactRecord(
                fact_id=fact_id,
                observation_id=observation_id,
                provenance_id=fact_provenance.provenance_id,
                snapshot_date="2026-09-01",
                sheet_name="overview",
                block_id="assets",
                block_title="Assets",
                fact_kind="synthetic_count",
                value_type="number",
                numeric_value_id=fact_value_id,
            )
        )
        balance_amount_id = _id()
        builder.add_exact_value(
            balance_amount_id,
            ExactValue.from_lexical("1234", value_kind="money", currency="KRW"),
            provenance_id=balance_provenance.provenance_id,
        )
        builder.add_overview_balance(
            OverviewBalanceRecord(
                balance_id=_id(),
                observation_id=observation_id,
                provenance_id=balance_provenance.provenance_id,
                source_fact_id=fact_id,
                amount_value_id=balance_amount_id,
                snapshot_date="2026-09-01",
                side="asset",
                category="cash",
                item_name="synthetic balance",
            )
        )

        quantity_id = _id()
        market_value_id = _id()
        builder.add_exact_value(
            quantity_id,
            ExactValue.from_lexical("1.250", value_kind="quantity", unit="share.v1"),
            provenance_id=asset_provenance.provenance_id,
        )
        builder.add_exact_value(
            market_value_id,
            ExactValue.from_lexical("999.50", value_kind="money", currency="KRW"),
            provenance_id=asset_provenance.provenance_id,
        )
        builder.add_asset_snapshot(
            AssetSnapshotRecord(
                snapshot_id=_id(),
                observation_id=observation_id,
                provenance_id=asset_provenance.provenance_id,
                account_id=account_id,
                resource_id=resource_id,
                quantity_value_id=quantity_id,
                market_value_id=market_value_id,
                snapshot_date="2026-09-01",
            )
        )
        info = builder.finalize()

    assert info.dataset_generation == generation
    assert info.dataset_revision == 0
    _assert_typed_domain_rows(paths, transaction_ids)


def test_new_builder_rejects_invented_dataset_revision(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "invented-revision")

    with pytest.raises(ValueError, match="must be zero"):
        RepositoryBuilder(paths, _id(), dataset_revision=4)

    assert not paths.database.exists()


def test_builder_rejects_permissive_generation_root(tmp_path: Path) -> None:
    root = tmp_path / "permissive-generation"
    root.mkdir(mode=0o755)
    root.chmod(0o755)

    with pytest.raises(RepositoryPathError, match="must be private"):
        RepositoryBuilder(GenerationPaths(root), _id())

    assert not (root / "finjuice.sqlite3").exists()


def test_builder_staging_and_published_database_are_private(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "private-database")
    builder = RepositoryBuilder(paths, _id())

    assert stat.S_IMODE(builder._staging.stat().st_mode) == 0o600
    builder.finalize()

    assert stat.S_IMODE(paths.database.stat().st_mode) == 0o600


def test_text_primary_keys_reject_explicit_null(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "generation")
    initialize_repository(paths, _id())

    connection = sqlite3.connect(paths.database)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            connection.execute(
                "INSERT INTO entities (entity_id, entity_kind) VALUES (NULL, 'party')"
            )
    finally:
        connection.close()


def test_upgrade_carries_referenced_objects_without_changing_source(tmp_path: Path) -> None:
    source_paths = GenerationPaths(tmp_path / "source")
    with RepositoryBuilder(source_paths, _id()) as builder:
        artifact = builder.publish_source(io.BytesIO(b"upgrade source"))
        builder.finalize()
    source_database_before = source_paths.database.read_bytes()
    source_object = source_paths.root / artifact.relative_path
    source_object_before = source_object.read_bytes()
    destination = GenerationPaths(tmp_path / "destination")

    info = upgrade_repository(source_paths.database, destination)

    assert info.schema_version == sqlite_schema.SQLITE_SCHEMA_VERSION
    assert source_paths.database.read_bytes() == source_database_before
    assert source_object.read_bytes() == source_object_before
    assert (destination.root / artifact.relative_path).read_bytes() == source_object_before
    with RepositoryReader(destination.database) as reader:
        assert reader.rows("source_artifacts")[0]["source_artifact_id"] == artifact.artifact_id


def test_finalize_and_validation_reject_missing_referenced_objects(tmp_path: Path) -> None:
    unpublished = GenerationPaths(tmp_path / "unpublished")
    with RepositoryBuilder(unpublished, _id()) as builder:
        artifact = builder.publish_source(io.BytesIO(b"missing before finalize"))
        (unpublished.root / artifact.relative_path).unlink()
        with pytest.raises(RepositoryIntegrityError, match="missing, mutable, or corrupt"):
            builder.finalize()
    assert not unpublished.database.exists()

    published = GenerationPaths(tmp_path / "published")
    with RepositoryBuilder(published, _id()) as builder:
        artifact = builder.publish_source(io.BytesIO(b"missing after finalize"))
        builder.finalize()
    (published.root / artifact.relative_path).unlink()

    with pytest.raises(RepositoryIntegrityError, match="missing, mutable, or corrupt"):
        validate_repository(published.database)


def test_validation_and_upgrade_normalize_corrupt_source_object_without_mutating_source(
    tmp_path: Path,
) -> None:
    source = GenerationPaths(tmp_path / "corrupt-source")
    with RepositoryBuilder(source, _id()) as builder:
        artifacts = [
            builder.publish_source(io.BytesIO(contents))
            for contents in (b"first source object", b"second source object")
        ]
        builder.finalize()
    ordered = sorted(artifacts, key=lambda artifact: artifact.artifact_id)
    corrupt_path = source.root / ordered[1].relative_path
    original = corrupt_path.read_bytes()
    corrupt_path.chmod(0o644)
    corrupt_path.write_bytes(bytes([original[0] ^ 0xFF]) + original[1:])
    corrupt_path.chmod(0o444)
    before = _tree_state(source.root)
    destination = GenerationPaths(tmp_path / "corrupt-destination")

    with pytest.raises(RepositoryIntegrityError, match="missing, mutable, or corrupt"):
        validate_repository(
            source.database,
            scratch_root=tmp_path / "corrupt-validate-scratch",
        )
    with pytest.raises(RepositoryIntegrityError, match="missing, mutable, or corrupt"):
        upgrade_repository(
            source.database,
            destination,
            scratch_root=tmp_path / "corrupt-upgrade-scratch",
        )

    assert _tree_state(source.root) == before
    first_source = source.root / ordered[0].relative_path
    assert (destination.root / ordered[0].relative_path).read_bytes() == first_source.read_bytes()
    assert not destination.database.exists()
    assert list(destination.root.glob(".finjuice-sqlite-staging-*")) == []


def test_validation_and_upgrade_normalize_missing_source_object_tree(
    tmp_path: Path,
) -> None:
    source = GenerationPaths(tmp_path / "missing-object-tree-source")
    with RepositoryBuilder(source, _id()) as builder:
        artifact = builder.publish_source(io.BytesIO(b"preserved outside expected tree"))
        builder.finalize()
    detached_objects = source.root / "detached-objects"
    source.objects.rename(detached_objects)
    before = _tree_state(source.root)
    destination = GenerationPaths(tmp_path / "missing-object-tree-destination")

    with pytest.raises(RepositoryIntegrityError, match="missing, mutable, or corrupt"):
        validate_repository(
            source.database,
            scratch_root=tmp_path / "missing-tree-validate-scratch",
        )
    with pytest.raises(RepositoryIntegrityError, match="missing, mutable, or corrupt"):
        upgrade_repository(
            source.database,
            destination,
            scratch_root=tmp_path / "missing-tree-upgrade-scratch",
        )

    assert _tree_state(source.root) == before
    assert (detached_objects / Path(artifact.relative_path).relative_to("objects")).exists()
    assert not destination.database.exists()
    assert list(destination.root.glob(".finjuice-sqlite-staging-*")) == []


def test_upgrade_does_not_misclassify_destination_object_path_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = GenerationPaths(tmp_path / "destination-path-source")
    with RepositoryBuilder(source, _id()) as builder:
        builder.publish_source(io.BytesIO(b"valid upgrade source"))
        builder.finalize()
    destination = GenerationPaths(tmp_path / "destination-path-failure")

    def fail_destination_publish(self: object, path: Path) -> None:
        raise RepositoryPathError("injected destination path failure")

    monkeypatch.setattr(sqlite_schema.SourceObjectStore, "publish_path", fail_destination_publish)

    with pytest.raises(RepositoryPathError, match="injected destination"):
        upgrade_repository(
            source.database,
            destination,
            scratch_root=tmp_path / "destination-path-scratch",
        )

    assert not destination.database.exists()
    assert list(destination.root.glob(".finjuice-sqlite-staging-*")) == []


def test_foreign_key_validation_detects_invalid_reference(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "foreign-key")
    initialize_repository(paths, _id())
    account_id = _id()
    missing_party_id = _id()
    connection = sqlite3.connect(paths.database)
    try:
        connection.execute("PRAGMA foreign_keys = OFF")
        connection.execute(
            "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'account')",
            (account_id,),
        )
        connection.execute(
            "INSERT INTO accounts "
            "(entity_id, account_kind, ownership_state, owner_party_id) "
            "VALUES (?, 'bank.v1', 'asserted', ?)",
            (account_id, missing_party_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RepositoryIntegrityError, match="foreign_key_check"):
        validate_repository(paths.database)


def test_upgrade_processing_failure_preserves_source_and_unpublishes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = GenerationPaths(tmp_path / "upgrade-failure-source")
    initialize_repository(source, _id())
    connection = sqlite3.connect(source.database)
    try:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        party_id = _id()
        connection.execute(
            "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'party')",
            (party_id,),
        )
        connection.execute(
            "INSERT INTO parties (entity_id, party_kind) VALUES (?, 'unknown')",
            (party_id,),
        )
        connection.commit()
        connection.execute("SELECT * FROM repository_meta").fetchall()
        sidecars = [
            candidate
            for candidate in (
                source.database,
                Path(f"{source.database}-wal"),
                Path(f"{source.database}-shm"),
            )
            if candidate.exists()
        ]
        before = {candidate: candidate.read_bytes() for candidate in sidecars}

        def fail_copy(*args: object, **kwargs: object) -> None:
            raise RepositoryIntegrityError("injected object-copy failure")

        monkeypatch.setattr(sqlite_schema, "_copy_source_objects", fail_copy)
        destination = GenerationPaths(tmp_path / "upgrade-failure-destination")

        with pytest.raises(RepositoryIntegrityError, match="injected"):
            upgrade_repository(source.database, destination)

        assert {candidate: candidate.read_bytes() for candidate in sidecars} == before
        assert not destination.database.exists()
        assert list(destination.root.glob(".finjuice-sqlite-staging-*")) == []
    finally:
        connection.close()


def test_committed_wal_reads_validate_and_upgrade_without_changing_source_sidecars(
    tmp_path: Path,
) -> None:
    source = GenerationPaths(tmp_path / "wal-source")
    generation = _id()
    initialize_repository(source, generation)
    connection = sqlite3.connect(source.database)
    try:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        party_id = _id()
        connection.execute("UPDATE repository_meta SET dataset_revision = 7 WHERE singleton = 1")
        connection.execute(
            "INSERT INTO entities (entity_id, entity_kind) VALUES (?, 'party')",
            (party_id,),
        )
        connection.execute(
            "INSERT INTO parties (entity_id, party_kind) VALUES (?, 'unknown')",
            (party_id,),
        )
        connection.commit()
        connection.execute("SELECT * FROM repository_meta").fetchall()
        source_files = (
            source.database,
            Path(f"{source.database}-wal"),
            Path(f"{source.database}-shm"),
        )
        assert all(path.exists() for path in source_files)
        before = {path: path.read_bytes() for path in source_files}

        validated = validate_repository(
            source.database,
            scratch_root=tmp_path / "validate-scratch",
        )
        with RepositoryReader(
            source.database,
            scratch_root=tmp_path / "reader-scratch",
        ) as reader:
            assert any(row["entity_id"] == party_id for row in reader.rows("parties"))

        destination = GenerationPaths(tmp_path / "wal-destination")
        upgraded = upgrade_repository(
            source.database,
            destination,
            scratch_root=tmp_path / "upgrade-scratch",
        )

        assert validated.dataset_generation == generation
        assert validated.dataset_revision == 7
        assert upgraded.dataset_generation == generation
        assert upgraded.dataset_revision == 7
        with RepositoryReader(
            destination.database,
            scratch_root=tmp_path / "destination-scratch",
        ) as reader:
            assert any(row["entity_id"] == party_id for row in reader.rows("parties"))
        assert {path: path.read_bytes() for path in source_files} == before
    finally:
        connection.close()


@pytest.mark.parametrize(
    ("application_id", "schema_version", "message"),
    [
        (SQLITE_APPLICATION_ID, 0, "unsupported"),
        (0, 1, "not a finjuice"),
    ],
)
def test_upgrade_rejects_v0_and_wrong_application_id_without_changing_source(
    tmp_path: Path,
    application_id: int,
    schema_version: int,
    message: str,
) -> None:
    source_directory = tmp_path / f"source-{application_id}-{schema_version}"
    source_directory.mkdir()
    source = source_directory / "foreign.sqlite3"
    connection = sqlite3.connect(source)
    try:
        connection.execute("CREATE TABLE foreign_payload (value TEXT)")
        connection.execute("INSERT INTO foreign_payload VALUES ('unchanged')")
        connection.execute(f"PRAGMA application_id = {application_id}")
        connection.execute(f"PRAGMA user_version = {schema_version}")
        connection.commit()
    finally:
        connection.close()
    before = source.read_bytes()
    destination = GenerationPaths(tmp_path / f"rejected-{application_id}-{schema_version}")
    scratch_parent = tmp_path / f"scratch-{application_id}-{schema_version}"

    with pytest.raises(RepositoryVersionError, match=message):
        inspect_repository(source, scratch_root=scratch_parent / "inspect")
    with pytest.raises(RepositoryVersionError, match=message):
        upgrade_repository(
            source,
            destination,
            scratch_root=scratch_parent / "upgrade",
        )

    assert source.read_bytes() == before
    assert not destination.database.exists()


def test_snapshot_rejects_preexisting_and_mid_capture_rollback_journal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = GenerationPaths(tmp_path / "rollback-journal")
    initialize_repository(paths, _id())
    journal = Path(f"{paths.database}-journal")
    journal.write_bytes(b"synthetic active journal")

    with pytest.raises(RepositorySnapshotError, match="active rollback journal"):
        inspect_repository(paths.database, scratch_root=tmp_path / "preexisting-scratch")

    journal.unlink()
    original_copy = sqlite_snapshot._copy_regular
    journal_created = False

    def copy_then_create_journal(source: Path, destination: Path) -> None:
        nonlocal journal_created
        original_copy(source, destination)
        if not journal_created:
            journal.write_bytes(b"appeared during capture")
            journal_created = True

    monkeypatch.setattr(sqlite_snapshot, "_copy_regular", copy_then_create_journal)

    with pytest.raises(RepositorySnapshotError, match="appeared during inspection"):
        inspect_repository(paths.database, scratch_root=tmp_path / "mid-capture-scratch")


def test_database_publication_syncs_link_before_removing_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / "staging.sqlite3"
    destination = tmp_path / "published.sqlite3"
    staging.write_bytes(b"candidate")
    states: list[tuple[bool, bool]] = []
    real_fsync_directory = sqlite_schema._fsync_directory

    def record_fsync(path: Path) -> None:
        states.append((staging.exists(), destination.exists()))
        real_fsync_directory(path)

    monkeypatch.setattr(sqlite_schema, "_fsync_directory", record_fsync)

    sqlite_schema._publish_database(staging, destination)

    assert states == [(True, True), (False, True)]
    assert destination.read_bytes() == b"candidate"


def test_database_publication_reports_first_directory_sync_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    staging = tmp_path / "staging.sqlite3"
    destination = tmp_path / "published.sqlite3"
    staging.write_bytes(b"candidate")

    def fail_fsync(path: Path) -> None:
        raise OSError(f"injected sync failure for {path}")

    monkeypatch.setattr(sqlite_schema, "_fsync_directory", fail_fsync)

    with pytest.raises(RepositoryPathError, match="could not be published"):
        sqlite_schema._publish_database(staging, destination)

    assert not destination.exists()


def test_database_publication_preserves_existing_destination_and_cleans_staging(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging.sqlite3"
    destination = tmp_path / "published.sqlite3"
    staging.write_bytes(b"candidate")
    destination.write_bytes(b"existing repository")
    staging_sidecars = [
        Path(f"{staging}-journal"),
        Path(f"{staging}-wal"),
        Path(f"{staging}-shm"),
    ]
    for sidecar in staging_sidecars:
        sidecar.write_bytes(b"staging sidecar")

    with pytest.raises(RepositoryPathError, match="already exists and was not replaced"):
        sqlite_schema._publish_database(staging, destination)

    assert destination.read_bytes() == b"existing repository"
    assert not staging.exists()
    assert all(not sidecar.exists() for sidecar in staging_sidecars)


def test_initialize_never_replaces_existing_database(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "generation")
    initialize_repository(paths, _id())
    before = paths.database.read_bytes()

    with pytest.raises(RepositoryPathError, match="already exists"):
        initialize_repository(paths, _id())

    assert paths.database.read_bytes() == before


def test_future_wal_version_rejection_does_not_touch_source_sidecars(tmp_path: Path) -> None:
    paths = GenerationPaths(tmp_path / "future")
    initialize_repository(paths, _id())
    connection = sqlite3.connect(paths.database)
    try:
        assert connection.execute("PRAGMA journal_mode = WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_autocheckpoint = 0")
        connection.execute("PRAGMA user_version = 999")
        connection.commit()
        connection.execute("SELECT * FROM repository_meta").fetchall()
        sidecars = [
            candidate
            for candidate in (
                paths.database,
                Path(f"{paths.database}-wal"),
                Path(f"{paths.database}-shm"),
            )
            if candidate.exists()
        ]
        before = {candidate: candidate.read_bytes() for candidate in sidecars}

        with pytest.raises(RepositoryVersionError, match="newer"):
            inspect_repository(paths.database)
        destination = GenerationPaths(tmp_path / "rejected-upgrade")
        with pytest.raises(RepositoryVersionError, match="newer"):
            upgrade_repository(paths.database, destination)

        assert {candidate: candidate.read_bytes() for candidate in sidecars} == before
        assert not destination.database.exists()
    finally:
        connection.close()


def test_snapshot_rejects_fifo_without_blocking(tmp_path: Path) -> None:
    fifo = tmp_path / "database.fifo"
    os.mkfifo(fifo)

    with pytest.raises(RepositorySnapshotError, match="regular"):
        inspect_repository(fifo)
