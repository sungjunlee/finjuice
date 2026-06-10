"""Privacy guard tests for standalone migration scripts."""

from pathlib import Path

from scripts import migrate_hash_length, migrate_schema_v3


def test_schema_migration_rejects_repo_local_data_dir(tmp_path, monkeypatch) -> None:
    """Schema migration must not target data under the program repository."""
    repo_root = tmp_path / "finjuice"
    repo_root.mkdir()
    monkeypatch.setattr(migrate_schema_v3, "PROGRAM_REPO_ROOT", repo_root)

    assert not migrate_schema_v3.validate_data_dir_location(repo_root / "data")


def test_hash_migration_rejects_repo_local_data_dir(tmp_path, monkeypatch) -> None:
    """Hash migration must not target data under the program repository."""
    repo_root = tmp_path / "finjuice"
    repo_root.mkdir()
    monkeypatch.setattr(migrate_hash_length, "PROGRAM_REPO_ROOT", repo_root)

    assert not migrate_hash_length.validate_data_dir_location(repo_root / "data")


def test_migration_defaults_use_home_finjuice() -> None:
    """Migration script defaults should point outside the source checkout."""
    assert migrate_schema_v3.DEFAULT_DATA_DIR == Path.home() / ".finjuice"
    assert migrate_hash_length.DEFAULT_DATA_DIR == Path.home() / ".finjuice"
