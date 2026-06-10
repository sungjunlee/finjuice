"""Performance metrics module for E2E testing.

This module provides utilities to measure and report pipeline performance metrics
including execution time, throughput, coverage, and resource usage.
"""

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import polars as pl

from finjuice.pipeline.storage import csv_partition

# Reviewed perf baseline — the single source of truth for the E2E perf budget.
_PERF_BASELINE_PATH = Path(__file__).parent / "perf_baseline.json"


def load_performance_budget() -> float:
    """Return the documented wall-clock budget for the synthetic E2E pipeline.

    Sourced from ``tests/e2e/perf_baseline.json`` so the perf gate and the E2E
    report compare against a reviewed baseline rather than an arbitrary high cap.
    """
    data = json.loads(_PERF_BASELINE_PATH.read_text(encoding="utf-8"))
    return float(data["synthetic_pipeline"]["total_budget_seconds"])


@dataclass
class PhaseMetrics:
    """Metrics for a single pipeline phase."""

    name: str
    execution_time: float  # seconds
    success: bool
    error_message: Optional[str] = None


@dataclass
class PipelineMetrics:
    """Comprehensive pipeline performance metrics."""

    # Execution time metrics
    phases: List[PhaseMetrics] = field(default_factory=list)
    total_execution_time: float = 0.0  # seconds

    # Throughput metrics
    total_transactions: int = 0
    transactions_per_second: float = 0.0
    files_processed: int = 0
    files_per_second: float = 0.0

    # Coverage metrics
    tagged_count: int = 0
    tag_coverage_pct: float = 0.0
    transfer_pairs_found: int = 0
    transfer_candidates: int = 0  # Total transfer-type candidates
    transfer_paired_transactions: int = 0  # is_transfer=1 transaction count
    transfer_detection_rate: float = 0.0

    # Storage metrics
    storage_size_bytes: int = 0
    storage_size_mb: float = 0.0

    # Rule effectiveness
    rule_hit_breakdown: Dict[str, int] = field(default_factory=dict)
    untagged_merchants: List[str] = field(default_factory=list)

    def add_phase(self, phase: PhaseMetrics) -> None:
        """Add a phase metric to the collection."""
        self.phases.append(phase)
        self.total_execution_time += phase.execution_time

    def calculate_throughput(self) -> None:
        """Calculate throughput metrics based on total execution time."""
        if self.total_execution_time > 0:
            self.transactions_per_second = self.total_transactions / self.total_execution_time
            self.files_per_second = self.files_processed / self.total_execution_time
        else:
            self.transactions_per_second = 0.0
            self.files_per_second = 0.0

    def calculate_coverage(self) -> None:
        """Calculate coverage percentages."""
        if self.total_transactions > 0:
            self.tag_coverage_pct = (self.tagged_count / self.total_transactions) * 100
        else:
            self.tag_coverage_pct = 0.0

        if self.transfer_candidates > 0:
            self.transfer_detection_rate = (
                self.transfer_paired_transactions / self.transfer_candidates
            ) * 100
        else:
            self.transfer_detection_rate = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for JSON serialization."""
        return {
            "execution_time": {
                "phases": [
                    {
                        "name": p.name,
                        "seconds": round(p.execution_time, 2),
                        "success": p.success,
                        "error": p.error_message,
                    }
                    for p in self.phases
                ],
                "total_seconds": round(self.total_execution_time, 2),
                "total_minutes": round(self.total_execution_time / 60, 2),
            },
            "throughput": {
                "transactions_per_second": round(self.transactions_per_second, 2),
                "files_per_second": round(self.files_per_second, 4),
            },
            "coverage": {
                "total_transactions": self.total_transactions,
                "tagged_count": self.tagged_count,
                "tag_coverage_pct": round(self.tag_coverage_pct, 2),
                "transfer_pairs_found": self.transfer_pairs_found,
                "transfer_candidates": self.transfer_candidates,
                "transfer_paired_transactions": self.transfer_paired_transactions,
                "transfer_detection_rate_pct": round(self.transfer_detection_rate, 2),
            },
            "storage": {
                "size_bytes": self.storage_size_bytes,
                "size_mb": round(self.storage_size_mb, 2),
            },
            "rule_effectiveness": {
                "rule_hit_breakdown": self.rule_hit_breakdown,
                "top_untagged_merchants": self.untagged_merchants[:10],
            },
        }


class MetricsCollector:
    """Collector for pipeline performance metrics."""

    def __init__(self, csv_base_dir: Path):
        """Initialize metrics collector.

        Args:
            csv_base_dir: Path to CSV partition base directory
        """
        self.csv_base_dir = csv_base_dir
        self.metrics = PipelineMetrics()
        self._phase_start_time: Optional[float] = None
        self._current_phase: Optional[str] = None

    def start_phase(self, phase_name: str) -> None:
        """Start timing a pipeline phase.

        Args:
            phase_name: Name of the phase (e.g., "ingest", "tag", "export")
        """
        self._current_phase = phase_name
        self._phase_start_time = time.time()

    def end_phase(self, success: bool = True, error_message: Optional[str] = None) -> None:
        """End timing the current phase.

        Args:
            success: Whether the phase completed successfully
            error_message: Error message if phase failed
        """
        if self._phase_start_time is None or self._current_phase is None:
            return

        execution_time = time.time() - self._phase_start_time
        phase_metric = PhaseMetrics(
            name=self._current_phase,
            execution_time=execution_time,
            success=success,
            error_message=error_message,
        )
        self.metrics.add_phase(phase_metric)

        self._phase_start_time = None
        self._current_phase = None

    def collect_storage_metrics(self) -> None:
        """Collect metrics from CSV partitions."""
        if not self.csv_base_dir.exists():
            return

        df = csv_partition.get_all_transactions(self.csv_base_dir)
        self.metrics.total_transactions = len(df)
        if df.is_empty():
            self.metrics.calculate_coverage()
            return

        tags = df["tags_final"].to_list()
        self.metrics.tagged_count = sum(1 for tag in tags if _has_tags(tag))

        paired_transfers = df.filter(
            (pl.col("is_transfer") == 1) & pl.col("transfer_group_id").is_not_null()
        )
        self.metrics.transfer_pairs_found = paired_transfers["transfer_group_id"].n_unique()
        self.metrics.transfer_paired_transactions = len(df.filter(pl.col("is_transfer") == 1))
        self.metrics.transfer_candidates = len(df.filter(pl.col("type_norm") == "transfer"))

        missing_tags = pl.col("tags_final").map_elements(
            lambda value: not _has_tags(value),
            return_dtype=pl.Boolean,
        )
        untagged = df.filter((pl.col("merchant_raw").is_not_null()) & missing_tags)
        if not untagged.is_empty():
            counts = (
                untagged.group_by("merchant_raw")
                .len(name="count")
                .sort(["count", "merchant_raw"], descending=[True, False])
                .head(10)
            )
            self.metrics.untagged_merchants = counts["merchant_raw"].to_list()

        self.metrics.storage_size_bytes = sum(
            path.stat().st_size for path in self.csv_base_dir.glob("*/*/transactions.csv")
        )
        self.metrics.storage_size_mb = self.metrics.storage_size_bytes / (1024 * 1024)
        self.metrics.calculate_coverage()

    def collect_file_metrics(self, imports_dir: Path) -> None:
        """Collect metrics about processed files.

        Args:
            imports_dir: Path to imports directory
        """
        if imports_dir.exists():
            xlsx_files = list(imports_dir.glob("*.xlsx"))
            self.metrics.files_processed = len(xlsx_files)

    def finalize(self) -> PipelineMetrics:
        """Finalize and return collected metrics.

        Returns:
            Complete pipeline metrics
        """
        self.metrics.calculate_throughput()
        return self.metrics

    def save_report(self, output_path: Path) -> None:
        """Save metrics report as JSON.

        Args:
            output_path: Path to output JSON file
        """
        metrics_dict = self.metrics.to_dict()

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(metrics_dict, f, indent=2, ensure_ascii=False)

    def print_summary(self) -> None:
        """Print a summary of metrics to console."""
        m = self.metrics

        print("\n" + "=" * 60)
        print("PIPELINE PERFORMANCE METRICS SUMMARY")
        print("=" * 60)

        print(
            f"\n⏱️  Execution Time: {m.total_execution_time:.2f}s "
            f"({m.total_execution_time / 60:.2f} min)"
        )

        print("\n📊 Phase Breakdown:")
        for phase in m.phases:
            status = "✅" if phase.success else "❌"
            print(f"  {status} {phase.name:12s}: {phase.execution_time:6.2f}s")
            if phase.error_message:
                print(f"      Error: {phase.error_message}")

        print("\n🔢 Throughput:")
        print(f"  Transactions/sec: {m.transactions_per_second:.2f}")
        print(f"  Files/sec:        {m.files_per_second:.4f}")

        print("\n📈 Coverage:")
        print(f"  Total transactions: {m.total_transactions}")
        print(f"  Tagged:            {m.tagged_count} ({m.tag_coverage_pct:.1f}%)")
        print(
            f"  Transfer pairs:    {m.transfer_pairs_found}/{m.transfer_candidates} "
            f"({m.transfer_detection_rate:.1f}%)"
        )

        print("\n💾 CSV Storage:")
        print(f"  Size: {m.storage_size_mb:.2f} MB")

        if m.untagged_merchants:
            print("\n🏷️  Top Untagged Merchants:")
            for merchant in m.untagged_merchants[:5]:
                print(f"  - {merchant}")

        print("\n" + "=" * 60 + "\n")


def _has_tags(tags_value: object) -> bool:
    """Return True when tags_final contains at least one visible tag."""
    if tags_value is None:
        return False
    if isinstance(tags_value, list):
        return len(tags_value) > 0
    if isinstance(tags_value, str):
        return tags_value.strip() not in ("", "[]")
    return False
