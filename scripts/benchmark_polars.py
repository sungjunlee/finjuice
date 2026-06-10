"""Benchmark script for comparing pandas vs Polars performance.

This script benchmarks common transaction data operations:
1. CSV loading (read_csv)
2. Filtering (date range, amount conditions)
3. Aggregation (groupby, sum, count)
4. Sorting (by date, amount)
5. Memory usage

Tests with varying dataset sizes: 1K, 10K, 100K rows

Usage:
    uv run python scripts/benchmark_polars.py
    uv run python scripts/benchmark_polars.py --sizes 1000,10000,100000 --iterations 5
    uv run python scripts/benchmark_polars.py --output docs/benchmarks/polars-results.json
"""

import argparse
import json
import logging
import random
import sys
import tempfile
import time
import tracemalloc
from datetime import datetime, timedelta
from functools import wraps
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Callable, Dict, List

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# ============================================================================
# Utility Functions
# ============================================================================


def timer(results_list: List[float]) -> Callable:
    """Decorator to measure execution time and append to results list."""

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            start = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start
            results_list.append(elapsed)
            return result

        return wrapper

    return decorator


def measure_memory() -> float:
    """Measure current memory usage in MB."""
    if not tracemalloc.is_tracing():
        tracemalloc.start()

    current, peak = tracemalloc.get_traced_memory()
    return current / (1024 * 1024)  # Convert to MB


def calculate_statistics(timings: List[float]) -> Dict[str, float]:
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
    return {
        "mean": mean(timings),
        "median": median(timings),
        "min": min(timings),
        "max": max(timings),
        "p95": (
            sorted_timings[int(len(sorted_timings) * 0.95)]
            if len(sorted_timings) > 1
            else timings[0]
        ),
        "std_dev": stdev(timings) if len(timings) > 1 else 0.0,
    }


# ============================================================================
# Synthetic Data Generation
# ============================================================================


def generate_synthetic_transactions(num_rows: int, output_path: Path) -> None:
    """Generate synthetic transaction data as CSV.

    Args:
        num_rows: Number of transactions to generate
        output_path: Path to write CSV file
    """
    logger.info(f"Generating {num_rows} synthetic transactions...")

    merchants = ["스타벅스", "CU", "GS25", "쿠팡", "맥도날드", "올리브영", "다이소", "이마트"]
    accounts = ["신한카드", "삼성카드", "우리은행", "하나은행"]
    tags = [["카페"], ["편의점"], ["쇼핑"], ["식비"], ["생활"], []]

    start_date = datetime(2024, 1, 1)

    # Write CSV header
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(
            "date,time,type_raw,major_raw,minor_raw,merchant_raw,amount,currency,account,tags_final\n"
        )

        for i in range(num_rows):
            # Random date within 2024
            days_offset = random.randint(0, 364)
            txn_date = start_date + timedelta(days=days_offset)
            date_str = txn_date.strftime("%Y-%m-%d")

            # Random time
            hour = random.randint(0, 23)
            minute = random.randint(0, 59)
            time_str = f"{hour:02d}:{minute:02d}"

            # Random transaction details
            merchant = random.choice(merchants)
            amount = -random.randint(1000, 100000)  # Expenses are negative
            account = random.choice(accounts)
            tag_list = random.choice(tags)
            tags_json = json.dumps(tag_list, ensure_ascii=False)

            # Write row
            f.write(
                f'{date_str},{time_str},지출,식비,카페,{merchant},{amount},KRW,{account},"{tags_json}"\n'
            )

    logger.info(f"Generated {num_rows} benchmark rows")


# ============================================================================
# Benchmark Operations - pandas
# ============================================================================


def benchmark_pandas_load(csv_path: Path, timings: List[float]) -> Any:
    """Benchmark pandas CSV loading."""
    import pandas as pd

    @timer(timings)
    def load():
        return pd.read_csv(csv_path)

    return load()


def benchmark_pandas_filter(df: Any, timings: List[float]) -> Any:
    """Benchmark pandas filtering (date range + amount condition)."""

    @timer(timings)
    def filter_op():
        date_filter = (df["date"] >= "2024-06-01") & (df["date"] <= "2024-06-30")
        return df[date_filter & (df["amount"] < -10000)]

    return filter_op()


def benchmark_pandas_aggregate(df: Any, timings: List[float]) -> Any:
    """Benchmark pandas aggregation (monthly spending)."""

    @timer(timings)
    def agg_op():
        df["month"] = df["date"].str[:7]
        return df.groupby("month")["amount"].sum()

    return agg_op()


def benchmark_pandas_sort(df: Any, timings: List[float]) -> Any:
    """Benchmark pandas sorting."""

    @timer(timings)
    def sort_op():
        return df.sort_values(["date", "time"])

    return sort_op()


# ============================================================================
# Benchmark Operations - Polars
# ============================================================================


def benchmark_polars_load(csv_path: Path, timings: List[float]) -> Any:
    """Benchmark Polars CSV loading."""
    import polars as pl

    @timer(timings)
    def load():
        return pl.read_csv(csv_path)

    return load()


def benchmark_polars_filter(df: Any, timings: List[float]) -> Any:
    """Benchmark Polars filtering (date range + amount condition)."""

    @timer(timings)
    def filter_op():
        return df.filter(
            (df["date"] >= "2024-06-01") & (df["date"] <= "2024-06-30") & (df["amount"] < -10000)
        )

    return filter_op()


def benchmark_polars_aggregate(df: Any, timings: List[float]) -> Any:
    """Benchmark Polars aggregation (monthly spending)."""
    import polars as pl

    @timer(timings)
    def agg_op():
        return (
            df.with_columns(pl.col("date").str.slice(0, 7).alias("month"))
            .group_by("month")
            .agg(pl.col("amount").sum())
        )

    return agg_op()


def benchmark_polars_sort(df: Any, timings: List[float]) -> Any:
    """Benchmark Polars sorting."""

    @timer(timings)
    def sort_op():
        return df.sort(["date", "time"])

    return sort_op()


# ============================================================================
# Main Benchmark Runner
# ============================================================================


def run_benchmark_suite(
    sizes: List[int], iterations: int, output_path: Path | None = None
) -> Dict[str, Any]:
    """Run full benchmark suite comparing pandas vs Polars.

    Args:
        sizes: List of dataset sizes to test (e.g., [1000, 10000, 100000])
        iterations: Number of iterations per test
        output_path: Optional path to save JSON results

    Returns:
        Dictionary with benchmark results
    """
    results = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "sizes": sizes,
            "iterations": iterations,
        },
        "benchmarks": {},
    }

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)

        for size in sizes:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Benchmarking size: {size:,} rows")
            logger.info(f"{'=' * 60}")

            # Generate synthetic data
            csv_path = tmpdir_path / f"transactions_{size}.csv"
            generate_synthetic_transactions(size, csv_path)

            # Initialize result structure
            size_key = f"{size}_rows"
            results["benchmarks"][size_key] = {"pandas": {}, "polars": {}, "speedup": {}}

            # ================================================================
            # pandas benchmarks
            # ================================================================
            logger.info("\n--- pandas benchmarks ---")

            # 1. Load
            load_timings = []
            df_pandas = None
            for i in range(iterations):
                tracemalloc.start()
                df_pandas = benchmark_pandas_load(csv_path, load_timings)
                mem_after = measure_memory()
                tracemalloc.stop()
                msg = f"  pandas load {i + 1}/{iterations}: {load_timings[-1]:.4f}s"
                logger.info(f"{msg}, mem: {mem_after:.2f} MB")

            results["benchmarks"][size_key]["pandas"]["load"] = calculate_statistics(load_timings)

            # 2. Filter
            filter_timings = []
            for i in range(iterations):
                _ = benchmark_pandas_filter(df_pandas, filter_timings)
                logger.info(f"  pandas filter {i + 1}/{iterations}: {filter_timings[-1]:.4f}s")

            stats = calculate_statistics(filter_timings)
            results["benchmarks"][size_key]["pandas"]["filter"] = stats

            # 3. Aggregate
            agg_timings = []
            for i in range(iterations):
                _ = benchmark_pandas_aggregate(df_pandas, agg_timings)
                logger.info(f"  pandas agg {i + 1}/{iterations}: {agg_timings[-1]:.4f}s")

            stats = calculate_statistics(agg_timings)
            results["benchmarks"][size_key]["pandas"]["aggregate"] = stats

            # 4. Sort
            sort_timings = []
            for i in range(iterations):
                _ = benchmark_pandas_sort(df_pandas, sort_timings)
                logger.info(
                    f"  pandas sort iteration {i + 1}/{iterations}: {sort_timings[-1]:.4f}s"
                )

            results["benchmarks"][size_key]["pandas"]["sort"] = calculate_statistics(sort_timings)

            # ================================================================
            # Polars benchmarks
            # ================================================================
            logger.info("\n--- Polars benchmarks ---")

            # 1. Load
            load_timings_pl = []
            df_polars = None
            for i in range(iterations):
                tracemalloc.start()
                df_polars = benchmark_polars_load(csv_path, load_timings_pl)
                mem_after = measure_memory()
                tracemalloc.stop()
                msg = f"  Polars load {i + 1}/{iterations}: {load_timings_pl[-1]:.4f}s"
                logger.info(f"{msg}, mem: {mem_after:.2f} MB")

            results["benchmarks"][size_key]["polars"]["load"] = calculate_statistics(
                load_timings_pl
            )

            # 2. Filter
            filter_timings_pl = []
            for i in range(iterations):
                _ = benchmark_polars_filter(df_polars, filter_timings_pl)
                logger.info(
                    f"  Polars filter iteration {i + 1}/{iterations}: {filter_timings_pl[-1]:.4f}s"
                )

            results["benchmarks"][size_key]["polars"]["filter"] = calculate_statistics(
                filter_timings_pl
            )

            # 3. Aggregate
            agg_timings_pl = []
            for i in range(iterations):
                _ = benchmark_polars_aggregate(df_polars, agg_timings_pl)
                logger.info(
                    f"  Polars aggregate iteration {i + 1}/{iterations}: {agg_timings_pl[-1]:.4f}s"
                )

            results["benchmarks"][size_key]["polars"]["aggregate"] = calculate_statistics(
                agg_timings_pl
            )

            # 4. Sort
            sort_timings_pl = []
            for i in range(iterations):
                _ = benchmark_polars_sort(df_polars, sort_timings_pl)
                logger.info(
                    f"  Polars sort iteration {i + 1}/{iterations}: {sort_timings_pl[-1]:.4f}s"
                )

            results["benchmarks"][size_key]["polars"]["sort"] = calculate_statistics(
                sort_timings_pl
            )

            # ================================================================
            # Calculate speedup ratios
            # ================================================================
            logger.info("\n--- Speedup Summary ---")

            for operation in ["load", "filter", "aggregate", "sort"]:
                pandas_mean = results["benchmarks"][size_key]["pandas"][operation]["mean"]
                polars_mean = results["benchmarks"][size_key]["polars"][operation]["mean"]

                speedup = pandas_mean / polars_mean if polars_mean > 0 else 0
                results["benchmarks"][size_key]["speedup"][operation] = round(speedup, 2)

                logger.info(
                    f"  {operation.capitalize()}: {speedup:.2f}x faster "
                    f"(pandas: {pandas_mean:.4f}s, Polars: {polars_mean:.4f}s)"
                )

    # Save results if output path provided
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        logger.info("\n✅ Benchmark results saved")

    return results


# ============================================================================
# CLI Interface
# ============================================================================


def main():
    """Main entry point for benchmark script."""
    parser = argparse.ArgumentParser(
        description="Benchmark pandas vs Polars performance on transaction data operations"
    )
    parser.add_argument(
        "--sizes",
        type=str,
        default="1000,10000,100000",
        help="Comma-separated list of dataset sizes (default: 1000,10000,100000)",
    )
    parser.add_argument(
        "--iterations", type=int, default=3, help="Number of iterations per benchmark (default: 3)"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Path to save JSON results (default: None, prints to console)",
    )

    args = parser.parse_args()

    # Parse sizes
    sizes = [int(s.strip()) for s in args.sizes.split(",")]

    # Parse output path
    output_path = Path(args.output) if args.output else None

    # Run benchmarks
    logger.info("Starting Polars vs pandas benchmark suite...")
    logger.info(f"Dataset sizes: {sizes}")
    logger.info(f"Iterations per test: {args.iterations}")

    results = run_benchmark_suite(sizes, args.iterations, output_path)

    # Print summary
    logger.info("\n" + "=" * 60)
    logger.info("BENCHMARK COMPLETE")
    logger.info("=" * 60)

    for size_key, size_results in results["benchmarks"].items():
        logger.info(f"\n{size_key}:")
        for operation, speedup in size_results["speedup"].items():
            logger.info(f"  {operation}: {speedup}x faster with Polars")


if __name__ == "__main__":
    main()
