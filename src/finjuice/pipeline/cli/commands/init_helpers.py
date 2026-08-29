"""Data-directory initialization helpers for ``finjuice init``.

Owns directory creation, template copying, and optional git repository
setup. The Typer command stays in :mod:`finjuice.pipeline.cli.commands.init_cmd`.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from finjuice.pipeline.config import Config
from finjuice.pipeline.constants import (
    SUBPROCESS_TIMEOUT_MEDIUM,
    SUBPROCESS_TIMEOUT_SHORT,
)

logger = logging.getLogger(__name__)


def initialize_data_directory(
    config: Config, with_git: bool = True, with_agents: bool = False
) -> dict[str, Any]:
    """Initialize data directory structure and templates.

    Helper function shared by init-related CLI flows.
    This function is idempotent - it will create missing directories and files
    without overwriting existing ones.

    Args:
        config: Config object with data_dir
        with_git: Whether to initialize git repository
        with_agents: Whether to include AGENTS.md

    Returns:
        Dict with initialization results (created_dirs, copied_files, skipped_files,
        git_initialized).

    Raises:
        PermissionError: If cannot create directories
        Exception: For other initialization errors
    """
    created_dirs: list[str] = []
    copied_files: list[str] = []
    skipped_files: list[str] = []

    # Create directory structure (idempotent - exist_ok=True)
    config.data_dir.mkdir(parents=True, exist_ok=True)
    _track_mkdir(config.data_dir / "imports", created_dirs)
    _track_mkdir(config.data_dir / "transactions", created_dirs)
    _track_mkdir(config.data_dir / "exports", created_dirs)
    _track_mkdir(config.data_dir / "metadata", created_dirs)

    logger.info("Created directory structure")

    # Copy template files
    templates_to_copy = {
        ".gitignore.data": ".gitignore",
        "README.data.md": "README.md",
        "rules.yaml.example": "rules.yaml",
        "goals.yaml.example": "goals.yaml",
        "assets.yaml.example": "assets.yaml.example",
        "scenarios.yaml.example": "scenarios.yaml.example",
    }

    if with_agents:
        templates_to_copy["AGENTS.md"] = "AGENTS.md"

    for template_name, dest_name in templates_to_copy.items():
        dest_path = config.data_dir / dest_name
        # Skip if file already exists (idempotent - don't overwrite user customizations)
        if dest_path.exists():
            skipped_files.append(dest_name)
            logger.debug(f"Skipping {dest_name} (already exists)")
            continue
        try:
            copy_template_file(template_name, dest_path)
            copied_files.append(dest_name)
            logger.debug(f"Created {dest_name}")
        except FileNotFoundError:
            logger.warning(f"Template file not found: {template_name}")

    # Initialize git repository
    git_initialized = False
    if with_git:
        if init_git_repository(config.data_dir):
            git_initialized = True
            logger.info("Initialized git repository")
        else:
            logger.warning("git initialization skipped (not available)")

    return {
        "data_dir": str(config.data_dir),
        "created_dirs": created_dirs,
        "copied_files": copied_files,
        "skipped_files": skipped_files,
        "git_initialized": git_initialized,
    }


def _track_mkdir(path: Path, created_dirs: list[str]) -> None:
    """Track directory creation relative to the data directory."""
    if not path.exists():
        path.mkdir(exist_ok=True)
        created_dirs.append(str(path.relative_to(path.parent.parent)) + "/")


def copy_template_file(template_name: str, dest_path: Path) -> bool:
    """Copy template file to destination.

    Args:
        template_name: Template filename (e.g., "rules.yaml.example")
        dest_path: Destination path

    Returns:
        True if successful, False otherwise

    Raises:
        ValueError: If template_name contains path separators (security)
        FileNotFoundError: If template file doesn't exist
    """
    import importlib.resources

    # Security: Prevent path traversal attacks
    if "/" in template_name or "\\" in template_name:
        raise ValueError(f"Invalid template name: {template_name}")

    # Use importlib.resources to access package data (works with installed packages)
    try:
        # Python 3.9+ syntax using importlib.resources.files()
        template_files = importlib.resources.files("finjuice.templates")
        template_resource = template_files.joinpath(template_name)

        # Read and write content (handles both file and zip-based packages)
        content = template_resource.read_text(encoding="utf-8")
        dest_path.write_text(content, encoding="utf-8")

        logger.info(f"Copied template {template_name} to {dest_path}")
        return True
    except (FileNotFoundError, TypeError) as e:
        raise FileNotFoundError(f"Template not found: {template_name}") from e


def init_git_repository(data_dir: Path) -> bool:
    """Initialize git repository with initial commit.

    Args:
        data_dir: Directory to initialize

    Returns:
        True if successful, False otherwise
    """
    try:
        # Check if git is available
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_SHORT,
        )
        if result.returncode != 0:
            logger.warning("git not available, skipping repository initialization")
            return False

        # Initialize repository
        subprocess.run(
            ["git", "init"],
            cwd=data_dir,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_MEDIUM,
            check=True,
        )

        # Add all files
        subprocess.run(
            ["git", "add", "."],
            cwd=data_dir,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_MEDIUM,
            check=True,
        )

        # Create initial commit
        subprocess.run(
            ["git", "commit", "-m", "init: personal finance data repository"],
            cwd=data_dir,
            capture_output=True,
            text=True,
            timeout=SUBPROCESS_TIMEOUT_MEDIUM,
            check=True,
        )

        logger.info("Initialized git repository")
        return True

    except subprocess.TimeoutExpired:
        logger.error("git command timed out")
        return False
    except subprocess.CalledProcessError as e:
        logger.error(f"git command failed: {e.stderr}")
        return False
    except OSError as e:
        logger.error(f"Failed to initialize git repository: {e}")
        return False
