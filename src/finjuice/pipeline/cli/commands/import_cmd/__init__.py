"""Import command stable entrypoint and thin Typer wrapper."""

from pathlib import Path
from typing import Annotated, Optional

import typer

from finjuice.pipeline.cli.output import ErrorCode
from finjuice.pipeline.config import Config

from .copying import import_xlsx_files
from .options import ImportOptions
from .pipeline import run_full_pipeline
from .rendering import (
    ImportErrorContext,
    _build_import_result,
    _raise_import_error,
    emit_import_result,
    format_size,
)
from .result import ImportResult
from .setup import is_first_run
from .use_case import ImportDependencies
from .use_case import run_import as _run_import
from .zip_extraction import _cleanup_temp_dirs, _zip_requires_password, extract_xlsx_from_zip

__all__ = [
    "ImportOptions",
    "ImportErrorContext",
    "ImportResult",
    "_build_import_result",
    "_cleanup_temp_dirs",
    "_raise_import_error",
    "_zip_requires_password",
    "extract_xlsx_from_zip",
    "format_size",
    "import_xlsx_files",
    "is_first_run",
    "register_import_command",
    "run_full_pipeline",
    "run_import",
]


def _dependencies() -> ImportDependencies:
    """Build dependencies from package globals for testability."""
    return ImportDependencies(
        is_first_run=is_first_run,
        import_xlsx_files=import_xlsx_files,
        extract_xlsx_from_zip=extract_xlsx_from_zip,
        zip_requires_password=_zip_requires_password,
        run_full_pipeline=run_full_pipeline,
    )


def run_import(options: ImportOptions) -> ImportResult:
    """Run the focused import use case."""
    return _run_import(options, dependencies=_dependencies())


def register_import_command(app: typer.Typer) -> None:
    """Register the import command with the Typer app."""

    @app.command(name="import", rich_help_panel="Commands")
    def import_files(  # noqa: PLR0913 - Typer command signature mirrors public CLI flags.
        ctx: typer.Context,
        files: Annotated[
            Optional[list[Path]],
            typer.Argument(
                help=(
                    "XLSX or ZIP file(s) to import. "
                    "Pass one or more paths, or use --file for a single XLSX."
                ),
            ),
        ] = None,
        file: Annotated[
            Optional[Path],
            typer.Option(
                "--file",
                help="XLSX file to import without prompts.",
            ),
        ] = None,
        force: Annotated[
            bool,
            typer.Option(
                "--force",
                "-f",
                help="Overwrite existing files in imports/",
            ),
        ] = False,
        dry_run: Annotated[
            bool,
            typer.Option(
                "--dry-run",
                help="Preview what would be imported without processing",
            ),
        ] = False,
        no_scan: Annotated[
            bool,
            typer.Option(
                "--no-scan",
                help="Disable auto-scan of ~/Downloads for Banksalad files",
            ),
        ] = False,
        password: Annotated[
            Optional[str],
            typer.Option(
                "--password",
                "-p",
                help="Password for encrypted ZIP files. If not provided, prompts interactively.",
                envvar="FINJUICE_ZIP_PASSWORD",
            ),
        ] = None,
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
    ) -> None:
        """
        Import XLSX files and run full pipeline.

        This is the main command for processing new Banksalad exports:
        1. Copy XLSX files to imports/ directory (extracts from ZIP if needed)
        2. Run full pipeline (ingest → tag → transfer → export)

        Supports both XLSX files and password-protected ZIP files from Banksalad.

        Examples:
            # Explicit file option
            finjuice import --file ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx

            # Import and process a single file
            finjuice import ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx

            # Import password-protected ZIP (prompts for password)
            finjuice import ~/Downloads/뱅크샐러드_2024-12-22~2025-12-22.zip

            # Import ZIP with password option
            finjuice import ~/Downloads/*.zip --password 1234

            # Headless ZIP import via environment variable
            FINJUICE_ZIP_PASSWORD=1234 finjuice import ~/Downloads/export.zip --json

            # Preview password-protected ZIP import without processing
            FINJUICE_ZIP_PASSWORD=1234 finjuice import --dry-run ~/Downloads/export.zip --json

            # Import multiple files (XLSX and ZIP mixed)
            finjuice import ~/Downloads/export1.xlsx ~/Downloads/export2.zip

            # Overwrite existing files
            finjuice import --force ~/Downloads/*.xlsx

            # Preview without processing
            finjuice import --dry-run ~/Downloads/*.xlsx
        """
        config = _config_from_context(ctx, json_output=json_output)
        result = run_import(
            ImportOptions(
                ctx=ctx,
                config=config,
                files=tuple(files or ()),
                file=file,
                force=force,
                dry_run=dry_run,
                password=password,
                json_output=json_output,
                no_scan=no_scan,
            )
        )
        emit_import_result(result, json_output=json_output)


def _config_from_context(ctx: typer.Context, *, json_output: bool) -> Config:
    """Return the CLI config from Typer context or exit with an error."""
    config: Config | None = None
    if ctx.obj and "config" in ctx.obj:
        config = ctx.obj["config"]

    if config is None:
        _raise_import_error(
            "Configuration not initialized",
            json_output=json_output,
            context=ImportErrorContext(error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED),
        )

    return config
