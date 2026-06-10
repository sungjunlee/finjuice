"""Tests for the DuckDB benchmark harness."""

import csv
import json

from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS
from scripts import benchmark_duckdb


def test_generate_csv_partitions_creates_distinct_months(tmp_path):
    """The benchmark dataset must create one CSV partition per requested month."""
    scenario = benchmark_duckdb.BenchmarkScenario(
        "24_months",
        partitions=24,
        rows_per_partition=2,
    )

    transactions_dir, metadata = benchmark_duckdb.generate_csv_partitions(
        tmp_path,
        scenario,
        seed=7,
    )

    csv_files = sorted(transactions_dir.glob("*/*/transactions.csv"))
    month_dirs = {path.parent.relative_to(transactions_dir).as_posix() for path in csv_files}

    assert len(csv_files) == 24
    assert len(month_dirs) == 24
    assert metadata["distinct_months"] == 24
    assert metadata["schema_columns"] == len(CSV_COLUMNS)
    assert metadata["month_range"] == {"start": "2024-01", "end": "2025-12"}

    with csv_files[0].open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == CSV_COLUMNS
    assert len(rows[1]) == len(CSV_COLUMNS)
    assert rows[1][rows[0].index("category_final")] != ""


def test_run_benchmark_suite_writes_multi_scenario_artifact(tmp_path, monkeypatch):
    """Artifact output should retain scenario names and metadata."""
    scenarios = [
        benchmark_duckdb.BenchmarkScenario("6k_rows", partitions=24, rows_per_partition=250),
        benchmark_duckdb.BenchmarkScenario("120k_rows", partitions=24, rows_per_partition=5000),
    ]
    output_path = tmp_path / "duckdb-results.json"

    monkeypatch.setattr(
        benchmark_duckdb,
        "collect_runtime_versions",
        lambda: {"python": "3.13.11", "polars": "1.35.2", "duckdb": "1.4.2"},
    )

    def fake_run_scenario(
        scenario: benchmark_duckdb.BenchmarkScenario,
        *,
        warm_iterations: int,
        seed: int,
    ) -> dict[str, object]:
        return {
            "dataset": {
                "partitions": scenario.partitions,
                "rows_per_partition": scenario.rows_per_partition,
                "total_rows": scenario.total_rows,
                "schema_columns": len(CSV_COLUMNS),
                "schema_source": "finjuice.pipeline.storage.csv_schema.CSV_COLUMNS",
                "distinct_months": scenario.partitions,
                "month_range": {"start": "2024-01", "end": "2025-12"},
            },
            "operations": {
                "monthly_spend": {
                    "measured_paths": {
                        "polars": "Pure Polars CSV read + group_by aggregation.",
                        "duckdb_analytics": "DuckDBAnalytics.monthly_spend()",
                    },
                    "polars": {"cold_seconds": 0.1, "warm": {"mean": 0.09}, "result_rows": 24},
                    "duckdb_analytics": {
                        "cold_seconds": 0.2,
                        "warm": {"mean": 0.18},
                        "result_rows": 24,
                    },
                    "speedup": {"cold": 0.5, "warm_mean": 0.5},
                }
            },
            "received": {"warm_iterations": warm_iterations, "seed": seed},
        }

    monkeypatch.setattr(benchmark_duckdb, "run_scenario", fake_run_scenario)

    results = benchmark_duckdb.run_benchmark_suite(
        scenarios,
        warm_iterations=3,
        output_path=output_path,
        seed=42,
    )

    assert output_path.exists()
    assert set(results["benchmarks"]) == {"6k_rows", "120k_rows"}
    assert results["metadata"]["runtime_versions"]["duckdb"] == "1.4.2"
    assert results["metadata"]["warm_iterations"] == 3
    assert "cold" in results["metadata"]["measurement_model"]
    assert "warm" in results["metadata"]["measurement_model"]
    assert (
        results["benchmarks"]["6k_rows"]["operations"]["monthly_spend"]["measured_paths"][
            "duckdb_analytics"
        ]
        == "DuckDBAnalytics.monthly_spend()"
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert saved["benchmarks"]["120k_rows"]["dataset"]["total_rows"] == 120000
    assert saved["benchmarks"]["120k_rows"]["dataset"]["schema_columns"] == len(CSV_COLUMNS)
    assert saved["benchmarks"]["6k_rows"]["received"] == {"warm_iterations": 3, "seed": 42}


def test_calculate_statistics_uses_highest_sample_for_three_point_p95():
    """Three warm iterations should report the highest sample as p95."""
    stats = benchmark_duckdb.calculate_statistics([0.1, 0.2, 0.3])

    assert stats["p95"] == 0.3
