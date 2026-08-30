"""ZIP member policy and pre-extract validation for Banksalad import archives.

Owns extraction limits, member-type/size/compression checks, ignored OS
metadata, XLSX member listing, and path-traversal validation. Password
prompts and archive extraction stay in
:mod:`finjuice.pipeline.cli.commands.import_cmd.zip_extraction`.
"""

import logging
import zipfile
from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.cli.output import error

logger = logging.getLogger(__name__)


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
    limits: ZipExtractionLimits,
) -> bool:
    """Validate ZIP metadata before any member is extracted."""
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
