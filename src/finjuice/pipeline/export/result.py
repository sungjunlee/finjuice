"""Core export result computation shared by CLI pipeline entry points."""

from __future__ import annotations

import importlib
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import polars as pl

from finjuice.pipeline.analytics.duckdb_layer import DUCKDB_INSTALL_HINT
from finjuice.pipeline.constants import STANDARD_CSV_REPORTS
from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters

logger = logging.getLogger(__name__)

# Derived from the canonical registry so it cannot drift from
# generate_all_reports() output (Issue #746).
_REPORT_OUTPUTS = tuple(
    (filename, f"{report_key}_report") for report_key, filename in STANDARD_CSV_REPORTS
)

InfoFn = Callable[[str], None]
WarningFn = Callable[[str], None]
OpenFileFn = Callable[[Path], bool]
ReportFiltersLoader = Callable[[Any, Any, bool], ReportFilters]


@dataclass(frozen=True)
class ExportResultRuntime:
    """CLI-provided side-effect hooks for the otherwise core export computation."""

    info: InfoFn | None = None
    warning: WarningFn | None = None
    open_file: OpenFileFn | None = None
    report_filters_loader: ReportFiltersLoader | None = None


@dataclass(frozen=True)
class ExportPaths:
    """Resolved export output directories and date suffix."""

    export_dir: Path
    reports_dir: Path
    today: str


@dataclass(frozen=True)
class ExportRunContext:
    """Shared state for one export computation."""

    config: Any
    paths: ExportPaths
    period: Optional[str]
    report_source_df: pl.DataFrame | None
    emit_text: bool
    online: bool = False


_runtime = ExportResultRuntime()


def configure_export_result_runtime(
    *,
    info: InfoFn | None = None,
    warning: WarningFn | None = None,
    open_file: OpenFileFn | None = None,
    report_filters_loader: ReportFiltersLoader | None = None,
) -> None:
    """Configure optional CLI side-effect hooks used by export result computation."""
    global _runtime
    _runtime = ExportResultRuntime(
        info=info,
        warning=warning,
        open_file=open_file,
        report_filters_loader=report_filters_loader,
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


def _no_filter_requested(ctx: Any) -> bool:
    """Return True when a CLI-like context disabled report filters."""
    if ctx is None:
        return False
    root_obj = ctx.find_root().obj
    return bool(((root_obj or ctx.obj) or {}).get("no_filter", False))


def _load_report_filters_for_export(
    ctx: Any,
    config: Any,
    *,
    json_output: bool,
) -> ReportFilters:
    """Load report filters using CLI hooks when present, otherwise core loading."""
    if _runtime.report_filters_loader is not None:
        return _runtime.report_filters_loader(ctx, config, json_output)
    if _no_filter_requested(ctx):
        return ReportFilters()
    return load_report_filters(config.rules_file)


def _load_filtered_report_export_source(
    ctx: Any,
    config: Any,
    *,
    json_output: bool,
    format_lower: str,
    period: Optional[str],
) -> tuple[pl.DataFrame | None, int]:
    """Load the filtered DataFrame used by report-style export outputs."""
    report_filters = _load_report_filters_for_export(
        ctx,
        config,
        json_output=json_output,
    )
    if report_filters.is_empty():
        return None, 0

    from finjuice.pipeline.storage import csv_transactions

    source_df = csv_transactions.get_all_transactions(config.csv_base_dir)
    if source_df.is_empty():
        return source_df, 0

    scope_period = period if format_lower in {"html", "md"} else None
    if scope_period is not None:
        source_df = source_df.filter(pl.col("date").str.starts_with(scope_period))

    filtered_df, filters_applied = apply_report_filters(source_df, report_filters)
    return filtered_df, filters_applied


def _emit_info(message: str, *, emit_text: bool) -> None:
    """Emit an informational line when a CLI runtime is configured."""
    if emit_text and _runtime.info is not None:
        _runtime.info(message)


def _emit_warning(message: str, *, emit_text: bool) -> None:
    """Emit a warning line when a CLI runtime is configured."""
    if emit_text and _runtime.warning is not None:
        _runtime.warning(message)


def _build_export_paths(config: Any) -> ExportPaths:
    """Resolve export output paths for one run."""
    export_dir = config.data_dir / "exports"
    return ExportPaths(
        export_dir=export_dir,
        reports_dir=export_dir / "reports",
        today=datetime.now().strftime("%Y%m%d"),
    )


def _generate_xlsx_outputs(run: ExportRunContext) -> tuple[int, list[dict[str, Any]]]:
    """Generate master XLSX and CSV reports."""
    from finjuice.pipeline.constants import REPORTS_COUNT
    from finjuice.pipeline.export.master import export_master_xlsx
    from finjuice.pipeline.export.reports import generate_all_reports

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


def _resolve_transaction_count(
    run: ExportRunContext,
    *,
    format_lower: str,
    transaction_count: int | None,
) -> int:
    """Resolve the transaction count for the export result payload."""
    if transaction_count is not None:
        return transaction_count
    if run.report_source_df is not None:
        return len(run.report_source_df)
    if format_lower in {"html", "md"} and run.period is not None:
        from finjuice.pipeline.export.aggregations import load_transactions

        return len(load_transactions(run.config.csv_base_dir, run.period))

    from finjuice.pipeline.storage import csv_partition

    return len(csv_partition.get_all_transactions(run.config.csv_base_dir, columns=["row_hash"]))


def _compute_export_result(  # noqa: PLR0913 - moved helper keeps the existing private signature.
    ctx: Any,
    config: Any,
    format_lower: str,
    period: Optional[str],
    auto_open: bool,
    dry_run: bool,
    emit_text: bool = True,
    online: bool = False,
) -> dict[str, Any]:
    """Compute export output without deciding how it is emitted."""
    report_source_df, filters_applied = _load_filtered_report_export_source(
        ctx,
        config,
        json_output=not emit_text,
        format_lower=format_lower,
        period=period,
    )

    paths = _build_export_paths(config)

    if dry_run:
        plan = build_export_plan(config.data_dir, config.csv_base_dir, format_lower, period)
        return {
            "command": "export",
            "dry_run": True,
            "_filters_applied": filters_applied,
            **plan,
        }

    paths.export_dir.mkdir(parents=True, exist_ok=True)
    paths.reports_dir.mkdir(parents=True, exist_ok=True)
    run = ExportRunContext(
        config=config,
        paths=paths,
        period=period,
        report_source_df=report_source_df,
        emit_text=emit_text,
        online=online,
    )

    generated_artifacts: list[dict[str, Any]] = []
    skipped_outputs: list[dict[str, Any]] = []
    transaction_count: int | None = None

    if format_lower in {"xlsx", "all"}:
        transaction_count, xlsx_artifacts = _generate_xlsx_outputs(run)
        generated_artifacts.extend(xlsx_artifacts)

    if format_lower in {"html", "all"}:
        html_artifacts, html_skipped = _generate_html_outputs(
            run,
            auto_open=auto_open,
            format_lower=format_lower,
        )
        generated_artifacts.extend(html_artifacts)
        skipped_outputs.extend(html_skipped)

    if format_lower in {"md", "all"}:
        md_artifacts, md_skipped = _generate_markdown_outputs(run)
        generated_artifacts.extend(md_artifacts)
        skipped_outputs.extend(md_skipped)

    transaction_count = _resolve_transaction_count(
        run,
        format_lower=format_lower,
        transaction_count=transaction_count,
    )

    return {
        "command": "export",
        "dry_run": False,
        "format": format_lower,
        "period": period,
        "transaction_count": transaction_count,
        "output_files": generated_artifacts,
        "skipped_outputs": skipped_outputs,
        "_filters_applied": filters_applied,
    }
