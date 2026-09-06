"""Identity checks for the split status transaction-metrics helpers."""

from pathlib import Path

from finjuice.pipeline.cli.commands.status import compute, compute_metrics

STATUS_DIR = Path("src/finjuice/pipeline/cli/commands/status")


def test_status_metrics_helpers_live_in_helper_module() -> None:
    """Transaction-metric aggregation should not live in compute.py."""
    compute_text = (STATUS_DIR / "compute.py").read_text(encoding="utf-8")
    metrics_text = (STATUS_DIR / "compute_metrics.py").read_text(encoding="utf-8")

    assert "def collect_status_facts" in compute_text
    assert "def _load_status_report_filters" in compute_text
    assert "def _read_last_import" in compute_text
    assert "class StatusCommandError" in compute_text
    assert "def _collect_transaction_metrics" not in compute_text
    assert "class _TransactionMetrics" not in compute_text
    assert "def _collect_transaction_metrics" in metrics_text
    assert "class _TransactionMetrics" in metrics_text


def test_status_metrics_helpers_reexport_from_compute() -> None:
    """Existing compute.py imports should keep resolving to the metrics helpers."""
    compute_text = (STATUS_DIR / "compute.py").read_text(encoding="utf-8")

    assert "def collect_status_facts" in compute_text
    assert "_collect_transaction_metrics" in compute_text
    assert "_TransactionMetrics" in compute_text
    assert compute._collect_transaction_metrics is compute_metrics._collect_transaction_metrics
    assert compute._TransactionMetrics is compute_metrics._TransactionMetrics
    assert callable(compute.collect_status_facts)
    assert callable(compute.StatusCommandError)
