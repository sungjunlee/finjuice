"""Privacy-safe output contracts for inactive migration commands."""

from .generate_schemas_helpers import JsonSchema, command_schema


def migration_schemas() -> dict[str, JsonSchema]:
    """Describe summaries only; source locators remain in private evidence files."""
    common: dict[str, JsonSchema] = {
        "status": {"enum": ["ok", "already_complete"]},
        "phase": {"enum": ["migration_plan", "migration_verify"]},
        "manifest_digest": {"type": "string", "pattern": "^sha256:[a-f0-9]{64}$"},
        "input_count": {"type": "integer", "minimum": 0},
        "cutover_ready": {"const": False},
        "limitations": {"type": "array", "items": {"type": "string"}},
    }
    verified: dict[str, JsonSchema] = {
        **common,
        "generation_status": {"const": "inactive"},
        "attempt_id": {"type": "string", "pattern": "^[a-f0-9]{32}$"},
        "origin_kind": {"const": "legacy_current_state"},
        "dataset_revision": {"const": 0},
        "checks": {
            "type": "object",
            "additionalProperties": {"enum": ["passed", "not_run", "failed"]},
        },
    }
    result = {}
    for action in ("plan", "build", "verify"):
        properties = common if action == "plan" else verified
        filename = f"ssot_migrate_{action}.schema.json"
        result[filename] = command_schema(
            filename, f"ssot migrate {action} --json output", properties, list(properties)
        )
    return result
