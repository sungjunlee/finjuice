"""ZIP password detection and prompting for Banksalad import archives.

Encryption-flag inspection and interactive password prompts live here.
Archive extraction orchestration stays in
:mod:`finjuice.pipeline.cli.commands.import_cmd.zip_extraction`, which
re-exports these names so existing callers can keep importing from that
module.
"""

import logging
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


def _zip_info_requires_password(info: zipfile.ZipInfo) -> bool:
    """Return True when a ZIP member advertises encryption."""
    return bool((info.flag_bits & 0x1) or (info.flag_bits & 0x40))


def _zip_file_requires_password(zf: zipfile.ZipFile) -> bool:
    """Return True when any member in an open ZIP is encrypted."""
    return any(_zip_info_requires_password(info) for info in zf.infolist())


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
