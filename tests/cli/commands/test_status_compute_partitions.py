"""Identity checks for the split status partition-discovery helpers."""

from pathlib import Path

from finjuice.pipeline.cli.commands.status import compute, compute_partitions

STATUS_DIR = Path("src/finjuice/pipeline/cli/commands/status")


def test_status_partition_helpers_live_in_helper_module() -> None:
    """Partition discovery and path validation should not live in compute.py."""
    compute_text = (STATUS_DIR / "compute.py").read_text(encoding="utf-8")
    partitions_text = (STATUS_DIR / "compute_partitions.py").read_text(encoding="utf-8")

    assert "def collect_status_facts" in compute_text
    assert "def _collect_transaction_metrics" in compute_text
    assert "class StatusCommandError" in compute_text
    assert "def _transaction_partitions_or_raise" not in compute_text
    assert "def _validated_partitions" not in compute_text
    assert "def _transaction_partitions_or_raise" in partitions_text
    assert "def _validated_partitions" in partitions_text


def test_status_partition_helpers_reexport_from_compute() -> None:
    """Existing compute.py imports should keep resolving to the partition helpers."""
    compute_text = (STATUS_DIR / "compute.py").read_text(encoding="utf-8")

    assert "def collect_status_facts" in compute_text
    assert "_transaction_partitions_or_raise" in compute_text
    assert "_validated_partitions" in compute_text
    assert (
        compute._transaction_partitions_or_raise
        is compute_partitions._transaction_partitions_or_raise
    )
    assert compute._validated_partitions is compute_partitions._validated_partitions
    assert callable(compute.collect_status_facts)
    assert callable(compute.StatusCommandError)
