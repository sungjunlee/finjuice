"""Structure checks for the split budget compute implementation."""

from pathlib import Path

from finjuice.pipeline import budget_compute, budget_edit_helpers

PIPELINE_DIR = Path("src/finjuice/pipeline")


def test_budget_edit_helpers_live_in_helper_module() -> None:
    """YAML edit helpers should not live in the compute entrypoint."""
    compute_text = (PIPELINE_DIR / "budget_compute.py").read_text(encoding="utf-8")
    helpers_text = (PIPELINE_DIR / "budget_edit_helpers.py").read_text(encoding="utf-8")

    assert "def compute_budget_edit" in compute_text
    assert "def compute_budget_status" in compute_text
    assert "def compute_budget_validate" in compute_text
    assert "def _apply_budget_update" not in compute_text
    assert "def _ensure_mapping" not in compute_text
    assert "def _bootstrap_budget_document" not in compute_text
    assert "def _parse_budget_int" not in compute_text
    assert "def _serialize_monthly_budget" not in compute_text
    assert "def _apply_budget_update" in helpers_text
    assert "def _ensure_mapping" in helpers_text
    assert "def _bootstrap_budget_document" in helpers_text
    assert "def _parse_budget_int" in helpers_text
    assert "def _serialize_monthly_budget" in helpers_text


def test_budget_edit_helpers_reexport_from_entrypoint() -> None:
    """Existing budget_compute imports should keep resolving to the edit helpers."""
    compute_text = (PIPELINE_DIR / "budget_compute.py").read_text(encoding="utf-8")

    assert "def compute_budget_edit" in compute_text
    assert "BUDGET_EDIT_UPDATE_HINT" in compute_text
    assert "_apply_budget_update" in compute_text
    assert "_ensure_mapping" in compute_text
    assert "_bootstrap_budget_document" in compute_text
    assert "_parse_budget_int" in compute_text
    assert "_serialize_monthly_budget" in compute_text
    assert "_RESERVED_BUDGET_EDIT_KEYS" in compute_text
    assert "BudgetEditConfirm" in compute_text

    assert budget_compute.BUDGET_EDIT_UPDATE_HINT is budget_edit_helpers.BUDGET_EDIT_UPDATE_HINT
    assert budget_compute.BudgetEditConfirm is budget_edit_helpers.BudgetEditConfirm
    assert (
        budget_compute._RESERVED_BUDGET_EDIT_KEYS is budget_edit_helpers._RESERVED_BUDGET_EDIT_KEYS
    )
    assert budget_compute._apply_budget_update is budget_edit_helpers._apply_budget_update
    assert budget_compute._ensure_mapping is budget_edit_helpers._ensure_mapping
    assert (
        budget_compute._bootstrap_budget_document is budget_edit_helpers._bootstrap_budget_document
    )
    assert budget_compute._parse_budget_int is budget_edit_helpers._parse_budget_int
    assert budget_compute._serialize_monthly_budget is budget_edit_helpers._serialize_monthly_budget
    assert callable(budget_compute.compute_budget_edit)
    assert callable(budget_compute.compute_budget_status)
    assert callable(budget_compute.compute_budget_validate)
