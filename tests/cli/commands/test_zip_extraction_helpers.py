"""Identity tests for the zip_extraction password helper split."""

from pathlib import Path

from finjuice.pipeline.cli.commands.import_cmd import zip_extraction, zip_extraction_helpers

IMPORT_CMD_DIR = Path("src/finjuice/pipeline/cli/commands/import_cmd")


def test_password_helpers_live_in_helper_module() -> None:
    """Password detection and prompts should not live in the extraction module."""
    extraction_text = (IMPORT_CMD_DIR / "zip_extraction.py").read_text(encoding="utf-8")
    helpers_text = (IMPORT_CMD_DIR / "zip_extraction_helpers.py").read_text(encoding="utf-8")

    assert "def extract_xlsx_from_zip" in extraction_text
    assert "def _extract_xlsx_from_open_zip" in extraction_text
    assert "def _extract_all" in extraction_text
    assert "def _cleanup_temp_dirs" in extraction_text
    assert "class _PasswordDecision" not in extraction_text
    assert "def _zip_requires_password" not in extraction_text
    assert "def _zip_info_requires_password" not in extraction_text
    assert "def _zip_file_requires_password" not in extraction_text
    assert "def _decide_password" not in extraction_text
    assert "def _re_prompt_password" not in extraction_text
    assert "class _PasswordDecision" in helpers_text
    assert "def _zip_requires_password" in helpers_text
    assert "def _zip_info_requires_password" in helpers_text
    assert "def _zip_file_requires_password" in helpers_text
    assert "def _decide_password" in helpers_text
    assert "def _re_prompt_password" in helpers_text


def test_password_helpers_reexport_from_zip_extraction() -> None:
    """Existing zip_extraction imports should keep resolving to the password helpers."""
    assert zip_extraction._PasswordDecision is zip_extraction_helpers._PasswordDecision
    assert zip_extraction._zip_requires_password is zip_extraction_helpers._zip_requires_password
    assert (
        zip_extraction._zip_info_requires_password
        is zip_extraction_helpers._zip_info_requires_password
    )
    assert (
        zip_extraction._zip_file_requires_password
        is zip_extraction_helpers._zip_file_requires_password
    )
    assert zip_extraction._decide_password is zip_extraction_helpers._decide_password
    assert zip_extraction._re_prompt_password is zip_extraction_helpers._re_prompt_password
    assert callable(zip_extraction.extract_xlsx_from_zip)
    assert callable(zip_extraction._extract_xlsx_from_open_zip)
    assert callable(zip_extraction._cleanup_temp_dirs)
