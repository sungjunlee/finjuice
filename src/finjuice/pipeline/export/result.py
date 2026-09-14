"""Core export result computation shared by CLI pipeline entry points.

Size formatting, JSON artifact entries, and dry-run plan helpers live in
:mod:`finjuice.pipeline.export.result_helpers`. XLSX, HTML, and Markdown
output generators live in :mod:`finjuice.pipeline.export.result_outputs`.
Those names are re-exported here so existing callers can keep importing
from this module.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
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
from finjuice.pipeline.export.source import (
    ExportSourceOptions,
    RepositoryExportError,
    RepositoryExportSource,
    load_export_source,
)
from finjuice.pipeline.report_filters import apply_report_filters
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
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
    full_source_df: pl.DataFrame | None = None
    repository_metadata: dict[str, Any] | None = None


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
    *,
    evidence_provider: ActivationEvidenceProvider | None = None,
) -> dict[str, Any]:
    """Compute export output without deciding how it is emitted."""
    source = load_export_source(
        config.data_dir,
        evidence_provider,
        ExportSourceOptions(format_lower, period, _no_filter_requested(ctx), online),
    )
    if source is not None:
        run = ExportRunContext(
            config=config,
            paths=replace(
                _build_export_paths(config),
                today=str(source.metadata["calculation_as_of"] or "undated").replace("-", ""),
            ),
            period=period,
            report_source_df=source.report_frame,
            emit_text=emit_text,
            online=online,
            full_source_df=source.full_frame,
            repository_metadata=source.metadata,
        )
        return _repository_export(run, source, format_lower, auto_open, dry_run)
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

    return _generate_export_result(run, format_lower, auto_open, filters_applied)


def _generate_export_result(
    run: ExportRunContext, format_lower: str, auto_open: bool, filters_applied: int
) -> dict[str, Any]:
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
        "period": run.period,
        "transaction_count": transaction_count,
        "output_files": generated_artifacts,
        "skipped_outputs": skipped_outputs,
        "_filters_applied": filters_applied,
    }


def _repository_export(
    run: ExportRunContext,
    source: RepositoryExportSource,
    format_lower: str,
    auto_open: bool,
    dry_run: bool,
) -> dict[str, Any]:
    try:
        if dry_run:
            count = len(
                source.full_frame if format_lower in {"xlsx", "all"} else source.report_frame
            )
            return _repository_plan(
                run,
                {
                    "command": "export",
                    "dry_run": True,
                    "_filters_applied": source.filters_applied,
                    "_repository_meta": source.metadata,
                    **build_export_plan(
                        run.config.data_dir,
                        run.config.csv_base_dir,
                        format_lower,
                        run.period,
                        transaction_count=count,
                    ),
                },
            )
        return _publish_repository_run(run, source, format_lower, auto_open)
    except Exception:
        raise RepositoryExportError(
            "Repository export could not generate verified artifacts."
        ) from None


def _publish_repository_run(
    run: ExportRunContext, source: RepositoryExportSource, format_lower: str, auto_open: bool
) -> dict[str, Any]:
    from finjuice.pipeline.export.artifacts import publish_repository_export

    export_root = run.paths.export_dir
    export_root.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix=".repository-export-", dir=export_root) as directory:
        staging = Path(directory)
        paths = ExportPaths(staging, staging / "reports", run.paths.today)
        paths.reports_dir.mkdir()
        staged_run = replace(run, paths=paths, emit_text=False)
        result = _generate_export_result(staged_run, format_lower, False, source.filters_applied)
        result["_repository_meta"] = source.metadata
        published: dict[str, Any] = publish_repository_export(
            staging, export_root, result, source.metadata
        )
    if auto_open and format_lower == "html" and _runtime.open_file is not None:
        _open_published_html(published, run.emit_text)
    return published


def _open_published_html(result: dict[str, Any], emit_text: bool) -> None:
    for entry in result.get("output_files", []):
        if entry.get("kind") != "html_report" or not entry.get("available", True):
            continue
        try:
            if _runtime.open_file is not None:
                _runtime.open_file(Path(entry["path"]))
        except Exception:
            _emit_warning("Export completed; the report could not be opened.", emit_text=emit_text)


def _repository_plan(run: ExportRunContext, plan: dict[str, Any]) -> dict[str, Any]:
    """Describe a future isolated run without inspecting old output sizes."""
    if plan["format"] in {"xlsx", "all"}:
        plan["output_files"].append(
            build_output_entry(
                run.paths.export_dir / "transactions.csv",
                "transactions_csv",
                row_count=plan["transaction_count"],
            )
        )
    for key in ("output_files", "skipped_outputs"):
        for item in plan[key]:
            path = Path(item["path"])
            if item["kind"] == "transactions_csv":
                relative = Path("transactions.csv")
            elif item["kind"] == "master_xlsx":
                relative = Path(f"master_{run.paths.today}.xlsx")
            else:
                name = path.name
                if item["kind"] in {"html_report", "markdown_report"}:
                    name = f"report_{run.period or run.paths.today}{path.suffix}"
                relative = Path("reports") / name
            item.update(
                path=str(run.paths.export_dir / "runs" / "<new-run>" / relative),
                would_overwrite=False,
                estimated_size_bytes=None,
                estimated_size_human=None,
            )
    return plan
