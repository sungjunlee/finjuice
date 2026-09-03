"""Identity checks for the split audit JSONL I/O helpers."""

from pathlib import Path

from finjuice.pipeline.cli.commands import audit as audit_module
from finjuice.pipeline.cli.commands import audit_io

COMMANDS_DIR = Path("src/finjuice/pipeline/cli/commands")


def test_audit_io_helpers_live_in_helper_module() -> None:
    """JSONL read/write helpers should not live in the Typer module."""
    audit_text = (COMMANDS_DIR / "audit.py").read_text(encoding="utf-8")
    io_text = (COMMANDS_DIR / "audit_io.py").read_text(encoding="utf-8")

    assert "def log(" in audit_text
    assert "def stats(" in audit_text
    assert "def clear(" in audit_text
    assert "def _read_audit_events_with_skip" not in audit_text
    assert "def _write_audit_events_atomically" not in audit_text
    assert "def _read_audit_events_with_skip" in io_text
    assert "def _write_audit_events_atomically" in io_text


def test_audit_io_helpers_reexport_from_entrypoint() -> None:
    """Existing audit.py imports should keep resolving to the JSONL I/O helpers."""
    audit_text = (COMMANDS_DIR / "audit.py").read_text(encoding="utf-8")

    assert "def log(" in audit_text
    assert "_read_audit_events_with_skip" in audit_text
    assert "_write_audit_events_atomically" in audit_text
    assert audit_module._read_audit_events_with_skip is audit_io._read_audit_events_with_skip
    assert audit_module._write_audit_events_atomically is audit_io._write_audit_events_atomically
    assert callable(audit_module.log)
    assert callable(audit_module.stats)
    assert callable(audit_module.clear)
