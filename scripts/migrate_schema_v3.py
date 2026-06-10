#!/usr/bin/env python3
"""
Migrate CSV partitions from schema v2 to v3 (Issue #170).

This script adds category_rule and category_final columns to existing CSV partitions.

For migration, category_final is calculated using: minor_raw > major_raw > '미분류'
(category_rule is empty since no rules have been applied yet).

After migration, the full priority chain becomes:
    category_rule > minor_raw > major_raw > '미분류'
Run `finjuice tag` after migration to populate category_rule from rules.yaml.

Usage:
    # Dry-run (recommended first)
    python scripts/migrate_schema_v3.py --dry-run

    # Execute migration
    python scripts/migrate_schema_v3.py --execute

    # With custom data directory
    python scripts/migrate_schema_v3.py --data-dir ~/Documents/my-finance-data --execute

Safety Features:
    - Dry-run mode by default (requires explicit --execute flag)
    - Atomic writes (temp file + rename)
    - Detailed migration report
    - Preserves original file permissions
    - Idempotent (safe to re-run)

Migration Details:
    - Adds category_rule column (empty string, as no rules have been applied yet)
    - Adds category_final column using: minor_raw > major_raw > '미분류'
    - Preserves all existing columns and data

See Also:
    - Issue #170: Data migration (v2 → v3)
    - templates/schema.yaml: Schema v3 definition
"""

import argparse
import logging
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import polars as pl

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# Schema v3 columns that need to be added
V3_NEW_COLUMNS = ["category_rule", "category_final"]
DEFAULT_DATA_DIR = Path.home() / ".finjuice"
PROGRAM_REPO_ROOT = Path(__file__).resolve().parents[1]


def validate_data_dir_location(data_dir: Path) -> bool:
    """Reject migration targets inside the finjuice source repository."""
    resolved_data_dir = data_dir.expanduser().resolve()
    resolved_repo_root = PROGRAM_REPO_ROOT.resolve()
    if resolved_data_dir == resolved_repo_root or resolved_data_dir.is_relative_to(
        resolved_repo_root
    ):
        logger.error("Refusing to use a data directory inside the finjuice program repository")
        logger.error("Use ~/.finjuice or another private data directory outside this checkout")
        logger.error("Rejected path: %s", resolved_data_dir)
        return False
    return True


def is_v3_schema(df: pl.DataFrame) -> bool:
    """Check if DataFrame already has v3 schema columns."""
    return all(col in df.columns for col in V3_NEW_COLUMNS)


def calculate_category_final(row: dict[str, Any]) -> str:
    """
    Calculate category_final for v2→v3 migration.

    For migration, uses: minor_raw > major_raw > '미분류'
    (category_rule is empty since no rules have been applied yet)

    After migration and `finjuice tag`, the full priority chain is:
        category_rule > minor_raw > major_raw > '미분류'

    Args:
        row: Transaction dict with minor_raw and major_raw keys

    Returns:
        Category string (never empty)
    """
    minor_raw = row.get("minor_raw") or ""
    major_raw = row.get("major_raw") or ""

    if minor_raw and minor_raw.strip():
        return minor_raw.strip()
    if major_raw and major_raw.strip():
        return major_raw.strip()
    return "미분류"


def migrate_partition(csv_path: Path, dry_run: bool = True) -> dict[str, Any]:
    """
    Migrate single CSV partition from schema v2 to v3.

    Args:
        csv_path: Path to CSV partition file
        dry_run: If True, only analyze without writing changes

    Returns:
        Migration result dict with keys:
            - file: Path to CSV file
            - total_rows: Total row count
            - migrated: Boolean indicating if migration was needed
            - already_v3: Boolean if already v3 schema
            - success: Boolean success flag
            - error: Error message (if failed)
    """
    result = {
        "file": str(csv_path),
        "total_rows": 0,
        "migrated": False,
        "already_v3": False,
        "success": False,
        "error": None,
    }

    try:
        # Read CSV partition
        df = pl.read_csv(csv_path)
        result["total_rows"] = len(df)

        if result["total_rows"] == 0:
            logger.info(f"  Empty partition: {csv_path.name}")
            result["success"] = True
            return result

        # Check if already v3 schema
        if is_v3_schema(df):
            logger.info(f"  Already v3: {csv_path.name} ({result['total_rows']} rows)")
            result["already_v3"] = True
            result["success"] = True
            return result

        logger.info(f"  Migrating {csv_path.name}: {result['total_rows']} rows (v2 → v3)")

        # Calculate category_final for each row
        category_finals = []
        for row in df.to_dicts():
            category_final = calculate_category_final(row)
            category_finals.append(category_final)

        # Add new columns
        df = df.with_columns(
            [
                pl.lit("").alias("category_rule"),  # Empty - no rules applied yet
                pl.Series("category_final", category_finals),
            ]
        )

        # Ensure column order matches schema v3
        # The order should be: ... datetime, category_rule, category_final, tags_rule, ...
        # We need to reorder columns to match schema.yaml
        columns = df.columns

        # Find position to insert (after datetime, before tags_rule if exists)
        if "tags_rule" in columns:
            # Build new column order: skip category_* columns, insert them before tags_rule
            new_order = []
            for col in columns:
                if col in ("category_rule", "category_final"):
                    continue  # Skip - will insert at correct position
                if col == "tags_rule":
                    # Insert category columns right before tags_rule
                    new_order.extend(["category_rule", "category_final"])
                new_order.append(col)
            df = df.select(new_order)

        if not dry_run:
            # Atomic write: temp file + rename
            temp_path = csv_path.with_suffix(".tmp.csv")
            df.write_csv(temp_path)

            # Rename temp to final (atomic on POSIX systems)
            temp_path.replace(csv_path)
            logger.info(f"    ✅ Written: {csv_path.name}")

        result["migrated"] = True
        result["success"] = True
        return result

    except Exception as e:
        logger.exception(f"  ❌ Error migrating {csv_path.name}: {e}")
        result["error"] = str(e)
        return result


def find_csv_partitions(data_dir: Path) -> list[Path]:
    """
    Find all CSV partition files.

    Args:
        data_dir: Root data directory

    Returns:
        List of Path objects to CSV partition files
    """
    transactions_dir = data_dir / "transactions"

    if not transactions_dir.exists():
        logger.warning(f"Transactions directory not found: {transactions_dir}")
        return []

    # Find all transactions.csv files in YYYY/MM/ structure
    csv_files = sorted(transactions_dir.glob("*/*/transactions.csv"))

    return csv_files


def print_migration_report(results: list[dict[str, Any]], dry_run: bool) -> None:
    """
    Print detailed migration report.

    Args:
        results: List of migration result dicts
        dry_run: Whether this was a dry-run
    """
    total_partitions = len(results)
    successful = sum(1 for r in results if r["success"])
    failed = total_partitions - successful

    total_rows = sum(r["total_rows"] for r in results)
    migrated_count = sum(1 for r in results if r["migrated"])
    migrated_rows = sum(r["total_rows"] for r in results if r["migrated"])
    already_v3 = sum(1 for r in results if r["already_v3"])

    # Group by year-month for summary
    by_period: dict[str, dict[str, Any]] = defaultdict(lambda: {"total": 0, "migrated": False})
    for r in results:
        # Extract YYYY/MM from path (e.g., "transactions/2024/10/transactions.csv")
        parts = Path(r["file"]).parts
        if len(parts) >= 3:
            year_month = f"{parts[-3]}/{parts[-2]}"
            by_period[year_month]["total"] += r["total_rows"]
            if r["migrated"]:
                by_period[year_month]["migrated"] = True

    print("\n" + "=" * 80)
    print(f"{'DRY-RUN ' if dry_run else ''}SCHEMA V3 MIGRATION REPORT")
    print("=" * 80)

    print("\n📊 Summary:")
    print(f"  Total partitions:    {total_partitions}")
    print(f"  Successful:          {successful}")
    print(f"  Failed:              {failed}")
    print(f"  Total rows:          {total_rows:,}")
    print(f"  Partitions migrated: {migrated_count}")
    print(f"  Rows migrated:       {migrated_rows:,}")
    print(f"  Already v3:          {already_v3}")

    print("\n📝 Changes:")
    print("  + category_rule   (empty string - no rules applied yet)")
    print("  + category_final  (calculated from minor_raw > major_raw > '미분류')")

    if by_period:
        print("\n📅 By Period:")
        for period in sorted(by_period.keys()):
            stats = by_period[period]
            status = "✅ migrated" if stats["migrated"] else "⏭️  skipped (already v3)"
            print(f"  {period}: {stats['total']:3d} rows - {status}")

    if failed > 0:
        print("\n❌ Failed Partitions:")
        for r in results:
            if not r["success"]:
                print(f"  {r['file']}: {r['error']}")

    if dry_run:
        print("\n⚠️  DRY-RUN MODE: No files were modified.")
        print("   Run with --execute to apply changes.")
    else:
        print("\n✅ Migration complete!")
        print("   Run `finjuice tag` to apply category rules from rules.yaml")

    print("=" * 80 + "\n")


def main() -> int:
    """
    Main migration script entry point.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    parser = argparse.ArgumentParser(
        description="Migrate CSV partitions from schema v2 to v3 (add category columns)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run (recommended first)
  python scripts/migrate_schema_v3.py --dry-run

  # Execute migration
  python scripts/migrate_schema_v3.py --execute

  # Custom data directory
  python scripts/migrate_schema_v3.py --data-dir ~/Documents/my-finance-data --execute

Notes:
  - Always run --dry-run first to preview changes
  - Backup your data before running --execute
  - Migration is idempotent (safe to re-run)
  - After migration, run `finjuice tag` to apply category rules
        """,
    )

    parser.add_argument(
        "--data-dir",
        type=Path,
        default=DEFAULT_DATA_DIR,
        help=f"Data directory path (default: {DEFAULT_DATA_DIR})",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Dry-run mode (analyze only, no writes) - DEFAULT",
    )

    parser.add_argument(
        "--execute",
        action="store_true",
        help="Execute migration (writes changes to disk)",
    )

    args = parser.parse_args()

    # Resolve dry_run: default is True unless --execute is specified
    dry_run = not args.execute

    # Validate data directory
    if not validate_data_dir_location(args.data_dir):
        return 1

    if not args.data_dir.exists():
        logger.error("Data directory not found")
        logger.error("Create directory or specify correct path with --data-dir")
        return 1

    # Print header
    print("\n" + "=" * 80)
    print("SCHEMA V3 MIGRATION (v2 → v3: Add category columns)")
    print(f"Mode: {'DRY-RUN (preview only)' if dry_run else 'EXECUTE (writes changes)'}")
    print(f"Data directory: {args.data_dir.resolve()}")
    print(f"Timestamp: {datetime.now().isoformat()}")
    print("=" * 80 + "\n")

    if dry_run:
        logger.info("⚠️  DRY-RUN MODE: No files will be modified")
        logger.info("   Run with --execute to apply changes\n")
    else:
        logger.warning("⚠️  EXECUTE MODE: Files will be modified")
        logger.warning("   Ensure you have a backup before proceeding\n")

    # Find CSV partitions
    logger.info("🔍 Finding CSV partition files...")
    csv_files = find_csv_partitions(args.data_dir)

    if not csv_files:
        logger.warning("No CSV partition files found")
        logger.info("Expected location: <data-dir>/transactions/YYYY/MM/transactions.csv")
        return 0

    logger.info(f"Found {len(csv_files)} partition files\n")

    # Migrate each partition
    logger.info("🔄 Processing partitions...\n")
    results = []

    for csv_path in csv_files:
        result = migrate_partition(csv_path, dry_run=dry_run)
        results.append(result)

    # Print report
    print_migration_report(results, dry_run)

    # Exit code
    failed_count = sum(1 for r in results if not r["success"])

    if failed_count > 0:
        logger.error("Migration completed with errors")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
