"""Human-readable rendering for ``finjuice ingest``.

Owns archive/standard ingest result formatting, dry-run previews, and
Banksalad overview summaries. The Typer command, archive/standard ingest
modes, and JSON payload stay in :mod:`finjuice.pipeline.cli.commands.ingest`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.cli import output


def _render_ingest_archive_result(result: dict[str, Any]) -> None:
    """Render human-readable archive ingest result."""
    s = result["summary"]
    output.success("[OK] Re-import complete:")
    output.info(f"  New transactions: {s['new_transactions']}")
    output.info(f"  Updated: {s['updated']}")
    _render_overview_write_summary(s.get("banksalad_overview"))
    if s["skipped"] > 0:
        output.warning(f"  Skipped: {s['skipped']}")


def _render_ingest_result(result: dict[str, Any]) -> None:
    """Render human-readable standard ingest result."""
    s = result["summary"]
    output.success("[OK] Ingestion complete:")
    output.info(f"  Files processed: {s['files_processed']}")
    output.info(f"  New transactions: {s['new_transactions']}")
    output.info(f"  Updated: {s['updated']}")
    _render_overview_write_summary(s.get("banksalad_overview"))
    if s["failed"] > 0:
        output.error(f"  Failed: {s['failed']}")
        for filename, err in s.get("failed_files", []):
            output.error(f"    - {filename}: {err}")


def _render_archive_dry_run(result: dict[str, Any]) -> None:
    """Render human-readable archive dry-run preview."""
    output.info(f"Previewing archived file_id: {result['from_archive']}")
    _render_ingest_dry_run(result["preview"])


def _render_ingest_dry_run(preview: dict[str, Any]) -> None:
    """Render the human-readable ingest dry-run preview."""
    tx_preview = preview["transactions"]
    asset_preview = preview["asset_snapshots"]
    overview_preview = preview.get("banksalad_overview")

    output.info("[Dry-run Summary]")
    output.info(f"  Source XLSX files found: {preview['files_found']}")
    output.info(f"  Estimated new rows: {tx_preview['estimated_new_rows']}")
    output.info(f"  Dedup skips: {tx_preview['estimated_dedup_skips']}")
    output.info(f"  Validation skips: {tx_preview['validation_skips']}")

    for file_preview in preview["files"]:
        file_name = Path(file_preview["source_file"]).name
        output.info(
            "  "
            f"{file_name}: +{file_preview['transactions']['estimated_new_rows']} rows, "
            f"{file_preview['transactions']['estimated_dedup_skips']} dedup skips"
        )

    affected_partitions = tx_preview["affected_partitions"]
    if affected_partitions:
        output.info("  Affected partitions:")
        for partition in affected_partitions:
            output.info(f"    → {partition}")

    if asset_preview["estimated_new_rows"] > 0 or asset_preview["estimated_dedup_skips"] > 0:
        output.info(
            "  Asset snapshots: "
            f"+{asset_preview['estimated_new_rows']} rows, "
            f"{asset_preview['estimated_dedup_skips']} dedup skips"
        )

    _render_overview_preview_summary(overview_preview)

    if preview["failed"] > 0:
        output.error(f"  Failed previews: {preview['failed']}")
        for filename, err in preview["failed_files"]:
            output.error(f"    - {filename}: {err}")

    output.warning("⚠️  No changes written (dry-run mode)")


def _render_overview_preview_summary(overview_preview: dict[str, Any] | None) -> None:
    """Render privacy-safe Banksalad overview dry-run counts."""
    if not overview_preview:
        return

    total_new = sum(
        int(overview_preview[table_name]["estimated_new_rows"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    total_skipped = sum(
        int(overview_preview[table_name]["estimated_dedup_skips"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    if total_new == 0 and total_skipped == 0 and not overview_preview.get("warnings"):
        return

    output.info(
        "  Banksalad overview: "
        f"+{total_new} rows, {total_skipped} dedup skips "
        "(facts/balance/cashflow)"
    )
    if overview_preview.get("warnings"):
        output.warning(f"  Banksalad overview warnings: {len(overview_preview['warnings'])}")


def _render_overview_write_summary(overview_summary: dict[str, Any] | None) -> None:
    """Render privacy-safe Banksalad overview write counts."""
    if not overview_summary:
        return

    total_inserted = sum(
        int(overview_summary[table_name]["inserted"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    total_skipped = sum(
        int(overview_summary[table_name]["dedup_skips"])
        for table_name in ("overview_facts", "balance", "cashflow")
    )
    if total_inserted == 0 and total_skipped == 0 and not overview_summary.get("warnings"):
        return

    output.info(
        "  Banksalad overview: "
        f"+{total_inserted} rows, {total_skipped} dedup skips "
        "(facts/balance/cashflow)"
    )
    if overview_summary.get("warnings"):
        output.warning(f"  Banksalad overview warnings: {len(overview_summary['warnings'])}")


def _render_standard_dry_run(result: dict[str, Any]) -> None:
    """Render human-readable standard dry-run preview."""
    _render_ingest_dry_run(result["preview"])
