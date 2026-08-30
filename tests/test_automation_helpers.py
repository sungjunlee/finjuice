"""Identity tests for the automation_helpers pending-import split."""

from pathlib import Path

from finjuice.pipeline import automation, automation_helpers, automation_pending_imports

PIPELINE_DIR = Path("src/finjuice/pipeline")


def test_pending_import_helpers_live_in_helper_module() -> None:
    """Pending-import preview helpers should not live in automation_helpers.py."""
    helpers_text = (PIPELINE_DIR / "automation_helpers.py").read_text(encoding="utf-8")
    pending_text = (PIPELINE_DIR / "automation_pending_imports.py").read_text(encoding="utf-8")

    assert "def _collect_tagging_pressure" in helpers_text
    assert "def _collect_large_transactions" in helpers_text
    assert "def _build_next_steps" in helpers_text
    assert "def _optional_text" in helpers_text
    assert "def _collect_pending_imports" not in helpers_text
    assert "class PendingImportFile" not in helpers_text
    assert "class PendingImportFailure" not in helpers_text
    assert "class PendingImportsSignal" not in helpers_text
    assert "def _basename" not in helpers_text
    assert "SignalStatus = Literal" not in helpers_text
    assert "def _collect_pending_imports" in pending_text
    assert "class PendingImportFile" in pending_text
    assert "class PendingImportFailure" in pending_text
    assert "class PendingImportsSignal" in pending_text
    assert "def _basename" in pending_text
    assert "SignalStatus = Literal" in pending_text


def test_pending_import_helpers_reexport_from_automation_helpers() -> None:
    """Existing automation_helpers imports should keep resolving to pending-import helpers."""
    helpers_text = (PIPELINE_DIR / "automation_helpers.py").read_text(encoding="utf-8")

    assert "def _collect_tagging_pressure" in helpers_text
    assert "_collect_pending_imports" in helpers_text
    assert "PendingImportFile" in helpers_text
    assert "PendingImportFailure" in helpers_text
    assert "PendingImportsSignal" in helpers_text
    assert "_basename" in helpers_text
    assert "SignalStatus" in helpers_text

    assert (
        automation_helpers._collect_pending_imports
        is automation_pending_imports._collect_pending_imports
    )
    assert automation_helpers.PendingImportFile is automation_pending_imports.PendingImportFile
    assert (
        automation_helpers.PendingImportFailure is automation_pending_imports.PendingImportFailure
    )
    assert (
        automation_helpers.PendingImportsSignal is automation_pending_imports.PendingImportsSignal
    )
    assert automation_helpers._basename is automation_pending_imports._basename
    assert automation_helpers.SignalStatus is automation_pending_imports.SignalStatus
    assert automation.PendingImportFile is automation_pending_imports.PendingImportFile
    assert automation.PendingImportFailure is automation_pending_imports.PendingImportFailure
    assert automation.PendingImportsSignal is automation_pending_imports.PendingImportsSignal
    assert callable(automation_helpers._collect_tagging_pressure)
    assert callable(automation_helpers._collect_large_transactions)
    assert callable(automation_helpers._build_next_steps)
    assert callable(automation.collect_automation_signals)
