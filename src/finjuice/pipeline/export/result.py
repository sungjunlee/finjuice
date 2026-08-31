"""Core export result computation shared by CLI pipeline entry points.

Size formatting, JSON artifact entries, and dry-run plan helpers live in
:mod:`finjuice.pipeline.export.result_helpers`. XLSX, HTML, and Markdown
output generators live in :mod:`finjuice.pipeline.export.result_outputs`.
Those names are re-exported here so existing callers can keep importing
from this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import polars as pl

from finjuice.pipeline.export.result_helpers import (
    _REPORT_OUTPUTS,  # noqa: F401 — re-exported for existing result imports
    build_export_plan,
    build_output_entry,  # noqa: F401 — re-exported for existing result imports
    estimate_output_size_bytes,  # noqa: F401 — re-exported for existing result imports
    format_size_bytes,  # noqa: F401 — re-exported for existing result imports
)
from finjuice.pipeline.export.result_outputs import (
    _generate_html_outputs,
    _generate_markdown_outputs,
    _generate_xlsx_outputs,
)
from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.tagging.models import ReportFilters
from finjuice.pipeline.tagging.rules_yaml_io import load_report_filters

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
