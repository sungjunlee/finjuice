"""Generate JSON Schema artifacts for finjuice --json command outputs."""

from __future__ import annotations

import json
import sys
from dataclasses import fields, is_dataclass
from importlib import import_module
from pathlib import Path
from types import NoneType
from typing import Any, get_args, get_origin, is_typeddict

ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_cli_output = import_module("finjuice.pipeline.cli.output")
error_code_values = _cli_output.error_code_values
exit_code_items = _cli_output.exit_code_items
exit_code_values = _cli_output.exit_code_values

JsonSchema = dict[str, Any]

SCHEMAS_DIR = ROOT / "schemas"
SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"
SCHEMA_ID_BASE = "https://github.com/sungjunlee/finjuice/schemas"


def nullable(schema_type: str) -> JsonSchema:
    """Return a JSON Schema type that also allows null."""
    return {"type": [schema_type, "null"]}


def array_of(item_schema: JsonSchema) -> JsonSchema:
    """Return an array schema for a repeated item shape."""
    return {"items": item_schema, "type": "array"}


def object_schema(
    properties: dict[str, JsonSchema] | None = None,
    *,
    required: list[str] | None = None,
    additional: bool = True,
) -> JsonSchema:
    """Return an object schema with the project's additive-default policy."""
    schema: JsonSchema = {"additionalProperties": additional, "type": "object"}
    if properties:
        schema["properties"] = properties
    if required:
        schema["required"] = required
    return schema


def command_schema(
    filename: str,
    title: str,
    properties: dict[str, JsonSchema],
    required: list[str],
    *,
    additional: bool = True,
) -> JsonSchema:
    """Build a command output schema with the shared _meta envelope."""
    return {
        "$id": filename,
        "$schema": SCHEMA_DRAFT,
        "additionalProperties": additional,
        "properties": {"_meta": {"$ref": "_meta.schema.json"}, **properties},
        "required": ["_meta", *required],
        "title": title,
        "type": "object",
    }


def privacy_profile_condition(*profiles: str) -> JsonSchema:
    """Return a schema condition matching one or more _meta.privacy.profile values."""
    return {
        "properties": {
            "_meta": {
                "properties": {
                    "privacy": {
                        "properties": {
                            "profile": {
                                "enum": list(profiles),
                                "type": "string",
                            },
                        },
                        "required": ["profile"],
                        "type": "object",
                    },
                },
                "required": ["privacy"],
                "type": "object",
            },
        },
        "required": ["_meta"],
        "type": "object",
    }


def schema_from_pydantic_model(model: Any) -> JsonSchema | None:
    """Return a Draft-compatible model schema when a future output uses Pydantic."""
    model_json_schema = getattr(model, "model_json_schema", None)
    if not callable(model_json_schema):
        return None
    return dict(model_json_schema())


def schema_from_python_annotation(annotation: Any) -> JsonSchema:
    """Map simple dataclass/TypedDict annotations to JSON Schema."""
    origin = get_origin(annotation)
    args = get_args(annotation)

    if annotation is str:
        return {"type": "string"}
    if annotation is int:
        return {"type": "integer"}
    if annotation is float:
        return {"type": "number"}
    if annotation is bool:
        return {"type": "boolean"}
    if annotation is Any:
        return {}
    if origin in {list, tuple} and args:
        return array_of(schema_from_python_annotation(args[0]))
    if origin is dict:
        return object_schema(additional=True)
    if origin is not None and NoneType in args:
        non_null_args = [arg for arg in args if arg is not NoneType]
        if len(non_null_args) == 1:
            schema = schema_from_python_annotation(non_null_args[0])
            schema_type = schema.get("type")
            if isinstance(schema_type, str):
                return {"type": [schema_type, "null"]}
            return {"anyOf": [schema, {"type": "null"}]}

    return {}


def schema_from_dataclass_type(model: Any) -> JsonSchema | None:
    """Return a manual schema projection for dataclass-backed outputs."""
    if not is_dataclass(model):
        return None

    properties = {field.name: schema_from_python_annotation(field.type) for field in fields(model)}
    return object_schema(properties, required=list(properties))


def schema_from_typed_dict_type(model: Any) -> JsonSchema | None:
    """Return a manual schema projection for TypedDict-backed outputs."""
    if not is_typeddict(model):
        return None

    annotations = getattr(model, "__annotations__", {})
    required = list(getattr(model, "__required_keys__", set(annotations)))
    properties = {
        name: schema_from_python_annotation(annotation) for name, annotation in annotations.items()
    }
    return object_schema(properties, required=required)


def schema_from_structured_model(model: Any) -> JsonSchema | None:
    """Prefer Pydantic schemas, then dataclass/TypedDict projections."""
    return (
        schema_from_pydantic_model(model)
        or schema_from_dataclass_type(model)
        or schema_from_typed_dict_type(model)
    )


string = {"type": "string"}
integer = {"type": "integer"}
number = {"type": "number"}
boolean = {"type": "boolean"}
any_value: JsonSchema = {}
string_or_null = nullable("string")
integer_or_null = nullable("integer")
number_or_null = nullable("number")
object_any = object_schema()
error_code_string: JsonSchema = {"enum": list(error_code_values()), "type": "string"}
exit_code_integer: JsonSchema = {
    "enum": list(exit_code_values()),
    "minimum": 0,
    "type": "integer",
}

money_or_null: JsonSchema = {"type": ["integer", "number", "null"]}

meta_schema: JsonSchema = {
    "$id": f"{SCHEMA_ID_BASE}/_meta.schema.json",
    "$schema": SCHEMA_DRAFT,
    "additionalProperties": True,
    "properties": {
        "command": string,
        "finjuice_version": string,
        "privacy": object_schema(
            {
                "profile": {
                    "enum": ["raw", "redacted", "compact"],
                    "type": "string",
                },
            },
            required=["profile"],
        ),
        "schema_version": {"pattern": r"^[0-9]+\.[0-9]+$", "type": "string"},
        "timestamp": {"format": "date-time", "type": "string"},
    },
    "required": ["schema_version", "finjuice_version", "command", "timestamp"],
    "title": "_meta envelope",
    "type": "object",
}

error_schema: JsonSchema = {
    "$id": f"{SCHEMA_ID_BASE}/_error.schema.json",
    "$schema": SCHEMA_DRAFT,
    "properties": {
        "_meta": {"$ref": "_meta.schema.json"},
        "error": object_schema(
            {
                "code": error_code_string,
                "message": string,
                "suggestion": string_or_null,
            },
            required=["code", "message"],
        ),
        "exit_code": exit_code_integer,
    },
    "required": ["_meta", "error", "exit_code"],
    "title": "Error envelope",
    "type": "object",
}

pagination_schema: JsonSchema = {
    "$id": "_pagination.schema.json",
    "$schema": SCHEMA_DRAFT,
    "additionalProperties": False,
    "properties": {
        "cursor": string,
        "has_more": boolean,
        "limit": {"minimum": 0, "type": "integer"},
        "next_cursor": string_or_null,
        "total_estimate": {"minimum": 0, "type": ["integer", "null"]},
        "truncated_by_bytes": boolean,
    },
    "required": ["limit", "cursor", "next_cursor", "has_more"],
    "title": "Pagination envelope",
    "type": "object",
}

next_step_schema = object_schema(
    {
        "command": string,
        "message": string,
        "signal": string,
    },
    required=["signal", "message", "command"],
)

TAGGING_REVIEW_TERMS: dict[str, str] = {
    "untagged": "A transaction whose tags_final is null or an empty tag array.",
    "uncategorized": "A transaction whose category_final is the fallback category 미분류.",
    "rule_matched": (
        "A transaction with rule-derived output: non-empty tags_rule or non-empty category_rule."
    ),
    "needs_review": "The explicit row flag needs_review == 1, not every row shown by review.",
    "suggestable_untagged": (
        "An untagged transaction eligible for rules suggest after excluding confirmed "
        "internal transfer pairs."
    ),
}


def add_terminology(schema: JsonSchema, field_map: dict[str, str]) -> JsonSchema:
    """Attach canonical tagging/review term references to a command schema."""
    schema["$defs"] = {
        "tagging_review_terms": {
            "additionalProperties": {"type": "string"},
            "description": "Canonical tagging/review terminology for this JSON contract.",
            "properties": {
                term: {"description": definition, "type": "string"}
                for term, definition in TAGGING_REVIEW_TERMS.items()
            },
            "type": "object",
        }
    }
    schema["x-finjuice-field-definitions"] = field_map
    return schema


tagging_terminology_schema = object_schema(
    {
        "definitions": object_schema(
            {term: string for term in TAGGING_REVIEW_TERMS},
            required=list(TAGGING_REVIEW_TERMS),
        ),
        "reference": string,
        "schema": string,
    },
    required=["reference", "schema", "definitions"],
)


status_schema = command_schema(
    "status.schema.json",
    "status --json output",
    {
        "actionable": boolean,
        "data_directory": object_schema(
            {"path": string, "source": string},
            required=["path", "source"],
        ),
        "detailed_stats": object_any,
        "detailed_stats_warning": string_or_null,
        "health": object_schema(
            {
                "reasons": array_of(string),
                "status": {"enum": ["ok", "warning", "critical"], "type": "string"},
            },
            required=["status", "reasons"],
        ),
        "last_import": object_schema(
            {"file_id": string_or_null, "imported_at": string_or_null},
            required=["imported_at", "file_id"],
        ),
        "next_steps": array_of(next_step_schema),
        "rules_file": object_schema(
            {"exists": boolean, "modified_at": string_or_null, "path": string},
            required=["path", "exists", "modified_at"],
        ),
        "terminology": tagging_terminology_schema,
        "signals": object_schema(
            {
                "detailed_requested": boolean,
                "filters_applied": integer,
                "rules_file_exists": boolean,
                "tagging_rate": number,
                "untagged_count": integer,
            },
            required=[
                "rules_file_exists",
                "tagging_rate",
                "untagged_count",
                "filters_applied",
                "detailed_requested",
            ],
        ),
        "tagging": object_schema(
            {
                "tagged_count": integer,
                "tagging_rate": number,
                "suggestable_tagged_count": integer,
                "suggestable_tagging_rate": number,
                "suggestable_transaction_count": integer,
                "suggestable_untagged_count": integer,
                "transfer_excluded_count": integer,
                "transfer_excluded_untagged_count": integer,
                "transfer_candidate_count": integer,
                "unconfirmed_transfer_candidate_count": integer,
                "transfer_exclusions": object_schema(
                    {
                        "candidate_count": integer,
                        "confirmed_count": integer,
                        "definition": string,
                        "excluded_count": integer,
                        "excluded_untagged_count": integer,
                        "unconfirmed_candidate_count": integer,
                    },
                    required=[
                        "excluded_count",
                        "confirmed_count",
                        "candidate_count",
                        "unconfirmed_candidate_count",
                        "excluded_untagged_count",
                        "definition",
                    ],
                ),
                "untagged_count": integer,
                "untagged_merchants": array_of(
                    object_schema(
                        {"count": integer, "merchant": string},
                        required=["merchant", "count"],
                    )
                ),
                "untagged_merchants_total": integer,
            },
            required=[
                "tagged_count",
                "untagged_count",
                "tagging_rate",
                "suggestable_transaction_count",
                "suggestable_tagged_count",
                "suggestable_untagged_count",
                "suggestable_tagging_rate",
                "transfer_candidate_count",
                "transfer_excluded_count",
                "transfer_excluded_untagged_count",
                "unconfirmed_transfer_candidate_count",
                "transfer_exclusions",
                "untagged_merchants",
                "untagged_merchants_total",
            ],
        ),
        "transactions": object_schema(
            {
                "count": integer,
                "date_range": object_schema(
                    {"end": string_or_null, "start": string_or_null},
                    required=["start", "end"],
                ),
                "partition_count": integer,
            },
            required=["count", "date_range", "partition_count"],
        ),
    },
    [
        "data_directory",
        "transactions",
        "last_import",
        "terminology",
        "tagging",
        "rules_file",
        "health",
        "actionable",
        "signals",
        "next_steps",
    ],
)
add_terminology(
    status_schema,
    {
        "tagging.untagged_count": "untagged",
        "tagging.suggestable_untagged_count": "suggestable_untagged",
        "tagging.transfer_excluded_untagged_count": (
            "untagged rows excluded from suggestable_untagged because they are confirmed "
            "transfer pairs"
        ),
        "terminology.reference": "schema documentation link for tagging/review terms",
        "health.reasons.low_untagged_remainder": (
            "non-alarming health cue when suggestable_untagged is small and coverage is >= 99%"
        ),
    },
)

action_schema = object_schema(
    {
        "command": string,
        "domain": string,
        "priority": {"enum": ["high", "medium", "low"], "type": "string"},
        "reason": string,
    },
    required=["domain", "priority", "reason", "command"],
)

checkup_schema = command_schema(
    "checkup.schema.json",
    "checkup --json output",
    {
        "actionable": boolean,
        "data_dir": string,
        "domains": object_schema(
            {
                "budget": object_any,
                "networth": object_any,
                "obligations": object_any,
                "pipeline": object_any,
                "review": object_any,
            },
            required=["pipeline", "review", "budget", "networth", "obligations"],
        ),
        "next_actions": array_of(action_schema),
        "summary": object_schema(
            {
                "domains_needing_attention": array_of(string),
                "headline": string,
                "next_action_count": integer,
                "priority": string_or_null,
                "recommended_command": string_or_null,
                "status": {"enum": ["ok", "needs_attention"], "type": "string"},
                "warning_count": integer,
            },
            required=[
                "status",
                "priority",
                "headline",
                "recommended_command",
                "domains_needing_attention",
                "warning_count",
                "next_action_count",
            ],
        ),
        "warnings": array_of(string),
    },
    ["summary", "actionable", "warnings", "next_actions", "domains"],
)
checkup_schema["description"] = (
    "checkup --json output. The raw and redacted privacy profiles include data_dir; "
    "compact omits that path while preserving workflow-driving summary fields."
)
checkup_schema["allOf"] = [
    {
        "if": privacy_profile_condition("raw", "redacted"),
        "then": {"required": ["data_dir"]},
    },
    {
        "if": privacy_profile_condition("compact"),
        "then": {"not": {"required": ["data_dir"]}},
    },
]

context_schema = command_schema(
    "context.schema.json",
    "context --json output",
    {
        "active_goals": array_of(any_value),
        "financial_metadata": object_any,
        "journals": array_of(
            object_schema(
                {
                    "created": string_or_null,
                    "data_range": string_or_null,
                    "filename": string,
                    "path": string,
                    "snapshot": object_any,
                    "summary_200": string,
                    "topic": string,
                },
                required=[
                    "path",
                    "filename",
                    "topic",
                    "created",
                    "data_range",
                    "snapshot",
                    "summary_200",
                ],
            )
        ),
        "rule_notes": array_of(
            object_schema(
                {
                    "category": string,
                    "notes": string,
                    "rule_name": string,
                    "tags": array_of(string),
                },
                required=["rule_name", "notes", "tags"],
            )
        ),
        "status_snapshot": object_any,
        "top_patterns": array_of(
            object_schema(
                {
                    "delta_krw": integer,
                    "direction": string,
                    "label": string,
                },
                required=["label", "delta_krw", "direction"],
            )
        ),
    },
    [
        "journals",
        "status_snapshot",
        "active_goals",
        "financial_metadata",
        "rule_notes",
        "top_patterns",
    ],
)

doctor_schema = command_schema(
    "doctor.schema.json",
    "doctor --json output",
    {
        "checks": array_of(
            object_schema(
                {
                    "detail": string_or_null,
                    "message": string,
                    "name": string,
                    "status": {"enum": ["pass", "warn", "fail"], "type": "string"},
                    "suggestion": string_or_null,
                },
                required=["name", "status", "message", "detail", "suggestion"],
            )
        ),
        "install_hint": string_or_null,
        "missing_extras": array_of(string),
        "summary": object_schema(
            {
                "errors": integer,
                "passed": integer,
                "total": integer,
                "warnings": integer,
            },
            required=["total", "passed", "warnings", "errors"],
        ),
    },
    ["checks", "summary", "missing_extras", "install_hint"],
)

history_schema = command_schema(
    "history.schema.json",
    "history --json output",
    {
        "count": integer,
        "records": array_of(
            object_schema(
                {
                    "archived": {"type": ["boolean", "string", "null"]},
                    "archived_path": string_or_null,
                    "file_id": string,
                    "imported_at": string,
                    "imported_from": string_or_null,
                    "original_filename": string_or_null,
                    "source_rows": integer_or_null,
                },
                required=["file_id", "imported_at"],
            )
        ),
    },
    ["records", "count"],
)

query_schema = command_schema(
    "query.schema.json",
    "query --json output",
    {
        "pagination": {"$ref": "_pagination.schema.json"},
        "row_count": integer,
        "rows": array_of(object_any),
    },
    ["rows", "row_count", "pagination"],
)

transaction_row_schema = object_schema(
    {
        "account": string_or_null,
        "amount": number,
        "category_final": string_or_null,
        "category_rule": string_or_null,
        "confidence": number_or_null,
        "counterparty": string_or_null,
        "currency": string_or_null,
        "date": string,
        "datetime": string_or_null,
        "file_id": string_or_null,
        "is_transfer": {"type": ["boolean", "integer", "null"]},
        "major_raw": string_or_null,
        "merchant_raw": string_or_null,
        "minor_raw": string_or_null,
        "memo_raw": string_or_null,
        "needs_review": {"type": ["boolean", "integer", "null"]},
        "row_hash": string,
        "source_row": integer_or_null,
        "tags_ai": array_of(string),
        "tags_final": array_of(string),
        "tags_manual": array_of(string),
        "tags_rule": array_of(string),
        "time": string_or_null,
        "transfer_group_id": string_or_null,
        "type_norm": string_or_null,
        "type_raw": string_or_null,
    },
    required=["row_hash", "date", "amount"],
)

show_schema = command_schema(
    "show.schema.json",
    "show --json output",
    {
        "pagination": {"$ref": "_pagination.schema.json"},
        "row_count": integer,
        "rows": array_of(transaction_row_schema),
        "total_matches": integer,
    },
    ["rows", "row_count", "total_matches", "pagination"],
)

journal_list_schema = command_schema(
    "journal_list.schema.json",
    "journal list --json output",
    {
        "count": integer,
        "entries": array_of(
            object_schema(
                {
                    "created": string_or_null,
                    "filename": string,
                    "path": string,
                    "size_bytes": integer,
                    "topic": string,
                },
                required=["path", "filename", "topic", "created", "size_bytes"],
            )
        ),
    },
    ["entries", "count"],
)

rule_schema = object_schema(
    {
        "category": string_or_null,
        "fields": array_of(string),
        "match": string,
        "name": string,
        "priority": integer,
        "tags": array_of(string),
    },
    required=["name", "match", "fields", "tags", "category", "priority"],
)

rules_list_schema = command_schema(
    "rules_list.schema.json",
    "rules list --json output",
    {
        "rule_count": integer,
        "rules": array_of(rule_schema),
    },
    ["rule_count", "rules"],
)

audit_log_schema = command_schema(
    "audit_log.schema.json",
    "audit log --json output",
    {
        "count": integer,
        "events": array_of(object_any),
        "skipped_entries": integer,
    },
    ["events", "count", "skipped_entries"],
)

problem_schema = object_schema(
    {
        "column": integer_or_null,
        "formatted": string,
        "line": integer_or_null,
        "message": string,
        "path": string,
        "severity": string,
        "type": string,
    },
    required=["severity", "type", "path", "message", "line", "column", "formatted"],
)

networth_validate_schema = command_schema(
    "networth_validate.schema.json",
    "networth validate --json output",
    {
        "errors": integer,
        "exists": boolean,
        "liabilities": integer,
        "manual_assets": integer,
        "path": string,
        "problems": array_of(problem_schema),
        "status": {"enum": ["valid", "issues"], "type": "string"},
        "valid": boolean,
        "version": integer_or_null,
        "warnings": integer,
    },
    [
        "path",
        "exists",
        "valid",
        "status",
        "version",
        "manual_assets",
        "liabilities",
        "errors",
        "warnings",
        "problems",
    ],
)

template_run_schema = command_schema(
    "template_run.schema.json",
    "template run --json output",
    {
        "pagination": {"$ref": "_pagination.schema.json"},
        "row_count": integer,
        "rows": array_of(object_any),
        "template_name": string,
    },
    ["template_name", "row_count", "rows", "pagination"],
)

template_list_schema = command_schema(
    "template_list.schema.json",
    "template list --json output",
    {
        "templates": array_of(
            object_schema(
                {"description": string, "name": string, "params": object_any},
                required=["name", "description", "params"],
            )
        )
    },
    ["templates"],
)

template_show_schema = command_schema(
    "template_show.schema.json",
    "template show --json output",
    {
        "description": string,
        "name": string,
        "parameters": object_any,
        "sql": string,
    },
    ["name", "description", "parameters", "sql"],
)

audit_stats_schema = command_schema(
    "audit_stats.schema.json",
    "audit stats --json output",
    {
        "executions": object_schema(
            {"failed": integer, "successful": integer, "total": integer},
            required=["total", "successful", "failed"],
        ),
        "skipped_entries": integer,
        "success_rate": number_or_null,
        "suggestions": object_schema(
            {"confirmed": integer, "declined": integer, "total": integer},
            required=["total", "confirmed", "declined"],
        ),
        "template_summary": object_any,
        "top_commands": array_of(
            object_schema({"command": string, "count": integer}, required=["command", "count"])
        ),
    },
    ["suggestions", "executions", "success_rate", "top_commands", "skipped_entries"],
)

audit_clear_schema = command_schema(
    "audit_clear.schema.json",
    "audit clear --json output",
    {"action": string, "entries_kept": integer, "skipped_entries": integer},
    ["entries_kept", "action", "skipped_entries"],
)

assets_status_schema = command_schema(
    "assets_status.schema.json",
    "assets status --json output",
    {
        "account_count": integer,
        "accounts": array_of(object_any),
        "available_months": array_of(string),
        "has_data": boolean,
        "latest_month": string_or_null,
        "position_count": integer,
        "snapshot_date": string_or_null,
        "total_value": number,
    },
    ["has_data"],
)

assets_show_schema = command_schema(
    "assets_show.schema.json",
    "assets show --json output",
    {
        "error": string,
        "has_data": boolean,
        "holdings": array_of(object_any),
        "month": string,
        "snapshot_date": string_or_null,
        "total_count": integer,
    },
    ["has_data"],
)

budget_row_schema = object_schema(
    {
        "actual": integer,
        "name": string,
        "progress_pct": number_or_null,
        "remaining": integer,
        "status": {"enum": ["under", "on-track", "over"], "type": "string"},
        "target": integer,
    },
    required=["name", "target", "actual", "remaining", "progress_pct", "status"],
)

budget_review_schema = object_schema(
    {
        "actual": integer_or_null,
        "at_risk_categories": array_of(string),
        "month": string,
        "over_budget_categories": array_of(string),
        "remaining": integer_or_null,
        "target": integer_or_null,
        "unbudgeted_categories": array_of(string),
    },
    required=[
        "month",
        "target",
        "actual",
        "remaining",
        "at_risk_categories",
        "over_budget_categories",
        "unbudgeted_categories",
    ],
)

budget_status_schema = command_schema(
    "budget_status.schema.json",
    "budget status --json output",
    {
        "actionable": boolean,
        "categories": array_of(budget_row_schema),
        "goals_file": object_schema(
            {"exists": boolean, "notes": string_or_null, "path": string, "updated": string_or_null},
            required=["path", "exists"],
        ),
        "health": object_schema(
            {
                "reasons": array_of(string),
                "status": {"enum": ["ok", "warning", "critical"], "type": "string"},
            },
            required=["status", "reasons"],
        ),
        "month": string,
        "next_steps": array_of(next_step_schema),
        "review": budget_review_schema,
        "signals": object_any,
        "summary": {"anyOf": [budget_row_schema, {"type": "null"}]},
    },
    [
        "month",
        "goals_file",
        "summary",
        "categories",
        "health",
        "actionable",
        "signals",
        "review",
        "next_steps",
    ],
)

budget_edit_schema = command_schema(
    "budget_edit.schema.json",
    "budget edit --json output",
    {
        "changes": array_of(
            object_schema(
                {"new": any_value, "old": any_value, "path": string},
                required=["path", "old", "new"],
            )
        ),
        "monthly_budget": object_schema(
            {
                "categories": object_schema(additional=True),
                "notes": string_or_null,
                "total": integer,
                "updated": string_or_null,
            },
            required=["total", "categories", "updated", "notes"],
        ),
        "path": string,
    },
    ["path", "changes", "monthly_budget"],
)

budget_validate_schema = command_schema(
    "budget_validate.schema.json",
    "budget validate --json output",
    {
        "path": string,
        "problems": array_of(object_any),
        "status": {"enum": ["valid", "invalid"], "type": "string"},
    },
    ["status", "path", "problems"],
)

networth_health_schema = object_schema(
    {
        "reasons": array_of(string),
        "status": {"enum": ["ok", "warning", "critical"], "type": "string"},
    },
    required=["status", "reasons"],
)

networth_schema = command_schema(
    "networth.schema.json",
    "networth --json output",
    {
        "actionable": boolean,
        "as_of": string_or_null,
        "health": networth_health_schema,
        "net_worth": number,
        "next_steps": array_of(next_step_schema),
        "signals": object_any,
        "total_assets": number,
        "total_liabilities": number,
    },
    [
        "as_of",
        "total_assets",
        "total_liabilities",
        "net_worth",
        "health",
        "actionable",
        "signals",
        "next_steps",
    ],
)

networth_breakdown_schema = command_schema(
    "networth_breakdown.schema.json",
    "networth breakdown --json output",
    {"as_of": string_or_null, "breakdown": array_of(object_any)},
    ["as_of", "breakdown"],
)

networth_history_schema = command_schema(
    "networth_history.schema.json",
    "networth history --json output",
    {
        "history": array_of(
            object_schema({"as_of": string, "net_worth": number}, required=["as_of", "net_worth"])
        )
    },
    ["history"],
)

forecast_projection_schema = object_schema(
    {
        "date": string,
        "events_fired": array_of(object_any),
        "net_worth": number,
        "total_assets": number,
        "total_liabilities": number,
    },
    required=["date", "total_assets", "total_liabilities", "net_worth", "events_fired"],
)

networth_forecast_schema = command_schema(
    "networth_forecast.schema.json",
    "networth forecast --json output",
    {
        "projections": array_of(forecast_projection_schema),
        "scenario": string,
        "scenarios": object_schema(additional=True),
        "summary": object_any,
    },
    [],
)

automation_merchant_pressure_schema = object_schema(
    {
        "avg_amount": number,
        "merchant": string,
        "sample_memos": array_of(string),
        "total_amount": number,
        "transaction_count": integer,
    },
    required=["merchant", "transaction_count", "total_amount", "avg_amount", "sample_memos"],
)

automation_tagging_pressure_schema = object_schema(
    {
        "coverage_pct": number,
        "merchant_pressure": array_of(automation_merchant_pressure_schema),
        "merchant_pressure_count": integer,
        "status": string,
        "suggestable_coverage_pct": number,
        "suggestable_untagged_transactions": integer,
        "threshold": integer,
        "threshold_basis": string,
        "threshold_exceeded": boolean,
        "total_transactions": integer,
        "transfer_excluded_untagged_transactions": integer,
        "untagged_transactions": integer,
    },
    required=[
        "status",
        "total_transactions",
        "untagged_transactions",
        "coverage_pct",
        "suggestable_untagged_transactions",
        "suggestable_coverage_pct",
        "transfer_excluded_untagged_transactions",
        "threshold",
        "threshold_basis",
        "threshold_exceeded",
    ],
)

automation_run_schema = command_schema(
    "automation_run.schema.json",
    "automation run --json output",
    {
        "actionable": boolean,
        "data_dir": string,
        "enabled": boolean,
        "large_transactions": object_any,
        "next_steps": array_of(next_step_schema),
        "pending_imports": object_any,
        "tagging_pressure": automation_tagging_pressure_schema,
        "thresholds": object_schema(
            {"large_transaction": number, "untagged_count": integer},
            required=["untagged_count", "large_transaction"],
        ),
        "warnings": array_of(string),
    },
    [
        "enabled",
        "actionable",
        "thresholds",
        "pending_imports",
        "tagging_pressure",
        "large_transactions",
        "next_steps",
        "warnings",
    ],
)
automation_run_schema["description"] = (
    "automation run --json output. The raw and redacted privacy profiles include "
    "data_dir and merchant_pressure samples; compact replaces those samples with counts."
)
automation_run_schema["allOf"] = [
    {
        "if": privacy_profile_condition("raw", "redacted"),
        "then": {
            "properties": {
                "tagging_pressure": {
                    "required": ["merchant_pressure"],
                    "type": "object",
                },
            },
            "required": ["data_dir"],
        },
    },
    {
        "if": privacy_profile_condition("compact"),
        "then": {
            "not": {"required": ["data_dir"]},
            "properties": {
                "tagging_pressure": {
                    "not": {"required": ["merchant_pressure"]},
                    "required": ["merchant_pressure_count"],
                    "type": "object",
                },
            },
        },
    },
]
add_terminology(
    automation_run_schema,
    {
        "tagging_pressure.untagged_transactions": "untagged",
        "tagging_pressure.suggestable_untagged_transactions": "suggestable_untagged",
        "tagging_pressure.threshold_basis": (
            "automation.thresholds.untagged_count is evaluated against "
            "suggestable_untagged_transactions"
        ),
        "tagging_pressure.transfer_excluded_untagged_transactions": (
            "untagged rows excluded from rule suggestions because they are confirmed transfer pairs"
        ),
    },
)

rule_detail_schema = object_schema(
    {
        "category": string_or_null,
        "confidence": number,
        "created_at": string_or_null,
        "created_by": string_or_null,
        "enabled": boolean,
        "fields": array_of(string),
        "match": string,
        "name": string,
        "notes": string_or_null,
        "priority": integer,
        "tags": array_of(string),
    },
    required=[
        "name",
        "match",
        "fields",
        "tags",
        "priority",
        "enabled",
        "category",
        "created_by",
        "created_at",
        "confidence",
        "notes",
    ],
)

validation_problem_schema = object_schema(
    {
        "message": string,
        "rules": array_of(string),
        "severity": string,
        "suggestion": string_or_null,
        "type": string,
    },
    required=["severity", "type", "message", "rules", "suggestion"],
)

rules_validation_summary_schema = object_schema(
    {
        "errors": integer,
        "passed": integer,
        "problems": array_of(validation_problem_schema),
        "status": {"enum": ["valid", "issues"], "type": "string"},
        "total_rules": integer,
        "warnings": integer,
    },
    required=["status", "total_rules", "errors", "warnings", "passed", "problems"],
)

rules_validate_schema = command_schema(
    "rules_validate.schema.json",
    "rules validate --json output",
    dict(rules_validation_summary_schema["properties"]),
    ["status", "total_rules", "errors", "warnings", "passed", "problems"],
)

rules_add_schema = command_schema(
    "rules_add.schema.json",
    "rules add --json output",
    {
        "action": {"enum": ["added", "updated"], "type": "string"},
        "coverage_after": number,
        "dry_run": boolean,
        "dry_run_action": {"enum": ["added", "updated"], "type": "string"},
        "impact": object_any,
        "preview_action": {"enum": ["would_add", "would_update"], "type": "string"},
        "rule": rule_detail_schema,
        "rules_file_modified": boolean,
        "validation": rules_validation_summary_schema,
    },
    ["action", "rule", "validation"],
)

rules_remove_schema = command_schema(
    "rules_remove.schema.json",
    "rules remove --json output",
    {"action": {"enum": ["removed"], "type": "string"}, "rule_name": string},
    ["action", "rule_name"],
)

rules_test_schema = command_schema(
    "rules_test.schema.json",
    "rules test --json output",
    {
        "cross_tags_top": array_of(
            object_schema({"count": integer, "tag": string}, required=["tag", "count"])
        ),
        "match_count": integer,
        "monthly_distribution": object_schema(additional=True),
        "rule_name": string,
        "sample": array_of(object_any),
        "scope": object_schema(
            {"month": string_or_null, "total_rows_scanned": integer},
            required=["month", "total_rows_scanned"],
        ),
    },
    ["rule_name", "scope", "match_count", "sample", "monthly_distribution", "cross_tags_top"],
)

rules_suggest_schema = command_schema(
    "rules_suggest.schema.json",
    "rules suggest --json output",
    {
        "applied": integer,
        "coverage_after_pct": number,
        "coverage_before_pct": number,
        "dry_run": boolean,
        "message": string,
        "rules_file": string,
        "rules_file_modified": boolean,
        "skipped": integer,
        "suggestable_coverage_before_pct": number,
        "suggestable_total_count": integer,
        "suggestable_untagged_count": integer,
        "suggestions": array_of(object_any),
        "total_count": integer,
        "transfer_exclusions": object_schema(
            {
                "definition": string,
                "excluded_count": integer,
                "excluded_untagged_count": integer,
            },
            required=["excluded_count", "excluded_untagged_count", "definition"],
        ),
        "untagged_count": integer,
        "would_apply": array_of(object_any),
    },
    [],
)
add_terminology(
    rules_suggest_schema,
    {
        "untagged_count": "untagged",
        "suggestable_untagged_count": "suggestable_untagged",
        "transfer_exclusions.excluded_untagged_count": (
            "untagged rows excluded from rule suggestions because they are confirmed transfer pairs"
        ),
    },
)

rules_export_schema = command_schema(
    "rules_export.schema.json",
    "rules export --json output",
    {"rule_count": integer, "rules": array_of(rule_schema)},
    ["rule_count", "rules"],
)

gap_item_schema = object_schema(
    {
        "banksalad_category": string_or_null,
        "current_tags": array_of(string),
        "expected_category": string_or_null,
        "gap_type": string,
        "mismatch_type": string_or_null,
        "mismatch_severity": string,
        "actionable": boolean,
        "merchant": string,
        "suggested_action": string,
        "total_amount": number,
        "transaction_count": integer,
    },
    required=[
        "merchant",
        "transaction_count",
        "total_amount",
        "banksalad_category",
        "current_tags",
        "gap_type",
        "suggested_action",
    ],
)

rules_gaps_schema = command_schema(
    "rules_gaps.schema.json",
    "rules gaps --json output",
    {
        "critical_gaps": array_of(gap_item_schema),
        "mismatches": array_of(gap_item_schema),
        "simulations": array_of(object_any),
        "summary": object_schema(
            {
                "actionable_mismatch_count": integer,
                "actionable_only": boolean,
                "category_mismatch_count": integer,
                "complete_count": integer,
                "conflict_count": integer,
                "critical_count": integer,
                "filtered_mismatch_count": integer,
                "filtered_out_mismatch_count": integer,
                "mismatch_count": integer,
                "multi_tag_noise_count": integer,
                "total_mismatch_count": integer,
            },
            required=["critical_count", "mismatch_count", "complete_count"],
        ),
    },
    ["summary", "critical_gaps", "mismatches", "simulations"],
)

pipeline_step_schema = object_schema(additional=True)
full_pipeline_properties = {
    "command": string,
    "steps": object_schema(
        {
            "export": pipeline_step_schema,
            "ingest": pipeline_step_schema,
            "tag": pipeline_step_schema,
            "transfer": pipeline_step_schema,
        },
        required=["ingest", "tag", "transfer", "export"],
    ),
}

refresh_schema = command_schema(
    "refresh.schema.json",
    "refresh --json output",
    full_pipeline_properties,
    ["command", "steps"],
)

all_schema = command_schema(
    "all.schema.json",
    "all --json output",
    full_pipeline_properties,
    ["command", "steps"],
)

tag_schema = command_schema(
    "tag.schema.json",
    "tag --json output",
    {
        "coverage_pct": number,
        "dry_run": boolean,
        "operation": string,
        "partition": object_any,
        "row_hash": string,
        "status": string,
        "tagged": integer,
        "total": integer,
        "transaction": object_any,
        "untagged": integer,
        "updated": boolean,
    },
    ["status"],
)

transfer_schema = command_schema(
    "transfer.schema.json",
    "transfer --json output",
    {
        "candidate_rows": integer,
        "confirmed_transfer_rows": integer,
        "pairs_found": integer,
        "pairs_linked": integer,
        "status": string,
        "unconfirmed_candidate_rows": integer,
    },
    [
        "status",
        "candidate_rows",
        "pairs_found",
        "pairs_linked",
        "confirmed_transfer_rows",
        "unconfirmed_candidate_rows",
    ],
)

import_schema = command_schema(
    "import.schema.json",
    "import --json output",
    {
        "dry_run": boolean,
        "errors": integer,
        "files_processed": integer,
        "files_skipped": integer,
        "pipeline_result": object_any,
        "steps": object_any,
        "transactions_inserted": integer,
    },
    ["files_processed", "files_skipped", "errors"],
)

ingest_schema = command_schema(
    "ingest.schema.json",
    "ingest --json output",
    {
        "archive_requested": boolean,
        "command": string,
        "dry_run": boolean,
        "from_archive": string,
        "preview": object_any,
        "source": string,
        "summary": object_any,
    },
    ["command", "dry_run", "source"],
)

export_output_file_schema = object_schema(
    {
        "available": boolean,
        "estimated_size_bytes": integer_or_null,
        "kind": string,
        "path": string,
        "reason": string_or_null,
        "row_count": integer_or_null,
    }
)

export_schema = command_schema(
    "export.schema.json",
    "export --json output",
    {
        "assumptions": object_any,
        "breakdown": object_any,
        "command": string,
        "domain": string,
        "dry_run": boolean,
        "format": string,
        "generated_at": string,
        "output_files": array_of(export_output_file_schema),
        "period": string_or_null,
        "review_items": array_of(object_any),
        "skipped_outputs": array_of(export_output_file_schema),
        "summary": object_any,
        "transaction_count": integer,
        "year": integer,
    },
    [],
)

review_schema = command_schema(
    "review.schema.json",
    "review --json output",
    {
        "actionable": boolean,
        "filters": object_any,
        "health": object_any,
        "month": string_or_null,
        "next_steps": array_of(next_step_schema),
        "rule_notes": array_of(
            object_schema(
                {
                    "category": string,
                    "notes": string,
                    "rule_name": string,
                    "tags": array_of(string),
                }
            )
        ),
        "pagination": {"$ref": "_pagination.schema.json"},
        "signals": object_any,
        "total_count": integer,
        "transactions": array_of(
            object_schema(
                {
                    "amount": money_or_null,
                    "category_final": string_or_null,
                    "confidence": number_or_null,
                    "date": string_or_null,
                    "merchant_raw": string_or_null,
                    "needs_review": {"type": ["boolean", "integer", "null"]},
                    "reasons": array_of(string),
                    "row_hash": string_or_null,
                    "rule_matched": boolean,
                    "severity": {"enum": ["high", "medium", "low"], "type": "string"},
                    "tags_final": array_of(string),
                },
                required=["row_hash", "needs_review", "rule_matched", "reasons", "severity"],
            )
        ),
    },
    [
        "transactions",
        "total_count",
        "filters",
        "month",
        "health",
        "actionable",
        "signals",
        "rule_notes",
        "next_steps",
        "pagination",
    ],
)
review_schema["description"] = (
    "review --json output. The raw and redacted privacy profiles keep full rule note "
    "shape; compact rule notes omit merchant-derived rule names and free-text notes."
)
review_schema["allOf"] = [
    {
        "if": privacy_profile_condition("raw", "redacted"),
        "then": {
            "properties": {
                "rule_notes": {
                    "items": {"required": ["rule_name", "notes", "tags"]},
                    "type": "array",
                },
            },
        },
    },
    {
        "if": privacy_profile_condition("compact"),
        "then": {
            "properties": {
                "rule_notes": {
                    "items": {
                        "not": {
                            "anyOf": [
                                {"required": ["rule_name"]},
                                {"required": ["notes"]},
                            ],
                        },
                    },
                    "type": "array",
                },
            },
        },
    },
]
add_terminology(
    review_schema,
    {
        "transactions[].rule_matched": "rule_matched",
        "transactions[].needs_review": "needs_review",
        "signals.untagged_count": "untagged",
        "signals.unclassified_count": "uncategorized",
        "signals.uncategorized_count": "uncategorized",
        "signals.needs_review_count": "needs_review",
        "signals.needs_review_flag_count": "needs_review",
        "signals.rule_matched_count": "rule_matched",
        "transactions[].reasons": "review reason labels",
        "transactions[].severity": "highest severity derived from review reasons",
    },
)

explain_schema = command_schema(
    "explain.schema.json",
    "explain --json output",
    {
        "candidates": array_of(object_any),
        "classification": {"type": ["object", "null"]},
        "date_filter": string_or_null,
        "match_count": integer,
        "matches": array_of(object_any),
        "query": string,
        "rule_trace": array_of(object_any),
        "selected_index": integer,
        "transaction": {"type": ["object", "null"]},
    },
    ["query", "date_filter"],
)

index_collection_schema = object_schema(
    {
        "count": integer_or_null,
        "count_label": string,
        "exists": boolean,
        "latest_modified": string_or_null,
        "name": string,
        "notes": array_of(string),
        "path": string_or_null,
        "path_included": boolean,
        "privacy_level": string,
        "recommended_commands": array_of(string),
        "status": string,
        "type": string,
    },
    required=[
        "name",
        "type",
        "status",
        "exists",
        "count",
        "count_label",
        "latest_modified",
        "privacy_level",
        "path",
        "path_included",
        "recommended_commands",
        "notes",
    ],
)

index_schema = command_schema(
    "index.schema.json",
    "index --json output",
    {
        "collections": array_of(index_collection_schema),
        "recommended_next": array_of(string),
        "schema_ref": string,
        "workspace": object_schema(
            {
                "data_dir_source": string,
                "path": string_or_null,
                "path_included": boolean,
                "status": string,
            },
            required=["status", "data_dir_source", "path", "path_included"],
        ),
    },
    ["workspace", "collections", "recommended_next", "schema_ref"],
)
index_schema["description"] = (
    "index --json output. The raw privacy profile preserves the full catalog shape and "
    "only includes paths when --include-paths is requested. Redacted and compact profiles "
    "suppress resolved workspace and collection paths; compact also drops operational "
    "command and note detail."
)
index_schema["allOf"] = [
    {
        "if": privacy_profile_condition("redacted", "compact"),
        "then": {
            "properties": {
                "collections": {
                    "items": {
                        "properties": {
                            "path": {"type": "null"},
                            "path_included": {"const": False},
                        },
                        "type": "object",
                    },
                    "type": "array",
                },
                "workspace": {
                    "properties": {
                        "path": {"type": "null"},
                        "path_included": {"const": False},
                    },
                    "type": "object",
                },
            },
        },
    },
    {
        "if": privacy_profile_condition("compact"),
        "then": {
            "properties": {
                "collections": {
                    "items": {
                        "properties": {
                            "latest_modified": {"type": "null"},
                            "notes": {"maxItems": 0, "type": "array"},
                            "recommended_commands": {"maxItems": 0, "type": "array"},
                        },
                        "type": "object",
                    },
                    "type": "array",
                },
                "recommended_next": {"maxItems": 0, "type": "array"},
            },
        },
    },
]

manifest_schema = command_schema(
    "manifest.schema.json",
    "manifest --json output",
    {
        "commands": array_of(
            object_schema(
                {
                    "arguments": array_of(
                        object_schema(
                            {
                                "default": any_value,
                                "help": string_or_null,
                                "name": string,
                                "required": boolean,
                                "type": string,
                            },
                            required=["name", "type", "required"],
                        )
                    ),
                    "help": string_or_null,
                    "help_oneline": string_or_null,
                    "error_schema_ref": string,
                    "examples": array_of(string),
                    "name": string,
                    "options": array_of(
                        object_schema(
                            {
                                "default": any_value,
                                "envvar": string_or_null,
                                "help": string_or_null,
                                "is_flag": boolean,
                                "name": string,
                                "short": string_or_null,
                                "type": string,
                            },
                            required=["name", "type", "is_flag"],
                        )
                    ),
                    "output_schema_ref": string_or_null,
                    "path": string,
                    "rich_help_panel": string_or_null,
                    "mutates_data": boolean,
                    "privacy_profile": string,
                    "requires_confirmation": boolean,
                    "safe_readonly": boolean,
                },
                required=["path", "output_schema_ref"],
            )
        ),
        "error_codes": array_of(error_code_string),
        "error_schema_ref": string,
        "examples": array_of(
            object_schema(
                {
                    "command": string,
                    "description": string,
                },
                required=["description", "command"],
            )
        ),
        "exit_codes": object_schema(
            {name: {"const": value, "type": "integer"} for name, value in exit_code_items()},
            required=[name for name, _value in exit_code_items()],
            additional=False,
        ),
        "finjuice_version": string,
        "global_options": array_of(
            object_schema(
                {
                    "default": any_value,
                    "envvar": string_or_null,
                    "help": string_or_null,
                    "is_flag": boolean,
                    "name": string,
                    "short": string_or_null,
                    "type": string,
                },
                required=["name", "type", "is_flag"],
            )
        ),
        "manifest_schema_version": string,
        "panels": array_of(string),
        "privacy_profiles": {
            "additionalProperties": object_schema(
                {
                    "description": string,
                    "external_disclosure": string,
                },
                required=["description", "external_disclosure"],
            ),
            "type": "object",
        },
        "root_env": array_of(
            object_schema(
                {
                    "help": string_or_null,
                    "name": string,
                    "option": string,
                },
                required=["name", "option"],
            )
        ),
    },
    ["manifest_schema_version", "finjuice_version", "commands"],
)

SCHEMAS: dict[str, JsonSchema] = {
    "_error.schema.json": error_schema,
    "_meta.schema.json": meta_schema,
    "_pagination.schema.json": pagination_schema,
    "all.schema.json": all_schema,
    "assets_show.schema.json": assets_show_schema,
    "assets_status.schema.json": assets_status_schema,
    "audit_clear.schema.json": audit_clear_schema,
    "audit_log.schema.json": audit_log_schema,
    "audit_stats.schema.json": audit_stats_schema,
    "automation_run.schema.json": automation_run_schema,
    "budget_edit.schema.json": budget_edit_schema,
    "budget_status.schema.json": budget_status_schema,
    "budget_validate.schema.json": budget_validate_schema,
    "checkup.schema.json": checkup_schema,
    "context.schema.json": context_schema,
    "doctor.schema.json": doctor_schema,
    "explain.schema.json": explain_schema,
    "export.schema.json": export_schema,
    "history.schema.json": history_schema,
    "import.schema.json": import_schema,
    "ingest.schema.json": ingest_schema,
    "index.schema.json": index_schema,
    "journal_list.schema.json": journal_list_schema,
    "manifest.schema.json": manifest_schema,
    "networth.schema.json": networth_schema,
    "networth_breakdown.schema.json": networth_breakdown_schema,
    "networth_forecast.schema.json": networth_forecast_schema,
    "networth_history.schema.json": networth_history_schema,
    "networth_validate.schema.json": networth_validate_schema,
    "query.schema.json": query_schema,
    "refresh.schema.json": refresh_schema,
    "review.schema.json": review_schema,
    "rules_add.schema.json": rules_add_schema,
    "rules_export.schema.json": rules_export_schema,
    "rules_gaps.schema.json": rules_gaps_schema,
    "rules_list.schema.json": rules_list_schema,
    "rules_remove.schema.json": rules_remove_schema,
    "rules_suggest.schema.json": rules_suggest_schema,
    "rules_test.schema.json": rules_test_schema,
    "rules_validate.schema.json": rules_validate_schema,
    "show.schema.json": show_schema,
    "status.schema.json": status_schema,
    "tag.schema.json": tag_schema,
    "template_list.schema.json": template_list_schema,
    "template_run.schema.json": template_run_schema,
    "template_show.schema.json": template_show_schema,
    "transfer.schema.json": transfer_schema,
}


def write_schema(path: Path, schema: JsonSchema) -> None:
    """Write one schema in canonical JSON form."""
    path.write_text(
        json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    """Generate all schema artifacts."""
    SCHEMAS_DIR.mkdir(parents=True, exist_ok=True)
    for filename, schema in sorted(SCHEMAS.items()):
        write_schema(SCHEMAS_DIR / filename, schema)


if __name__ == "__main__":
    main()
