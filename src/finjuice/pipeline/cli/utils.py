"""Utility functions for CLI commands.

Shared utilities used across multiple CLI command modules.
Extracted from main.py as part of Issue #85 (CLI Modularization).
"""

import logging
import os
import platform
import subprocess
from pathlib import Path

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.config import Config
from finjuice.pipeline.constants import SUBPROCESS_TIMEOUT_SHORT
from finjuice.pipeline.metadata import check_schema_version

logger = logging.getLogger(__name__)


def warn_on_schema_mismatch(data_dir: Path) -> None:
    """Render a data-directory schema-version warning when one applies."""
    schema_warning = check_schema_version(data_dir)
    if schema_warning is not None:
        output.warning(schema_warning)


def get_config(ctx: typer.Context) -> Config:
    """
    Get Config instance from Typer context.

    Args:
        ctx: Typer context containing config

    Returns:
        Config instance with resolved paths
    """
    if ctx.obj is None or "config" not in ctx.obj:
        # Fallback to default config (shouldn't happen with callback)
        return Config.from_env()
    config: Config = ctx.obj["config"]
    return config


def set_log_level(verbose: bool) -> None:
    """Set logging level based on verbose flag."""
    if verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger("finjuice").setLevel(logging.DEBUG)
        logger.debug("DEBUG logging enabled")


def open_file_in_system_viewer(path: Path) -> bool:
    """
    Open a file in the system's default viewer (cross-platform).

    Args:
        path: Path to the file to open

    Returns:
        True if opened successfully, False otherwise

    Raises:
        Nothing - all errors are caught and logged
    """
    try:
        if not path.exists():
            logger.warning(f"File does not exist: {path}")
            return False

        system = platform.system()

        if system == "Darwin":  # macOS
            subprocess.run(
                ["open", str(path)],
                check=True,
                timeout=SUBPROCESS_TIMEOUT_SHORT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:  # Linux and others
            subprocess.run(
                ["xdg-open", str(path)],
                check=True,
                timeout=SUBPROCESS_TIMEOUT_SHORT,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        logger.debug(f"Opened file in system viewer: {path}")
        return True

    except FileNotFoundError as e:
        logger.warning(f"Could not open file (viewer not found): {e}")
        return False
    except subprocess.TimeoutExpired:
        logger.warning(f"Timeout while opening file: {path}")
        return False
    except subprocess.CalledProcessError as e:
        logger.warning(f"Failed to open file: {e}")
        return False
    except OSError as e:
        logger.warning(f"Unexpected error opening file: {e}")
        return False
