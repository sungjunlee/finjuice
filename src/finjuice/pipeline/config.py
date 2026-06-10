"""
Configuration and path management for finjuice.

Provides centralized configuration with support for:
- 4-tier precedence: CLI > ENV > Config file > default path
- Environment variables
- Intelligent defaults
- Automatic directory creation
"""

import errno
import logging
import os
import platform
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .config_file import load_config
from .config_schema import AutomationConfig

# Logger for config module
logger = logging.getLogger(__name__)


def _get_program_repo_root(start: Path | None = None) -> Path | None:
    """Return the source checkout root when running from a finjuice git repo."""
    probe = (start or Path(__file__).resolve()).resolve()
    candidates = (probe, *probe.parents) if probe.is_dir() else (probe.parent, *probe.parents)
    for candidate in candidates:
        if (
            (candidate / ".git").exists()
            and (candidate / "pyproject.toml").is_file()
            and (candidate / "src" / "finjuice").is_dir()
        ):
            return candidate
    return None


def is_inside_program_repo(path: Path) -> bool:
    """Return whether path points inside the finjuice program repository checkout."""
    repo_root = _get_program_repo_root()
    if repo_root is None:
        return False

    resolved_path = path.expanduser().resolve()
    return resolved_path == repo_root or resolved_path.is_relative_to(repo_root)


def validate_not_program_repo_path(path: Path, *, context: str) -> None:
    """Reject private-data paths inside this program repository checkout."""
    if not is_inside_program_repo(path):
        return

    raise ValueError(
        f"Refusing to use {context} inside the finjuice program repository: "
        f"{path.expanduser().resolve()}\n"
        "Financial data must live outside the program repo, for example ~/.finjuice "
        "or another private data directory."
    )


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


def get_default_data_dir() -> Path:
    """
    Get the default data directory using the unified finjuice home directory.

    The default path is always `~/.finjuice`, regardless of platform.

    Returns:
        Path: The default data directory path

    Examples:
        >>> get_default_data_dir()
        PosixPath('/Users/user/.finjuice')
    """
    return Path.home() / ".finjuice"


@dataclass
class Config:
    """
    Application configuration for finance data pipeline.

    Manages paths for data directories, imports, exports, rules, and local storage.
    Supports 4-tier configuration precedence and automatic directory creation.

    Attributes:
        data_dir: Root directory for all finance data.
                  Priority (highest to lowest):
                  1. Explicit argument (from CLI --data-dir)
                  2. FINJUICE_DATA_DIR environment variable
                  3. Config file (~/.finjuice/config.toml)
                  4. Default path (~/.finjuice)
        automation: One-shot automation defaults loaded from config.toml
    """

    data_dir: Path
    automation: AutomationConfig = field(default_factory=AutomationConfig)

    @property
    def import_dir(self) -> Path:
        """Directory for XLSX import files from Banksalad."""
        return self.data_dir / "imports"

    @property
    def export_dir(self) -> Path:
        """Directory for exported master files and reports."""
        return self.data_dir / "exports"

    @property
    def reports_dir(self) -> Path:
        """Directory for generated CSV reports."""
        return self.export_dir / "reports"

    @property
    def rules_file(self) -> Path:
        """Path to rules.yaml file."""
        return self.data_dir / "rules.yaml"

    @property
    def assets_file(self) -> Path:
        """Path to assets.yaml file."""
        return self.data_dir / "assets.yaml"

    @property
    def goals_file(self) -> Path:
        """Path to goals.yaml file."""
        return self.data_dir / "goals.yaml"

    @property
    def scenarios_file(self) -> Path:
        """Path to scenarios.yaml file."""
        return self.data_dir / "scenarios.yaml"

    @property
    def csv_base_dir(self) -> Path:
        """Base directory for CSV partitions (year/month structure)."""
        return self.data_dir / "transactions"

    @property
    def metadata_dir(self) -> Path:
        """Directory for metadata files (import history, workspaces, etc.)."""
        return self.data_dir / "metadata"

    @property
    def journal_dir(self) -> Path:
        """Directory for markdown journal entries."""
        if journal_dir := os.getenv("FINJUICE_JOURNAL_DIR"):
            return Path(journal_dir).expanduser().resolve()

        parent = self.data_dir.parent
        if parent != self.data_dir:
            return (parent / "_journal").resolve()

        return (self.data_dir / "_journal").resolve()

    @classmethod
    def from_env(cls, data_dir: Path | str | None = None) -> "Config":
        """
        Create Config from environment with 4-tier precedence order.

        Priority (highest to lowest):
        1. Explicit data_dir argument (from CLI --data-dir)
        2. FINJUICE_DATA_DIR environment variable
        3. Config file (~/.finjuice/config.toml)
        4. Default path (~/.finjuice)

        Args:
            data_dir: Optional explicit path (overrides all other sources)

        Returns:
            Config instance with resolved data_dir

        Examples:
            >>> # Use unified default (first run, no config file)
            >>> config = Config.from_env()

            >>> # Use config file (if exists)
            >>> config = Config.from_env()  # Loads from ~/.finjuice/config.toml

            >>> # Use environment variable (overrides config file)
            >>> os.environ['FINJUICE_DATA_DIR'] = '/custom/path'
            >>> config = Config.from_env()

            >>> # Override with explicit path (from CLI, highest priority)
            >>> config = Config.from_env(data_dir='/explicit/path')
        """
        user_config = None
        automation = AutomationConfig()

        # Load config once so non-data settings remain stable even when a
        # higher-precedence data_dir source overrides the configured path.
        try:
            user_config = load_config()
            if user_config is not None:
                automation = user_config.automation
                logger.debug("Loaded automation settings from config file")
        except (OSError, PermissionError, ValueError) as e:
            # Log warning but don't fail - fall back to defaults
            logger.warning(f"Failed to load config file, using default automation: {e}")

        resolved_dir: Optional[Path] = None

        # Priority 1: Explicit argument (from CLI --data-dir)
        if data_dir is not None:
            resolved_dir = Path(data_dir).expanduser().resolve()
            return cls(data_dir=resolved_dir, automation=automation)

        # Priority 2: Environment variable (FINJUICE_DATA_DIR)
        env_dir = os.getenv("FINJUICE_DATA_DIR")
        if env_dir:
            resolved_dir = Path(env_dir).expanduser().resolve()
            return cls(data_dir=resolved_dir, automation=automation)

        # Priority 3: Config file
        if user_config is not None:
            resolved_dir = user_config.get_data_path()
            logger.debug(f"Loaded data directory from config file: {resolved_dir}")
            return cls(data_dir=resolved_dir, automation=automation)

        # Priority 4: Unified default
        resolved_dir = get_default_data_dir()
        logger.debug(f"Using default data directory: {resolved_dir}")
        return cls(data_dir=resolved_dir, automation=automation)

    def validate(self) -> None:
        """
        Validate data directory path.

        Checks:
        - Path is not a file (must be a directory or not exist)
        - Parent directory exists (for absolute paths)
        - Path is writable (if exists) or parent is writable (if creating)

        Raises:
            ValueError: If data_dir is a file (not a directory)
            PermissionError: If no write permissions
            FileNotFoundError: If parent directory doesn't exist (absolute paths only)
        """
        validate_not_program_repo_path(self.data_dir, context="data directory")

        # Check if path exists and is a file
        if self.data_dir.exists() and not self.data_dir.is_dir():
            raise ValueError(f"Data directory path is a file, not a directory: {self.data_dir}")

        # Check if parent directory exists (for absolute paths)
        if self.data_dir.is_absolute() and not self.data_dir.parent.exists():
            raise FileNotFoundError(
                f"Parent directory does not exist: {self.data_dir.parent}\n"
                f"Create it first or use a relative path."
            )

        # Check write permissions
        test_dir = self.data_dir if self.data_dir.exists() else self.data_dir.parent
        if not os.access(test_dir, os.W_OK):
            raise PermissionError(
                f"No write permission for: {test_dir}\n"
                f"Check directory permissions or choose a different location."
            )

    def ensure_dirs(self) -> None:
        """
        Create all required directories if they don't exist.

        Creates:
        - data_dir (root)
        - imports/ (XLSX files)
        - exports/ (master files)
        - exports/reports/ (CSV reports)
        - transactions/ (CSV partitions)
        - metadata/ (import history, workspaces, etc.)

        Note: rules.yaml is created separately.

        Security:
            Uses _ensure_directory() with TOCTOU protection for all directory creation.
        """
        validate_not_program_repo_path(self.data_dir, context="data directory")

        _ensure_directory(self.data_dir, "data directory")
        _ensure_directory(self.import_dir, "import directory")
        _ensure_directory(self.export_dir, "export directory")
        _ensure_directory(self.reports_dir, "reports directory")
        _ensure_directory(self.csv_base_dir, "CSV partition directory")
        _ensure_directory(self.metadata_dir, "metadata directory")
