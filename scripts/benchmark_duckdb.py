"""Benchmark DuckDB vs Polars on synthetic CSV partition datasets.

This harness measures the current in-repo analytics paths for:
1. Monthly spend aggregation
2. Tag breakdown aggregation

The benchmark records:
- exact year/month partition coverage
- cold vs warm execution times
- runtime versions (Python, Polars, DuckDB)

Usage:
    # Single scenario (backward compatible)
    uv run --extra analytics python scripts/benchmark_duckdb.py \
        --partitions 24 --rows-per-partition 250 --iterations 3

    # Multi-scenario artifact (recommended for docs)
    uv run --extra analytics python scripts/benchmark_duckdb.py \
        --scenario 6k_rows:24:250 \
        --scenario 120k_rows:24:5000 \
        --iterations 3 \
        --output docs/benchmarks/duckdb-results.json
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import math
import platform
import random
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Callable, ContextManager, Iterator

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)
logging.getLogger("finjuice.pipeline.analytics.duckdb_layer").setLevel(logging.WARNING)

DEFAULT_SEED = 42
DEFAULT_START_YEAR = 2024
DEFAULT_START_MONTH = 1


@dataclass(frozen=True)
class BenchmarkScenario:
    """Benchmark dataset definition."""

    name: str
    partitions: int
    rows_per_partition: int

    @property
    def total_rows(self) -> int:
        return self.partitions * self.rows_per_partition


def calculate_statistics(timings: list[float]) -> dict[str, float]:
    """Calculate statistical metrics from timing results."""
    if not timings:
        return {
            "mean": 0.0,
            "median": 0.0,
            "min": 0.0,
            "max": 0.0,
            "p95": 0.0,
            "std_dev": 0.0,
        }

    sorted_timings = sorted(timings)
    p95_index = min(len(sorted_timings) - 1, max(0, math.ceil(len(sorted_timings) * 0.95) - 1))

    return {
        "mean": mean(timings),
        "median": median(timings),
        "min": min(timings),
        "max": max(timings),
        "p95": sorted_timings[p95_index],
        "std_dev": stdev(timings) if len(timings) > 1 else 0.0,
    }


def calculate_speedup(baseline_seconds: float, candidate_seconds: float) -> float:
    """Return baseline/candidate ratio rounded for reporting."""
    if candidate_seconds <= 0:
        return 0.0
    return round(baseline_seconds / candidate_seconds, 2)


def month_for_offset(start_year: int, start_month: int, offset: int) -> tuple[int, int]:
    """Return a distinct YYYY/MM pair for a zero-based month offset."""
    absolute_month = (start_month - 1) + offset
    year = start_year + absolute_month // 12
    month = (absolute_month % 12) + 1
    return year, month


def month_key(year: int, month: int) -> str:
    """Format a YYYY-MM partition key."""
    return f"{year:04d}-{month:02d}"


def parse_scenario(raw_value: str) -> BenchmarkScenario:
    """Parse NAME:PARTITIONS:ROWS into a benchmark scenario."""
    parts = raw_value.split(":")
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            f"Invalid scenario {raw_value!r}. Expected NAME:PARTITIONS:ROWS."
        )

    name, partitions_raw, rows_raw = parts
    try:
        partitions = int(partitions_raw)
        rows_per_partition = int(rows_raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid scenario {raw_value!r}. PARTITIONS and ROWS must be integers."
        ) from exc

    if not name:
        raise argparse.ArgumentTypeError("Scenario name must not be empty.")
    if partitions <= 0 or rows_per_partition <= 0:
        raise argparse.ArgumentTypeError("Scenario partitions and rows must be positive integers.")

    return BenchmarkScenario(
        name=name,
        partitions=partitions,
        rows_per_partition=rows_per_partition,
    )


def collect_runtime_versions() -> dict[str, str]:
    """Collect runtime version metadata for the artifact."""
    import polars as pl

    versions = {
        "python": platform.python_version(),
        "polars": pl.__version__,
    }

    try:
        import duckdb

        versions["duckdb"] = duckdb.__version__
    except ImportError:
        versions["duckdb"] = "not-installed"

    return versions


def current_partition_columns() -> list[str]:
    """Return the live CSV partition column order used by the storage layer."""
    from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS

    return list(CSV_COLUMNS)


def resolve_scenarios(args: argparse.Namespace) -> list[BenchmarkScenario]:
    """Resolve CLI arguments into one or more benchmark scenarios."""
    if args.scenario:
        return args.scenario

    return [
        BenchmarkScenario(
            name=f"{args.partitions * args.rows_per_partition}_rows",
            partitions=args.partitions,
            rows_per_partition=args.rows_per_partition,
        )
    ]


def generate_csv_partitions(
    base_dir: Path,
    scenario: BenchmarkScenario,
    *,
    seed: int = DEFAULT_SEED,
    start_year: int = DEFAULT_START_YEAR,
    start_month: int = DEFAULT_START_MONTH,
) -> tuple[Path, dict[str, Any]]:
    """Generate synthetic CSV partitions in YYYY/MM structure."""
    logger.info(
        "Generating scenario %s with %s partitions x %s rows (%s total rows)",
        scenario.name,
        scenario.partitions,
        scenario.rows_per_partition,
        f"{scenario.total_rows:,}",
    )

    transactions_dir = base_dir / "transactions"
    transactions_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(seed)
    merchants = ["Starbucks", "CU", "GS25", "Coupang", "McDonalds", "Olive", "Daiso", "EMart"]
    accounts = ["Shinhan", "Samsung", "Woori", "Hana"]
    generated_months: list[str] = []
    partition_columns = current_partition_columns()

    for month_offset in range(scenario.partitions):
        year, month = month_for_offset(start_year, start_month, month_offset)
        generated_months.append(month_key(year, month))

        month_dir = transactions_dir / f"{year:04d}" / f"{month:02d}"
        month_dir.mkdir(parents=True, exist_ok=True)
        csv_path = month_dir / "transactions.csv"

        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(partition_columns)

            for row_index in range(scenario.rows_per_partition):
                row = synthetic_transaction_row(
                    year=year,
                    month=month,
                    month_offset=month_offset,
                    row_index=row_index,
                    merchants=merchants,
                    accounts=accounts,
                    rng=rng,
                )
                writer.writerow([row[column] for column in partition_columns])

    distinct_months = sorted(set(generated_months))
    if len(distinct_months) != scenario.partitions:
        raise RuntimeError(
            "Benchmark dataset generation produced duplicate month partitions: "
            f"requested={scenario.partitions}, distinct={len(distinct_months)}"
        )

    logger.info(
        "Generated %s distinct partitions from %s through %s",
        len(distinct_months),
        distinct_months[0],
        distinct_months[-1],
    )

    dataset_metadata = {
        "partitions": scenario.partitions,
        "rows_per_partition": scenario.rows_per_partition,
        "total_rows": scenario.total_rows,
        "schema_columns": len(partition_columns),
        "schema_source": "finjuice.pipeline.storage.csv_schema.CSV_COLUMNS",
        "distinct_months": len(distinct_months),
        "month_range": {
            "start": distinct_months[0],
            "end": distinct_months[-1],
        },
    }
    return transactions_dir, dataset_metadata


def benchmark_polars_monthly_spend(data_root: Path) -> Any:
    """Benchmark Polars monthly spend aggregation."""
    import polars as pl

    partitions = sorted((data_root / "transactions").glob("*/*/*.csv"))
    dfs = [pl.read_csv(path) for path in partitions]
    df = pl.concat(dfs)

    return (
        df.filter(pl.col("is_transfer") == 0)
        .filter(pl.col("amount") < 0)
        .with_columns(pl.col("date").str.slice(0, 7).alias("month"))
        .group_by("month")
        .agg([pl.len().alias("transaction_count"), pl.col("amount").sum().alias("total_amount")])
        .sort("month", descending=True)
    )


def benchmark_polars_tag_breakdown(data_root: Path) -> Any:
    """Benchmark Polars tag breakdown aggregation."""
    import polars as pl

    partitions = sorted((data_root / "transactions").glob("*/*/*.csv"))
    dfs = [pl.read_csv(path) for path in partitions]
    df = pl.concat(dfs)

    return (
        df.filter(pl.col("is_transfer") == 0)
        .filter(pl.col("amount") < 0)
        .with_columns(
            pl.col("tags_final").str.json_decode(dtype=pl.List(pl.Utf8)).alias("tags_array")
        )
        .explode("tags_array")
        .group_by("tags_array")
        .agg([pl.len().alias("transaction_count"), pl.col("amount").sum().alias("total_amount")])
        .sort("total_amount")
        .head(10)
    )


def benchmark_duckdb_monthly_spend(data_root: Path) -> Any:
    """Benchmark the DuckDBAnalytics monthly_spend path."""
    from finjuice.pipeline.analytics import DuckDBAnalytics

    with DuckDBAnalytics(data_root) as analytics:
        return analytics.monthly_spend(exclude_transfers=True, exclude_income=True)


def benchmark_duckdb_tag_breakdown(data_root: Path) -> Any:
    """Benchmark the DuckDBAnalytics tag_breakdown path."""
    from finjuice.pipeline.analytics import DuckDBAnalytics

    with DuckDBAnalytics(data_root) as analytics:
        return analytics.tag_breakdown(top_n=10)


def synthetic_transaction_row(
    *,
    year: int,
    month: int,
    month_offset: int,
    row_index: int,
    merchants: list[str],
    accounts: list[str],
    rng: random.Random,
) -> dict[str, Any]:
    """Build one synthetic transaction row aligned to the live v4 CSV schema."""
    taxonomy = [
        ("food", "cafe", ["cafe"]),
        ("shopping", "mart", ["shopping"]),
        ("living", "daily", ["living"]),
        ("transport", "subway", ["transport"]),
        ("food", "restaurant", ["food"]),
        ("other", "misc", []),
    ]
    major_raw, minor_raw, tag_list = rng.choice(taxonomy)
    day = rng.randint(1, 28)
    hour = rng.randint(0, 23)
    minute = rng.randint(0, 59)
    date_str = f"{year:04d}-{month:02d}-{day:02d}"
    time_str = f"{hour:02d}:{minute:02d}"
    datetime_str = f"{date_str}T{time_str}:00"
    tags_json = json.dumps(tag_list, ensure_ascii=True)

    category_rule_value = rng.choice([minor_raw, major_raw, ""])
    category_final = category_rule_value or minor_raw or major_raw or "misc"

    return {
        "row_hash": f"{month_offset:08x}{row_index:08x}",
        "date": date_str,
        "time": time_str,
        "type_raw": "expense",
        "type_norm": "expense",
        "major_raw": major_raw,
        "minor_raw": minor_raw,
        "merchant_raw": rng.choice(merchants),
        "memo_raw": "",
        "notes_manual": "",
        "amount": -rng.randint(1000, 100000),
        "account": rng.choice(accounts),
        "currency": "KRW",
        "counterparty": "",
        "datetime": datetime_str,
        "category_rule": category_rule_value,
        "category_final": category_final,
        "tags_rule": tags_json,
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": tags_json,
        "confidence": "1.0",
        "needs_review": "0",
        "is_transfer_candidate": "0",
        "is_transfer": "0",
        "transfer_group_id": "",
        "file_id": f"{year % 100:02d}{month:02d}01_1",
        "source_row": str(row_index + 1),
    }


@contextmanager
def make_stateless_runner(run_once: Callable[[], Any]) -> Iterator[Callable[[], Any]]:
    """Wrap a stateless callable in a context manager."""
    yield run_once


@contextmanager
def make_duckdb_runner(
    data_root: Path,
    operation: str,
) -> Iterator[Callable[[], Any]]:
    """Create a warm DuckDB runner that reuses one connection and view."""
    from finjuice.pipeline.analytics import DuckDBAnalytics

    with DuckDBAnalytics(data_root) as analytics:
        if operation == "monthly_spend":
            yield lambda: analytics.monthly_spend(exclude_transfers=True, exclude_income=True)
            return
        if operation == "tag_breakdown":
            yield lambda: analytics.tag_breakdown(top_n=10)
            return
        raise ValueError(f"Unsupported DuckDB operation: {operation}")


def measure_once(run_once: Callable[[], Any]) -> tuple[Any, float]:
    """Measure a single execution."""
    start = time.perf_counter()
    result = run_once()
    elapsed = time.perf_counter() - start
    return result, elapsed


def benchmark_operation(
    *,
    cold_runner: Callable[[], Any],
    warm_runner_factory: Callable[[], ContextManager[Callable[[], Any]]],
    warm_iterations: int,
) -> dict[str, Any]:
    """Benchmark one operation with explicit cold and warm runs."""
    cold_result, cold_seconds = measure_once(cold_runner)

    warm_timings: list[float] = []
    warm_rows = len(cold_result)
    with warm_runner_factory() as warm_runner:
        for _ in range(warm_iterations):
            warm_result, elapsed = measure_once(warm_runner)
            warm_rows = len(warm_result)
            warm_timings.append(elapsed)

    return {
        "cold_seconds": cold_seconds,
        "warm": calculate_statistics(warm_timings),
        "result_rows": warm_rows,
    }


def run_scenario(
    scenario: BenchmarkScenario,
    *,
    warm_iterations: int,
    seed: int,
) -> dict[str, Any]:
    """Run all benchmarks for a single scenario."""
    logger.info("%s", "=" * 72)
    logger.info("Scenario %s (%s rows)", scenario.name, f"{scenario.total_rows:,}")
    logger.info("%s", "=" * 72)

    with tempfile.TemporaryDirectory() as tmpdir:
        data_root = Path(tmpdir)
        _, dataset_metadata = generate_csv_partitions(data_root, scenario, seed=seed)

        operations = {
            "monthly_spend": {
                "measured_paths": {
                    "polars": "Pure Polars CSV read + group_by aggregation.",
                    "duckdb_analytics": (
                        "DuckDBAnalytics.monthly_spend() with DuckDB view-backed SQL aggregation."
                    ),
                },
                "polars": benchmark_operation(
                    cold_runner=lambda: benchmark_polars_monthly_spend(data_root),
                    warm_runner_factory=lambda: make_stateless_runner(
                        lambda: benchmark_polars_monthly_spend(data_root)
                    ),
                    warm_iterations=warm_iterations,
                ),
                "duckdb_analytics": benchmark_operation(
                    cold_runner=lambda: benchmark_duckdb_monthly_spend(data_root),
                    warm_runner_factory=lambda: make_duckdb_runner(data_root, "monthly_spend"),
                    warm_iterations=warm_iterations,
                ),
            },
            "tag_breakdown": {
                "measured_paths": {
                    "polars": "Pure Polars CSV read + JSON explode + aggregation.",
                    "duckdb_analytics": (
                        "DuckDBAnalytics.tag_breakdown(): DuckDB view read plus Polars JSON "
                        "explode/aggregation fallback."
                    ),
                },
                "polars": benchmark_operation(
                    cold_runner=lambda: benchmark_polars_tag_breakdown(data_root),
                    warm_runner_factory=lambda: make_stateless_runner(
                        lambda: benchmark_polars_tag_breakdown(data_root)
                    ),
                    warm_iterations=warm_iterations,
                ),
                "duckdb_analytics": benchmark_operation(
                    cold_runner=lambda: benchmark_duckdb_tag_breakdown(data_root),
                    warm_runner_factory=lambda: make_duckdb_runner(data_root, "tag_breakdown"),
                    warm_iterations=warm_iterations,
                ),
            },
        }

    for operation_name, benchmarks in operations.items():
        benchmarks["speedup"] = {
            "cold": calculate_speedup(
                benchmarks["polars"]["cold_seconds"],
                benchmarks["duckdb_analytics"]["cold_seconds"],
            ),
            "warm_mean": calculate_speedup(
                benchmarks["polars"]["warm"]["mean"],
                benchmarks["duckdb_analytics"]["warm"]["mean"],
            ),
        }
        logger.info(
            "%s: cold=%sx, warm_mean=%sx",
            operation_name,
            benchmarks["speedup"]["cold"],
            benchmarks["speedup"]["warm_mean"],
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
) -> dict[str, Any]:
    """Run the DuckDB vs Polars benchmark suite."""
    results = {
        "metadata": {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "runtime_versions": collect_runtime_versions(),
            "platform": platform.platform(),
            "warm_iterations": warm_iterations,
            "random_seed": seed,
            "measurement_model": {
                "cold": (
                    "First execution on a fresh engine state. "
                    "DuckDB cold includes connection creation and transactions view registration."
                ),
                "warm": (
                    "Subsequent executions in the same Python process. "
                    "DuckDB warm reuses one DuckDBAnalytics connection and transactions view."
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
        description="Benchmark DuckDB vs Polars performance on transaction aggregations"
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
        "--partitions",
        type=int,
        default=12,
        help="Number of monthly CSV partitions to generate for the fallback single scenario.",
    )
    parser.add_argument(
        "--rows-per-partition",
        type=int,
        default=200,
        help="Rows per partition for the fallback single scenario.",
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

    scenarios = resolve_scenarios(args)
    output_path = Path(args.output) if args.output else None

    logger.info("%s", "=" * 72)
    logger.info("DuckDB Analytics Layer Benchmark")
    logger.info("Scenarios: %s", ", ".join(scenario.name for scenario in scenarios))
    logger.info("Warm iterations per operation: %s", args.iterations)
    logger.info("Random seed: %s", args.seed)
    logger.info("%s", "=" * 72)

    results = run_benchmark_suite(
        scenarios,
        warm_iterations=args.iterations,
        output_path=output_path,
        seed=args.seed,
    )

    logger.info("%s", "=" * 72)
    logger.info("Benchmark complete")
    logger.info("%s", "=" * 72)
    for scenario_name, scenario_results in results["benchmarks"].items():
        logger.info("Scenario %s", scenario_name)
        for operation_name, operation_results in scenario_results["operations"].items():
            speedup = operation_results["speedup"]
            logger.info(
                "  %s: cold=%sx, warm_mean=%sx",
                operation_name,
                speedup["cold"],
                speedup["warm_mean"],
            )


if __name__ == "__main__":
    main()
