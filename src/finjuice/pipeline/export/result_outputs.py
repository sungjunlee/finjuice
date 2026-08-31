"""Format-specific export artifact generators.

Owns XLSX, HTML, and Markdown output generation for one export run.
Runtime configuration and ``_compute_export_result`` stay in
:mod:`finjuice.pipeline.export.result`, which re-exports these names so
existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT
from finjuice.pipeline.export.result_helpers import _REPORT_OUTPUTS, build_output_entry

if TYPE_CHECKING:
    from finjuice.pipeline.export.result import ExportRunContext

logger = logging.getLogger(__name__)


def _generate_xlsx_outputs(run: ExportRunContext) -> tuple[int, list[dict[str, Any]]]:
    """Generate master XLSX and CSV reports."""
    from finjuice.pipeline.constants import REPORTS_COUNT
    from finjuice.pipeline.export.master import export_master_xlsx
    from finjuice.pipeline.export.reports import generate_all_reports
    from finjuice.pipeline.export.result import _emit_info

    master_path = run.paths.export_dir / f"master_{run.paths.today}.xlsx"
    logger.info(f"Exporting master file to: {master_path}")

    _emit_info(f"Exporting master file: {master_path}", emit_text=run.emit_text)
    row_count = export_master_xlsx(run.config.csv_base_dir, master_path)
    generated_artifacts = [
        build_output_entry(
            master_path,
            "master_xlsx",
            estimated_size_bytes=master_path.stat().st_size if master_path.exists() else None,
            row_count=row_count,
        )
    ]

    _emit_info(f"Generating {REPORTS_COUNT} CSV reports...", emit_text=run.emit_text)
    report_summary = generate_all_reports(
        run.config.csv_base_dir,
        run.paths.reports_dir,
        source_df=run.report_source_df,
    )
    for filename, kind in _REPORT_OUTPUTS:
        report_path = run.paths.reports_dir / filename
        if report_path.exists():
            generated_artifacts.append(
                build_output_entry(
                    report_path,
                    kind,
                    estimated_size_bytes=report_path.stat().st_size,
                    row_count=int(report_summary.get(filename.removesuffix(".csv"), 0) or 0),
                )
            )

    return row_count, generated_artifacts


def _generate_html_outputs(
    run: ExportRunContext,
    *,
    auto_open: bool,
    format_lower: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate HTML report output or a skipped-output entry."""
    from finjuice.pipeline.export.result import _emit_info, _emit_warning, _runtime

    generated_artifacts: list[dict[str, Any]] = []
    skipped_outputs: list[dict[str, Any]] = []
    html_path = run.paths.reports_dir / f"report_{run.period or run.paths.today}.html"
    try:
        from finjuice.pipeline.export.html_report import generate_html_report

        logger.info(f"Generating HTML report: {html_path} (online=%s)", run.online)

        _emit_info(f"Generating HTML report: {html_path}", emit_text=run.emit_text)
        generate_html_report(
            csv_base_dir=run.config.csv_base_dir,
            output_path=html_path,
            period=run.period,
            include_charts=True,
            source_df=run.report_source_df,
            offline=not run.online,
        )
        generated_artifacts.append(
            build_output_entry(
                html_path,
                "html_report",
                estimated_size_bytes=html_path.stat().st_size if html_path.exists() else None,
            )
        )

        if auto_open and format_lower == "html":
            opened = _runtime.open_file(html_path) if _runtime.open_file is not None else False
            if opened:
                _emit_info("   📂 Opened in browser", emit_text=run.emit_text)
            else:
                _emit_info(f"   📂 Open manually: {html_path}", emit_text=run.emit_text)

    except ImportError as e:
        skipped_outputs.append(
            build_output_entry(
                html_path,
                "html_report",
                available=False,
                reason=str(e) if str(e) == DUCKDB_INSTALL_HINT else f"missing dependency: {e}",
            )
        )
        _emit_warning(
            str(e)
            if str(e) == DUCKDB_INSTALL_HINT
            else f"⚠️  HTML export skipped (missing dependency): {e}",
            emit_text=run.emit_text,
        )
        _emit_info(
            "   Run 'finjuice doctor' for the exact analytics install command."
            if str(e) == DUCKDB_INSTALL_HINT
            else "   Install with: uv sync --extra templates",
            emit_text=run.emit_text,
        )

    return generated_artifacts, skipped_outputs


def _generate_markdown_outputs(
    run: ExportRunContext,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Generate Markdown report output or a skipped-output entry."""
    from finjuice.pipeline.export.result import _emit_info, _emit_warning

    generated_artifacts: list[dict[str, Any]] = []
    skipped_outputs: list[dict[str, Any]] = []
    md_path = run.paths.reports_dir / f"report_{run.period or run.paths.today}.md"
    try:
        from finjuice.pipeline.export.markdown_report import generate_markdown_report

        logger.info(f"Generating Markdown report: {md_path}")

        _emit_info(f"Generating Markdown report: {md_path}", emit_text=run.emit_text)
        generate_markdown_report(
            csv_base_dir=run.config.csv_base_dir,
            output_path=md_path,
            period=run.period,
            source_df=run.report_source_df,
        )
        generated_artifacts.append(
            build_output_entry(
                md_path,
                "markdown_report",
                estimated_size_bytes=md_path.stat().st_size if md_path.exists() else None,
            )
        )

    except ImportError as e:
        skipped_outputs.append(
            build_output_entry(
                md_path,
                "markdown_report",
                available=False,
                reason=str(e) if str(e) == DUCKDB_INSTALL_HINT else f"missing dependency: {e}",
            )
        )
        _emit_warning(
            str(e)
            if str(e) == DUCKDB_INSTALL_HINT
            else f"⚠️  Markdown export skipped (missing dependency): {e}",
            emit_text=run.emit_text,
        )
        _emit_info(
            "   Run 'finjuice doctor' for the exact analytics install command."
            if str(e) == DUCKDB_INSTALL_HINT
            else "   Install with: uv sync --extra templates",
            emit_text=run.emit_text,
        )

    return generated_artifacts, skipped_outputs
