"""Structure checks for the split status compute implementation."""

from pathlib import Path

STATUS_DIR = Path("src/finjuice/pipeline/cli/commands/status")


def test_status_compute_helpers_live_in_helper_module() -> None:
    """Partition-read and tagging-metric helpers should not live in compute.py."""
    compute_text = (STATUS_DIR / "compute.py").read_text(encoding="utf-8")
    helpers_text = (STATUS_DIR / "compute_helpers.py").read_text(encoding="utf-8")

    assert "def collect_status_facts" in compute_text
    assert "def _collect_transaction_metrics" in compute_text
    assert "class StatusCommandError" in compute_text
    assert "def _normalize_status_partition_schema" not in compute_text
    assert "def _count_tagging_rows" not in compute_text
    assert "def _tags_empty_expr" not in compute_text
    assert "def _normalize_status_partition_schema" in helpers_text
    assert "def _count_tagging_rows" in helpers_text
    assert "def _tags_empty_expr" in helpers_text


def test_status_public_command_names_stay_on_entrypoint() -> None:
    """The stable status import path should keep public command names."""
    init_text = (STATUS_DIR / "__init__.py").read_text(encoding="utf-8")

    assert "def status(" in init_text
    assert '"status"' in init_text
    assert "collect_status_facts" in init_text
    assert "StatusOptions" in init_text
    assert "StatusFacts" in init_text
