"""JSON Schema construction helpers for command output artifacts.

Owns draft constants, object/array builders, privacy-profile conditions, and
Python type projections. Command schema catalogs and the generator entry stay
in :mod:`tools.generate_schemas`, which re-exports these names so existing
callers can keep importing from that module.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from types import NoneType
from typing import Any, get_args, get_origin, is_typeddict

JsonSchema = dict[str, Any]

SCHEMA_DRAFT = "https://json-schema.org/draft/2020-12/schema"


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
