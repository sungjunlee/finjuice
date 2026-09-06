"""Structure checks for the split CLI output error/exit-code catalog."""

from pathlib import Path

from finjuice.pipeline.cli import output, output_codes, output_messages, output_pagination

CLI_DIR = Path("src/finjuice/pipeline/cli")
CODES_MODULE = "finjuice.pipeline.cli.output_codes"
OUTPUT_MODULE = "finjuice.pipeline.cli.output"

PUBLIC_ENTRY_NAMES = (
    "emit",
    "emit_list",
    "emit_error",
    "render_markdown_table",
    "render_markdown_dataframe",
)
CODE_CLASS_NAMES = ("ErrorCode", "ExitCode")
CODE_FUNCTION_NAMES = (
    "error_code_values",
    "exit_code_items",
    "exit_code_values",
    "_normalize_error_code",
    "_normalize_exit_code",
)
CODE_CATALOG_NAMES = ("ERROR_CODE_CATALOG", "EXIT_CODE_CATALOG")


def test_error_exit_code_helpers_live_in_helper_module() -> None:
    """Error/exit catalogs should not live in the public emit entry module."""
    output_text = (CLI_DIR / "output.py").read_text(encoding="utf-8")
    codes_text = (CLI_DIR / "output_codes.py").read_text(encoding="utf-8")
    messages_text = (CLI_DIR / "output_messages.py").read_text(encoding="utf-8")
    pagination_text = (CLI_DIR / "output_pagination.py").read_text(encoding="utf-8")

    for name in PUBLIC_ENTRY_NAMES:
        assert f"def {name}" in output_text
        assert f"def {name}" not in codes_text

    for name in CODE_CLASS_NAMES:
        assert f"class {name}" not in output_text
        assert f"class {name}" in codes_text
        assert f"class {name}" not in messages_text
        assert f"class {name}" not in pagination_text

    for name in CODE_FUNCTION_NAMES:
        assert f"def {name}" not in output_text
        assert f"def {name}" in codes_text
        assert name in output_text

    for name in CODE_CATALOG_NAMES:
        assert f"{name}:" not in output_text
        assert f"{name}:" in codes_text
        assert name in output_text


def test_error_exit_code_names_stay_on_output() -> None:
    """Public error/exit names stay importable from output after the split."""
    for name in CODE_CLASS_NAMES + CODE_FUNCTION_NAMES + CODE_CATALOG_NAMES:
        assert getattr(output, name) is getattr(output_codes, name)

    for name in PUBLIC_ENTRY_NAMES:
        assert callable(getattr(output, name))
        assert getattr(output, name).__module__ == OUTPUT_MODULE

    assert output.success is output_messages.success
    assert output.Pagination is output_pagination.Pagination


def test_code_helpers_are_defined_exactly_once() -> None:
    """Moved catalog helpers should be the same objects, not local copies."""
    for name in CODE_FUNCTION_NAMES:
        helper = getattr(output_codes, name)
        assert helper.__module__ == CODES_MODULE
        assert getattr(output, name).__module__ == CODES_MODULE

    for name in CODE_CLASS_NAMES:
        helper = getattr(output_codes, name)
        assert helper.__module__ == CODES_MODULE
        assert getattr(output, name).__module__ == CODES_MODULE
