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
        "mutations_helpers",
        "testing",
        "suggest",
        "suggest_rendering",
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


def test_rules_suggest_rendering_lives_in_helper_module() -> None:
    """Merchant-context formatting and tables should not live in the Typer command."""
    suggest_text = (COMMANDS_DIR / "rules_cmd" / "suggest.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "rules_cmd" / "suggest_rendering.py").read_text(
        encoding="utf-8"
    )

    assert "def suggest_rules_command" in suggest_text
    assert "def _interactive_apply_suggestions" in suggest_text
    assert "def _render_suggestion_context_table" not in suggest_text
    assert "def _render_apply_dry_run" not in suggest_text
    assert "def _format_suggestion_category" not in suggest_text
    assert "def _render_suggestion_context_table" in rendering_text
    assert "def _render_apply_dry_run" in rendering_text
    assert "def _format_suggestion_category" in rendering_text


def test_rules_mutation_helpers_live_in_helper_module() -> None:
    """Upsert, impact preview, and rendering should not live in the Typer command."""
    mutations_text = (COMMANDS_DIR / "rules_cmd" / "mutations.py").read_text(encoding="utf-8")
    helpers_text = (COMMANDS_DIR / "rules_cmd" / "mutations_helpers.py").read_text(encoding="utf-8")

    assert "def add_rule_command" in mutations_text
    assert "def remove_rule_command" in mutations_text
    assert "def _compute_add_rule" in mutations_text
    assert "def _compute_remove_rule" in mutations_text
    assert "def _upsert_candidate_rules" not in mutations_text
    assert "def _compute_rule_impact_preview" not in mutations_text
    assert "def _render_rule_mutation" not in mutations_text
    assert "def _upsert_candidate_rules" in helpers_text
    assert "def _compute_rule_impact_preview" in helpers_text
    assert "def _render_rule_mutation" in helpers_text
