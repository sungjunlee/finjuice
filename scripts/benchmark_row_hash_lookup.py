"""Benchmark row_hash lookup and edit costs on synthetic CSV partitions.

This harness is intentionally read/write isolated: it creates temporary synthetic
transaction partitions and never reads a user's data directory. It compares the
current full-partition scan path with an ephemeral in-memory row_hash map so the
project can decide whether a persisted manifest/cache is warranted.

Usage:
    uv run python scripts/benchmark_row_hash_lookup.py \
        --scenario personal_6k:24:250 \
        --scenario power_60k:60:1000 \
        --scenario stress_120k:120:1000 \
        --iterations 3 \
        --output docs/benchmarks/row-hash-lookup-results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import platform
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import polars as pl

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = REPO_ROOT / "scripts"
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(SCRIPTS_DIR))

from benchmark_duckdb import (  # noqa: E402
    BenchmarkScenario,
    calculate_statistics,
    collect_runtime_versions,
    generate_csv_partitions,
    parse_scenario,
)

from finjuice.pipeline.storage.csv_transactions import (  # noqa: E402
    find_transaction_by_hash,
    write_month,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_SEED = 597
DEFAULT_PROBE_COUNT = 10_000
DEFAULT_SCENARIOS = [
    BenchmarkScenario("personal_6k", partitions=24, rows_per_partition=250),
    BenchmarkScenario("power_60k", partitions=60, rows_per_partition=1000),
    BenchmarkScenario("stress_120k", partitions=120, rows_per_partition=1000),
]


@dataclass(frozen=True)
class LookupTarget:
    """One deterministic row_hash target inside or outside a generated dataset."""

    name: str
    row_hash: str
    expected_found: bool
    description: str


def synthetic_row_hash(month_offset: int, row_index: int) -> str:
    """Return the row_hash format emitted by scripts.benchmark_duckdb."""
    return f"{month_offset:08x}{row_index:08x}"


def lookup_targets(scenario: BenchmarkScenario) -> list[LookupTarget]:
    """Return first/middle/last/missing lookup targets for a scenario."""
    middle_partition = scenario.partitions // 2
    middle_row = scenario.rows_per_partition // 2

    return [
        LookupTarget(
            name="first_partition",
            row_hash=synthetic_row_hash(0, 0),
            expected_found=True,
            description="Best-case hit in the first scanned partition.",
        ),
        LookupTarget(
            name="middle_partition",
            row_hash=synthetic_row_hash(middle_partition, middle_row),
            expected_found=True,
            description="Representative hit after scanning about half the partitions.",
        ),
        LookupTarget(
            name="last_partition",
            row_hash=synthetic_row_hash(
                scenario.partitions - 1,
                scenario.rows_per_partition - 1,
            ),
            expected_found=True,
            description="Worst-case hit in the final scanned partition.",
        ),
        LookupTarget(
            name="missing_hash",
            row_hash="f" * 16,
            expected_found=False,
            description="Worst-case miss after scanning all partitions.",
        ),
    ]


def measure_once(run_once: Callable[[], dict[str, Any]]) -> tuple[dict[str, Any], float]:
    """Measure one callable execution."""
    start = time.perf_counter()
    result = run_once()
    elapsed = time.perf_counter() - start
    return result, elapsed


def benchmark_callable(
    run_once: Callable[[], dict[str, Any]],
    *,
    warm_iterations: int,
) -> dict[str, Any]:
    """Benchmark a callable with one cold execution and repeated warm executions."""
    cold_result, cold_seconds = measure_once(run_once)

    warm_timings: list[float] = []
    warm_result = cold_result
    for _ in range(warm_iterations):
        warm_result, elapsed = measure_once(run_once)
        warm_timings.append(elapsed)

    return {
        "cold_seconds": cold_seconds,
        "warm": calculate_statistics(warm_timings),
        "cold_result": cold_result,
        "last_warm_result": warm_result,
    }


def lookup_transaction(base_dir: Path, row_hash: str) -> dict[str, Any]:
    """Run the current production lookup helper and summarize the result."""
    try:
        partition_df, year, month = find_transaction_by_hash(base_dir, row_hash)
    except FileNotFoundError:
        return {"found": False, "row_hash": row_hash}

    return {
        "found": True,
        "row_hash": row_hash,
        "partition": f"{year:04d}-{month:02d}",
        "partition_rows": partition_df.height,
    }


def edit_transaction_by_hash(base_dir: Path, row_hash: str, edit_number: int) -> dict[str, Any]:
    """Simulate the storage portion of a manual edit by row_hash."""
    partition_df, year, month = find_transaction_by_hash(base_dir, row_hash)
    target_row = partition_df.filter(pl.col("row_hash") == row_hash).row(0, named=True)

    updated_row = dict(target_row)
    manual_tag = f"lookup-benchmark-{edit_number}"
    updated_row["tags_manual"] = [manual_tag]
    updated_row["tags_final"] = [manual_tag]
    updated_row["confidence"] = 1.0
    updated_row["needs_review"] = 0

    updated_partition_df = pl.concat(
        [
            partition_df.filter(pl.col("row_hash") != row_hash),
            pl.DataFrame([updated_row]),
        ],
        how="diagonal_relaxed",
    )
    write_result = write_month(base_dir, updated_partition_df, year, month)

    return {
        "row_hash": row_hash,
        "partition": f"{year:04d}-{month:02d}",
        "partition_rows": int(write_result["row_count"]),
        "file_size_bytes": int(write_result["file_size_bytes"]),
    }


def iter_partition_paths(base_dir: Path) -> list[Path]:
    """Return transaction CSV partitions in the same sorted order as lookup scans."""
    partition_paths: list[Path] = []
    for year_dir in sorted(base_dir.iterdir()):
        if not year_dir.is_dir() or not year_dir.name.isdigit():
            continue
        for month_dir in sorted(year_dir.iterdir()):
            if not month_dir.is_dir() or not month_dir.name.isdigit():
                continue
            partition_path = month_dir / "transactions.csv"
            if partition_path.exists():
                partition_paths.append(partition_path)
    return partition_paths


def build_row_hash_partition_map(base_dir: Path) -> dict[str, str]:
    """Build an ephemeral row_hash -> YYYY-MM map by scanning synthetic partitions."""
    row_hash_to_partition: dict[str, str] = {}
    for partition_path in iter_partition_paths(base_dir):
        month = partition_path.parent.name
        year = partition_path.parent.parent.name
        partition_key = f"{year}-{month}"

        hashes = (
            pl.scan_csv(
                partition_path,
                schema_overrides={"row_hash": pl.Utf8},
                null_values=["", "NA", "NULL"],
            )
            .select("row_hash")
            .collect()
            .get_column("row_hash")
        )
        for row_hash in hashes:
            row_hash_to_partition[str(row_hash)] = partition_key

    return row_hash_to_partition


def summarize_row_hash_partition_map(base_dir: Path) -> dict[str, Any]:
    """Build an ephemeral lookup map and return its size."""
    row_hash_map = build_row_hash_partition_map(base_dir)
    return {
        "entries": len(row_hash_map),
        "partitions": len(set(row_hash_map.values())),
    }


def probe_row_hash_partition_map(
    row_hash_map: dict[str, str],
    row_hashes: list[str],
    *,
    probe_count: int,
) -> dict[str, Any]:
    """Probe a prebuilt map repeatedly so dict lookup cost is measurable."""
    found = 0
    for index in range(probe_count):
        row_hash = row_hashes[index % len(row_hashes)]
        if row_hash in row_hash_map:
            found += 1

    return {
        "probe_count": probe_count,
        "found": found,
        "missing": probe_count - found,
    }


def run_scenario(
    scenario: BenchmarkScenario,
    *,
    warm_iterations: int,
    seed: int,
    probe_count: int,
) -> dict[str, Any]:
    """Run row_hash lookup benchmarks for one synthetic dataset scenario."""
    logger.info("%s", "=" * 72)
    logger.info("Scenario %s (%s rows)", scenario.name, f"{scenario.total_rows:,}")
    logger.info("%s", "=" * 72)

    with tempfile.TemporaryDirectory() as tmpdir:
        data_root = Path(tmpdir)
        transactions_dir, dataset_metadata = generate_csv_partitions(
            data_root,
            scenario,
            seed=seed,
        )

        targets = lookup_targets(scenario)
        lookup_results = {
            target.name: {
                "target": {
                    "row_hash": target.row_hash,
                    "expected_found": target.expected_found,
                    "description": target.description,
                },
                "measurement": benchmark_callable(
                    lambda target=target: lookup_transaction(transactions_dir, target.row_hash),
                    warm_iterations=warm_iterations,
                ),
            }
            for target in targets
        }

        edit_target = targets[2]
        edit_counter = 0

        def edit_once() -> dict[str, Any]:
            nonlocal edit_counter
            edit_counter += 1
            return edit_transaction_by_hash(transactions_dir, edit_target.row_hash, edit_counter)

        map_build = benchmark_callable(
            lambda: summarize_row_hash_partition_map(transactions_dir),
            warm_iterations=warm_iterations,
        )
        row_hash_map = build_row_hash_partition_map(transactions_dir)
        probe_hashes = [target.row_hash for target in targets]
        map_probe = benchmark_callable(
            lambda: probe_row_hash_partition_map(
                row_hash_map,
                probe_hashes,
                probe_count=probe_count,
            ),
            warm_iterations=warm_iterations,
        )
        map_probe["warm"]["mean_per_lookup_seconds"] = (
            map_probe["warm"]["mean"] / probe_count if probe_count else 0.0
        )

        operations = {
            "find_transaction_by_hash": {
                "measured_path": (
                    "csv_transactions.find_transaction_by_hash(); scans sorted "
                    "YYYY/MM partitions and loads full partition DataFrames."
                ),
                "targets": lookup_results,
            },
            "manual_edit_round_trip": {
                "measured_path": (
                    "find_transaction_by_hash() plus rewriting the matching monthly "
                    "partition with write_month()."
                ),
                "target": {
                    "row_hash": edit_target.row_hash,
                    "description": "Worst-case manual edit target in the final partition.",
                },
                "measurement": benchmark_callable(edit_once, warm_iterations=warm_iterations),
            },
            "ephemeral_row_hash_map": {
                "measured_path": (
                    "Experimental in-memory row_hash -> YYYY-MM map built from synthetic "
                    "partitions. This is not a production artifact."
                ),
                "build": map_build,
                "probe": map_probe,
            },
        }

    logger.info(
        "Scenario %s: last lookup warm p95 %.4fs, edit warm p95 %.4fs",
        scenario.name,
        operations["find_transaction_by_hash"]["targets"]["last_partition"]["measurement"]["warm"][
            "p95"
        ],
        operations["manual_edit_round_trip"]["measurement"]["warm"]["p95"],
    )

    return {
        "dataset": dataset_metadata,
        "operations": operations,
    }


def run_benchmark_suite(
    scenarios: list[BenchmarkScenario],
    *,
    warm_iterations: int,
    output_path: Path | None = None,
    seed: int = DEFAULT_SEED,
    probe_count: int = DEFAULT_PROBE_COUNT,
) -> dict[str, Any]:
    """Run all row_hash lookup benchmark scenarios."""
    results = {
        "metadata": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "runtime_versions": collect_runtime_versions(),
            "platform": platform.platform(),
            "warm_iterations": warm_iterations,
            "random_seed": seed,
            "probe_count": probe_count,
            "data_policy": (
                "Synthetic partitions only; the harness creates a TemporaryDirectory and "
                "does not read user transaction data."
            ),
            "measurement_model": {
                "cold": "First measured execution after synthetic dataset generation.",
                "warm": (
                    "Repeated executions in the same Python process with OS page cache effects."
                ),
            },
        },
        "benchmarks": {},
    }

    for scenario in scenarios:
        results["benchmarks"][scenario.name] = run_scenario(
            scenario,
            warm_iterations=warm_iterations,
            seed=seed,
            probe_count=probe_count,
        )

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as handle:
            json.dump(results, handle, indent=2, ensure_ascii=False)
        logger.info("Saved benchmark results")

    return results


def build_parser() -> argparse.ArgumentParser:
    """Build CLI parser."""
    parser = argparse.ArgumentParser(
        description="Benchmark row_hash lookup/edit performance on synthetic CSV partitions."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        type=parse_scenario,
        help=(
            "Benchmark scenario in NAME:PARTITIONS:ROWS format. Repeat to benchmark multiple sizes."
        ),
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of warm iterations after one cold run for each benchmark.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for deterministic synthetic data generation.",
    )
    parser.add_argument(
        "--probe-count",
        type=int,
        default=DEFAULT_PROBE_COUNT,
        help="Number of repeated dict probes against the ephemeral row_hash map.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to save JSON results.",
    )
    return parser


def main() -> None:
    """Main entry point for the benchmark script."""
    parser = build_parser()
    args = parser.parse_args()

    scenarios = args.scenario or DEFAULT_SCENARIOS
    output_path = Path(args.output) if args.output else None

    logger.info("%s", "=" * 72)
    logger.info("row_hash Lookup Benchmark")
    logger.info("Scenarios: %s", ", ".join(scenario.name for scenario in scenarios))
    logger.info("Warm iterations per operation: %s", args.iterations)
    logger.info("Random seed: %s", args.seed)
    logger.info("%s", "=" * 72)

    results = run_benchmark_suite(
        scenarios,
        warm_iterations=args.iterations,
        output_path=output_path,
        seed=args.seed,
        probe_count=args.probe_count,
    )

    logger.info("%s", "=" * 72)
    logger.info("Benchmark complete")
    logger.info("%s", "=" * 72)
    for scenario_name, scenario_results in results["benchmarks"].items():
        operations = scenario_results["operations"]
        last_lookup = operations["find_transaction_by_hash"]["targets"]["last_partition"][
            "measurement"
        ]["warm"]
        missing_lookup = operations["find_transaction_by_hash"]["targets"]["missing_hash"][
            "measurement"
        ]["warm"]
        edit = operations["manual_edit_round_trip"]["measurement"]["warm"]
        logger.info(
            "Scenario %s: last p95=%.4fs, missing p95=%.4fs, edit p95=%.4fs",
            scenario_name,
            last_lookup["p95"],
            missing_lookup["p95"],
            edit["p95"],
        )


if __name__ == "__main__":
    main()
