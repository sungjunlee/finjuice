"""
Tagging pipeline integration (Polars-only).

This module integrates the rule engine into the main data processing pipeline,
applying tagging rules to transactions in CSV partitions with batch processing
and coverage statistics.
"""

import logging
from pathlib import Path
from typing import Any, Dict, List

import polars as pl

from finjuice.pipeline.tagging.manual import (
    merge_final_tags,
    normalize_tag_list,
    resolve_category_final,
)

from .models import TagRule
from .rules import apply_tagging_rules_v3
from .rules_yaml_io import load_rules

logger = logging.getLogger(__name__)


def tag_all_transactions(
    csv_base_dir: Path,
    rules: List[TagRule],
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Apply tagging rules to all transactions in CSV partitions (Polars-only).

    Processes transactions from all partitions and updates tags_rule and tags_final fields.

    Args:
        csv_base_dir: Base directory for CSV partitions
        rules: List of TagRule objects (sorted by priority)
        dry_run: If True, calculate changes without writing to CSV

    Returns:
        Summary dict with counts and coverage percentage:
        {
            'total': int,          # Total transactions processed
            'tagged': int,         # Transactions with at least one tag
            'untagged': int,       # Transactions with no tags
            'coverage_pct': float, # Percentage of tagged transactions
            'previously_tagged': int,  # (dry_run only) Count before applying rules
            'changes': list,       # (dry_run only) List of changed transactions
        }
    """
    logger.info(f"Starting tagging process (Polars backend, dry_run={dry_run})")

    # Load all transactions from CSV partitions (using Polars)
    from finjuice.pipeline.storage import csv_transactions

    df = csv_transactions.get_all_transactions(csv_base_dir)

    if df.is_empty():
        logger.warning("No transactions found in CSV partitions")
        empty_result = {"total": 0, "tagged": 0, "untagged": 0, "coverage_pct": 0.0}  # type: Dict[str, Any]
        if dry_run:
            empty_result["previously_tagged"] = 0
            empty_result["changes"] = []
        return empty_result

    # Track changes for dry-run mode
    changes: List[Dict[str, Any]] = []
    previously_tagged = 0

    # Define UDF for applying tagging rules to each row
    def apply_tags_to_row(row_dict: dict) -> dict:
        """
        Apply tagging rules to a single row (as dict).

        Returns dict with category_rule, category_final, tags_rule, tags_final,
        binary coverage confidence, and needs_review (v3 schema).
        """
        # Build transaction dict for rule matching
        transaction = {
            "merchant_raw": row_dict.get("merchant_raw") or "",
            "memo_raw": row_dict.get("memo_raw") or "",
            "major_raw": row_dict.get("major_raw") or "",
            "minor_raw": row_dict.get("minor_raw") or "",
            "type_norm": row_dict.get("type_norm") or "",
            "amount": row_dict.get("amount"),
            "account": row_dict.get("account") or "",
        }

        # Apply rules (v3 with category support)
        result = apply_tagging_rules_v3(transaction, rules)

        tags_ai = normalize_tag_list(row_dict.get("tags_ai"))
        tags_manual = normalize_tag_list(row_dict.get("tags_manual"))
        tags_final = merge_final_tags(result.tags, tags_ai, tags_manual)
        category_final = resolve_category_final(
            result.category_rule,
            row_dict.get("minor_raw"),
            row_dict.get("major_raw"),
            tags_manual=tags_manual,
        )

        # Persisted confidence is coverage confidence, not model confidence.
        confidence = 1.0 if tags_final else 0.0
        return {
            "category_rule": result.category_rule or None,  # None if empty
            "category_final": category_final,
            "tags_rule": result.tags,
            "tags_final": tags_final,
            "confidence": confidence,
            "needs_review": 1 if confidence < 0.7 else 0,
        }

    # Apply tagging using map_rows for batch processing
    # Convert to Python dicts for UDF processing
    logger.info(f"Processing {len(df)} transactions with {len(rules)} rules")

    tagged_results = []
    max_changes = 50  # Limit changes list for performance

    for row in df.iter_rows(named=True):
        # Track existing tags for dry-run comparison
        raw_tags = row.get("tags_final")
        old_tags: List[str] = raw_tags if isinstance(raw_tags, list) else []
        if old_tags:
            previously_tagged += 1

        result = apply_tags_to_row(row)
        tagged_results.append(result)

        # Track changes for dry-run mode
        new_tags: List[str] = result["tags_final"]
        if dry_run and len(changes) < max_changes:
            # Check if tags changed (compare as sets for content equality)
            if set(old_tags) != set(new_tags):
                changes.append(
                    {
                        "date": row.get("date", ""),
                        "merchant_raw": row.get("merchant_raw", ""),
                        "current_tags": old_tags,
                        "new_tags": new_tags,
                    }
                )

    # Create DataFrame from results
    results_df = pl.DataFrame(tagged_results)

    # Update original DataFrame with tagging results (v3 schema)
    df = df.with_columns(
        [
            results_df["category_rule"].alias("category_rule"),
            results_df["category_final"].alias("category_final"),
            results_df["tags_rule"].alias("tags_rule"),
            results_df["tags_final"].alias("tags_final"),
            results_df["confidence"].alias("confidence"),
            results_df["needs_review"].alias("needs_review"),
        ]
    )

    # Calculate statistics
    tagged_count = df.filter(pl.col("tags_final").list.len() > 0).height
    total = len(df)
    empty_count = total - tagged_count
    coverage = (tagged_count / total * 100) if total > 0 else 0

    # Write updated DataFrame back to CSV partitions (skip if dry_run)
    if not dry_run:
        # Group by year/month and write each partition
        df = df.with_columns(
            [
                pl.col("date").str.strptime(pl.Date, "%Y-%m-%d").dt.year().alias("_year"),
                pl.col("date").str.strptime(pl.Date, "%Y-%m-%d").dt.month().alias("_month"),
            ]
        )

        for (year, month), group_df in df.group_by(["_year", "_month"]):
            # Remove temporary columns
            partition_df = group_df.drop(["_year", "_month"])
            csv_transactions.write_month(csv_base_dir, partition_df, year, month)

        logger.info(f"Tagging complete: {tagged_count}/{total} tagged ({coverage:.1f}% coverage)")
    else:
        logger.info(f"Dry-run complete: {tagged_count}/{total} would be tagged ({coverage:.1f}%)")

    final_result = {
        "total": total,
        "tagged": tagged_count,
        "untagged": empty_count,
        "coverage_pct": coverage,
    }  # type: Dict[str, Any]

    if dry_run:
        final_result["previously_tagged"] = previously_tagged
        final_result["changes"] = changes

    return final_result


def run_tagging(
    csv_base_dir: Path,
    rules_path: Path,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """
    Main entry point for tagging pipeline.

    Loads rules from YAML file and applies them to all transactions
    in CSV partitions.

    Args:
        csv_base_dir: Base directory for CSV partitions
        rules_path: Path to rules.yaml file
        dry_run: If True, calculate changes without writing to CSV

    Returns:
        Summary dict with counts and coverage:
        {
            'total': int,
            'tagged': int,
            'untagged': int,
            'coverage_pct': float,
            'previously_tagged': int,  # (dry_run only)
            'changes': list,           # (dry_run only)
        }

    Example:
        >>> from pathlib import Path
        >>> result = run_tagging(
        ...     Path('data/transactions'),
        ...     Path('data/rules.yaml')
        ... )
        >>> print(f"Coverage: {result['coverage_pct']:.1f}%")
    """
    # Load rules
    rules = load_rules(rules_path)
    logger.info(f"Loaded {len(rules)} rules from {rules_path}")

    if not rules:
        logger.warning("No rules loaded. Transactions will not be tagged.")
        result: Dict[str, Any] = {"total": 0, "tagged": 0, "untagged": 0, "coverage_pct": 0.0}
        if dry_run:
            result["previously_tagged"] = 0
            result["changes"] = []
        return result

    # Apply rules
    return tag_all_transactions(csv_base_dir, rules, dry_run=dry_run)
