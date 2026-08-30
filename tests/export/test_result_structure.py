"""Structure checks for the split export result helper implementation."""

from pathlib import Path

from finjuice.pipeline.export import result, result_outputs

EXPORT_DIR = Path("src/finjuice/pipeline/export")


def test_format_output_helpers_live_in_helper_module() -> None:
    """XLSX/HTML/Markdown generators should not live in result.py."""
    result_text = (EXPORT_DIR / "result.py").read_text(encoding="utf-8")
    outputs_text = (EXPORT_DIR / "result_outputs.py").read_text(encoding="utf-8")

    assert "def _compute_export_result" in result_text
    assert "def configure_export_result_runtime" in result_text
    assert "def _generate_xlsx_outputs" not in result_text
    assert "def _generate_html_outputs" not in result_text
    assert "def _generate_markdown_outputs" not in result_text
    assert "def _generate_xlsx_outputs" in outputs_text
    assert "def _generate_html_outputs" in outputs_text
    assert "def _generate_markdown_outputs" in outputs_text


def test_format_output_helpers_reexport_from_result() -> None:
    """Existing result imports should keep resolving to the helper functions."""
    assert result._generate_xlsx_outputs is result_outputs._generate_xlsx_outputs
    assert result._generate_html_outputs is result_outputs._generate_html_outputs
    assert result._generate_markdown_outputs is result_outputs._generate_markdown_outputs
    assert callable(result._compute_export_result)
    assert callable(result.configure_export_result_runtime)
    assert callable(result.build_export_plan)
    assert callable(result.build_output_entry)
    assert callable(result.format_size_bytes)
    assert callable(result.estimate_output_size_bytes)


def test_result_modules_do_not_import_cli() -> None:
    """Export result modules must not import finjuice.pipeline.cli.*."""
    for path in (
        EXPORT_DIR / "result.py",
        EXPORT_DIR / "result_outputs.py",
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from finjuice.pipeline.cli" not in stripped
            assert "import finjuice.pipeline.cli" not in stripped
