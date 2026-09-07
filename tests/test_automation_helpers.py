"""Identity tests for the automation_helpers collector splits."""

from pathlib import Path

from finjuice.pipeline import (
    automation,
    automation_helpers,
    automation_large_transactions,
    automation_pending_imports,
    automation_tagging_pressure,
)
from finjuice.pipeline.automation_helpers import AutomationHint, _build_next_steps
from finjuice.pipeline.automation_large_transactions import LargeTransactionSignal
from finjuice.pipeline.automation_pending_imports import PendingImportsSignal
from finjuice.pipeline.automation_tagging_pressure import TaggingPressureSignal

PIPELINE_DIR = Path("src/finjuice/pipeline")


def _pending_signal(*, status: str) -> PendingImportsSignal:
    """Return a pending-imports signal with the requested status."""
    return PendingImportsSignal(
        status=status,  # type: ignore[arg-type]
        files_found=0,
        pending_files=0,
        estimated_new_rows=0,
        estimated_new_asset_rows=0,
        failed_files=[],
        sample_files=[],
    )


def _tagging_signal(*, status: str) -> TaggingPressureSignal:
    """Return a tagging-pressure signal with the requested status."""
    return TaggingPressureSignal(
        status=status,  # type: ignore[arg-type]
        total_transactions=0,
        untagged_transactions=0,
        coverage_pct=0.0,
        suggestable_untagged_transactions=0,
        suggestable_coverage_pct=0.0,
        transfer_excluded_untagged_transactions=0,
        merchant_pressure=[],
    )


def _large_signal(*, status: str, threshold: int = 300000) -> LargeTransactionSignal:
    """Return a large-transaction signal with the requested status."""
    return LargeTransactionSignal(
        status=status,  # type: ignore[arg-type]
        threshold=threshold,
        count=0,
        samples=[],
    )


def test_pending_import_helpers_live_in_helper_module() -> None:
    """Pending-import preview helpers should not live in automation_helpers.py."""
    helpers_text = (PIPELINE_DIR / "automation_helpers.py").read_text(encoding="utf-8")
    pending_text = (PIPELINE_DIR / "automation_pending_imports.py").read_text(encoding="utf-8")

    assert "def _build_next_steps" in helpers_text
    assert "class AutomationHint" in helpers_text
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
    assert callable(automation_helpers._build_next_steps)
    assert callable(automation.collect_automation_signals)


def test_tagging_pressure_helpers_live_in_helper_module() -> None:
    """Tagging-pressure collector should not live in automation_helpers.py."""
    helpers_text = (PIPELINE_DIR / "automation_helpers.py").read_text(encoding="utf-8")
    tagging_text = (PIPELINE_DIR / "automation_tagging_pressure.py").read_text(encoding="utf-8")

    assert "def _collect_tagging_pressure" not in helpers_text
    assert "class TaggingPressureSignal" not in helpers_text
    assert "class MerchantPressureSample" not in helpers_text
    assert "def _build_next_steps" in helpers_text
    assert "get_suggestion_coverage_stats" not in helpers_text
    assert "SignalStatus = Literal" not in tagging_text
    assert "def _collect_tagging_pressure" in tagging_text
    assert "class TaggingPressureSignal" in tagging_text
    assert "class MerchantPressureSample" in tagging_text


def test_tagging_pressure_helpers_reexport_from_automation_helpers() -> None:
    """Existing automation_helpers imports should keep resolving to tagging-pressure helpers."""
    helpers_text = (PIPELINE_DIR / "automation_helpers.py").read_text(encoding="utf-8")

    assert "_collect_tagging_pressure" in helpers_text
    assert "TaggingPressureSignal" in helpers_text
    assert "MerchantPressureSample" in helpers_text

    assert (
        automation_helpers._collect_tagging_pressure
        is automation_tagging_pressure._collect_tagging_pressure
    )
    assert (
        automation_helpers.TaggingPressureSignal
        is automation_tagging_pressure.TaggingPressureSignal
    )
    assert (
        automation_helpers.MerchantPressureSample
        is automation_tagging_pressure.MerchantPressureSample
    )
    assert automation.TaggingPressureSignal is automation_tagging_pressure.TaggingPressureSignal
    assert automation.MerchantPressureSample is automation_tagging_pressure.MerchantPressureSample
    assert callable(automation_helpers._collect_tagging_pressure)


def test_large_transaction_helpers_live_in_helper_module() -> None:
    """Large-transaction collector should not live in automation_helpers.py."""
    helpers_text = (PIPELINE_DIR / "automation_helpers.py").read_text(encoding="utf-8")
    large_text = (PIPELINE_DIR / "automation_large_transactions.py").read_text(encoding="utf-8")

    assert "def _collect_large_transactions" not in helpers_text
    assert "class LargeTransactionSignal" not in helpers_text
    assert "class LargeTransactionSample" not in helpers_text
    assert "def _optional_text" not in helpers_text
    assert "def _build_next_steps" in helpers_text
    assert "DuckDBAnalytics" not in helpers_text
    assert "FROM transactions" not in helpers_text
    assert "SignalStatus = Literal" not in large_text
    assert "def _collect_large_transactions" in large_text
    assert "class LargeTransactionSignal" in large_text
    assert "class LargeTransactionSample" in large_text
    assert "def _optional_text" in large_text


def test_large_transaction_helpers_reexport_from_automation_helpers() -> None:
    """Existing automation_helpers imports should keep resolving to large-transaction helpers."""
    helpers_text = (PIPELINE_DIR / "automation_helpers.py").read_text(encoding="utf-8")

    assert "_collect_large_transactions" in helpers_text
    assert "LargeTransactionSignal" in helpers_text
    assert "LargeTransactionSample" in helpers_text
    assert "_optional_text" in helpers_text

    assert (
        automation_helpers._collect_large_transactions
        is automation_large_transactions._collect_large_transactions
    )
    assert (
        automation_helpers.LargeTransactionSignal
        is automation_large_transactions.LargeTransactionSignal
    )
    assert (
        automation_helpers.LargeTransactionSample
        is automation_large_transactions.LargeTransactionSample
    )
    assert automation_helpers._optional_text is automation_large_transactions._optional_text
    assert automation.LargeTransactionSignal is automation_large_transactions.LargeTransactionSignal
    assert automation.LargeTransactionSample is automation_large_transactions.LargeTransactionSample
    assert callable(automation_helpers._collect_large_transactions)


def test_build_next_steps_composes_present_collector_signals() -> None:
    """Next-step composition should map present collector statuses to existing commands."""
    # Arrange
    pending = _pending_signal(status="present")
    tagging = _tagging_signal(status="present")
    large = _large_signal(status="present", threshold=300000)

    # Act
    next_steps = _build_next_steps(
        pending_imports=pending,
        tagging_pressure=tagging,
        large_transactions=large,
    )

    # Assert
    assert [hint.signal for hint in next_steps] == [
        "pending_imports",
        "tagging_pressure",
        "large_transactions",
    ]
    assert [hint.command for hint in next_steps] == [
        "finjuice refresh",
        "finjuice rules suggest",
        "finjuice template run anomaly_large_txn --param threshold=300000",
    ]
    assert all(isinstance(hint, AutomationHint) for hint in next_steps)


def test_build_next_steps_skips_clear_and_unavailable_signals() -> None:
    """Clear and unavailable collector statuses should not invent next-step policy."""
    # Arrange
    pending = _pending_signal(status="clear")
    tagging = _tagging_signal(status="unavailable")
    large = _large_signal(status="clear")

    # Act
    next_steps = _build_next_steps(
        pending_imports=pending,
        tagging_pressure=tagging,
        large_transactions=large,
    )

    # Assert
    assert next_steps == []
