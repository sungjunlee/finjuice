"""Structure and identity checks for the rules suggest JSON-payload split."""

import importlib
from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

JSON_HELPERS = (
    "_audit_applied_suggestion",
    "_emit_suggest_compute_error",
    "_rules_suggest_json_payload",
)


def test_rules_suggest_json_helpers_live_in_helper_module() -> None:
    """JSON payload and compute-error helpers should not live in the Typer command."""
    suggest_text = (COMMANDS_DIR / "rules_cmd" / "suggest.py").read_text(encoding="utf-8")
    json_text = (COMMANDS_DIR / "rules_cmd" / "suggest_json.py").read_text(encoding="utf-8")

    assert "def suggest_rules_command" in suggest_text
    for name in JSON_HELPERS:
        assert f"def {name}" not in suggest_text
        assert f"def {name}" in json_text


def test_rules_suggest_json_helpers_reexport_from_entrypoint() -> None:
    """JSON helpers stay importable from the stable suggest module as the same objects."""
    suggest = importlib.import_module("finjuice.pipeline.cli.commands.rules_cmd.suggest")
    json_mod = importlib.import_module("finjuice.pipeline.cli.commands.rules_cmd.suggest_json")

    for name in JSON_HELPERS:
        assert getattr(suggest, name) is getattr(json_mod, name)
    assert callable(suggest.suggest_rules_command)
