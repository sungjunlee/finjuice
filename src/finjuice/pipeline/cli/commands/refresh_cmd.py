"""Refresh (full pipeline) command for finjuice CLI.

Runs the complete pipeline: ingest → tag → transfer → export.
"""

import logging
from typing import Any

import typer
from rich.progress import Progress, SpinnerColumn, TextColumn

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import run_full_pipeline_orchestrator
from finjuice.pipeline.cli.export_runtime import configure_cli_export_result_runtime
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit, emit_error
from finjuice.pipeline.cli.utils import get_config, warn_on_schema_mismatch
from finjuice.pipeline.constants import SCHEMA_VERSION
from finjuice.pipeline.metadata import write_schema_version

logger = logging.getLogger(__name__)


def _compute_full_pipeline_result(
    ctx: typer.Context,
    config: Any,
    json_output: bool,
    *,
    command_name: str,
) -> dict[str, Any]:
    """Run all pipeline steps and return a single structured result."""
    if json_output:
        return run_full_pipeline_orchestrator(ctx, config, command_name=command_name)

    step_descriptions = {
        "ingest": "[cyan]{index}/{total} XLSX 파일 가져오는 중...",
        "tag": "[cyan]{index}/{total} 규칙 적용 중...",
        "transfer": "[cyan]{index}/{total} 이체 감지 중...",
        "export": "[cyan]{index}/{total} 리포트 생성 중...",
    }

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        transient=False,
    ) as progress:
        task = progress.add_task("[cyan]파이프라인 실행 중...", total=4)

        def _on_step_start(step_name: str, index: int, total: int) -> None:
            description = step_descriptions.get(step_name, "[cyan]파이프라인 실행 중...")
            progress.update(task, description=description.format(index=index, total=total))

        def _on_step_complete(
            step_name: str,
            step_result: dict[str, Any],
            _index: int,
            _total: int,
        ) -> None:
            progress.advance(task)

            if step_name == "ingest":
                ingest_summary = step_result["summary"]
                if ingest_summary["failed"] > 0:
                    output.warning(f"⚠️  가져오기 완료 (실패: {ingest_summary['failed']}개 파일)")
                    for filename, error_msg in ingest_summary.get("failed_files", []):
                        output.error(f"   - {filename}: {error_msg}")
                else:
                    output.info(
                        f"   ✓ ingest: {ingest_summary['new_transactions']}건 추가, "
                        f"{ingest_summary['updated']}건 업데이트"
                    )
                return

            if step_name == "tag":
                if step_result.get("skipped"):
                    output.warning("   ⚠️  건너뜀: rules.yaml 파일 없음")
                    output.info(
                        f"   'finjuice init' 실행하여 {config.data_dir / 'rules.yaml'} 생성"
                    )
                else:
                    output.info(
                        f"   ✓ tag: {step_result['tagged']}건 태깅, "
                        f"{step_result['untagged']}건 미태깅"
                    )
                return

            if step_name == "transfer":
                output.info(
                    f"   ✓ transfer: {step_result['pairs_found']}개 쌍 감지, "
                    f"{step_result['confirmed_transfer_rows']}건 확정, "
                    f"{step_result['unconfirmed_candidate_rows']}건 후보 유지"
                )
                return

            if step_name == "export":
                output.info("   ✓ export: master + reports 생성")

        return run_full_pipeline_orchestrator(
            ctx,
            config,
            command_name=command_name,
            export_emit_text=True,
            on_step_start=_on_step_start,
            on_step_complete=_on_step_complete,
        )


def _render_full_pipeline_result(result: dict[str, Any], config: Any) -> None:
    """Render final human-readable full-pipeline summary."""
    from finjuice.pipeline.constants import REPORTS_COUNT

    ingest_summary = result["steps"]["ingest"]["summary"]
    tag_result = result["steps"]["tag"]
    transfer_result = result["steps"]["transfer"]

    output.section("파이프라인 완료")
    output.info(f"   새 거래: {ingest_summary['new_transactions']}건 처리됨")
    output.info(f"   태깅: {tag_result.get('tagged', 0)}건")
    output.info(f"   이체: {transfer_result['pairs_found']}개 쌍 감지")
    output.info(f"   리포트: {REPORTS_COUNT}개 파일 생성")
    output.success(f"📁 결과 확인: {config.data_dir / 'exports'}")


def run_full_pipeline_command(
    ctx: typer.Context,
    json_output: bool,
    *,
    command_name: str,
) -> None:
    """Execute the shared full-pipeline flow for refresh/all aliases."""
    config = get_config(ctx)
    configure_cli_export_result_runtime()

    try:
        warn_on_schema_mismatch(config.data_dir)

        if not json_output:
            output.section("전체 파이프라인")

        result = _compute_full_pipeline_result(
            ctx,
            config,
            json_output,
            command_name=command_name,
        )
        write_schema_version(config.data_dir, SCHEMA_VERSION)
        emit(
            result,
            json_output,
            lambda _: _render_full_pipeline_result(result, config),
            command=command_name,
        )

    except typer.Exit:
        raise
    except KeyboardInterrupt:
        emit_error(
            "사용자가 파이프라인을 취소했습니다.",
            error_code=ErrorCode.USER_CANCELLED,
            exit_code=ExitCode.USER_CANCELLED,
            json_output=json_output,
            command=command_name,
        )
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Pipeline failed: {type(e).__name__}: {e}", exc_info=True)
        emit_error(
            f"파이프라인 실패: {e}",
            error_code=ErrorCode.GENERAL_ERROR,
            json_output=json_output,
            command=command_name,
        )


def refresh_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Re-process all existing data (ingest → tag → transfer → export).

    This is the recommended way to re-run the full pipeline against your current
    imports and transaction partitions.

    Examples:
        # Run with default location
        finjuice refresh

        # Run with custom data directory
        finjuice --data-dir ~/my-finance-data refresh
    """
    run_full_pipeline_command(ctx, json_output, command_name="refresh")
