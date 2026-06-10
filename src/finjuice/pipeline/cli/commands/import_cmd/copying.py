"""File copy helpers for import command inputs."""

import shutil
from pathlib import Path

from .result import ImportFileResults


def import_xlsx_files(
    files: list[Path],
    imports_dir: Path,
    force: bool = False,
    dry_run: bool = False,
) -> ImportFileResults:
    """
    Import XLSX files to imports/ directory.

    Args:
        files: List of XLSX file paths to import.
        imports_dir: Target imports directory.
        force: Overwrite existing files if True.
        dry_run: Preview only, don't actually copy.

    Returns:
        Summary dict with imported, skipped, and errors lists.
    """
    results: ImportFileResults = {"imported": [], "skipped": [], "errors": []}

    if not dry_run:
        imports_dir.mkdir(parents=True, exist_ok=True)

    for file_path in files:
        resolved_file = file_path.expanduser().resolve()
        _import_one_xlsx(resolved_file, imports_dir, results, force=force, dry_run=dry_run)

    return results


def _import_one_xlsx(
    file_path: Path,
    imports_dir: Path,
    results: ImportFileResults,
    *,
    force: bool,
    dry_run: bool,
) -> None:
    """Import one XLSX path and append the outcome to results."""
    if not file_path.exists():
        results["errors"].append((file_path, "파일 없음"))
        return

    if file_path.suffix.lower() != ".xlsx":
        results["errors"].append((file_path, "XLSX 파일 아님"))
        return

    dest_path = imports_dir / file_path.name

    if dest_path.resolve() == file_path:
        results["skipped"].append((file_path, "이미 imports 디렉토리에 있음"))
        return

    if dest_path.exists() and not force:
        results["skipped"].append((file_path, "이미 존재하는 파일"))
        return

    if dry_run:
        results["imported"].append((file_path, dest_path))
        return

    try:
        shutil.copy2(file_path, dest_path)
    except OSError as exc:
        results["errors"].append((file_path, str(exc)))
        return

    results["imported"].append((file_path, dest_path))
