"""Structure checks for the split explain command implementation."""

from pathlib import Path

from finjuice.pipeline.cli.commands import explain as explain_module
from finjuice.pipeline.cli.commands import explain_rendering

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_explain_rendering_helpers_live_in_helper_module() -> None:
    """Transaction-details and rule-trace rendering should not live in the Typer module."""
    explain_text = (COMMANDS_DIR / "explain.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "explain_rendering.py").read_text(encoding="utf-8")

    assert "def explain_command" in explain_text
    assert "def _search_transactions" in explain_text
    assert "def _select_transaction" in explain_text
    assert "def _build_explanation" in explain_text
    assert "def render_explain" not in explain_text
    assert "def render_explain" in rendering_text


def test_explain_public_names_stay_on_entrypoint() -> None:
    """The stable explain import path should keep the command and extracted helper names."""
    explain_text = (COMMANDS_DIR / "explain.py").read_text(encoding="utf-8")

    assert "def explain_command" in explain_text
    assert "def register_explain_command" in explain_text
    assert "render_explain" in explain_text
    assert explain_module.render_explain is explain_rendering.render_explain
    assert callable(explain_module.explain_command)
    assert callable(explain_module.register_explain_command)
