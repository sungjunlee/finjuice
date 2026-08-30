"""Artifact description and dry-run plan helpers for export results.

Owns size formatting, JSON artifact entries, and the read-only export
manifest. Runtime configuration and ``_compute_export_result`` stay in
:mod:`finjuice.pipeline.export.result`, which re-exports the public names
used by existing callers.
"""

from __future__ import annotations

import importlib
from datetime import datetime
from pathlib import Path
from typing import Any

from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT
from finjuice.pipeline.constants import STANDARD_CSV_REPORTS

# Derived from the canonical registry so it cannot drift from
# generate_all_reports() output (Issue #746).
_REPORT_OUTPUTS = tuple(
    (filename, f"{report_key}_report") for report_key, filename in STANDARD_CSV_REPORTS
)


def format_size_bytes(size_bytes: int | None) -> str | None:
    """Convert a byte count to a concise human-readable string."""
    if size_bytes is None:
        return None
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def estimate_output_size_bytes(path: Path) -> int | None:
    """Estimate output size from an existing artifact when one is available."""
    if path.exists():
        return path.stat().st_size

    if path.suffix == ".xlsx" and path.parent.exists():
        candidates = sorted(path.parent.glob("master_*.xlsx"))
        if candidates:
            return candidates[-1].stat().st_size

    return None


def build_output_entry(  # noqa: PLR0913 - JSON artifact entries expose these stable fields.
    path: Path,
    kind: str,
    *,
    estimated_size_bytes: int | None = None,
    row_count: int | None = None,
    available: bool = True,
    reason: str | None = None,
) -> dict[str, Any]:
    """Build a JSON-friendly description of an export artifact."""
    return {
        "path": str(path),
        "kind": kind,
        "would_overwrite": path.exists(),
        "estimated_size_bytes": estimated_size_bytes,
        "estimated_size_human": format_size_bytes(estimated_size_bytes),
        "row_count": row_count,
        "available": available,
        "reason": reason,
    }


def build_export_plan(
    data_dir: Path,
    csv_base_dir: Path,
    format_lower: str,
    period: str | None,
) -> dict[str, Any]:
    """Build a read-only export manifest for text and JSON dry-run output."""
    from finjuice.pipeline.storage import csv_partition

    export_dir = data_dir / "exports"
    reports_dir = export_dir / "reports"
    today = datetime.now().strftime("%Y%m%d")
    transaction_count = len(csv_partition.get_all_transactions(csv_base_dir, columns=["row_hash"]))
    output_files: list[dict[str, Any]] = []
    skipped_outputs: list[dict[str, Any]] = []

    if format_lower in {"xlsx", "all"}:
        master_path = export_dir / f"master_{today}.xlsx"
        output_files.append(
            build_output_entry(
                master_path,
                "master_xlsx",
                estimated_size_bytes=estimate_output_size_bytes(master_path),
                row_count=transaction_count,
            )
        )
        for filename, kind in _REPORT_OUTPUTS:
            report_path = reports_dir / filename
            output_files.append(
                build_output_entry(
                    report_path,
                    kind,
                    estimated_size_bytes=estimate_output_size_bytes(report_path),
                )
            )

    if format_lower in {"html", "all"}:
        html_path = reports_dir / f"report_{period or today}.html"
        try:
            importlib.import_module("finjuice.pipeline.export.html_report")
        except ImportError as exc:
            reason = str(exc) if str(exc) == DUCKDB_INSTALL_HINT else f"missing dependency: {exc}"
            skipped_outputs.append(
                build_output_entry(
                    html_path,
                    "html_report",
                    available=False,
                    reason=reason,
                )
            )
        else:
            output_files.append(
                build_output_entry(
                    html_path,
                    "html_report",
                    estimated_size_bytes=estimate_output_size_bytes(html_path),
                )
            )

    if format_lower in {"md", "all"}:
        md_path = reports_dir / f"report_{period or today}.md"
        try:
            importlib.import_module("finjuice.pipeline.export.markdown_report")
        except ImportError as exc:
            reason = str(exc) if str(exc) == DUCKDB_INSTALL_HINT else f"missing dependency: {exc}"
            skipped_outputs.append(
                build_output_entry(
                    md_path,
                    "markdown_report",
                    available=False,
                    reason=reason,
                )
            )
        else:
            output_files.append(
                build_output_entry(
                    md_path,
                    "markdown_report",
                    estimated_size_bytes=estimate_output_size_bytes(md_path),
                )
            )

    return {
        "format": format_lower,
        "period": period,
        "transaction_count": transaction_count,
        "output_files": output_files,
        "skipped_outputs": skipped_outputs,
    }
