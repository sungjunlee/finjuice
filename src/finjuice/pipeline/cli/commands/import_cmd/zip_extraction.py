"""ZIP extraction orchestration for Banksalad import archives.

Member policy, size limits, and path-traversal checks live in
:mod:`finjuice.pipeline.cli.commands.import_cmd.zip_policy`.

Password detection and prompting live in
:mod:`finjuice.pipeline.cli.commands.import_cmd.zip_extraction_helpers`
and are re-exported here so existing callers can keep importing from this
module.
"""

import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.cli.output import console, error

from .zip_extraction_helpers import (
    _decide_password,
    _PasswordDecision,  # noqa: F401 — re-exported for existing zip_extraction imports
    _re_prompt_password,
    _zip_file_requires_password,  # noqa: F401 — re-exported for existing zip_extraction imports
    _zip_info_requires_password,  # noqa: F401 — re-exported for existing zip_extraction imports
    _zip_requires_password,  # noqa: F401 — re-exported for existing zip_extraction imports
)
from .zip_policy import (
    ZIP_EXTRACTION_LIMITS,
    ZipExtractionLimits,  # noqa: F401 — re-exported for existing zip_extraction imports
    _validate_member_paths,
    _validate_zip_members,
    _xlsx_member_names,
)

logger = logging.getLogger(__name__)


@dataclass
class _ActivePassword:
    """Mutable password holder used for sanitized exception handling."""

    value: str | None


@dataclass(frozen=True)
class _ZipExtractionOptions:
    """Options used while extracting an open ZIP archive."""

    password: str | None
    interactive: bool
    emit_text: bool


def _cleanup_temp_dirs(temp_dirs: list[str]) -> None:
    """Remove temporary ZIP extraction directories."""
    for temp_dir in temp_dirs:
        shutil.rmtree(temp_dir, ignore_errors=True)


def extract_xlsx_from_zip(
    zip_path: Path,
    password: str | None = None,
    interactive: bool = True,
    emit_text: bool = True,
) -> Path | None:
    """
    Extract XLSX file from a password-protected ZIP file.

    Args:
        zip_path: Path to the ZIP file.
        password: ZIP password. If None, prompts interactively when needed.
        interactive: Whether to prompt for password if not provided.
        emit_text: Whether to print Rich output for errors/prompts.

    Returns:
        Path to extracted XLSX file in temp directory, or None if failed.
    """
    active_password = _ActivePassword(password)

    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return _extract_xlsx_from_open_zip(
                zf,
                zip_path,
                options=_ZipExtractionOptions(
                    password=password,
                    interactive=interactive,
                    emit_text=emit_text,
                ),
                active_password=active_password,
            )

    except (zipfile.BadZipFile, PermissionError, OSError) as exc:
        return _handle_known_zip_error(zip_path, exc, temp_dir=None, emit_text=emit_text)
    # intended catch-all for unexpected ZIP errors; specific types handled above
    except Exception as exc:
        return _handle_unexpected_zip_error(
            zip_path,
            exc,
            password=active_password.value,
            temp_dir=None,
            emit_text=emit_text,
        )


def _extract_xlsx_from_open_zip(
    zf: zipfile.ZipFile,
    zip_path: Path,
    *,
    options: _ZipExtractionOptions,
    active_password: _ActivePassword,
) -> Path | None:
    """Extract the first XLSX member from an already-open ZIP archive."""
    temp_dir: str | None = None
    try:
        if not _validate_zip_members(
            zf,
            zip_path,
            emit_text=options.emit_text,
            limits=ZIP_EXTRACTION_LIMITS,
        ):
            return None

        xlsx_files = _xlsx_member_names(zf)
        if not xlsx_files:
            return _handle_no_xlsx(zip_path, emit_text=options.emit_text)

        password_decision = _decide_password(
            zf,
            zip_path,
            password=options.password,
            interactive=options.interactive,
            emit_text=options.emit_text,
        )
        active_password.value = password_decision.password
        if not password_decision.can_extract:
            return None

        temp_dir = tempfile.mkdtemp(prefix="finjuice_zip_")
        temp_dir_path = Path(temp_dir).resolve()
        if not _validate_member_paths(zf, zip_path, temp_dir_path, emit_text=options.emit_text):
            shutil.rmtree(temp_dir, ignore_errors=True)
            return None

        password = password_decision.password
        max_attempts = 3 if options.interactive and options.password is None else 1
        for attempt in range(max_attempts):
            if _extract_all(
                zf,
                zip_path,
                temp_dir,
                password=password,
                emit_text=options.emit_text,
            ):
                return _resolved_extracted_xlsx(
                    zip_path,
                    temp_dir,
                    xlsx_files[0],
                    emit_text=options.emit_text,
                )

            if attempt < max_attempts - 1:
                remaining = max_attempts - attempt - 1
                password = _re_prompt_password(zip_path, remaining, emit_text=options.emit_text)
                active_password.value = password
                if password is None:
                    return None
                shutil.rmtree(temp_dir, ignore_errors=True)
                temp_dir = tempfile.mkdtemp(prefix="finjuice_zip_")
            else:
                return None
        return None
    # I/O errors from mkdtemp, resolve, rmtree, exists; _extract_all handles RuntimeError
    except OSError:
        if temp_dir:
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise


def _handle_no_xlsx(zip_path: Path, *, emit_text: bool) -> Path | None:
    """Render and log a ZIP-without-XLSX failure."""
    logger.debug("No XLSX files found in ZIP: %s", zip_path.name)
    if emit_text:
        error(f"ZIP에 XLSX 파일 없음: {zip_path.name}", prefix="   ❌")
    return None


def _extract_all(
    zf: zipfile.ZipFile,
    zip_path: Path,
    temp_dir: str,
    *,
    password: str | None,
    emit_text: bool,
) -> bool:
    """Extract all ZIP members with password-aware error handling."""
    pwd_bytes = password.encode() if password else None

    try:
        zf.extractall(temp_dir, pwd=pwd_bytes)
    except RuntimeError as exc:
        if _is_password_runtime_error(exc):
            logger.debug("Incorrect password for ZIP: %s", zip_path.name)
            shutil.rmtree(temp_dir, ignore_errors=True)
            return False

        sanitized_msg = _sanitize_error_message(str(exc), password=password)
        logger.debug("RuntimeError during ZIP extraction: %s", sanitized_msg)
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise RuntimeError(sanitized_msg) from None

    return True


def _is_password_runtime_error(exc: RuntimeError) -> bool:
    """Return True when a ZIP RuntimeError is password-related."""
    error_msg = str(exc).lower()
    password_errors = ("bad password", "password required", "encrypted")
    return any(text in error_msg for text in password_errors)


def _sanitize_error_message(message: str, *, password: str | None) -> str:
    """Replace a password value in an error message if present."""
    if password and password in message:
        return message.replace(password, "***")
    return message


def _resolved_extracted_xlsx(
    zip_path: Path,
    temp_dir: str,
    xlsx_member: str,
    *,
    emit_text: bool,
) -> Path | None:
    """Return the extracted XLSX path if it exists."""
    xlsx_path = Path(temp_dir) / xlsx_member
    if xlsx_path.exists():
        return xlsx_path

    logger.debug("Extraction succeeded but XLSX not found: %s", zip_path.name)
    if emit_text:
        error(f"압축 해제 실패: {zip_path.name}", prefix="   ❌")
    shutil.rmtree(temp_dir, ignore_errors=True)
    return None


def _handle_known_zip_error(
    zip_path: Path,
    exc: Exception,
    *,
    temp_dir: str | None,
    emit_text: bool,
) -> Path | None:
    """Handle expected ZIP/file-system failures."""
    if isinstance(exc, zipfile.BadZipFile):
        logger.debug("Corrupted ZIP file: %s", zip_path.name)
        if emit_text:
            error(f"손상된 ZIP 파일: {zip_path.name}", prefix="   ❌")
            console.print("      💡 파일을 다시 다운로드해보세요", style="dim")
    elif isinstance(exc, PermissionError):
        logger.debug("Permission denied reading ZIP: %s", zip_path.name)
        if emit_text:
            error(f"파일 읽기 권한 없음: {zip_path.name}", prefix="   ❌")
    else:
        logger.debug("OS error during ZIP extraction: %s", zip_path.name)
        if emit_text:
            error(f"파일 시스템 오류: {zip_path.name}", prefix="   ❌")

    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return None


def _handle_unexpected_zip_error(
    zip_path: Path,
    exc: Exception,
    *,
    password: str | None,
    temp_dir: str | None,
    emit_text: bool,
) -> Path | None:
    """Handle unexpected ZIP extraction failures without leaking passwords."""
    error_msg = _sanitize_error_message(str(exc), password=password)
    if emit_text:
        error(f"ZIP 처리 오류: {zip_path.name}", prefix="   ❌")
    logger.error("ZIP extraction failed: %s - %s: %s", zip_path.name, type(exc).__name__, error_msg)
    if temp_dir:
        shutil.rmtree(temp_dir, ignore_errors=True)
    return None
