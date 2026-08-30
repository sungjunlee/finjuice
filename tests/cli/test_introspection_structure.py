"""Structure and identity checks for the split CLI introspection helpers."""

from pathlib import Path

from finjuice.pipeline.cli import introspection, introspection_schema

CLI_DIR = Path("src/finjuice/pipeline/cli")

_SCHEMA_HELPER_NAMES = (
    "ENUM_HELP_PATTERNS",
    "option_property_name",
    "infer_enum_from_help",
    "base_type_schema",
    "make_nullable",
    "serialize_default",
    "build_parameter_schema",
    "build_parameters_schema",
    "has_json_flag",
)


def test_schema_helpers_live_in_helper_module() -> None:
    """JSON Schema parameter helpers should not live in introspection.py."""
    introspection_text = (CLI_DIR / "introspection.py").read_text(encoding="utf-8")
    schema_text = (CLI_DIR / "introspection_schema.py").read_text(encoding="utf-8")

    assert "def iter_executable_commands" in introspection_text
    assert "def iter_leaf_commands" in introspection_text
    assert "def is_executable_command" in introspection_text
    assert "def rich_help_panel_name" in introspection_text
    assert "def option_property_name" not in introspection_text
    assert "def infer_enum_from_help" not in introspection_text
    assert "def base_type_schema" not in introspection_text
    assert "def make_nullable" not in introspection_text
    assert "def serialize_default" not in introspection_text
    assert "def build_parameter_schema" not in introspection_text
    assert "def build_parameters_schema" not in introspection_text
    assert "def has_json_flag" not in introspection_text
    assert "def option_property_name" in schema_text
    assert "def infer_enum_from_help" in schema_text
    assert "def base_type_schema" in schema_text
    assert "def make_nullable" in schema_text
    assert "def serialize_default" in schema_text
    assert "def build_parameter_schema" in schema_text
    assert "def build_parameters_schema" in schema_text
    assert "def has_json_flag" in schema_text
    assert "ENUM_HELP_PATTERNS" in schema_text


def test_schema_helpers_reexport_from_introspection() -> None:
    """Public schema names stay importable from introspection after the split."""
    assert introspection.ENUM_HELP_PATTERNS is introspection_schema.ENUM_HELP_PATTERNS
    assert introspection.option_property_name is introspection_schema.option_property_name
    assert introspection.infer_enum_from_help is introspection_schema.infer_enum_from_help
    assert introspection.base_type_schema is introspection_schema.base_type_schema
    assert introspection.make_nullable is introspection_schema.make_nullable
    assert introspection.serialize_default is introspection_schema.serialize_default
    assert introspection.build_parameter_schema is introspection_schema.build_parameter_schema
    assert introspection.build_parameters_schema is introspection_schema.build_parameters_schema
    assert introspection.has_json_flag is introspection_schema.has_json_flag
    assert callable(introspection.iter_executable_commands)
    assert callable(introspection.iter_leaf_commands)
    assert callable(introspection.is_executable_command)
    assert callable(introspection.rich_help_panel_name)
    assert callable(introspection.iter_executable_commands_with_panels)
    assert callable(introspection.iter_leaf_commands_with_panels)


def test_schema_helper_names_are_not_defined_on_introspection() -> None:
    """Extracted helpers should be the same objects, not local copies."""
    for name in _SCHEMA_HELPER_NAMES:
        assert getattr(introspection, name) is getattr(introspection_schema, name)
