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
    graph: dict[str, JsonSchema] = {
        "kind": {"const": "local_graph_verified"},
        **dict.fromkeys(
            (
                "graph_digest",
                "activation_sha256",
                "wheel_basename",
                "snapshot_generation",
                "snapshot_backup_id",
                "snapshot_manifest_digest",
                "capsule_digest",
            ),
            text,
        ),
        **dict.fromkeys(
            (
                "snapshot_schema_version",
                "snapshot_revision",
                "activation_revision",
                "file_count",
            ),
            count,
        ),
    }
    contracts = (
        ("create", create),
        ("restore", restore),
        ("status", status),
        ("capture-bundle", graph),
        ("verify-bundle", graph),
        ("restore-bundle", restore),
    )
    schemas: dict[str, JsonSchema] = {}
    for action, properties in contracts:
        filename = f"ssot_backup_{action.replace('-', '_')}.schema.json"
        schema = command_schema(
            filename,
            f"ssot backup {action} --json output",
            properties,
            list(properties),
        )
        if "-" in action:
            schema["x-command"] = f"ssot.backup.{action}"
        schemas[filename] = schema
    return schemas
