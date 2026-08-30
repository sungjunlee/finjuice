"""Identity tests for the import use_case path-split helper."""

from pathlib import Path

from finjuice.pipeline.cli.commands.import_cmd import use_case, use_case_helpers

IMPORT_CMD_DIR = Path("src/finjuice/pipeline/cli/commands/import_cmd")


def test_split_import_inputs_lives_in_helper_module() -> None:
    """Path splitting should not live in the use-case orchestrator."""
    use_case_text = (IMPORT_CMD_DIR / "use_case.py").read_text(encoding="utf-8")
    helpers_text = (IMPORT_CMD_DIR / "use_case_helpers.py").read_text(encoding="utf-8")

    assert "def run_import" in use_case_text
    assert "class ImportDependencies" in use_case_text
    assert "def _ensure_initialized" in use_case_text
    assert "def _copy_and_maybe_run_pipeline" in use_case_text
    assert "def _split_import_inputs" not in use_case_text
    assert "def _split_import_inputs" in helpers_text


def test_split_import_inputs_reexport_from_use_case() -> None:
    """Existing use_case imports should keep resolving to the split helper."""
    assert use_case._split_import_inputs is use_case_helpers._split_import_inputs
    assert callable(use_case.run_import)
    assert callable(use_case._ensure_initialized)
    assert callable(use_case._copy_and_maybe_run_pipeline)
