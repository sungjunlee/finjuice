"""Schema version tracking for finjuice data directories."""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from finjuice.pipeline.constants import SCHEMA_VERSION
from finjuice.pipeline.storage.schema_registry import get_compatible_read_versions

SCHEMA_VERSION_FILENAME: Final = "schema_version"


class SchemaVersionState(str, Enum):
    """Compatibility state for metadata/schema_version."""

    ACTIVE = "active"
    COMPATIBLE_LEGACY = "compatible-legacy"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class SchemaVersionStatus:
    """Evaluation result for a data directory's tracked schema version."""

    state: SchemaVersionState
    stored_version: int | None
    current_version: int
    message: str | None = None


def _get_schema_version_path(data_dir: Path) -> Path:
    """Return the metadata file path that stores the data directory schema version."""
    return data_dir / "metadata" / SCHEMA_VERSION_FILENAME


def write_schema_version(data_dir: Path, version: int) -> None:
    """Persist the schema version for a data directory."""
    schema_version_path = _get_schema_version_path(data_dir)
    schema_version_path.parent.mkdir(parents=True, exist_ok=True)
    schema_version_path.write_text(f"{version}\n", encoding="utf-8")


def read_schema_version(data_dir: Path) -> int | None:
    """Read the tracked schema version for a data directory."""
    schema_version_path = _get_schema_version_path(data_dir)
    if not schema_version_path.exists():
        return None

    raw_value = schema_version_path.read_text(encoding="utf-8").strip()
    if not raw_value:
        raise ValueError(f"Schema version file is empty: {schema_version_path}")

    try:
        return int(raw_value)
    except ValueError as exc:
        raise ValueError(f"Invalid schema version in {schema_version_path}: {raw_value!r}") from exc


def evaluate_schema_version(data_dir: Path) -> SchemaVersionStatus:
    """Evaluate the tracked data-directory schema version as active/legacy/unsupported."""
    schema_version_path = _get_schema_version_path(data_dir)

    try:
        stored_version = read_schema_version(data_dir)
    except (OSError, ValueError) as exc:
        return SchemaVersionStatus(
            state=SchemaVersionState.UNSUPPORTED,
            stored_version=None,
            current_version=SCHEMA_VERSION,
            message=(
                "Could not read the tracked data schema version from "
                f"{schema_version_path}: {exc}. finjuice expects schema v{SCHEMA_VERSION}."
            ),
        )

    if stored_version is None or stored_version == SCHEMA_VERSION:
        return SchemaVersionStatus(
            state=SchemaVersionState.ACTIVE,
            stored_version=stored_version,
            current_version=SCHEMA_VERSION,
        )

    compatible_versions = get_compatible_read_versions()
    if stored_version in compatible_versions and stored_version < SCHEMA_VERSION:
        return SchemaVersionStatus(
            state=SchemaVersionState.COMPATIBLE_LEGACY,
            stored_version=stored_version,
            current_version=SCHEMA_VERSION,
            message=(
                f"Data directory schema mismatch: compatible legacy schema v{stored_version}; "
                f"this finjuice build reads it and writes v{SCHEMA_VERSION}. "
                "Run 'finjuice refresh' to rewrite partitions and backfill "
                "category_rule/category_final."
            ),
        )

    return SchemaVersionStatus(
        state=SchemaVersionState.UNSUPPORTED,
        stored_version=stored_version,
        current_version=SCHEMA_VERSION,
        message=(
            f"Data directory uses unsupported schema v{stored_version}; "
            f"this finjuice build expects v{SCHEMA_VERSION}. Back up the data directory "
            "and run 'finjuice refresh' after migrating it to a compatible schema."
        ),
    )


def check_schema_version(data_dir: Path) -> str | None:
    """Return a schema-version warning message, or None when the version is current.

    This core helper does not emit output itself; CLI callers render the
    returned message so non-CLI code can reuse the check without depending on
    `finjuice.pipeline.cli.*`.
    """
    return evaluate_schema_version(data_dir).message
