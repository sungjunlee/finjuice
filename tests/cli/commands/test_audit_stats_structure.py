"""Identity checks for the split audit stats payload helpers."""

from pathlib import Path

from finjuice.pipeline.cli.commands import audit as audit_module
from finjuice.pipeline.cli.commands import audit_stats

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")

MOVED_HELPER_NAMES = (
    "_count_command_suggestions",
    "_count_command_executions",
    "_build_top_commands",
    "_attach_template_run_summary",
    "_build_audit_stats_result",
)


def test_audit_stats_helpers_live_in_helper_module() -> None:
    """Suggestion/execution payload assembly should not live in the Typer module."""
    audit_text = (COMMANDS_DIR / "audit.py").read_text(encoding="utf-8")
    stats_text = (COMMANDS_DIR / "audit_stats.py").read_text(encoding="utf-8")

    assert "def log(" in audit_text
    assert "def stats(" in audit_text
    assert "def clear(" in audit_text
    for name in MOVED_HELPER_NAMES:
        assert f"def {name}" not in audit_text
        assert f"def {name}" in stats_text


def test_audit_stats_helpers_reexport_from_entrypoint() -> None:
    """Existing audit.py imports should keep resolving to the stats helpers."""
    audit_text = (COMMANDS_DIR / "audit.py").read_text(encoding="utf-8")

    assert "app = typer.Typer(" in audit_text
    assert "def log(" in audit_text
    assert "def stats(" in audit_text
    assert "def clear(" in audit_text
    assert "_build_audit_stats_result" in audit_text
    assert audit_module._build_audit_stats_result is audit_stats._build_audit_stats_result
    assert audit_stats._build_audit_stats_result.__module__ == (
        "finjuice.pipeline.cli.commands.audit_stats"
    )
    assert callable(audit_module.log)
    assert callable(audit_module.stats)
    assert callable(audit_module.clear)
