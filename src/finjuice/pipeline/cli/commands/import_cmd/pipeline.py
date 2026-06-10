"""Full-pipeline orchestration for the import command."""

from datetime import datetime
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.export_runtime import configure_cli_export_result_runtime
from finjuice.pipeline.cli.output import console
from finjuice.pipeline.config import Config


def run_full_pipeline(
    ctx: typer.Context,
    config: Config,
    *,
    emit_text: bool = True,
) -> dict[str, Any]:
    """Run the full pipeline (ingest → tag → transfer → export)."""
    from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import (
        run_full_pipeline_orchestrator,
    )

    configure_cli_export_result_runtime()

    if emit_text:
        console.print("\n🔄 [bold]파이프라인 실행 중...[/bold]\n")

    orchestrated = run_full_pipeline_orchestrator(
        ctx,
        config,
        command_name="import",
        export_emit_text=emit_text,
        on_step_start=_render_step_start if emit_text else None,
        on_step_complete=_step_complete_renderer(config) if emit_text else None,
    )
    return _pipeline_summary(orchestrated["steps"], config)


def _render_step_start(step_name: str, index: int, _total: int) -> None:
    """Render a full-pipeline step header."""
    step_titles = {
        "ingest": "데이터 가져오기",
        "tag": "태그 적용",
        "transfer": "이체 감지",
        "export": "내보내기",
    }
    console.print(f"=== {index}/4단계: {step_titles[step_name]} ===")


def _step_complete_renderer(config: Config):
    """Return a callback that renders full-pipeline step results."""

    def _on_step_complete(
        step_name: str,
        step_result: dict[str, Any],
        _index: int,
        _total: int,
    ) -> None:
        _render_step_complete(step_name, step_result, config)

    return _on_step_complete


def _render_step_complete(
    step_name: str,
    step_result: dict[str, Any],
    config: Config,
) -> None:
    """Render a full-pipeline step result."""
    if step_name == "ingest":
        _render_ingest_step(step_result)
        return
    if step_name == "tag":
        _render_tag_step(step_result)
        return
    if step_name == "transfer":
        console.print(f"   → {step_result['pairs_found']}쌍 감지\n")
        return
    if step_name == "export":
        _render_export_step(step_result, config)


def _render_ingest_step(step_result: dict[str, Any]) -> None:
    """Render ingest step output."""
    ingest_info = step_result["summary"]
    console.print(
        f"   → {ingest_info['new_transactions']}건 추가, {ingest_info['updated']}건 업데이트\n"
    )


def _render_tag_step(step_result: dict[str, Any]) -> None:
    """Render tag step output."""
    if step_result.get("skipped"):
        console.print("   → 규칙 파일 없음 (건너뜀)\n", style="yellow")
        return

    console.print(f"   → {step_result['tagged']}건 태깅됨 ({step_result['coverage_pct']:.1f}%)\n")


def _render_export_step(step_result: dict[str, Any], config: Config) -> None:
    """Render export step output."""
    output_files = step_result.get("output_files", [])
    report_count = _csv_report_count(output_files)
    row_count = int(step_result.get("transaction_count", 0) or 0)
    master_file = _master_xlsx_path(output_files, config)
    if row_count == 0:
        console.print("   → 데이터 없음\n", style="yellow")
        return

    console.print(f"   → {master_file.name} ({row_count}건), {report_count}개 리포트\n")


def _pipeline_summary(steps: dict[str, dict[str, Any]], config: Config) -> dict[str, Any]:
    """Convert orchestrator steps into the import command summary shape."""
    ingest_step = steps["ingest"]
    tag_step = steps["tag"]
    transfer_step = steps["transfer"]
    export_step = steps["export"]
    output_files = export_step.get("output_files", [])

    return {
        "ingest": {
            "files": int(ingest_step["summary"]["files_processed"]),
            "inserted": int(ingest_step["summary"]["new_transactions"]),
            "updated": int(ingest_step["summary"]["updated"]),
            "failed": int(ingest_step["summary"]["failed"]),
            "failed_files": ingest_step["summary"].get("failed_files", []),
        },
        "tag": {
            "total": int(tag_step.get("total", 0)),
            "tagged": int(tag_step.get("tagged", 0)),
            "untagged": int(tag_step.get("untagged", 0)),
            "coverage_pct": float(tag_step.get("coverage_pct", 0.0)),
        },
        "transfer": {
            "pairs": int(transfer_step.get("pairs_found", 0)),
            "paired": int(transfer_step.get("pairs_linked", 0)),
        },
        "export": {
            "rows": int(export_step.get("transaction_count", 0) or 0),
            "reports": _csv_report_count(output_files),
        },
        "master_path": _master_xlsx_path(output_files, config),
        "steps": steps,
    }


def _csv_report_count(output_files: Any) -> int:
    """Return the number of CSV report files in an export output list."""
    if not isinstance(output_files, list):
        return 0
    return sum(1 for item in output_files if str(item.get("path", "")).endswith(".csv"))


def _master_xlsx_path(output_files: Any, config: Config) -> Path:
    """Return the master XLSX output path from export output metadata."""
    if isinstance(output_files, list):
        for item in output_files:
            if item.get("kind") == "master_xlsx":
                return Path(str(item["path"]))
    return config.export_dir / f"master_{datetime.now().strftime('%Y%m%d')}.xlsx"
