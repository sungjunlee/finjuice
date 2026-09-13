"""Structure and behavior tests for revision-based month close (issue #447)."""

from __future__ import annotations

import importlib
from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline.close.errors import CloseLockedError, ClosePathError, CloseStateError
from finjuice.pipeline.close.ledger import CloseStore
from finjuice.pipeline.close.models import CloseLine, CloseSnapshot

CLOSE_DIR = Path("src/finjuice/pipeline/close")
PACKAGE = "finjuice.pipeline.close"
OPERATIONS_MODULE = "finjuice.pipeline.close.operations"
REPORT_MODULE = "finjuice.pipeline.close.report"
LEDGER_MODULE = "finjuice.pipeline.close.ledger"
MODELS_MODULE = "finjuice.pipeline.close.models"
ERRORS_MODULE = "finjuice.pipeline.close.errors"

OPERATIONS_NAMES = (
    "backup_close_ledger",
    "close_month",
    "close_status",
    "normalize_snapshot",
    "regenerate_close_report",
    "reopen_month",
    "restore_close_ledger",
    "retry_close",
)
REPORT_NAMES = ("compute_close_report", "explain_close_diff")
LEDGER_NAMES = (
    "CloseStore",
    "copy_close_ledger",
    "validate_period",
    "validate_store_root",
)
MODEL_NAMES = (
    "CloseDiff",
    "CloseEvent",
    "CloseLine",
    "CloseReport",
    "CloseRevisionRecord",
    "CloseSnapshot",
    "CloseStatus",
)
ERROR_NAMES = (
    "CloseError",
    "CloseLockedError",
    "CloseNotFoundError",
    "ClosePathError",
    "CloseStateError",
)


def _snapshot() -> CloseSnapshot:
    return CloseSnapshot(
        period="2026-01",
        dataset_revision=0,
        rules_policy="rules:v1",
        calculation_policy="calc:v1",
        source_as_of="2026-02-01",
        lines=(
            CloseLine(line_id="in1", amount="1000", category="income"),
            CloseLine(line_id="out1", amount="-400", category="food"),
        ),
        unconfirmed_item_ids=(),
    )


def test_close_package_reexports_definition_identity() -> None:
    """Public close names stay identity-equal to their definition modules."""
    package = importlib.import_module(PACKAGE)
    operations = importlib.import_module(OPERATIONS_MODULE)
    report = importlib.import_module(REPORT_MODULE)
    ledger = importlib.import_module(LEDGER_MODULE)
    models = importlib.import_module(MODELS_MODULE)
    errors = importlib.import_module(ERRORS_MODULE)

    for name in OPERATIONS_NAMES:
        assert getattr(package, name) is getattr(operations, name)
    for name in REPORT_NAMES:
        assert getattr(package, name) is getattr(report, name)
    for name in LEDGER_NAMES:
        assert getattr(package, name) is getattr(ledger, name)
    for name in MODEL_NAMES:
        assert getattr(package, name) is getattr(models, name)
    for name in ERROR_NAMES:
        assert getattr(package, name) is getattr(errors, name)


def test_close_names_are_defined_once_at_their_home() -> None:
    """Moved close names are defined exactly once, at the definition site."""
    package = importlib.import_module(PACKAGE)
    operations = importlib.import_module(OPERATIONS_MODULE)
    report = importlib.import_module(REPORT_MODULE)
    ledger = importlib.import_module(LEDGER_MODULE)

    for name in OPERATIONS_NAMES:
        assert getattr(operations, name).__module__ == OPERATIONS_MODULE
        assert getattr(package, name).__module__ == OPERATIONS_MODULE
    for name in REPORT_NAMES:
        assert getattr(report, name).__module__ == REPORT_MODULE
        assert getattr(package, name).__module__ == REPORT_MODULE
    for name in LEDGER_NAMES:
        assert getattr(ledger, name).__module__ == LEDGER_MODULE
        assert getattr(package, name).__module__ == LEDGER_MODULE


def test_close_bodies_do_not_leak_into_package_init() -> None:
    """Definitions stay in child modules; the package only re-exports."""
    init_text = (CLOSE_DIR / "__init__.py").read_text(encoding="utf-8")
    operations_text = (CLOSE_DIR / "operations.py").read_text(encoding="utf-8")
    report_text = (CLOSE_DIR / "report.py").read_text(encoding="utf-8")
    ledger_text = (CLOSE_DIR / "ledger.py").read_text(encoding="utf-8")

    for name in OPERATIONS_NAMES:
        assert f"def {name}" in operations_text
        assert f"def {name}" not in init_text
        assert f"def {name}" not in report_text
        assert name in init_text
    for name in REPORT_NAMES:
        assert f"def {name}" in report_text
        assert f"def {name}" not in operations_text
        assert f"def {name}" not in init_text
    assert "class CloseStore" in ledger_text
    assert "class CloseStore" not in operations_text
    assert "from finjuice.pipeline.close import" not in operations_text
    assert "from finjuice.pipeline.close import" not in report_text
    assert "from finjuice.pipeline.close import" not in ledger_text


def test_same_close_revision_report_is_regenerated(tmp_path: Path) -> None:
    """The same frozen revision rebuilds an identical report."""
    store = CloseStore(tmp_path / "close")
    closed = importlib.import_module(OPERATIONS_MODULE).close_month(
        store, _snapshot(), occurred_at="2026-02-02T00:00:00+00:00"
    )
    operations = importlib.import_module(OPERATIONS_MODULE)
    first = operations.regenerate_close_report(store, "2026-01", 1)
    second = operations.regenerate_close_report(store, "2026-01", 1)
    report = importlib.import_module(REPORT_MODULE)
    computed = report.compute_close_report(closed.snapshot, close_revision=1)

    assert first == second == closed.report == computed
    assert first.net == "600"
    assert first.state == "closed"
    assert first.digest == closed.report.digest


def test_late_input_and_rule_change_do_not_overwrite_closed_month(tmp_path: Path) -> None:
    """Late rows or rule policy changes cannot silently replace a closed report."""
    operations = importlib.import_module(OPERATIONS_MODULE)
    store = CloseStore(tmp_path / "close")
    original = operations.close_month(store, _snapshot())
    late_rows = replace(
        _snapshot(),
        lines=(CloseLine(line_id="in1", amount="1000", category="income"),),
    )
    late_rules = replace(_snapshot(), rules_policy="rules:v2")

    with pytest.raises(CloseLockedError):
        operations.close_month(store, late_rows)
    with pytest.raises(CloseLockedError):
        operations.close_month(store, late_rules)

    regenerated = operations.regenerate_close_report(store, "2026-01", 1)
    current = store.current("2026-01")
    assert regenerated == original.report
    assert current is not None
    assert current.close_revision == 1
    assert current.report.net == "600"


def test_reopen_reclose_retry_and_restore_keep_history(tmp_path: Path) -> None:
    """Reopen, reclose, retry, and backup restore keep prior revisions and events."""
    operations = importlib.import_module(OPERATIONS_MODULE)
    report = importlib.import_module(REPORT_MODULE)
    live = CloseStore(tmp_path / "live")
    first = operations.close_month(live, _snapshot(), occurred_at="2026-02-02T00:00:00+00:00")
    operations.retry_close(live, _snapshot(), occurred_at="2026-02-02T01:00:00+00:00")
    operations.reopen_month(
        live, "2026-01", occurred_at="2026-02-03T00:00:00+00:00", reason="late_source"
    )
    second_input = replace(
        _snapshot(),
        dataset_revision=1,
        rules_policy="rules:v2",
        source_as_of="2026-02-10",
        lines=(
            CloseLine(line_id="in1", amount="1000", category="income"),
            CloseLine(line_id="out1", amount="-400", category="food"),
            CloseLine(line_id="out2", amount="-50", category="fee"),
        ),
        unconfirmed_item_ids=("xfer-1",),
    )
    second = operations.close_month(live, second_input, occurred_at="2026-02-11T00:00:00+00:00")

    assert first.close_revision == 1
    assert second.close_revision == 2
    assert operations.regenerate_close_report(live, "2026-01", 1) == first.report
    assert operations.regenerate_close_report(live, "2026-01", 2) == second.report
    diff = report.explain_close_diff(first.report, second.report)
    assert "dataset_revision_changed" in diff.reasons
    assert "rules_policy_changed" in diff.reasons
    assert "source_as_of_changed" in diff.reasons
    assert "totals_changed" in diff.reasons
    assert "unconfirmed_changed" in diff.reasons

    backup_root = tmp_path / "backup"
    operations.backup_close_ledger(live, backup_root)
    restored = CloseStore(tmp_path / "restored")
    history = operations.restore_close_ledger(
        backup_root, restored, occurred_at="2026-02-12T00:00:00+00:00"
    )
    actions = [event.action for event in history]
    assert actions == ["closed", "retried", "reopened", "reclosed", "restored"]
    live_current = live.current("2026-01")
    assert operations.regenerate_close_report(restored, "2026-01", 1) == first.report
    assert operations.regenerate_close_report(restored, "2026-01", 2) == second.report
    assert live_current is not None
    assert live_current.close_revision == 2


def test_unconfirmed_items_are_shown_on_close_status(tmp_path: Path) -> None:
    """A close with unconfirmed items is labeled, not treated as a clean close."""
    operations = importlib.import_module(OPERATIONS_MODULE)
    store = CloseStore(tmp_path / "close")
    snapshot = replace(_snapshot(), unconfirmed_item_ids=("pair-9", "xfer-1"))
    closed = operations.close_month(store, snapshot)
    status = operations.close_status(store, "2026-01")

    assert closed.report.state == "closed_with_unconfirmed"
    assert status.result_state == "closed_with_unconfirmed"
    assert status.has_unconfirmed is True
    assert status.unconfirmed_item_ids == ("pair-9", "xfer-1")
    assert status.unconfirmed_label == "unconfirmed:2"
    assert status.period_state == "closed"
    clean = operations.close_status(store, "2026-02")
    assert clean.period_state == "open"
    assert clean.has_unconfirmed is False
    assert clean.unconfirmed_label == "none"


def test_close_rejects_invalid_period_and_parent_store_path(tmp_path: Path) -> None:
    """Period names and store roots are validated before any write."""
    ledger = importlib.import_module(LEDGER_MODULE)
    with pytest.raises(ClosePathError):
        ledger.validate_period("../01")
    with pytest.raises(ClosePathError):
        CloseStore(tmp_path / ".." / "escaped")
    with pytest.raises(CloseStateError):
        importlib.import_module(OPERATIONS_MODULE).reopen_month(
            CloseStore(tmp_path / "empty"), "2026-01"
        )
