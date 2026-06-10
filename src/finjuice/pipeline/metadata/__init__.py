"""
Metadata management for finjuice.

Handles import history tracking with file_id system for token-efficient CSV storage.
Supports optional archiving for reproducibility (Issue #62).
"""

from finjuice.pipeline.metadata.import_history import (
    archive_source_file,
    generate_file_id,
    get_metadata_path,
    get_source_file_info,
    list_source_files,
    record_import,
)
from finjuice.pipeline.metadata.schema_version import (
    SchemaVersionState,
    SchemaVersionStatus,
    check_schema_version,
    evaluate_schema_version,
    read_schema_version,
    write_schema_version,
)

__all__ = [
    "archive_source_file",
    "check_schema_version",
    "evaluate_schema_version",
    "generate_file_id",
    "get_metadata_path",
    "read_schema_version",
    "SchemaVersionState",
    "SchemaVersionStatus",
    "get_source_file_info",
    "list_source_files",
    "record_import",
    "write_schema_version",
]
