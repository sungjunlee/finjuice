"""
Directory creation helpers with platform-aware error reporting.

Split out of ``config.py``; used to safely create data directories with
TOCTOU protection and helpful diagnostics on failure.
"""

import errno
import logging
import platform
import shutil
from pathlib import Path

# Logger for directory helpers
logger = logging.getLogger(__name__)


def _get_platform_suggestions(path: Path) -> str:
    """
    Generate platform-specific permission fix suggestions.

    Args:
        path: Directory path that failed to create

    Returns:
        Formatted suggestion string with emoji-based formatting

    Examples:
        >>> _get_platform_suggestions(Path("/data"))
        '💡 Suggestions:\\n  1. Check permissions: ls -la /data\\n  ...'
    """
    system = platform.system()

    if system == "Darwin":  # macOS
        return (
            f"💡 Suggestions:\n"
            f"  1. Check permissions: ls -la {path.parent}\n"
            f"  2. Fix permissions: chmod u+w {path.parent}\n"
            f"  3. Try alternative: ~/.finjuice"
        )
    elif system == "Linux":
        return (
            f"💡 Suggestions:\n"
            f"  1. Check permissions: ls -la {path.parent}\n"
            f"  2. Fix permissions: chmod u+w {path.parent}\n"
            f"  3. Try alternative: ~/.finjuice"
        )
    elif system == "Windows":
        return (
            "💡 Suggestions:\n"
            "  1. Right-click folder → Properties → Security\n"
            "  2. Ensure your user has 'Write' permission\n"
            "  3. Try alternative: %USERPROFILE%\\.finjuice"
        )
    else:
        # Fallback for unknown platforms
        return (
            f"💡 Suggestions:\n"
            f"  1. Check directory permissions\n"
            f"  2. Ensure you have write access to {path.parent}"
        )


def _get_disk_space_info(path: Path) -> str:
    """
    Get disk space information for error messages.

    Args:
        path: Directory path to check

    Returns:
        Formatted disk space info with emoji

    Examples:
        >>> _get_disk_space_info(Path("/data"))
        '📊 Free space: 12.34 GB'
    """
    try:
        usage = shutil.disk_usage(path.parent)
        free_gb = usage.free / (1024**3)
        return f"📊 Free space: {free_gb:.2f} GB"
    except OSError:
        return "📊 Free space: Unable to determine"


def _ensure_directory(path: Path, context: str = "data directory") -> Path:
    """
    Atomically create directory with TOCTOU race condition protection.

    Security Guarantees:
        - Atomic creation via Path.mkdir(exist_ok=True)
        - Post-creation validation to detect malicious tampering
        - Concurrent access from multiple processes is safe

    TOCTOU Protection:
        This function is designed to be safe against time-of-check-time-of-use
        race conditions. It uses atomic operations and validates the result.

        Attack Scenario Prevented:
            1. Attacker creates symlink to sensitive file (e.g., /etc/passwd)
            2. Between check and creation, symlink points to malicious target
            3. Post-validation detects that path is not a directory

    Args:
        path: Directory path to create
        context: Human-readable description for error messages (e.g., "import directory")

    Returns:
        Validated directory path

    Raises:
        ValueError: If path exists but is not a directory (TOCTOU attack detected)
        PermissionError: If lacking permissions to create directory
        OSError: If creation fails for other reasons (disk full, etc.)

    Examples:
        >>> _ensure_directory(Path("/tmp/test"), "test directory")
        PosixPath('/tmp/test')

        >>> # Concurrent creation is safe
        >>> # Multiple threads can call this simultaneously without errors

    See Also:
        - https://owasp.org/www-community/vulnerabilities/Time_of_check_to_time_of_use
        - https://docs.python.org/3/library/pathlib.html#pathlib.Path.mkdir
    """
    logger.debug(f"Ensuring {context} exists: {path}")

    try:
        # Atomic operation - safe from TOCTOU
        path.mkdir(parents=True, exist_ok=True)

        # Post-creation validation (detect race condition tampering)
        # Check for symlink attacks: is_symlink() returns True even for symlinks to directories
        if not path.is_dir() or path.is_symlink():
            raise ValueError(
                f"TOCTOU race condition detected: {path} exists but is not a directory "
                f"or is a symlink. This may indicate a security issue (symlink attack)."
            )

        logger.info(f"Successfully ensured {context}: {path}")
        return path

    except FileExistsError:
        # File exists but is not a directory (e.g., regular file, symlink, etc.)
        # This happens when mkdir() encounters a non-directory at the path
        if path.is_symlink():
            raise ValueError(
                f"TOCTOU race condition detected: {path} is a symlink. "
                f"This may indicate a security issue (symlink attack)."
            )
        else:
            raise ValueError(
                f"Path exists but is not a directory: {path}. Expected directory for {context}."
            )

    except PermissionError as e:
        suggestions = _get_platform_suggestions(path)
        raise PermissionError(
            f"❌ Cannot create {context} at {path}\n\n"
            f"💡 Reason: Permission denied\n\n"
            f"{suggestions}\n\n"
            f"🔧 For more help: finjuice init --help"
        ) from e

    except OSError as e:
        # Check for disk space issue using errno for locale-independence
        is_disk_full = hasattr(e, "errno") and e.errno in (
            errno.ENOSPC,
            getattr(errno, "EDQUOT", None),
        )

        # Fallback to string matching for edge cases
        error_msg = str(e)
        if is_disk_full or "No space left" in error_msg or "Disk quota exceeded" in error_msg:
            disk_info = _get_disk_space_info(path)
            raise OSError(
                f"❌ Cannot create {context} at {path}\n\n"
                f"💡 Reason: No disk space available\n"
                f"{disk_info}\n\n"
                f"🔧 Try:\n"
                f"  1. Free up disk space\n"
                f"  2. Use alternative: finjuice init --data-dir /other/path"
            ) from e
        else:
            # Generic OSError
            raise OSError(
                f"❌ Failed to create {context} at {path}\n\n"
                f"💡 Reason: {error_msg}\n\n"
                f"🔧 Try:\n"
                f"  1. Check directory permissions\n"
                f"  2. Ensure parent directory exists\n"
                f"  3. Use alternative path: finjuice init --data-dir /other/path"
            ) from e
