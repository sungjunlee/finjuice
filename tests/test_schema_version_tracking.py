"""Tests for data-directory schema version tracking."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.constants import SCHEMA_VERSION
from finjuice.pipeline.metadata.schema_version import (
    SchemaVersionState,
    check_schema_version,
    evaluate_schema_version,
    read_schema_version,
    write_schema_version,
)
from finjuice.pipeline.storage.schema_registry import clear_cache

runner = CliRunner()


def _read_template_schema_version() -> int:
    """Load the current schema version from the source-of-truth template."""
    schema_path = Path(__file__).resolve().parents[1] / "templates" / "schema.yaml"
    schema = yaml.safe_load(schema_path.read_text(encoding="utf-8"))
    return int(schema["current_version"])


def _write_stale_local_registry(data_dir: Path, current_version: int) -> None:
    """Write a minimal stale metadata/schema.yaml for compatibility tests."""
    metadata_dir = data_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "current_version": current_version,
        "schemas": {
            f"v{current_version}": {
                "active": True,
            }
        },
    }
    (metadata_dir / "schema.yaml").write_text(
        yaml.safe_dump(schema, sort_keys=False),
        encoding="utf-8",
    )
    clear_cache()


def _create_taggable_data_dir(tmp_path: Path) -> Path:
    """Create a minimal data directory that can run the tag command."""
    data_dir = tmp_path / "data"
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True)
    (data_dir / "imports").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    partition_dir.joinpath("transactions.csv").write_text(
        (
            "row_hash,date,time,type_raw,type_norm,major_raw,minor_raw,"
            "merchant_raw,memo_raw,amount,account,currency,counterparty,datetime,"
            "category_rule,category_final,tags_rule,tags_ai,tags_manual,tags_final,"
            "confidence,needs_review,"
            "is_transfer_candidate,is_transfer,transfer_group_id,file_id,source_row\n"
            "abc1234567890123,2024-10-01,10:00,지출,expense,식비,카페,스타벅스,,"
            "-5000,신한카드,KRW,,2024-10-01T10:00:00,,카페,[],[],[],[],0,0,0,0,,241001_1,1\n"
        ),
        encoding="utf-8",
    )
    return data_dir


def _create_initialized_data_dir(tmp_path: Path) -> Path:
    """Create an empty but initialized data directory for full-pipeline tests."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "transactions").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def test_schema_version_constant_matches_template() -> None:
    """The in-code schema version should stay aligned with templates/schema.yaml."""
    assert SCHEMA_VERSION == _read_template_schema_version()


def test_schema_version_read_returns_none_when_missing(tmp_path: Path) -> None:
    """Missing metadata/schema_version should be treated as an uninitialized data directory."""
    assert read_schema_version(tmp_path / "data") is None


def test_schema_version_read_rejects_empty_file(tmp_path: Path) -> None:
    """Empty metadata/schema_version should fail loudly instead of implying a version."""
    data_dir = tmp_path / "data"
    schema_version_path = data_dir / "metadata" / "schema_version"
    schema_version_path.parent.mkdir(parents=True)
    schema_version_path.write_text("\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Schema version file is empty"):
        read_schema_version(data_dir)


def test_schema_version_read_rejects_non_integer_value(tmp_path: Path) -> None:
    """Non-integer metadata/schema_version content should identify the bad value."""
    data_dir = tmp_path / "data"
    schema_version_path = data_dir / "metadata" / "schema_version"
    schema_version_path.parent.mkdir(parents=True)
    schema_version_path.write_text("v3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid schema version"):
        read_schema_version(data_dir)


def test_schema_version_write_creates_metadata_file(tmp_path: Path) -> None:
    """write_schema_version() should create metadata/schema_version on first use."""
    data_dir = tmp_path / "data"

    write_schema_version(data_dir, SCHEMA_VERSION)

    schema_version_path = data_dir / "metadata" / "schema_version"
    assert schema_version_path.exists()
    assert schema_version_path.read_text(encoding="utf-8").strip() == str(SCHEMA_VERSION)


def test_schema_version_check_returns_none_when_matching(tmp_path: Path) -> None:
    """Matching versions should produce no warning message."""
    data_dir = tmp_path / "data"
    write_schema_version(data_dir, SCHEMA_VERSION)

    assert check_schema_version(data_dir) is None


def test_schema_version_check_guides_compatible_legacy_v2(tmp_path: Path) -> None:
    """Tracked v2 directories should be compatible legacy with refresh guidance."""
    data_dir = tmp_path / "data"
    write_schema_version(data_dir, 2)

    status = evaluate_schema_version(data_dir)
    message = check_schema_version(data_dir)

    assert status.state is SchemaVersionState.COMPATIBLE_LEGACY
    assert status.stored_version == 2
    assert status.current_version == SCHEMA_VERSION
    assert message is not None
    assert "compatible legacy schema v2" in message
    assert "finjuice refresh" in message
    assert "category_rule/category_final" in message


def test_schema_version_check_warns_on_unsupported_mismatch(tmp_path: Path) -> None:
    """Unsupported mismatches should return a clear warning message."""
    data_dir = tmp_path / "data"
    write_schema_version(data_dir, 1)

    message = check_schema_version(data_dir)

    assert message is not None
    assert "unsupported schema v1" in message
    assert f"v{SCHEMA_VERSION}" in message
    assert "finjuice refresh" in message


def test_schema_version_check_ignores_stale_local_registry_compatibility(
    tmp_path: Path,
) -> None:
    """A stale v1 registry must not make metadata/schema_version=1 compatible."""
    data_dir = tmp_path / "data"
    _write_stale_local_registry(data_dir, current_version=1)
    write_schema_version(data_dir, 1)

    status = evaluate_schema_version(data_dir)
    message = check_schema_version(data_dir)

    assert status.state is SchemaVersionState.UNSUPPORTED
    assert status.stored_version == 1
    assert message is not None
    assert "unsupported schema v1" in message


def test_tag_command_schema_version_fresh_init_creates_file(tmp_path: Path) -> None:
    """A first successful pipeline command should create metadata/schema_version."""
    data_dir = _create_taggable_data_dir(tmp_path)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "tag"])

    assert result.exit_code == 0, result.output
    assert read_schema_version(data_dir) == SCHEMA_VERSION


def test_tag_command_schema_version_mismatch_warns_and_updates_file(tmp_path: Path) -> None:
    """Standalone tag runs should warn on mismatch and rewrite the tracked version."""
    data_dir = _create_taggable_data_dir(tmp_path)
    write_schema_version(data_dir, SCHEMA_VERSION - 1)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "tag"])

    assert result.exit_code == 0, result.output
    assert "schema mismatch" in result.output.lower()
    assert "finjuice refresh" in result.output
    assert read_schema_version(data_dir) == SCHEMA_VERSION


def test_refresh_command_schema_version_creates_file(tmp_path: Path) -> None:
    """A successful full pipeline run should persist metadata/schema_version."""
    data_dir = _create_initialized_data_dir(tmp_path)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "refresh"])

    assert result.exit_code == 0, result.output
    assert read_schema_version(data_dir) == SCHEMA_VERSION
