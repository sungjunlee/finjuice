"""Structure checks for the split audit command implementation."""

from pathlib import Path

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_audit_rendering_helpers_live_in_helper_module() -> None:
    """Log/stats/clear rendering should not live in the Typer command module."""
    audit_text = (COMMANDS_DIR / "audit.py").read_text(encoding="utf-8")
    rendering_text = (COMMANDS_DIR / "audit_rendering.py").read_text(encoding="utf-8")

    assert "def log(" in audit_text
    assert "def stats(" in audit_text
    assert "def clear(" in audit_text
    assert "def _read_audit_events_with_skip" not in audit_text
    assert "def _write_audit_events_atomically" not in audit_text
    assert "def _build_audit_log_details" not in audit_text
    assert "def _render_audit_log" not in audit_text
    assert "def _render_audit_stats" not in audit_text
    assert "def _render_audit_clear" not in audit_text
    assert "def _render_template_run_metrics" not in audit_text
    assert "def _build_audit_log_details" in rendering_text
    assert "def _render_audit_log" in rendering_text
    assert "def _render_audit_stats" in rendering_text
    assert "def _render_audit_clear" in rendering_text
    assert "def _render_template_run_metrics" in rendering_text


def test_audit_public_command_names_stay_on_entrypoint() -> None:
    """The stable audit import path should keep public command names."""
    audit_text = (COMMANDS_DIR / "audit.py").read_text(encoding="utf-8")

    assert "app = typer.Typer(" in audit_text
    assert "def log(" in audit_text
    assert "def stats(" in audit_text
    assert "def clear(" in audit_text
    assert "_read_audit_events_with_skip" in audit_text
    assert "_write_audit_events_atomically" in audit_text
    assert "_render_audit_log" in audit_text
    assert "_render_audit_stats" in audit_text
    assert "_render_audit_clear" in audit_text
