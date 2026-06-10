"""Config file schema and validation.

This module defines the structure of the user configuration file (config.toml).
The config file uses TOML format and follows XDG Base Directory specification.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class DataConfig:
    """Data directory configuration.

    Attributes:
        directory: Path to data directory (supports ~ expansion)
    """

    directory: str

    def validate(self) -> None:
        """Validate data configuration.

        Raises:
            ValueError: If directory path is invalid
        """
        if not self.directory or not self.directory.strip():
            raise ValueError("Data directory cannot be empty")

        # Check for null bytes (security)
        if "\x00" in self.directory:
            raise ValueError("Data directory path contains null bytes")

        # Check path is not excessively long
        if len(self.directory) > 1000:
            raise ValueError("Data directory path too long (max 1000 characters)")


@dataclass
class PreferencesConfig:
    """User preferences configuration.

    Attributes:
        auto_init: Automatically initialize data directory if missing
        interactive_mode: Enable interactive mode by default
        language: UI language (ko=Korean, en=English)
    """

    auto_init: bool = True
    interactive_mode: bool = True
    language: Literal["ko", "en"] = "ko"

    def validate(self) -> None:
        """Validate preferences configuration.

        Raises:
            ValueError: If preferences are invalid
        """
        if self.language not in ("ko", "en"):
            raise ValueError(f"Invalid language: {self.language}. Must be 'ko' or 'en'")


@dataclass
class AutomationThresholdsConfig:
    """Thresholds that control one-shot automation behavior."""

    untagged_count: int = 10
    large_transaction: int = 300_000

    def validate(self) -> None:
        """Validate automation thresholds."""
        for field_name, value in (
            ("untagged_count", self.untagged_count),
            ("large_transaction", self.large_transaction),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"Automation threshold '{field_name}' must be an integer")
            if value < 0:
                raise ValueError(f"Automation threshold '{field_name}' must be >= 0")


@dataclass
class AutomationConfig:
    """Minimal automation configuration for the Phase 1 CLI-first wedge."""

    enabled: bool = False
    thresholds: AutomationThresholdsConfig = field(default_factory=AutomationThresholdsConfig)

    def validate(self) -> None:
        """Validate automation configuration."""
        if not isinstance(self.enabled, bool):
            raise ValueError("Automation 'enabled' must be a boolean")
        self.thresholds.validate()


@dataclass
class UserConfig:
    """Complete user configuration from config.toml.

    Example TOML:
        [data]
        directory = "~/Documents/finjuice-data"

        [preferences]
        auto_init = true
        interactive_mode = true
        language = "ko"

    Attributes:
        data: Data directory configuration
        preferences: User preferences
        automation: One-shot automation defaults and thresholds
    """

    data: DataConfig
    preferences: PreferencesConfig = field(default_factory=PreferencesConfig)
    automation: AutomationConfig = field(default_factory=AutomationConfig)
    _automation_explicit: bool = field(default=False, repr=False, compare=False)

    def validate(self) -> None:
        """Validate complete configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        self.data.validate()
        self.preferences.validate()
        self.automation.validate()

    @classmethod
    def from_dict(cls, data: dict) -> "UserConfig":
        """Parse config dict from TOML file.

        Args:
            data: Dictionary loaded from TOML file

        Returns:
            UserConfig instance

        Raises:
            ValueError: If required fields are missing or invalid
            KeyError: If required sections are missing

        Example:
            >>> data = {
            ...     "data": {"directory": "~/my-data"},
            ...     "preferences": {"language": "en"}
            ... }
            >>> config = UserConfig.from_dict(data)
        """
        # Required: [data] section
        if "data" not in data:
            raise KeyError("Missing required [data] section in config file")

        data_section = data["data"]
        if "directory" not in data_section:
            raise KeyError("Missing required 'directory' field in [data] section")

        # Parse data config
        data_config = DataConfig(directory=data_section["directory"])

        # Optional: [preferences] section
        prefs_section = data.get("preferences", {})
        preferences_config = PreferencesConfig(
            auto_init=prefs_section.get("auto_init", True),
            interactive_mode=prefs_section.get("interactive_mode", True),
            language=prefs_section.get("language", "ko"),
        )

        # Optional: [automation] section
        automation_explicit = "automation" in data
        automation_section = data.get("automation", {})
        thresholds_section = automation_section.get("thresholds", {})
        automation_config = AutomationConfig(
            enabled=automation_section.get("enabled", False),
            thresholds=AutomationThresholdsConfig(
                untagged_count=thresholds_section.get("untagged_count", 10),
                large_transaction=thresholds_section.get("large_transaction", 300_000),
            ),
        )

        config = cls(
            data=data_config,
            preferences=preferences_config,
            automation=automation_config,
            _automation_explicit=automation_explicit,
        )
        config.validate()  # Validate on creation
        return config

    def to_dict(self) -> dict:
        """Serialize to dict for TOML writing.

        Returns:
            Dictionary suitable for TOML serialization

        Example:
            >>> config = UserConfig(
            ...     data=DataConfig(directory="~/my-data"),
            ...     preferences=PreferencesConfig(language="en")
            ... )
            >>> config.to_dict()
            {
                'data': {'directory': '~/my-data'},
                'preferences': {
                    'auto_init': True,
                    'interactive_mode': True,
                    'language': 'en'
                }
            }
        """
        result = {
            "data": {"directory": self.data.directory},
            "preferences": {
                "auto_init": self.preferences.auto_init,
                "interactive_mode": self.preferences.interactive_mode,
                "language": self.preferences.language,
            },
        }

        default_automation = AutomationConfig()
        if self._automation_explicit or self.automation != default_automation:
            result["automation"] = {
                "enabled": self.automation.enabled,
                "thresholds": {
                    "untagged_count": self.automation.thresholds.untagged_count,
                    "large_transaction": self.automation.thresholds.large_transaction,
                },
            }

        return result

    def get_data_path(self) -> Path:
        """Get resolved data directory path with ~ expansion.

        Returns:
            Absolute path to data directory

        Example:
            >>> config = UserConfig(data=DataConfig(directory="~/my-data"))
            >>> config.get_data_path()
            PosixPath('/Users/username/my-data')
        """
        return Path(self.data.directory).expanduser().resolve()
