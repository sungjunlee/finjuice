"""Structure checks for the split generate_schemas helper implementation."""

from pathlib import Path

from tools import generate_schemas, generate_schemas_helpers

TOOLS_DIR = Path("tools")

SCHEMA_CONSTRUCTION_HELPERS = (
    "nullable",
    "array_of",
    "object_schema",
    "command_schema",
    "privacy_profile_condition",
    "schema_from_pydantic_model",
    "schema_from_python_annotation",
    "schema_from_dataclass_type",
    "schema_from_typed_dict_type",
    "schema_from_structured_model",
)


def test_schema_construction_helpers_live_in_helper_module() -> None:
    """JSON Schema builders should not live in the generator entry module."""
    generator_text = (TOOLS_DIR / "generate_schemas.py").read_text(encoding="utf-8")
    helpers_text = (TOOLS_DIR / "generate_schemas_helpers.py").read_text(encoding="utf-8")

    assert "def main(" in generator_text
    assert "def write_schema" in generator_text
    assert "SCHEMAS: dict[str, JsonSchema]" in generator_text

    for name in SCHEMA_CONSTRUCTION_HELPERS:
        assert f"def {name}" not in generator_text
        assert f"def {name}" in helpers_text


def test_schema_construction_helpers_reexport_from_generate_schemas() -> None:
    """Existing generate_schemas imports should keep resolving to the helpers."""
    generator_text = (TOOLS_DIR / "generate_schemas.py").read_text(encoding="utf-8")

    for name in SCHEMA_CONSTRUCTION_HELPERS:
        assert name in generator_text
        assert getattr(generate_schemas, name) is getattr(generate_schemas_helpers, name)

    assert generate_schemas.SCHEMA_DRAFT is generate_schemas_helpers.SCHEMA_DRAFT
    assert generate_schemas.JsonSchema is generate_schemas_helpers.JsonSchema
    assert callable(generate_schemas.main)
    assert callable(generate_schemas.write_schema)
    assert generate_schemas.SCHEMAS
