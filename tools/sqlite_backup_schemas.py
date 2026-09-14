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
    copy_item: dict[str, JsonSchema] = {
        "copy_id": text,
        "created_at": {"type": ["string", "null"]},
        "graph_digest": {"type": ["string", "null"]},
        "health": {"enum": ["healthy", "held"], "type": "string"},
        "hold_reason": {"type": ["string", "null"]},
        "protected": {"type": "boolean"},
    }
    store_init: dict[str, JsonSchema] = {
        "kind": {"const": "local_recovery_store_initialized"},
        **dict.fromkeys(("store_id", "activation_sha256", "enrollment_digest"), text),
    }
    store_capture = {
        **graph,
        "kind": {"const": "local_recovery_store_captured"},
        "copy_id": text,
        "baseline_registered": {"type": "boolean"},
    }
    store_list: dict[str, JsonSchema] = {
        "kind": {"const": "local_recovery_store_inventory"},
        "store_id": text,
        "healthy_count": count,
        "held_count": count,
        "baseline_copy_ids": {"type": "array", "items": text},
        "latest_healthy_id": {"type": ["string", "null"]},
        "copies": {"type": "array", "items": {"type": "object", "properties": copy_item}},
        "plan_digest": {"type": ["string", "null"]},
    }
    store_protect: dict[str, JsonSchema] = {
        "kind": {"const": "local_recovery_store_protected"},
        "copy_id": text,
        "graph_digest": text,
    }
    policy = {
        "type": "object",
        "properties": dict.fromkeys(("daily", "weekly", "monthly"), count),
        "required": ["daily", "weekly", "monthly"],
    }
    store_plan: dict[str, JsonSchema] = {
        "kind": {"const": "local_recovery_store_plan"},
        "plan_digest": text,
        **dict.fromkeys(("delete_count", "keep_count", "protected_count"), count),
        "latest_healthy_id": {"type": ["string", "null"]},
        "policy": policy,
        **dict.fromkeys(
            ("keep_ids", "delete_ids", "protected_ids"),
            {"type": "array", "items": text},
        ),
    }
    store_prune: dict[str, JsonSchema] = {
        "kind": {"const": "local_recovery_store_pruned"},
        **dict.fromkeys(("deleted_count", "kept_count", "held_count"), count),
        "plan_digest": text,
        **dict.fromkeys(("deleted_ids", "kept_ids"), {"type": "array", "items": text}),
    }
    recording = {
        "type": ["object", "null"],
        "properties": {
            "status": {"enum": ["committed", "unknown"], "type": "string"},
            "changeset_id": text,
            "committed_revision": count,
            "replayed": {"type": "boolean"},
        },
    }
    backup_lanes = {
        "type": "object",
        "properties": {
            "destination": {
                "enum": [
                    "covered",
                    "pending",
                    "transfer_failed",
                    "verification_failed",
                    "unknown",
                ],
                "type": "string",
            },
            "local": {
                "enum": ["covered", "pending", "verification_failed", "unknown"],
                "type": "string",
            },
        },
        "required": ["destination", "local"],
    }
    deliver: dict[str, JsonSchema] = {
        "kind": {"enum": ["backup_delivery_status", "backup_delivery_run"], "type": "string"},
        "job_id": text,
        "recording": recording,
        "backup": backup_lanes,
        "source_observed_revision": {"type": ["integer", "null"], "minimum": 0},
        "coverage_as_of": {"type": ["string", "null"]},
        "pending_commit_count": {"type": ["integer", "null"], "minimum": 0},
        "last_verified_at": {"type": ["string", "null"]},
        "last_attempt_error_code": {"type": ["string", "null"]},
        "history_unknown": {"type": "boolean"},
        "attempt": {"type": ["object", "null"]},
    }
    contracts = (
        ("create", create),
        ("restore", restore),
        ("status", status),
        ("capture-bundle", graph),
        ("verify-bundle", graph),
        ("restore-bundle", restore),
        ("store init", store_init),
        ("store capture", store_capture),
        ("store list", store_list),
        ("store verify", graph),
        ("store restore", restore),
        ("store protect", store_protect),
        ("store plan", store_plan),
        ("store prune", store_prune),
        ("deliver status", deliver),
        ("deliver run", deliver),
    )
    schemas: dict[str, JsonSchema] = {}
    for action, properties in contracts:
        filename = f"ssot_backup_{action.replace('-', '_').replace(' ', '_')}.schema.json"
        schema = command_schema(
            filename,
            f"ssot backup {action} --json output",
            properties,
            list(properties),
        )
        if action.startswith("deliver "):
            schema["$defs"] = {
                "projection": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                }
            }
        if "-" in action or " " in action:
            schema["x-command"] = "ssot.backup." + action.replace(" ", ".")
        schemas[filename] = schema
    return schemas
