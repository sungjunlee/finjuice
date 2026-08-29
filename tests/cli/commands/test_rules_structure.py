"""Structure checks for the split rules command implementation."""

from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_rules_entrypoint_stays_thin() -> None:
    """The stable rules import path should only wire focused command handlers."""
    rules_py = COMMANDS_DIR / "rules.py"
    text = rules_py.read_text(encoding="utf-8")

    assert len(text.splitlines()) < 200
    for token in (
        "rules_app = typer.Typer",
        "register_rules_commands",
        'rules_app.command(name="validate")',
        'rules_app.command(name="suggest")',
        'rules_app.command(name="gaps")',
    ):
        assert token in text

    assert "def _compute_rules_suggest_json" not in text
    assert "def _compute_add_rule" not in text
    assert "def _compute_rules_gaps_json" not in text


def test_rules_command_implementations_are_split_by_domain() -> None:
    """Focused modules should own the command-specific implementation details."""
    rules_cmd_dir = COMMANDS_DIR / "rules_cmd"
    module_names = {path.stem for path in rules_cmd_dir.glob("*.py")}

    assert {
        "shared",
        "mutations",
        "testing",
        "suggest",
        "export",
        "gaps",
    }.issubset(module_names)


def test_rules_suggest_compute_lives_in_tagging_pipeline() -> None:
    """JSON compute and compact helpers should not live in the Typer command module."""
    suggest_text = (COMMANDS_DIR / "rules_cmd" / "suggest.py").read_text(encoding="utf-8")
    compute_text = Path("src/finjuice/pipeline/tagging/suggest_compute.py").read_text(
        encoding="utf-8"
    )

    assert "def suggest_rules_command" in suggest_text
    assert "def _interactive_apply_suggestions" in suggest_text
    assert "def _compute_rules_suggest_json" not in suggest_text
    assert "def _compact_suggested_rule" not in suggest_text
    assert "def _compact_rule_suggestion" not in suggest_text
    assert "def _compact_rules_suggest_result" not in suggest_text
    assert "def _compute_rules_suggest_json" in compute_text
    assert "def _compact_suggested_rule" in compute_text
    assert "def _compact_rule_suggestion" in compute_text
    assert "def _compact_rules_suggest_result" in compute_text
