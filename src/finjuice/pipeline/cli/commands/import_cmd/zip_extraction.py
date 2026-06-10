"""ZIP extraction helpers for Banksalad import archives."""

import logging
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from prompt_toolkit import PromptSession

from finjuice.pipeline.cli.output import console, error

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PasswordDecision:
    """Password state for one ZIP extraction."""

    password: str | None
    can_extract: bool


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


@dataclass(frozen=True)
class ZipExtractionLimits:
    """Resource limits for ZIP imports.

    Banksalad ZIPs normally contain one compressed XLSX export plus occasional
    OS metadata. The defaults leave room for large personal exports while
    bounding archive shapes that are risky to extract.
    """

    max_members: int = 32
    max_total_uncompressed_bytes: int = 100 * 1024 * 1024
    max_single_member_bytes: int = 50 * 1024 * 1024
    max_compression_ratio: float = 100.0


ZIP_EXTRACTION_LIMITS = ZipExtractionLimits()


def _cleanup_temp_dirs(temp_dirs: list[str]) -> None:
    """Remove temporary ZIP extraction directories."""
    for temp_dir in temp_dirs:
        shutil.rmtree(temp_dir, ignore_errors=True)


def _zip_requires_password(zip_path: Path) -> bool:
    """Return True when any ZIP member is encrypted.

    For unreadable or corrupt archives, return False so the normal extraction
    path can surface the existing detailed error message.
    """
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            return _zip_file_requires_password(zf)
    except (zipfile.BadZipFile, PermissionError, OSError):
        return False


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
        if not _validate_zip_members(zf, zip_path, emit_text=options.emit_text):
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


def _zip_info_requires_password(info: zipfile.ZipInfo) -> bool:
    """Return True when a ZIP member advertises encryption."""
    return bool((info.flag_bits & 0x1) or (info.flag_bits & 0x40))


def _zip_file_requires_password(zf: zipfile.ZipFile) -> bool:
    """Return True when any member in an open ZIP is encrypted."""
    return any(_zip_info_requires_password(info) for info in zf.infolist())


def _xlsx_member_names(zf: zipfile.ZipFile) -> list[str]:
    """Return XLSX member names, excluding macOS metadata."""
    return [
        filename
        for filename in zf.namelist()
        if filename.lower().endswith(".xlsx") and not _is_ignored_metadata_name(filename)
    ]


def _validate_zip_members(
    zf: zipfile.ZipFile,
    zip_path: Path,
    *,
    emit_text: bool,
) -> bool:
    """Validate ZIP metadata before any member is extracted."""
    limits = ZIP_EXTRACTION_LIMITS
    members = zf.infolist()
    if len(members) > limits.max_members:
        return _handle_zip_policy_error(
            zip_path,
            emit_text=emit_text,
            log_reason=f"member count limit exceeded ({len(members)} > {limits.max_members})",
            user_reason="ZIP 항목 수 제한 초과",
        )

    total_uncompressed_bytes = 0
    for member in members:
        if not _is_supported_zip_member(member):
            return _handle_zip_policy_error(
                zip_path,
                emit_text=emit_text,
                log_reason="unsupported member type",
                user_reason="ZIP에 지원하지 않는 항목 포함 (XLSX만 지원)",
            )

        if member.file_size > limits.max_single_member_bytes:
            return _handle_zip_policy_error(
                zip_path,
                emit_text=emit_text,
                log_reason=(
                    "single member size limit exceeded "
                    f"({member.file_size} > {limits.max_single_member_bytes})"
                ),
                user_reason="ZIP 항목 크기 제한 초과",
            )

        total_uncompressed_bytes += member.file_size
        if total_uncompressed_bytes > limits.max_total_uncompressed_bytes:
            return _handle_zip_policy_error(
                zip_path,
                emit_text=emit_text,
                log_reason=(
                    "total uncompressed size limit exceeded "
                    f"({total_uncompressed_bytes} > {limits.max_total_uncompressed_bytes})"
                ),
                user_reason="ZIP 압축 해제 크기 제한 초과",
            )

        if _has_suspicious_compression_ratio(member, limits):
            return _handle_zip_policy_error(
                zip_path,
                emit_text=emit_text,
                log_reason="compression ratio limit exceeded",
                user_reason="ZIP 압축률이 비정상적으로 높음",
            )

    return True


def _is_supported_zip_member(member: zipfile.ZipInfo) -> bool:
    """Return True for XLSX payloads and harmless metadata entries."""
    if member.is_dir():
        return True

    filename = member.filename
    return filename.lower().endswith(".xlsx") or _is_ignored_metadata_name(filename)


def _is_ignored_metadata_name(filename: str) -> bool:
    """Return True for ZIP members that represent harmless OS metadata."""
    normalized = filename.replace("\\", "/")
    relative_name = normalized.lstrip("/")
    parts = [part for part in relative_name.split("/") if part]
    if not parts:
        return False

    basename = parts[-1]
    return parts[0] == "__MACOSX" or basename == ".DS_Store" or basename.startswith("._")


def _has_suspicious_compression_ratio(
    member: zipfile.ZipInfo,
    limits: ZipExtractionLimits,
) -> bool:
    """Return True when ZIP metadata indicates a suspicious expansion ratio."""
    if member.is_dir() or member.file_size <= 0:
        return False
    if member.compress_size <= 0:
        return True

    return member.file_size / member.compress_size > limits.max_compression_ratio


def _handle_zip_policy_error(
    zip_path: Path,
    *,
    emit_text: bool,
    log_reason: str,
    user_reason: str,
) -> bool:
    """Render and log a ZIP policy rejection without exposing member names."""
    logger.debug("Rejected ZIP import: %s - %s", zip_path.name, log_reason)
    if emit_text:
        error(f"{user_reason}: {zip_path.name}", prefix="   ❌")
    return False


def _handle_no_xlsx(zip_path: Path, *, emit_text: bool) -> Path | None:
    """Render and log a ZIP-without-XLSX failure."""
    logger.debug("No XLSX files found in ZIP: %s", zip_path.name)
    if emit_text:
        error(f"ZIP에 XLSX 파일 없음: {zip_path.name}", prefix="   ❌")
    return None


def _decide_password(
    zf: zipfile.ZipFile,
    zip_path: Path,
    *,
    password: str | None,
    interactive: bool,
    emit_text: bool,
) -> _PasswordDecision:
    """Resolve whether extraction can proceed and which password to use."""
    if not _zip_file_requires_password(zf):
        return _PasswordDecision(password=password, can_extract=True)

    if password is not None:
        return _PasswordDecision(password=password, can_extract=True)

    if interactive:
        if emit_text:
            console.print(f"   🔐 [bold]{zip_path.name}[/bold]")
        _ps: PromptSession[str] = PromptSession(is_password=True)
        password = _ps.prompt("      ZIP 암호: ")
        if not password:
            return _PasswordDecision(password=None, can_extract=False)
        return _PasswordDecision(password=password, can_extract=True)

    logger.debug("Password required for encrypted ZIP: %s", zip_path.name)
    if emit_text:
        error(f"암호 필요: {zip_path.name} (--password 옵션 사용)", prefix="   ❌")
    return _PasswordDecision(password=None, can_extract=False)


def _re_prompt_password(
    zip_path: Path,
    remaining: int,
    *,
    emit_text: bool,
) -> str | None:
    """Re-prompt for ZIP password after a wrong attempt with remaining count."""
    if emit_text:
        error(f"잘못된 암호: {zip_path.name} ({remaining}회 남음)", prefix="   ❌")
    _ps: PromptSession[str] = PromptSession(is_password=True)
    pwd = _ps.prompt("      ZIP 암호 (그만두려면 Enter): ")
    if not pwd:
        return None
    return pwd


def _validate_member_paths(
    zf: zipfile.ZipFile,
    zip_path: Path,
    temp_dir_path: Path,
    *,
    emit_text: bool,
) -> bool:
    """Validate ZIP member targets to prevent directory traversal."""
    for member in zf.infolist():
        member_path = (temp_dir_path / member.filename).resolve()
        if member_path.is_relative_to(temp_dir_path):
            continue

        logger.warning("SECURITY: Path traversal attempt detected in ZIP archive")
        if emit_text:
            error(
                f"보안 오류: ZIP에 잘못된 경로 포함 ({zip_path.name})",
                prefix="   ❌",
            )
        return False

    return True


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
