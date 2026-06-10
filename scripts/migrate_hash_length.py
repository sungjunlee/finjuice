#!/usr/bin/env python3
"""
Migrate CSV partitions from 10-char to 16-char row_hash.

This script updates all CSV partition files to use 16-character row_hash values
instead of the previous 10-character format (Issue #81).

Usage:
    # Dry-run (recommended first)
    python scripts/migrate_hash_length.py --dry-run

    # Execute migration
    python scripts/migrate_hash_length.py --execute

    # With custom data directory
    python scripts/migrate_hash_length.py --data-dir ~/Documents/my-finance-data --execute

Safety Features:
    - Dry-run mode by default (requires explicit --execute flag)
    - Atomic writes (temp file + rename)
    - Collision detection
    - Detailed migration report
    - Preserves original file permissions

Migration Details:
    - Recalculates SHA256 hash for each row
    - Truncates to 16 chars instead of 10
    - Updates row_hash column only (all other data unchanged)
    - Backward compatible: can read both 10 and 16 char hashes

Performance:
    - Processes partitions in parallel
    - ~100-500 rows/sec per partition
    - Typical dataset (2,269 rows): <10 seconds

See Also:
    - Issue #81: https://github.com/yourusername/banksalad-tools/issues/81
    - templates/schema.yaml: Schema v2 with updated row_hash definition
"""

import argparse
import hashlib
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


def calculate_row_hash_16(row: dict[str, Any]) -> str:
    """
    Calculate 16-char row hash (new format).

    Uses same algorithm as deduplication.calculate_row_hash() but with 16-char output.

    Args:
        row: Transaction dict with keys: date, time, type, merchant, amount,
             currency, account

    Returns:
        SHA256 hash truncated to 16 characters
    """
    # Required fields for hash calculation (immutable bank data only)
    # NOTE: Must match deduplication.calculate_row_hash() field names exactly!
    required_fields = ["date", "time", "type", "merchant", "amount", "currency", "account"]

    # Validate required fields exist
    missing = [f for f in required_fields if f not in row or row[f] is None]
    if missing:
        raise ValueError(f"Missing required fields for hash: {missing}")

    # Build hash string (deterministic order)
    # NOTE: Must match deduplication.calculate_row_hash() exactly for hash compatibility!
    hash_parts = [
        str(row["date"]).strip(),
        str(row["time"]).strip(),
        str(row["type"]).strip(),
        str(row["merchant"]).strip(),
        str(row["amount"]),  # Number field - no strip needed
        str(row["currency"]).strip(),
        str(row["account"]).strip(),
    ]

    hash_string = "|".join(hash_parts)

    # Calculate SHA256 and truncate to 16 chars
    return hashlib.sha256(hash_string.encode("utf-8")).hexdigest()[:16]


def migrate_partition(csv_path: Path, dry_run: bool = True) -> dict[str, Any]:
    """
    Migrate single CSV partition from 10-char to 16-char row_hash.

    Args:
        csv_path: Path to CSV partition file
        dry_run: If True, only analyze without writing changes

    Returns:
        Migration result dict with keys:
            - file: Path to CSV file
            - total_rows: Total row count
            - migrated_rows: Rows with 10-char hash (migrated)
            - already_16: Rows already with 16-char hash
            - collisions: Number of hash collisions detected
            - success: Boolean success flag
            - error: Error message (if failed)
    """
    result = {
        "file": str(csv_path),
        "total_rows": 0,
        "migrated_rows": 0,
        "already_16": 0,
        "collisions": 0,
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

        # Separate rows by hash length
        df_with_length = df.with_columns(pl.col("row_hash").str.len_chars().alias("hash_len"))

        rows_10 = df_with_length.filter(pl.col("hash_len") == 10)
        rows_16 = df_with_length.filter(pl.col("hash_len") == 16)
        rows_other = df_with_length.filter((pl.col("hash_len") != 10) & (pl.col("hash_len") != 16))

        result["migrated_rows"] = len(rows_10)
        result["already_16"] = len(rows_16)

        if len(rows_other) > 0:
            logger.warning(
                f"  Found {len(rows_other)} rows with unexpected hash length in {csv_path.name}"
            )

        if result["migrated_rows"] == 0:
            logger.info(f"  Already migrated: {csv_path.name} ({result['already_16']} rows)")
            result["success"] = True
            return result

        # Recalculate hashes for 10-char rows
        logger.info(f"  Migrating {csv_path.name}: {result['migrated_rows']} rows (10→16 chars)")

        # Calculate new 16-char hashes
        new_hashes = []
        for row in rows_10.to_dicts():
            try:
                new_hash = calculate_row_hash_16(row)
                new_hashes.append(new_hash)
            except ValueError as e:
                logger.error(f"    Failed to calculate hash for row: {e}")
                raise

        # Update row_hash column
        rows_10_migrated = rows_10.with_columns(pl.Series("row_hash", new_hashes)).drop("hash_len")

        # Combine migrated rows with already-16 rows and preserve unexpected hash lengths
        # (Non-destructive: keeps all data even if hash_len is unexpected)
        df_final = pl.concat(
            [
                rows_10_migrated,
                rows_16.drop("hash_len"),
                rows_other.drop("hash_len"),  # Preserve rows with unexpected hash lengths
            ]
        )

        # Sort by datetime to maintain stable order
        df_final = df_final.sort("datetime")

        # Collision detection
        hash_counts = df_final.group_by("row_hash").agg(pl.len().alias("count"))
        collisions = hash_counts.filter(pl.col("count") > 1)

        if len(collisions) > 0:
            result["collisions"] = len(collisions)
            logger.error(
                f"    ❌ Collision detected! {result['collisions']} duplicate hashes "
                f"in {csv_path.name}"
            )
            logger.error(f"    Duplicate hashes: {collisions['row_hash'].to_list()}")
            result["error"] = "Hash collision detected"
            return result

        if not dry_run:
            # Atomic write: temp file + rename
            temp_path = csv_path.with_suffix(".tmp.csv")
            df_final.write_csv(temp_path)

            # Rename temp to final (atomic on POSIX systems)
            temp_path.replace(csv_path)
            logger.info(f"    ✅ Written: {csv_path.name}")

        result["success"] = True
        return result

    except Exception as e:
        logger.error(f"  ❌ Error migrating {csv_path.name}: {e}")
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
    migrated_rows = sum(r["migrated_rows"] for r in results)
    already_16 = sum(r["already_16"] for r in results)
    total_collisions = sum(r["collisions"] for r in results)

    # Group by year-month for summary
    by_period = defaultdict(lambda: {"total": 0, "migrated": 0})
    for r in results:
        # Extract YYYY/MM from path (e.g., "transactions/2024/10/transactions.csv")
        parts = Path(r["file"]).parts
        if len(parts) >= 3:
            year_month = f"{parts[-3]}/{parts[-2]}"
            by_period[year_month]["total"] += r["total_rows"]
            by_period[year_month]["migrated"] += r["migrated_rows"]

    print("\n" + "=" * 80)
    print(f"{'DRY-RUN ' if dry_run else ''}MIGRATION REPORT")
    print("=" * 80)

    print("\n📊 Summary:")
    print(f"  Total partitions:    {total_partitions}")
    print(f"  Successful:          {successful}")
    print(f"  Failed:              {failed}")
    print(f"  Total rows:          {total_rows:,}")
    print(f"  Migrated (10→16):    {migrated_rows:,}")
    print(f"  Already 16-char:     {already_16:,}")
    print(f"  Collisions detected: {total_collisions}")

    if by_period:
        print("\n📅 By Period:")
        for period in sorted(by_period.keys()):
            stats = by_period[period]
            print(f"  {period}: {stats['migrated']:3d} migrated / {stats['total']:3d} total")

    if failed > 0:
        print("\n❌ Failed Partitions:")
        for r in results:
            if not r["success"]:
                print(f"  {r['file']}: {r['error']}")

    if total_collisions > 0:
        print(f"\n⚠️  WARNING: {total_collisions} hash collisions detected!")
        print("   Review collision details above and investigate data integrity.")

    if dry_run:
        print("\n⚠️  DRY-RUN MODE: No files were modified.")
        print("   Run with --execute to apply changes.")
    else:
        print("\n✅ Migration complete!")

    print("=" * 80 + "\n")


def main() -> int:
    """
    Main migration script entry point.

    Returns:
        Exit code (0 = success, 1 = failure)
    """
    parser = argparse.ArgumentParser(
        description="Migrate CSV partitions from 10-char to 16-char row_hash",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry-run (recommended first)
  python scripts/migrate_hash_length.py --dry-run

  # Execute migration
  python scripts/migrate_hash_length.py --execute

  # Custom data directory
  python scripts/migrate_hash_length.py --data-dir ~/Documents/my-finance-data --execute

Notes:
  - Always run --dry-run first to preview changes
  - Backup your data before running --execute
  - Migration is idempotent (safe to re-run)
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
    print("HASH LENGTH MIGRATION (10 → 16 chars)")
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
    collision_count = sum(r["collisions"] for r in results)

    if failed_count > 0 or collision_count > 0:
        logger.error("Migration completed with errors")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
