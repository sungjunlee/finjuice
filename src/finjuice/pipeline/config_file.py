"""Config file I/O operations.

This module handles reading and writing the user configuration file.
Config file location: ~/.finjuice/config.toml
"""

import sys
from pathlib import Path
from typing import Optional

# Python 3.11+ has tomllib in stdlib (read-only)
if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

import tomli_w

from .config_schema import UserConfig


def _get_primary_config_path() -> Path:
    """Return the config file path."""
    return Path.home() / ".finjuice" / "config.toml"


def get_config_path() -> Path:
    """Get config file path.

    Returns:
        Path: Config file path (~/.finjuice/config.toml)

    Example:
        >>> path = get_config_path()
        >>> str(path)
        '/Users/username/.finjuice/config.toml'
    """
    return _get_primary_config_path()


def load_config() -> Optional[UserConfig]:
    """Load config file if exists.

    Returns:
        UserConfig object if config file exists, None otherwise

    Raises:
        ValueError: If config file is invalid or malformed
        TOMLDecodeError: If TOML syntax is invalid

    Example:
        >>> config = load_config()
        >>> if config:
        ...     print(config.data.directory)
        ~/Documents/finjuice-data
    """
    config_path = get_config_path()

    # Return None if config doesn't exist (first run)
    if not config_path.exists():
        return None

    # Security: validate config file is not a symlink
    validate_config_path(config_path)

    # Load TOML file
    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except (OSError, PermissionError, ValueError) as e:
        raise ValueError(f"Failed to load config file {config_path}: {e}") from e

    # Parse and validate
    try:
        return UserConfig.from_dict(data)
    except (KeyError, ValueError) as e:
        raise ValueError(f"Invalid config file {config_path}: {e}") from e


def save_config(config: UserConfig) -> None:
    """Save config to file, creating parent dirs if needed.

    Uses atomic write pattern (write to temp file, then rename) to prevent
    corruption if interrupted.

    Security: Validates that config file is not a symlink before writing
    to prevent symlink attacks where an attacker replaces the config file
    with a symlink to a sensitive system file.

    Args:
        config: UserConfig object to save

    Raises:
        OSError: If cannot create directory or write file
        ValueError: If config validation fails or path security check fails

    Example:
        >>> config = UserConfig(
        ...     data=DataConfig(directory="~/my-data"),
        ...     preferences=PreferencesConfig(language="en")
        ... )
        >>> save_config(config)
    """
    # Validate before saving
    config.validate()

    config_path = _get_primary_config_path()

    # Create parent directory if needed
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise OSError(f"Failed to create config directory {config_path.parent}: {e}") from e

    # Security: validate parent directory after creation
    if not config_path.parent.is_dir():
        raise ValueError(f"Config parent must be a directory: {config_path.parent}")

    # Security: validate config file is not a symlink before writing
    # This prevents symlink attacks where ~/.finjuice/config.toml
    # is replaced with a symlink to /etc/passwd or other sensitive files
    if config_path.exists():
        validate_config_path(config_path)

    # Atomic write: write to temp file, then rename
    temp_path = config_path.with_suffix(".toml.tmp")
    try:
        # Security: ensure temp file is not a symlink either
        if temp_path.exists() and temp_path.is_symlink():
            temp_path.unlink()

        with open(temp_path, "wb") as f:
            tomli_w.dump(config.to_dict(), f)

        # Atomic rename (platform-specific behavior)
        temp_path.replace(config_path)

    except (OSError, PermissionError, ValueError) as e:
        # Clean up temp file on failure
        temp_path.unlink(missing_ok=True)
        raise OSError(f"Failed to save config to {config_path}: {e}") from e


def validate_config_path(path: Path) -> None:
    """Validate config file doesn't have security issues.

    Security checks:
    - Not a symlink (prevents symlink attacks)
    - Parent directory exists and is a directory

    Args:
        path: Config file path to validate

    Raises:
        ValueError: If path is invalid or has security issues

    Example:
        >>> path = Path("~/.finjuice/config.toml").expanduser()
        >>> validate_config_path(path)
    """
    # Check it's not a symlink (security: prevent symlink attacks)
    if path.is_symlink():
        raise ValueError(f"Config file must not be a symlink: {path}")

    # Check parent directory (if file exists)
    if path.exists() and path.parent.exists():
        if not path.parent.is_dir():
            raise ValueError(f"Config parent must be a directory: {path.parent}")


def config_exists() -> bool:
    """Check if config file exists.

    Returns:
        True if config file exists, False otherwise

    Example:
        >>> if not config_exists():
        ...     print("First run detected")
    """
    return get_config_path().exists()
