"""Boundary tests for the checkup compute/detector/rendering CLI split."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest

from finjuice.pipeline.checkup import (
    BudgetPostureSummary,
    CheckupBundle,
    NetWorthPostureSummary,
    NextAction,
    PipelineFreshnessSummary,
    ReviewPressureSummary,
)
from finjuice.pipeline.cli.commands.checkup.compute import CheckupFacts
from finjuice.pipeline.cli.commands.checkup.detector import detect_checkup_diagnoses
from finjuice.pipeline.cli.commands.checkup.rendering import serialize_checkup_payload

_CHECKUP_CLI_DIR = (
    Path(__file__).resolve().parents[3] / "src" / "finjuice" / "pipeline" / "cli" / "commands"
) / "checkup"
_RENDERING_PATH = _CHECKUP_CLI_DIR / "rendering.py"
_DETECTOR_PATH = _CHECKUP_CLI_DIR / "detector.py"

_REVIEW_REASON = "최신 월에 수동 검토 후보 1건이 남아 있습니다."


def _minimal_bundle(*, actionable: bool) -> CheckupBundle:
    """Build the smallest explicit-state bundle that exercises the detector."""
    return CheckupBundle(
        data_dir="/tmp/finjuice-data",
        actionable=actionable,
        warnings=["review backlog detected."] if actionable else [],
        next_actions=[
            NextAction(
                domain="review",
                priority="high",
                reason=_REVIEW_REASON,
                command="finjuice review --json",
            )
        ]
        if actionable
        else [],
        pipeline=PipelineFreshnessSummary(
            status="healthy",
            actionable=False,
            pending_import_status="clear",
            pending_import_files=0,
            failed_import_files=0,
            transaction_partitions=1,
            data_range=None,
            latest_transaction_date=None,
            days_since_latest=None,
            monthly_avg_income=None,
            monthly_avg_expense=None,
            savings_rate_3mo=None,
            active_filters=0,
        ),
        review=ReviewPressureSummary(
            status="needs_attention" if actionable else "healthy",
            actionable=actionable,
            month=None,
            total_candidates=1 if actionable else 0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
        ),
        budget=BudgetPostureSummary(
            status="healthy",
            actionable=False,
            month="2026-01",
            goals_file_exists=True,
            filters_applied=0,
            summary=None,
        ),
        networth=NetWorthPostureSummary(
            status="on_target",
            actionable=False,
            as_of=None,
            snapshot_months=0,
            assets_file_exists=False,
            asset_count=0,
            liability_count=0,
            total_assets=0.0,
            total_liabilities=0.0,
            net_worth=0.0,
            target=None,
            gap_to_target=None,
        ),
    )


@pytest.mark.parametrize(
    ("actionable", "expected_status"),
    [(True, "needs_attention"), (False, "ok")],
)
def test_detector_summary_status_is_needs_attention_iff_bundle_actionable(
    actionable: bool, expected_status: str
) -> None:
    """The detector derives summary.status purely from bundle.actionable."""
    facts = CheckupFacts(bundle=_minimal_bundle(actionable=actionable))

    diagnoses = detect_checkup_diagnoses(facts)

    assert diagnoses.summary["status"] == expected_status


def test_detector_summary_owns_every_decision_field() -> None:
    """All summary decision fields come from facts, decided only by the detector."""
    facts = CheckupFacts(bundle=_minimal_bundle(actionable=True))

    diagnoses = detect_checkup_diagnoses(facts)

    assert diagnoses.summary == {
        "status": "needs_attention",
        "priority": "high",
        "headline": _REVIEW_REASON,
        "recommended_command": "finjuice review --json",
        "domains_needing_attention": ["review"],
        "warning_count": 1,
        "next_action_count": 1,
    }


def test_rendering_serializes_without_collecting_or_deciding() -> None:
    """Rendering must never reference fact collection or diagnosis helpers."""
    source = _RENDERING_PATH.read_text(encoding="utf-8")

    assert "collect_checkup_bundle" not in source
    assert "collect_checkup_facts" not in source
    assert "detect_checkup_diagnoses" not in source


def test_rendered_payload_reflects_minimal_facts_and_diagnoses() -> None:
    """serialize_checkup_payload projects given stages without re-collecting."""
    facts = CheckupFacts(bundle=_minimal_bundle(actionable=False))
    diagnoses = detect_checkup_diagnoses(facts)

    payload = serialize_checkup_payload(facts, diagnoses)

    assert payload["summary"]["status"] == "ok"
    assert payload["actionable"] is False


def test_detector_module_never_collects_facts() -> None:
    """The detector must decide from given facts, never collect them itself."""
    tree = ast.parse(_DETECTOR_PATH.read_text(encoding="utf-8"))
    called: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            called.add(node.func.attr)

    assert "collect_checkup_facts" not in called
    assert "collect_checkup_bundle" not in called


def test_importing_boundary_modules_does_not_load_bundle_composer() -> None:
    """Importing the CLI boundary must stay lazy about the pipeline composer."""
    composer_module = "finjuice.pipeline.checkup.compose"
    sys.modules.pop(composer_module, None)
    importlib.import_module("finjuice.pipeline.cli.commands.checkup.compute")
    importlib.import_module("finjuice.pipeline.cli.commands.checkup.detector")
    importlib.import_module("finjuice.pipeline.cli.commands.checkup.rendering")

    assert composer_module not in sys.modules
