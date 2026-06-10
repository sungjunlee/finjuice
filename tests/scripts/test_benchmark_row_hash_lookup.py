"""Tests for the row_hash lookup benchmark harness."""

import json

from scripts import benchmark_row_hash_lookup


def test_lookup_targets_match_synthetic_partition_hashes(tmp_path):
    """Generated targets should resolve against generated synthetic partitions."""
    scenario = benchmark_row_hash_lookup.BenchmarkScenario(
        "tiny",
        partitions=3,
        rows_per_partition=4,
    )
    transactions_dir, metadata = benchmark_row_hash_lookup.generate_csv_partitions(
        tmp_path,
        scenario,
        seed=7,
    )

    targets = {
        target.name: target
        for target in benchmark_row_hash_lookup.lookup_targets(scenario)
        if target.expected_found
    }

    first = benchmark_row_hash_lookup.lookup_transaction(
        transactions_dir,
        targets["first_partition"].row_hash,
    )
    middle = benchmark_row_hash_lookup.lookup_transaction(
        transactions_dir,
        targets["middle_partition"].row_hash,
    )
    last = benchmark_row_hash_lookup.lookup_transaction(
        transactions_dir,
        targets["last_partition"].row_hash,
    )

    assert metadata["distinct_months"] == 3
    assert first["partition"] == "2024-01"
    assert middle["partition"] == "2024-02"
    assert last["partition"] == "2024-03"


def test_build_row_hash_partition_map_uses_synthetic_partitions(tmp_path):
    """The ephemeral map should index every generated synthetic row_hash."""
    scenario = benchmark_row_hash_lookup.BenchmarkScenario(
        "tiny",
        partitions=2,
        rows_per_partition=3,
    )
    transactions_dir, _ = benchmark_row_hash_lookup.generate_csv_partitions(
        tmp_path,
        scenario,
        seed=11,
    )

    row_hash_map = benchmark_row_hash_lookup.build_row_hash_partition_map(transactions_dir)

    assert len(row_hash_map) == 6
    assert row_hash_map[benchmark_row_hash_lookup.synthetic_row_hash(0, 0)] == "2024-01"
    assert row_hash_map[benchmark_row_hash_lookup.synthetic_row_hash(1, 2)] == "2024-02"


def test_run_benchmark_suite_writes_json_artifact(tmp_path, monkeypatch):
    """Benchmark artifacts should retain scenario names, metadata, and operation results."""
    scenario = benchmark_row_hash_lookup.BenchmarkScenario(
        "tiny",
        partitions=2,
        rows_per_partition=3,
    )
    output_path = tmp_path / "row-hash-results.json"

    monkeypatch.setattr(
        benchmark_row_hash_lookup,
        "collect_runtime_versions",
        lambda: {"python": "3.13.11", "polars": "1.35.2", "duckdb": "not-installed"},
    )

    results = benchmark_row_hash_lookup.run_benchmark_suite(
        [scenario],
        warm_iterations=1,
        output_path=output_path,
        seed=19,
        probe_count=8,
    )

    assert output_path.exists()
    assert set(results["benchmarks"]) == {"tiny"}
    assert results["metadata"]["probe_count"] == 8
    assert "Synthetic partitions only" in results["metadata"]["data_policy"]

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    operations = saved["benchmarks"]["tiny"]["operations"]
    assert saved["benchmarks"]["tiny"]["dataset"]["total_rows"] == 6
    assert operations["find_transaction_by_hash"]["targets"]["last_partition"]["measurement"][
        "last_warm_result"
    ]["found"]
    assert (
        operations["manual_edit_round_trip"]["measurement"]["last_warm_result"]["partition_rows"]
        == 3
    )
    assert operations["ephemeral_row_hash_map"]["probe"]["last_warm_result"]["probe_count"] == 8
