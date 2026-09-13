"""Output contracts for local SQLite snapshots and inactive restore receipts."""

from .generate_schemas_helpers import JsonSchema, command_schema


def sqlite_backup_schemas() -> dict[str, JsonSchema]:
    """Describe path-free API receipts without claiming activation evidence."""
    text: JsonSchema = {"type": "string"}
    count: JsonSchema = {"type": "integer", "minimum": 0}
    create: dict[str, JsonSchema] = {
        **dict.fromkeys(
            ("backup_id", "backup_kind", "database_digest", "manifest_digest", "source_generation"),
            text,
        ),
        **dict.fromkeys(
            ("byte_count", "dataset_revision", "file_count", "manifest_schema_version"), count
        ),
        "complete": {"const": True},
        "status": {"const": "complete"},
        "warnings": {"type": "array", "items": text},
    }
    restore: dict[str, JsonSchema] = {
        **dict.fromkeys(
            (
                "restore_id",
                "descriptor_digest",
                "dataset_generation",
                "initial_database_digest",
                "source_manifest_digest",
            ),
            text,
        ),
        **dict.fromkeys(("initial_dataset_revision", "sqlite_schema_version"), count),
    }
    status: dict[str, JsonSchema] = {
        "byte_count": count,
        "file_count": count,
        "complete": {"type": "boolean"},
        "reason": text,
        "manifest_digest": {"type": ["string", "null"]},
        "source_generation": {"type": ["string", "null"]},
    }
    return {
        f"ssot_backup_{action}.schema.json": command_schema(
            f"ssot_backup_{action}.schema.json",
            f"ssot backup {action} --json output",
            properties,
            list(properties),
        )
        for action, properties in (("create", create), ("restore", restore), ("status", status))
    }
