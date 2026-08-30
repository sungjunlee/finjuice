"""XLSX/ZIP path-splitting helper for the import use case.

ZIP extraction itself lives in
:mod:`finjuice.pipeline.cli.commands.import_cmd.zip_inputs`.
The orchestrator in
:mod:`finjuice.pipeline.cli.commands.import_cmd.use_case`
re-exports ``_split_import_inputs`` so existing callers can keep
importing it from that module.
"""

from __future__ import annotations

from pathlib import Path


def _split_import_inputs(resolved_files: list[Path]) -> tuple[list[Path], list[Path]]:
    """Split resolved import inputs into XLSX and ZIP paths."""
    xlsx_files: list[Path] = []
    zip_files: list[Path] = []
    for resolved_file in resolved_files:
        if resolved_file.suffix.lower() == ".zip":
            zip_files.append(resolved_file)
        else:
            xlsx_files.append(resolved_file)
    return xlsx_files, zip_files
