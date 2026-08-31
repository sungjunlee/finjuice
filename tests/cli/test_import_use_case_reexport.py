"""The import use case keeps re-exporting ZIP input helpers after the split."""

import importlib


def test_use_case_reexports_zip_input_helpers() -> None:
    """ZIP input preparation helpers stay importable from use_case after the split."""
    use_case = importlib.import_module("finjuice.pipeline.cli.commands.import_cmd.use_case")
    zip_inputs = importlib.import_module("finjuice.pipeline.cli.commands.import_cmd.zip_inputs")

    assert use_case._extract_zip_inputs is zip_inputs._extract_zip_inputs
    assert use_case._extract_one_zip is zip_inputs._extract_one_zip
    assert use_case._fail_json_password_prompt is zip_inputs._fail_json_password_prompt
    assert callable(use_case.run_import)
    assert callable(use_case.ImportDependencies)
