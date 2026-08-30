"""Structure and identity checks for the rules test rendering split."""

import importlib
from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

RENDERING_HELPERS = (
    "_format_rules_test_amount",
    "_format_rules_test_header",
    "_format_rules_test_tags",
    "_render_rules_test",
    "_render_rules_test_counter_table",
    "_render_rules_test_sample",
)


def test_rules_test_rendering_lives_in_helper_module() -> None:
    """Sample tables and the summary header should not live in the Typer command."""
    testing_text = (COMMANDS_DIR / "rules_cmd" / "testing.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "rules_cmd" / "testing_rendering.py").read_text(
        encoding="utf-8"
    )

    assert "def test_rule_command" in testing_text
    for name in RENDERING_HELPERS:
        assert f"def {name}" not in testing_text
        assert f"def {name}" in rendering_text


def test_rules_test_rendering_names_stay_on_entrypoint() -> None:
    """Rendering helpers stay importable from the stable testing module."""
    testing = importlib.import_module("finjuice.pipeline.cli.commands.rules_cmd.testing")
    rendering = importlib.import_module(
        "finjuice.pipeline.cli.commands.rules_cmd.testing_rendering"
    )

    for name in RENDERING_HELPERS:
        assert getattr(testing, name) is getattr(rendering, name)
    assert callable(testing.test_rule_command)
