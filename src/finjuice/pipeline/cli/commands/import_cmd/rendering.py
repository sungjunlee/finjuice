"""Rendering and JSON payload assembly for the import command."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, NoReturn

import typer

from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    console,
    emit,
    emit_error,
    error,
    panel_info,
    success,
    warning,
)
from finjuice.pipeline.config import Config

from .result import ImportFileResults, ImportResult


@dataclass(frozen=True)
class ImportErrorContext:
    """Structured options for an import command error exit."""

    error_code: ErrorCode | str = ErrorCode.GENERAL_ERROR
    exit_code: ExitCode | int = ExitCode.GENERAL_ERROR
    suggestion: str | None = None
    hints: tuple[str, ...] = ()


def format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.2f} MB"


def _raise_import_error(
    message: str,
    *,
    json_output: bool,
    context: ImportErrorContext | None = None,
) -> NoReturn:
    """Exit the import command with Rich text or structured JSON."""
    resolved_context = context or ImportErrorContext()
    if json_output:
        emit_error(
            message,
            error_code=resolved_context.error_code,
            exit_code=resolved_context.exit_code,
            suggestion=resolved_context.suggestion,
            json_output=True,
            command="import",
        )

    error(message)
    for hint in resolved_context.hints:
        console.print(hint, style="dim")
    raise typer.Exit(code=1)


def _build_import_result(
    summary: dict[str, Any],
    imported_count: int,
    skipped_count: int,
    error_count: int,
) -> dict[str, Any]:
    """Build the structured import result payload."""
    result = {
        "files_processed": imported_count,
        "files_skipped": skipped_count,
        "errors": error_count,
        "transactions_inserted": summary.get("ingest", {}).get("inserted", 0),
        "pipeline_result": {
            "ingest": summary.get("ingest", {}),
            "tag": {key: value for key, value in summary.get("tag", {}).items()},
            "transfer": summary.get("transfer", {}),
            "export": summary.get("export", {}),
        },
    }
    if "steps" in summary:
        result["steps"] = summary["steps"]
    return result


def render_first_run_initialized(data_dir: Path) -> None:
    """Render the first-run initialization message."""
    success(f"데이터 디렉터리 초기화됨: {data_dir}")
    panel_info(
        f"데이터 위치: {data_dir}",
        title="초기 설정",
    )


def render_zip_processing_start(zip_count: int) -> None:
    """Render ZIP processing header."""
    console.print(f"\n📦 [bold]ZIP 파일 {zip_count}개 처리 중...[/bold]\n")


def render_zip_dry_run(zip_path: Path) -> None:
    """Render ZIP dry-run extraction preview."""
    console.print(f"   📦 Would extract: {zip_path.name}")


def render_zip_extracted(zip_path: Path, extracted_path: Path) -> None:
    """Render successful ZIP extraction."""
    success(f"압축 해제: {zip_path.name} → {extracted_path.name}", prefix="   ✅")


def render_zip_processing_end() -> None:
    """Render spacing after ZIP processing."""
    console.print()


def render_import_mode(*, dry_run: bool, file_count: int) -> None:
    """Render copy step mode header."""
    if dry_run:
        console.print("\n🔍 [bold]미리보기 모드[/bold] - 파일을 처리하지 않습니다\n")
        return

    console.print(f"\n📥 [bold]파일 {file_count}개 가져오는 중...[/bold]\n")


def render_copy_results(results: ImportFileResults, *, dry_run: bool) -> None:
    """Render per-file copy outcomes."""
    action = "복사 예정" if dry_run else "복사됨"

    for src, _dest in results["imported"]:
        size = format_size(src.stat().st_size)
        success(f"{action}: {src.name} ({size})", prefix="   ✅")

    for src, reason in results["skipped"]:
        warning(f"건너뜀: {src.name} ({reason})", prefix="   ⏭️")

    for src, error_message in results["errors"]:
        error(f"오류: {src} - {error_message}", prefix="   ❌")


def render_before_copy_error() -> None:
    """Render spacing before a copy-step error."""
    console.print()


def render_all_files_skipped(skipped_count: int, *, dry_run: bool) -> None:
    """Render the all-skipped copy summary."""
    console.print()
    warning(
        f"파일 {skipped_count}개가 이미 존재합니다 (덮어쓰려면 --force 사용)",
        prefix="⏭️",
    )
    if not dry_run:
        console.print("\n💡 기존 파일로 파이프라인 실행 중...\n")


def render_dry_run_summary(imported_count: int, imports_dir: Path) -> None:
    """Render dry-run summary."""
    console.print(f"\n📋 파일 {imported_count}개를 {imports_dir}로 가져올 예정")


def render_final_summary(
    summary: dict[str, Any],
    *,
    imported_count: int,
    config: Config,
) -> None:
    """Render final import and pipeline summary."""
    console.print("=" * 50)
    success("완료!")
    console.print("=" * 50)
    console.print(f"   📥 파일: {imported_count}개 복사됨")
    console.print(f"   📊 거래: {summary['ingest']['inserted']}건 추가")
    tag_count = summary["tag"]["tagged"]
    tag_pct = summary["tag"]["coverage_pct"]
    console.print(f"   🏷️  태깅: {tag_count}건 ({tag_pct:.1f}%)")
    console.print(f"   🔄 이체: {summary['transfer']['pairs']}쌍")
    console.print(f"   📁 결과: {summary['master_path'].name}")
    console.print(f"   📈 리포트: {config.reports_dir}")


def render_scan_banner() -> None:
    """Render the download scan banner."""
    console.print("🔍 ~/Downloads에서 뱅크샐러드 내보내기 파일 찾는 중...")


def render_scan_no_files() -> None:
    """Render message when no Banksalad files found in Downloads."""
    console.print("   뱅크샐러드 내보내기 파일을 찾을 수 없습니다.", style="dim")


def render_scan_single_file(file_path: Path) -> None:
    """Render single file found in Downloads."""
    size = format_size(file_path.stat().st_size)
    console.print(f"   발견: {file_path.name} ({size})")


def render_scan_multiple_files(candidates: list[Path]) -> None:
    """Render multiple files found in Downloads."""
    for i, path in enumerate(candidates, 1):
        size = format_size(path.stat().st_size)
        console.print(f"   {i}. {path.name} ({size})")


def render_before_pipeline_error() -> None:
    """Render spacing before a pipeline error."""
    console.print()


def emit_import_result(result: ImportResult, *, json_output: bool) -> None:
    """Emit the final import result payload."""
    emit(
        result.payload,
        json_output,
        lambda _: None,
        command="import",
    )
