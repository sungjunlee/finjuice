"""
Tests for schema registry module.

Tests schema loading, version detection, and validation against schema.yaml.
"""

import re
from pathlib import Path
from typing import Any, Generator

import pytest
import yaml

from finjuice.pipeline.constants import SCHEMA_VERSION
from finjuice.pipeline.metadata.import_history import generate_file_id
from finjuice.pipeline.storage.schema_registry import (
    PartitionSchemaSummary,
    SchemaCompatibilityState,
    clear_cache,
    detect_schema_version,
    get_column_definition,
    get_current_schema,
    get_schema_migration_guidance,
    get_schema_version,
    list_migrations,
    load_schema_registry,
    summarize_partition_schema_versions,
    validate_column_names,
)

V2_COLUMNS = [
    "row_hash",
    "date",
    "time",
    "type_raw",
    "type_norm",
    "major_raw",
    "minor_raw",
    "merchant_raw",
    "memo_raw",
    "amount",
    "account",
    "currency",
    "counterparty",
    "datetime",
    "tags_rule",
    "tags_ai",
    "tags_manual",
    "tags_final",
    "confidence",
    "needs_review",
    "is_transfer",
    "transfer_group_id",
    "file_id",
    "source_row",
]


def _write_schema_file(metadata_dir: Path, schema: dict[str, Any]) -> None:
    """Write schema registry data to metadata/schema.yaml."""
    metadata_dir.mkdir(parents=True, exist_ok=True)
    schema_path = metadata_dir / "schema.yaml"
    schema_path.write_text(
        yaml.safe_dump(schema, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _build_v2_schema_registry() -> dict[str, Any]:
    """Build a minimal v2 schema registry for explicit compatibility tests."""
    return {
        "current_version": 2,
        "schemas": {
            "v2": {
                "active": True,
                "partition_schema": {
                    "columns": [
                        {
                            "name": column_name,
                            "type": "string",
                            "description": f"{column_name} column",
                        }
                        for column_name in V2_COLUMNS
                    ]
                },
            }
        },
        "migrations": [
            {
                "version": 2,
                "from_version": 1,
                "issue": "#59",
                "title": "CSV Metadata Optimization",
                "executed_at": "2025-11-03T20:45:30Z",
                "changes": [],
                "results": {},
            }
        ],
    }


def _build_v1_schema_registry() -> dict[str, Any]:
    """Build a stale v1-only registry to verify unsupported legacy detection."""
    return {
        "current_version": 1,
        "schemas": {
            "v1": {
                "active": True,
                "partition_schema": {
                    "columns": [
                        {
                            "name": "legacy_hash",
                            "type": "string",
                            "description": "legacy hash column",
                        },
                        {
                            "name": "date",
                            "type": "date",
                            "description": "date column",
                        },
                    ]
                },
            }
        },
    }


@pytest.fixture(autouse=True)
def isolated_schema_registry_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Path, None, None]:
    """Isolate schema registry defaults from local OS/home paths."""
    # Arrange
    clear_cache()
    data_dir = tmp_path / "data"
    metadata_dir = data_dir / "metadata"
    template_schema_path = Path(__file__).resolve().parents[1] / "templates" / "schema.yaml"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "schema.yaml").write_text(
        template_schema_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    monkeypatch.setenv("FINJUICE_DATA_DIR", str(data_dir))
    monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

    # Act
    yield metadata_dir

    # Assert (teardown)
    clear_cache()


@pytest.fixture
def v2_metadata_dir(tmp_path: Path) -> Path:
    """Create explicit v2-only metadata dir for compatibility-path tests."""
    metadata_dir = tmp_path / "metadata_v2"
    _write_schema_file(metadata_dir, _build_v2_schema_registry())
    return metadata_dir


class TestLoadSchemaRegistry:
    """Test schema.yaml loading."""

    def test_load_schema_registry_success(self, tmp_path):
        """Should load and parse schema.yaml successfully."""
        # Arrange - Create minimal schema.yaml
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
    partition_schema:
      columns:
        - {name: row_hash, type: string}
""",
            encoding="utf-8",
        )

        # Act
        schema = load_schema_registry(metadata_dir)

        # Assert
        assert schema["current_version"] == 2
        assert "schemas" in schema
        assert "v2" in schema["schemas"]

    def test_load_schema_registry_not_found(self, tmp_path):
        """Should raise FileNotFoundError if schema.yaml doesn't exist."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()

        # Act & Assert
        with pytest.raises(FileNotFoundError, match="Schema registry not found"):
            load_schema_registry(metadata_dir)

    def test_load_schema_registry_malformed_yaml(self, tmp_path):
        """Should raise YAMLError for malformed YAML."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text("invalid: yaml: content: [unclosed", encoding="utf-8")

        # Act & Assert
        with pytest.raises(Exception, match="Failed to parse"):
            load_schema_registry(metadata_dir)

    def test_load_schema_registry_missing_current_version(self, tmp_path):
        """Should raise ValueError if current_version is missing."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text("schemas: {}", encoding="utf-8")

        # Act & Assert
        with pytest.raises(ValueError, match="missing 'current_version'"):
            load_schema_registry(metadata_dir)

    def test_load_schema_registry_caching(self, tmp_path):
        """Should cache loaded schema for performance."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
""",
            encoding="utf-8",
        )

        # Act - Load twice
        clear_cache()  # Ensure clean state
        schema1 = load_schema_registry(metadata_dir)
        schema2 = load_schema_registry(metadata_dir)

        # Assert - Same cached object
        assert schema1 is schema2


class TestDefaultMetadataResolution:
    """Test default metadata_dir resolution with and without environment variable."""

    def test_get_current_schema_uses_env_path_when_set(self, tmp_path, monkeypatch):
        """Should resolve metadata from FINJUICE_DATA_DIR when environment variable is set."""
        # Arrange
        clear_cache()
        env_data_dir = tmp_path / "env_data"
        metadata_dir = env_data_dir / "metadata"
        _write_schema_file(
            metadata_dir,
            {
                "current_version": 9,
                "schemas": {
                    "v9": {
                        "active": True,
                        "introduced": "2026-02-23",
                        "description": "from-env",
                        "partition_schema": {
                            "columns": [
                                {
                                    "name": "row_hash",
                                    "type": "string",
                                    "description": "hash",
                                }
                            ]
                        },
                    }
                },
            },
        )
        monkeypatch.setenv("FINJUICE_DATA_DIR", str(env_data_dir))
        monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)

        # Act
        schema = get_current_schema()

        # Assert
        assert schema["description"] == "from-env"

    def test_get_current_schema_uses_default_data_dir_when_env_missing(self, tmp_path, monkeypatch):
        """Should fall back to get_default_data_dir when FINJUICE_DATA_DIR is not set."""
        # Arrange
        import finjuice.pipeline.config as config_module

        clear_cache()
        fallback_data_dir = tmp_path / "fallback_data"
        metadata_dir = fallback_data_dir / "metadata"
        _write_schema_file(
            metadata_dir,
            {
                "current_version": 8,
                "schemas": {
                    "v8": {
                        "active": True,
                        "introduced": "2026-02-23",
                        "description": "from-default-data-dir",
                        "partition_schema": {
                            "columns": [
                                {
                                    "name": "row_hash",
                                    "type": "string",
                                    "description": "hash",
                                }
                            ]
                        },
                    }
                },
            },
        )
        monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
        monkeypatch.delenv("BSALAD_DATA_DIR", raising=False)
        monkeypatch.setattr(config_module, "get_default_data_dir", lambda: fallback_data_dir)

        # Act
        schema = get_current_schema()

        # Assert
        assert schema["description"] == "from-default-data-dir"


class TestGetCurrentSchema:
    """Test current schema retrieval."""

    def test_get_current_schema_success(self):
        """Should retrieve current active schema definition."""
        # Act - Use actual project schema
        schema = get_current_schema()

        # Assert
        assert "partition_schema" in schema
        assert "columns" in schema["partition_schema"]
        assert len(schema["partition_schema"]["columns"]) == 28  # v4 has 28 columns

    def test_get_current_schema_has_required_fields(self):
        """Current schema should have all required metadata fields."""
        # Act
        schema = get_current_schema()

        # Assert
        assert "active" in schema
        assert "introduced" in schema
        assert "description" in schema
        assert schema["active"] is True

    def test_get_current_schema_columns_match_csv_partition(self):
        """Schema columns should match CSV_COLUMNS from csv_partition.py."""
        # Arrange - Import expected columns
        from finjuice.pipeline.storage.csv_partition import CSV_COLUMNS

        # Act
        schema = get_current_schema()
        schema_columns = [col["name"] for col in schema["partition_schema"]["columns"]]

        # Assert
        assert schema_columns == CSV_COLUMNS


class TestGetSchemaVersion:
    """Test schema version auto-detection."""

    def test_detect_schema_version_active_partition(self, tmp_path, isolated_schema_registry_env):
        """Active v4 partitions should be detected as active."""
        # Arrange
        schema = get_current_schema()
        columns = [col["name"] for col in schema["partition_schema"]["columns"]]
        csv_file = tmp_path / "transactions.csv"
        csv_file.write_text(",".join(columns) + "\n", encoding="utf-8")

        # Act
        detection = detect_schema_version(csv_file, metadata_dir=isolated_schema_registry_env)

        # Assert
        assert detection.version == 4
        assert detection.state is SchemaCompatibilityState.ACTIVE
        assert detection.is_supported is True
        assert detection.is_legacy is False

    def test_detect_schema_version_v2_compatible_legacy_partition(
        self,
        tmp_path,
        isolated_schema_registry_env,
    ):
        """Inactive v2 partitions should be detected as compatible legacy under v3."""
        # Arrange
        csv_file = tmp_path / "transactions.csv"
        csv_file.write_text(",".join(V2_COLUMNS) + "\n", encoding="utf-8")

        # Act
        detection = detect_schema_version(csv_file, metadata_dir=isolated_schema_registry_env)
        version = get_schema_version(csv_file, metadata_dir=isolated_schema_registry_env)
        guidance = get_schema_migration_guidance(
            detection,
            metadata_dir=isolated_schema_registry_env,
        )

        # Assert
        assert detection.version == 2
        assert detection.state is SchemaCompatibilityState.COMPATIBLE_LEGACY
        assert detection.is_supported is True
        assert detection.is_legacy is True
        assert version == 2
        assert guidance["command"] == "finjuice refresh"
        assert "category_rule/category_final" in guidance["message"]

    def test_detect_schema_version_uses_packaged_compatibility_with_stale_v2_registry(
        self,
        tmp_path: Path,
    ) -> None:
        """Stale v2 metadata/schema.yaml should not make v2 partitions look active."""
        # Arrange
        data_dir = tmp_path / "data"
        metadata_dir = data_dir / "metadata"
        _write_schema_file(metadata_dir, _build_v2_schema_registry())
        csv_file = data_dir / "transactions" / "2024" / "10" / "transactions.csv"
        csv_file.parent.mkdir(parents=True)
        csv_file.write_text(",".join(V2_COLUMNS) + "\n", encoding="utf-8")

        # Act
        detection = detect_schema_version(csv_file, metadata_dir=metadata_dir)
        summary = summarize_partition_schema_versions([csv_file], metadata_dir=metadata_dir)

        # Assert
        assert detection.current_version == SCHEMA_VERSION
        assert detection.version == 2
        assert detection.state is SchemaCompatibilityState.COMPATIBLE_LEGACY
        assert summary.state is SchemaCompatibilityState.COMPATIBLE_LEGACY
        assert summary.compatible_legacy_versions == (2,)
        assert summary.active_versions == ()

    def test_detect_schema_version_uses_stale_v1_registry_only_for_header_matching(
        self,
        tmp_path: Path,
    ) -> None:
        """Stale v1 metadata/schema.yaml can identify headers but not compatibility."""
        # Arrange
        data_dir = tmp_path / "data"
        metadata_dir = data_dir / "metadata"
        _write_schema_file(metadata_dir, _build_v1_schema_registry())
        csv_file = data_dir / "transactions" / "2024" / "10" / "transactions.csv"
        csv_file.parent.mkdir(parents=True)
        csv_file.write_text("legacy_hash,date\n", encoding="utf-8")

        # Act
        detection = detect_schema_version(csv_file, metadata_dir=metadata_dir)
        summary = summarize_partition_schema_versions([csv_file], metadata_dir=metadata_dir)

        # Assert
        assert detection.current_version == SCHEMA_VERSION
        assert detection.version == 1
        assert detection.state is SchemaCompatibilityState.UNSUPPORTED
        assert detection.is_supported is False
        assert summary.state is SchemaCompatibilityState.UNSUPPORTED
        assert summary.unsupported_versions == (1,)
        assert summary.unsupported_count == 1

    def test_migration_guidance_reports_unsupported_summary_versions(
        self,
        isolated_schema_registry_env,
    ) -> None:
        """Unsupported summary guidance should report blockers, not compatible legacy versions."""
        # Arrange
        summary = PartitionSchemaSummary(
            state=SchemaCompatibilityState.UNSUPPORTED,
            current_version=SCHEMA_VERSION,
            partition_count=2,
            active_versions=(),
            compatible_legacy_versions=(2,),
            unsupported_versions=(1,),
            unsupported_count=1,
        )

        # Act
        guidance = get_schema_migration_guidance(
            summary,
            metadata_dir=isolated_schema_registry_env,
        )

        # Assert
        assert "Detected unsupported schema v1" in guidance["message"]
        assert "v2" not in guidance["message"]
        assert "unknown" not in guidance["message"]

    def test_get_schema_version_v2_partition(self, tmp_path, v2_metadata_dir):
        """Should detect v2 schema from CSV partition when v2 registry is provided."""
        # Arrange - Create CSV with v2 schema
        csv_file = tmp_path / "transactions.csv"
        csv_file.write_text(
            ",".join(V2_COLUMNS) + "\n",
            encoding="utf-8",
        )

        # Act
        version = get_schema_version(csv_file, metadata_dir=v2_metadata_dir)

        # Assert
        assert version == 2

    def test_get_schema_version_file_not_found(self):
        """Should raise FileNotFoundError for non-existent file."""
        # Arrange
        csv_file = Path("nonexistent.csv")

        # Act & Assert
        with pytest.raises(FileNotFoundError, match="CSV file not found"):
            get_schema_version(csv_file)

    def test_get_schema_version_empty_file(self, tmp_path):
        """Should raise ValueError for empty CSV file."""
        # Arrange
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("", encoding="utf-8")

        # Act & Assert
        with pytest.raises(ValueError, match="Empty CSV file"):
            get_schema_version(csv_file)

    def test_get_schema_version_unknown_schema(self, tmp_path):
        """Should raise ValueError for unrecognized schema."""
        # Arrange - Create CSV with unknown column structure
        csv_file = tmp_path / "unknown.csv"
        csv_file.write_text("col1,col2,col3\n", encoding="utf-8")

        # Act & Assert
        with pytest.raises(ValueError, match="Could not detect schema version"):
            get_schema_version(csv_file)

    def test_detect_schema_version_unsupported_inactive_partition(self, tmp_path):
        """Known but incompatible inactive schemas should be reported as unsupported."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        _write_schema_file(
            metadata_dir,
            {
                "current_version": 3,
                "minimum_compatible_version": 2,
                "schemas": {
                    "v3": {
                        "active": True,
                        "partition_schema": {
                            "columns": [
                                {"name": "row_hash", "type": "string"},
                                {"name": "date", "type": "date"},
                            ]
                        },
                    },
                    "v1": {
                        "active": False,
                        "partition_schema": {
                            "columns": [
                                {"name": "legacy_hash", "type": "string"},
                                {"name": "date", "type": "date"},
                            ]
                        },
                    },
                },
                "compatibility": {"v3": {"can_read": [2, 3]}},
            },
        )
        csv_file = tmp_path / "legacy.csv"
        csv_file.write_text("legacy_hash,date\n", encoding="utf-8")

        # Act
        detection = detect_schema_version(csv_file, metadata_dir=metadata_dir)

        # Assert
        assert detection.version == 1
        assert detection.state is SchemaCompatibilityState.UNSUPPORTED
        assert detection.is_supported is False


class TestListMigrations:
    """Test migration history retrieval."""

    def test_list_migrations_returns_list(self):
        """Should return list of migration records."""
        # Act
        migrations = list_migrations()

        # Assert
        assert isinstance(migrations, list)
        assert len(migrations) > 0  # At least Issue #59 migration

    def test_list_migrations_has_issue_59(self):
        """Should include Issue #59 migration."""
        # Act
        migrations = list_migrations()

        # Assert
        issue_59 = next((m for m in migrations if m["issue"] == "#59"), None)
        assert issue_59 is not None
        assert issue_59["version"] == 2
        assert issue_59["title"] == "CSV Metadata Optimization"

    def test_list_migrations_sorted_by_version(self):
        """Migrations should be sorted by version ascending."""
        # Act
        migrations = list_migrations()

        # Assert
        versions = [m["version"] for m in migrations]
        assert versions == sorted(versions)

    def test_list_migrations_has_required_fields(self):
        """Each migration should have required fields."""
        # Act
        migrations = list_migrations()

        # Assert
        for migration in migrations:
            assert "version" in migration
            assert "from_version" in migration
            assert "issue" in migration
            assert "title" in migration
            assert "changes" in migration


class TestGetColumnDefinition:
    """Test column definition lookup."""

    def test_get_column_definition_row_hash(self):
        """Should retrieve row_hash column definition."""
        # Act
        col = get_column_definition("row_hash")

        # Assert
        assert col is not None
        assert col["name"] == "row_hash"
        assert col["type"] == "string"
        assert col["length"] == 16

    def test_get_column_definition_file_id(self):
        """Should retrieve file_id column definition."""
        # Act
        col = get_column_definition("file_id")

        # Assert
        assert col is not None
        assert col["name"] == "file_id"
        assert col["type"] == "string"
        assert col["min_length"] == 8
        assert col["common_length"] == 8
        assert col["pattern"] == "^(?:\\d{6}_\\d+|[0-9a-f]{8})$"

    def test_get_column_definition_not_found(self):
        """Should return None for non-existent column."""
        # Act
        col = get_column_definition("nonexistent_column")

        # Assert
        assert col is None

    def test_get_column_definition_specific_version(self):
        """Should retrieve column definition for specific version."""
        # Act
        col = get_column_definition("row_hash", schema_version=2)

        # Assert
        assert col is not None
        assert col["name"] == "row_hash"


class TestValidateColumnNames:
    """Test CSV column name validation."""

    def test_validate_column_names_valid_v2(self, tmp_path, v2_metadata_dir):
        """Should validate CSV with correct v2 schema using explicit metadata dir."""
        # Arrange - Create valid v2 CSV
        csv_file = tmp_path / "transactions.csv"
        csv_file.write_text(
            ",".join(V2_COLUMNS) + "\n",
            encoding="utf-8",
        )

        # Act
        result = validate_column_names(csv_file, metadata_dir=v2_metadata_dir)

        # Assert
        assert result["valid"] is True
        assert result["errors"] == []
        assert result["detected_version"] == 2

    def test_validate_column_names_missing_columns(self, tmp_path):
        """Should report error for missing columns."""
        # Arrange - CSV with only 3 columns
        csv_file = tmp_path / "transactions.csv"
        csv_file.write_text("row_hash,date,time\n", encoding="utf-8")

        # Act
        result = validate_column_names(csv_file)

        # Assert
        assert result["valid"] is False
        assert len(result["errors"]) > 0
        # Since schema version cannot be detected, error message includes "Could not detect"
        assert "Could not detect schema version" in result["errors"][0]

    def test_validate_column_names_wrong_order(self, tmp_path):
        """Should report error for wrong column order."""
        # Arrange - CSV with columns in wrong order
        csv_file = tmp_path / "transactions.csv"
        csv_file.write_text(
            "date,row_hash,time,type_raw,type_norm,major_raw,minor_raw,merchant_raw,"
            "memo_raw,amount,account,currency,counterparty,datetime,tags_rule,tags_ai,"
            "tags_manual,tags_final,confidence,needs_review,is_transfer,"
            "transfer_group_id,file_id,source_row\n",
            encoding="utf-8",
        )

        # Act
        result = validate_column_names(csv_file)

        # Assert
        assert result["valid"] is False
        # Schema version detection fails due to wrong column order
        assert "Could not detect schema version" in result["errors"][0]

    def test_validate_column_names_file_not_found(self):
        """Should return validation error for non-existent file."""
        # Arrange
        csv_file = Path("nonexistent.csv")

        # Act
        result = validate_column_names(csv_file)

        # Assert
        assert result["valid"] is False
        assert "File not found" in result["errors"][0]

    def test_validate_column_names_empty_file(self, tmp_path):
        """Should return validation error for empty file."""
        # Arrange
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("", encoding="utf-8")

        # Act
        result = validate_column_names(csv_file)

        # Assert
        assert result["valid"] is False
        assert "Empty CSV file" in result["errors"][0]


class TestClearCache:
    """Test cache management."""

    def test_clear_cache_forces_reload(self, tmp_path):
        """Should force reload after clearing cache."""
        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
    description: "Initial"
""",
            encoding="utf-8",
        )

        # Act - Load, modify, clear, reload
        schema1 = load_schema_registry(metadata_dir)
        assert schema1["schemas"]["v2"]["description"] == "Initial"

        schema_file.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
    description: "Modified"
""",
            encoding="utf-8",
        )

        clear_cache()
        schema2 = load_schema_registry(metadata_dir)

        # Assert - Reloaded with new content
        assert schema2["schemas"]["v2"]["description"] == "Modified"


class TestSchemaStructure:
    """Test actual schema.yaml structure and content."""

    def test_schema_has_28_columns(self):
        """v4 schema should have exactly 28 columns."""
        # Act
        schema = get_current_schema()

        # Assert
        columns = schema["partition_schema"]["columns"]
        assert len(columns) == 28

    def test_schema_has_validation_rules(self, isolated_schema_registry_env):
        """Schema should define validation rules."""
        # Act
        schema = load_schema_registry(isolated_schema_registry_env)

        # Assert
        assert "validation_rules" in schema
        assert len(schema["validation_rules"]) > 0

    def test_schema_has_migration_history(self):
        """Schema should record migration history."""
        # Act
        migrations = list_migrations()

        # Assert
        assert len(migrations) >= 1  # At least Issue #59
        migration = migrations[0]
        assert "changes" in migration
        assert "results" in migration

    def test_schema_columns_have_required_fields(self):
        """Each column definition should have required fields."""
        # Act
        schema = get_current_schema()
        columns = schema["partition_schema"]["columns"]

        # Assert
        for col in columns:
            assert "name" in col, f"Column missing name: {col}"
            assert "type" in col, f"Column {col['name']} missing type"
            assert "description" in col, f"Column {col['name']} missing description"

    def test_schema_token_efficiency_documented(self):
        """Schema should document token efficiency metrics."""
        # Act
        schema = get_current_schema()

        # Assert
        assert "metrics" in schema
        metrics = schema["metrics"]
        assert metrics["csv_columns"] == 28
        assert "new_columns" in metrics
        assert set(metrics["new_columns"]) == {"notes_manual"}

    def test_v4_compatibility_documents_refresh_migration_path(
        self,
        isolated_schema_registry_env: Path,
    ):
        """v4 compatibility notes should match the runtime refresh/backfill behavior."""
        # Act
        registry = load_schema_registry(isolated_schema_registry_env)
        compatibility = registry["compatibility"]["v4"]
        migration_strategy = registry["migrations"][0]["migration_strategy"]

        # Assert
        assert compatibility["migration_required"] is False
        assert "finjuice refresh" in compatibility["runtime_migration"]
        assert "notes_manual" in compatibility["runtime_migration"]
        assert "is_transfer_candidate" in compatibility["runtime_migration"]
        assert "rules.yaml is missing" in compatibility["runtime_migration"]
        assert "tagging is skipped" in compatibility["runtime_migration"]
        assert "No eager migration required" in compatibility["manual_migration"]
        assert "write_month" in compatibility["note"]
        assert "rules.yaml is missing" in migration_strategy["runtime_path"]
        assert "not required" in migration_strategy["manual_script"]

    @pytest.mark.parametrize(
        ("file_path", "existing_ids", "expected_file_id"),
        [
            (Path("data/imports/2024-10-27~2025-10-27.xlsx"), set(), "241027_1"),
            (
                Path("data/imports/2024-10-27~2025-10-27.xlsx"),
                {f"241027_{i}" for i in range(1, 100)},
                "241027_100",
            ),
            (Path("data/imports/banksalad_export.xlsx"), set(), None),
        ],
    )
    def test_file_id_schema_pattern_matches_real_generated_ids(
        self,
        file_path: Path,
        existing_ids: set[str],
        expected_file_id: str | None,
        isolated_schema_registry_env: Path,
    ):
        """schema.yaml file_id regexes should accept IDs generated by import history."""
        # Arrange
        registry = load_schema_registry(isolated_schema_registry_env)
        file_id_column = get_column_definition(
            "file_id",
            metadata_dir=isolated_schema_registry_env,
        )
        validation_rule = next(
            rule for rule in registry["validation_rules"] if rule.get("field") == "file_id"
        )

        # Act
        file_id = generate_file_id(file_path, existing_ids)

        # Assert
        if expected_file_id is not None:
            assert file_id == expected_file_id
        assert file_id_column is not None
        assert re.fullmatch(file_id_column["pattern"], file_id)
        assert re.fullmatch(validation_rule["regex"], file_id)


class TestThreadSafety:
    """
    Test thread safety of schema registry caching.

    These tests verify that the double-checked locking pattern provides proper
    thread safety for concurrent access to load_schema_registry().

    Implementation:
    - Fast path: Atomic dict.get() without lock
    - Slow path: Lock-protected double-check and file load
    - TOCTOU-safe: Uses .get() instead of check-then-use pattern
    """

    def test_concurrent_schema_loading_returns_same_object(self, tmp_path):
        """
        Multiple threads should receive the same cached schema object.

        This verifies that the double-checked locking pattern properly handles
        concurrent access without race conditions.
        """
        from concurrent.futures import ThreadPoolExecutor

        # Arrange - Create test schema
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
    partition_schema:
      columns:
        - {name: row_hash, type: string}
        - {name: date, type: date}
""",
            encoding="utf-8",
        )

        # Clear cache to ensure fresh start
        clear_cache()

        # Act - Load from 100 concurrent threads
        def load_schema():
            return load_schema_registry(metadata_dir)

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(load_schema) for _ in range(100)]
            results = [f.result() for f in futures]

        # Assert - All results should be the same cached object
        first_result = results[0]
        assert all(r is first_result for r in results), (
            "All threads should receive same cached object"
        )
        assert all(r["current_version"] == 2 for r in results)

    def test_cache_clear_is_thread_safe(self, tmp_path):
        """
        Cache clearing should work correctly with concurrent access.

        Verifies that clear_cache() can be called safely even while
        other threads are accessing the cache.
        """
        import time
        from concurrent.futures import ThreadPoolExecutor

        # Arrange - Create test schema
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
    partition_schema:
      columns: []
""",
            encoding="utf-8",
        )

        clear_cache()

        # Act - Load from multiple threads while clearing cache
        results = []
        errors = []

        def load_and_sleep():
            try:
                schema = load_schema_registry(metadata_dir)
                time.sleep(0.001)  # Simulate some work
                return schema
            except Exception as e:
                errors.append(e)
                raise

        def clear_repeatedly():
            for _ in range(10):
                clear_cache()
                time.sleep(0.001)

        with ThreadPoolExecutor(max_workers=11) as executor:
            # 10 threads loading, 1 thread clearing
            load_futures = [executor.submit(load_and_sleep) for _ in range(10)]
            clear_future = executor.submit(clear_repeatedly)

            # Wait for completion
            clear_future.result()
            results = [f.result() for f in load_futures]

        # Assert - No errors, all results valid
        assert len(errors) == 0, f"No errors should occur: {errors}"
        assert len(results) == 10
        assert all(r["current_version"] == 2 for r in results)

    def test_concurrent_access_to_different_paths(self, tmp_path):
        """
        Loading from different metadata_dir paths should not conflict.

        Verifies that the cache correctly stores schemas per metadata_dir path,
        allowing multiple schemas to be cached simultaneously.
        """
        from concurrent.futures import ThreadPoolExecutor

        # Arrange - Create two different schema files
        metadata_dir1 = tmp_path / "metadata1"
        metadata_dir1.mkdir()
        schema_file1 = metadata_dir1 / "schema.yaml"
        schema_file1.write_text(
            """
current_version: 1
schemas:
  v1:
    active: true
""",
            encoding="utf-8",
        )

        metadata_dir2 = tmp_path / "metadata2"
        metadata_dir2.mkdir()
        schema_file2 = metadata_dir2 / "schema.yaml"
        schema_file2.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
""",
            encoding="utf-8",
        )

        clear_cache()

        # Act - Load both schemas concurrently
        def load_schema1():
            return load_schema_registry(metadata_dir1)

        def load_schema2():
            return load_schema_registry(metadata_dir2)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures1 = [executor.submit(load_schema1) for _ in range(50)]
            futures2 = [executor.submit(load_schema2) for _ in range(50)]

            results1 = [f.result() for f in futures1]
            results2 = [f.result() for f in futures2]

        # Assert - Each path has its own cached object
        assert all(r["current_version"] == 1 for r in results1)
        assert all(r["current_version"] == 2 for r in results2)
        assert all(r is results1[0] for r in results1), "Path 1 results should be same object"
        assert all(r is results2[0] for r in results2), "Path 2 results should be same object"

    def test_high_concurrency_stress_test(self, tmp_path):
        """
        Stress test with high concurrency to detect race conditions.

        Runs 1000 concurrent loads to stress-test the cache implementation.
        """
        from concurrent.futures import ThreadPoolExecutor

        # Arrange
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        schema_file = metadata_dir / "schema.yaml"
        schema_file.write_text(
            """
current_version: 2
schemas:
  v2:
    active: true
    partition_schema:
      columns:
        - {name: row_hash, type: string}
""",
            encoding="utf-8",
        )

        clear_cache()

        # Act - 1000 concurrent loads
        def load_schema():
            return load_schema_registry(metadata_dir)

        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(load_schema) for _ in range(1000)]
            results = [f.result() for f in futures]

        # Assert - All results identical
        assert len(results) == 1000
        assert all(r is results[0] for r in results), "All 1000 loads should return same object"
        assert all(r["current_version"] == 2 for r in results)
