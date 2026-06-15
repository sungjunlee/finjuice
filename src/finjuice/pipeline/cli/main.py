"""
CLI for finjuice.

Provides Typer-based commands for the full data pipeline.

Global options:
- --data-dir / -d: Specify data directory (or set FINJUICE_DATA_DIR env var)
- --verbose / -v: Enable DEBUG-level logging
"""

import logging
import sys
from pathlib import Path
from typing import Optional

import click
import typer
from typer.core import TyperGroup

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands import audit
from finjuice.pipeline.cli.commands.assets import assets_app
from finjuice.pipeline.cli.commands.automation import automation_app
from finjuice.pipeline.cli.commands.budget import budget_app
from finjuice.pipeline.cli.commands.checkup import register_checkup_command
from finjuice.pipeline.cli.commands.context import register_context_command
from finjuice.pipeline.cli.commands.doctor import register_doctor_command
from finjuice.pipeline.cli.commands.explain import register_explain_command
from finjuice.pipeline.cli.commands.export_cmd import export_command
from finjuice.pipeline.cli.commands.import_cmd import register_import_command
from finjuice.pipeline.cli.commands.index import register_index_command
from finjuice.pipeline.cli.commands.ingest import ingest_command
from finjuice.pipeline.cli.commands.init import register_init_commands
from finjuice.pipeline.cli.commands.inspect_cmd import inspect_app
from finjuice.pipeline.cli.commands.journal import journal_app
from finjuice.pipeline.cli.commands.manifest import register_manifest_command
from finjuice.pipeline.cli.commands.networth import networth_app
from finjuice.pipeline.cli.commands.open_cmd import register_open_command
from finjuice.pipeline.cli.commands.query import register_query_command
from finjuice.pipeline.cli.commands.refresh_cmd import refresh_command
from finjuice.pipeline.cli.commands.review import review_command
from finjuice.pipeline.cli.commands.rules import rules_app
from finjuice.pipeline.cli.commands.tag import tag_command
from finjuice.pipeline.cli.commands.template_cmd import template_app
from finjuice.pipeline.cli.commands.transfer import transfer_command
from finjuice.pipeline.cli.commands.update_agents import register_update_agents_command
from finjuice.pipeline.cli.commands.validate_cmd import validate_partitions_command
from finjuice.pipeline.cli.commands.workspace_cmd import register_workspace_command
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from finjuice.pipeline.cli.utils import set_log_level
from finjuice.pipeline.config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)
_SUPPRESSED_JSON_LOGGERS = ("finjuice", "duckdb")


class FinjuiceGroup(TyperGroup):
    """Capture raw invocation args for callback-level flag checks."""

    def parse_args(self, ctx: click.Context, args: list[str]) -> list[str]:
        ctx.ensure_object(dict)
        ctx.obj["_raw_args"] = list(args)
        return super().parse_args(ctx, args)


# Create Typer app
app = typer.Typer(
    name="finjuice",
    cls=FinjuiceGroup,
    help="Local-first personal finance pipeline for Banksalad data",
    add_completion=False,
)

# Add subcommand groups
app.add_typer(template_app, name="template", rich_help_panel="Analysis")
app.add_typer(inspect_app, name="inspect", rich_help_panel="Analysis")

# Register import command
register_import_command(app)

# Register core pipeline commands (split from pipeline.py, Issue #269)
app.command(name="tag", rich_help_panel="Commands")(tag_command)
app.command(name="export", rich_help_panel="Commands")(export_command)
app.command(
    name="refresh",
    rich_help_panel="Commands",
    help="Re-process all existing data (ingest → tag → transfer → export).",
    short_help="Re-process all existing data",
)(refresh_command)
# Register query command (Issue #174: finjuice query)
register_query_command(app)

# Register explain command (Issue #176: finjuice explain)
register_explain_command(app)

# Register context command (Issue #431: structured AI prompt context emitter)
register_context_command(app)

# Register checkup command (Issue #466: unified runtime entrypoint)
register_checkup_command(app)

# Register review command (Issue #389: restore deleted review queue)
app.command(name="review", rich_help_panel="Analysis")(review_command)

# Register admin commands split from deprecated AI surface
register_update_agents_command(app)

# Register validate command (Issue #812 extension)
app.command(name="validate", rich_help_panel="Commands")(validate_partitions_command)

# Register init/utility commands (Issue #85: CLI Modularization)
register_init_commands(app)

# Register open command
register_open_command(app)

# Register workspace command
register_workspace_command(app)

# Register doctor command
register_doctor_command(app)

# Register index command (agent-friendly workspace catalog)
register_index_command(app)

# Register manifest command (machine-readable CLI self-description)
register_manifest_command(app)


# Register version command (software + schema version)
@app.command(name="version", rich_help_panel="Admin")
def version_command(
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Show finjuice CLI version and data schema version.

    Examples:
        finjuice version             # text output
        finjuice version --json      # machine-readable JSON
    """
    from finjuice import get_version
    from finjuice.pipeline.cli.output import emit
    from finjuice.pipeline.constants import SCHEMA_VERSION

    result = {
        "finjuice_version": get_version(),
        "schema_version": SCHEMA_VERSION,
    }

    emit(
        result,
        json_output,
        lambda _: typer.echo(
            f"finjuice {result['finjuice_version']} (schema v{result['schema_version']})"
        ),
        command="version",
    )


# Register advanced pipeline commands
app.command(name="ingest", rich_help_panel="Advanced")(ingest_command)
app.command(name="transfer", rich_help_panel="Advanced")(transfer_command)

# Register remaining subcommand groups
app.add_typer(audit.app, name="audit", rich_help_panel="Advanced")
app.add_typer(automation_app, name="automation", rich_help_panel="Commands")
app.add_typer(rules_app, name="rules", rich_help_panel="Commands")
app.add_typer(assets_app, name="assets", rich_help_panel="Analysis")
app.add_typer(networth_app, name="networth", rich_help_panel="Analysis")
app.add_typer(budget_app, name="budget", rich_help_panel="Analysis")
app.add_typer(journal_app, name="journal", rich_help_panel="Commands")


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


def _machine_output_requested(raw_args: list[str] | None = None) -> bool:
    """Return True when the invocation requests machine-readable JSON output."""
    args = raw_args or sys.argv[1:]
    output_json_requested = any(
        (arg in ("--output", "-o") and i + 1 < len(args) and args[i + 1] == "json")
        or arg in ("--output=json", "-o=json")
        for i, arg in enumerate(args)
    )
    return "--json" in args or output_json_requested


def _json_error_command_name(ctx: typer.Context) -> str:
    """Return the best command name for callback-level JSON errors."""
    if ctx.invoked_subcommand:
        return ctx.invoked_subcommand
    if isinstance(ctx.obj, dict):
        raw_args = list(ctx.obj.get("_raw_args", []))
        for arg in raw_args:
            if arg.startswith("-"):
                continue
            return str(arg)
    return "unknown"


def _suppress_logs_for_machine_output(ctx: typer.Context, enabled: bool) -> None:
    """Silence logger noise for machine-readable JSON responses."""
    if not enabled:
        return

    previous_levels = {
        logger_name: logging.getLogger(logger_name).level
        for logger_name in _SUPPRESSED_JSON_LOGGERS
    }

    for logger_name in _SUPPRESSED_JSON_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.CRITICAL + 1)

    def _restore_logger_levels() -> None:
        for logger_name, previous_level in previous_levels.items():
            logging.getLogger(logger_name).setLevel(previous_level)

    ctx.call_on_close(_restore_logger_levels)


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


def _version_callback(value: bool) -> None:
    """Print the CLI version and exit before config validation."""
    if not value:
        return

    from finjuice import get_version

    typer.echo(f"finjuice {get_version()}")
    raise typer.Exit()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show finjuice version and exit. 'finjuice version --json' for machine-readable.",
    ),
    data_dir: Optional[Path] = typer.Option(
        None,
        "--data-dir",
        "-d",
        help=(
            "Data directory path. "
            "Priority: CLI arg > FINJUICE_DATA_DIR env var > ~/.finjuice default. "
            "Example: finjuice --data-dir ~/my-finance-data refresh"
        ),
        envvar="FINJUICE_DATA_DIR",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable DEBUG-level logging",
    ),
    no_filter: bool = typer.Option(
        False,
        "--no-filter",
        help="Disable read-time report_filters for this invocation.",
    ),
) -> None:
    """
    Configure global options for all commands.

    The data directory can be specified in three ways (priority order):
    1. CLI argument: --data-dir /path/to/data
    2. Environment variable: export FINJUICE_DATA_DIR=/path/to/data
    3. Default: ~/.finjuice
    """
    # Skip validation and config setup when help is requested
    # This allows --help to work without a valid data directory
    raw_args = []
    if isinstance(ctx.obj, dict):
        raw_args = list(ctx.obj.get("_raw_args", []))

    ctx.ensure_object(dict)
    ctx.obj["no_filter"] = no_filter
    machine_output = _machine_output_requested(raw_args)

    if machine_output:
        # Suppress all log output for machine-readable JSON mode.
        # Skip set_log_level() entirely so no debug messages leak to stderr.
        _suppress_logs_for_machine_output(ctx, machine_output)
    else:
        set_log_level(verbose)

    # Check captured raw args first (CliRunner/nested commands), then sys.argv for direct CLI usage.
    help_requested = (
        any(arg in ("--help", "-h") for arg in raw_args) or "--help" in sys.argv or "-h" in sys.argv
    )
    utility_without_data_dir_requested = ctx.invoked_subcommand in {"manifest", "inspect"}
    # Also check for resilient_parsing (used during completion/help)
    if help_requested or utility_without_data_dir_requested or ctx.resilient_parsing:
        ctx.obj["config"] = None
        return

    # Create Config instance with specified data directory
    config = Config.from_env(data_dir=data_dir)

    # Validate data directory (will raise on errors)
    try:
        config.validate()
    except (ValueError, PermissionError, FileNotFoundError) as e:
        output.emit_error(
            str(e),
            error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
            exit_code=ExitCode.USAGE_ERROR if machine_output else ExitCode.GENERAL_ERROR,
            json_output=machine_output,
            command=_json_error_command_name(ctx),
        )

    # Store config in context for commands to access
    ctx.ensure_object(dict)
    ctx.obj["config"] = config

    logger.debug("Data directory resolved")

    # Handle no subcommand case (Issue #141)
    if ctx.invoked_subcommand is None:
        # Default: show brief status (CLI convention)
        if not machine_output:
            _show_brief_status(config)
        raise typer.Exit(0)


@app.command(rich_help_panel="Commands")
def status(
    ctx: typer.Context,
    detailed: bool = typer.Option(
        False,
        "--detailed",
        "-d",
        help="상세 통계 포함 (태그별/가맹점별 지출)",
    ),
    top_n: int = typer.Option(
        5,
        "--top",
        "-n",
        help="상세 통계에서 보여줄 상위 항목 수",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Show current data status.

    Displays:
    - Transaction count and date range
    - Last import information
    - Untagged transactions needing review
    - Rules file status

    With --detailed flag:
    - Monthly average income and expense
    - Recent savings rate
    - Top spending categories

    Examples:
        finjuice status             # 기본 상태
        finjuice status --detailed  # 상세 통계 포함
        finjuice status -d -n 10    # 상위 10개 항목
    """
    from finjuice.pipeline.cli.commands.status import status as status_impl

    status_impl(ctx, detailed=detailed, top_n=top_n, json_output=json_output)


def cli_entry() -> None:
    """Entry point for finjuice CLI."""
    app()


if __name__ == "__main__":
    cli_entry()
