"""No-args brief status helpers for the finjuice CLI root command.

Owns data-directory initialization checks, partition/import counts, and the
CLI-style status shown when ``finjuice`` is run without a subcommand. The
Typer app, global callback, and command registration stay in
:mod:`finjuice.pipeline.cli.main`.
"""

from __future__ import annotations

from finjuice.pipeline.config import Config


def _is_data_directory_initialized(config: Config) -> bool:
    """Return True when the standard finjuice data layout exists."""
    required_paths = (
        config.import_dir,
        config.csv_base_dir,
        config.export_dir,
        config.metadata_dir,
    )
    return (
        config.data_dir.exists()
        and config.rules_file.exists()
        and all(path.exists() for path in required_paths)
    )


def _count_transaction_partitions(config: Config) -> int:
    """Count CSV partition files under transactions/."""
    if not config.csv_base_dir.exists():
        return 0
    return len(list(config.csv_base_dir.rglob("*.csv")))


def _count_pending_imports(config: Config) -> int:
    """Count pending XLSX files already staged in imports/."""
    if not config.import_dir.exists():
        return 0
    return len(list(config.import_dir.glob("*.xlsx")))


def _show_brief_status(config: Config) -> None:
    """
    Show brief CLI-style status output.

    This is shown when finjuice is run without arguments (Issue #141).
    """
    from finjuice import get_version
    from finjuice.pipeline.cli.output import console

    is_initialized = _is_data_directory_initialized(config)
    transaction_partitions = _count_transaction_partitions(config)
    pending_imports = _count_pending_imports(config)

    console.print()
    console.print(f"[bold cyan]📊 finjuice[/bold cyan] [dim]v{get_version()}[/dim]")
    console.print()

    # Show data location
    console.print(f"[bold]데이터 위치:[/bold] [cyan]{config.data_dir}[/cyan]")

    # Show status based on state
    if not is_initialized:
        console.print("[yellow]상태: 초기화 필요[/yellow]")
    elif transaction_partitions == 0:
        console.print("[yellow]상태: 거래 데이터 없음[/yellow]")
    else:
        console.print(f"[green]거래 CSV 파티션:[/green] {transaction_partitions}개")

    if pending_imports > 0:
        console.print(f"[yellow]미처리 파일:[/yellow] {pending_imports}개")

    # Show useful commands
    console.print()
    console.print("[bold]💡 자주 쓰는 명령어:[/bold]")

    if not is_initialized:
        console.print("  [cyan]finjuice import <file.xlsx>[/cyan]   파일 가져오기 + 초기화")
    elif pending_imports > 0:
        console.print("  [cyan]finjuice refresh[/cyan]         파이프라인 실행")
    else:
        console.print("  [cyan]finjuice import <file.xlsx>[/cyan]   파일 가져오기 + 처리")

    console.print("  [cyan]finjuice status[/cyan]          상태 확인")
    console.print("  [cyan]finjuice query --help[/cyan]    SQL 조회")
    console.print("  [cyan]finjuice explain QUERY[/cyan]   태깅 규칙 추적")
    console.print()
    console.print("[dim]'finjuice --help'로 전체 명령어를 확인하세요.[/dim]")
    console.print()
