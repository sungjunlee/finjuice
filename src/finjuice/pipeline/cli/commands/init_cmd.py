"""finjuice CLI: ``init`` command + shared init/data-directory helpers."""

import logging
import subprocess
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.output import console, emit
from finjuice.pipeline.cli.utils import get_config
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


def init_command(
    ctx: typer.Context,
    with_git: bool = typer.Option(
        True, "--with-git/--no-git", help="Initialize git repository (default: True)"
    ),
    with_agents: bool = typer.Option(
        False,
        "--with-agents",
        help="Include AGENTS.md for AI tool integration (Codex, Gemini, Cursor)",
    ),
    save_config: bool = typer.Option(
        False,
        "--save-config",
        help="Save this location to config file (~/.finjuice/config.toml)",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Initialize directory structure (advanced setup).

    ⚠️  Most users should use `finjuice import` which handles setup automatically.

    This command is for advanced users who need:
    - Custom data directory location
    - Skip git initialization (--no-git)
    - Include AGENTS.md for AI tools (--with-agents)
    - Save location to config file (--save-config)

    Creates a new data directory with:
    - Directory structure (imports/, transactions/, exports/)
    - Template files (.gitignore, README.md, rules.yaml)
    - Optional git repository initialization
    - Optional AGENTS.md for AI tool integration

    Examples:
        # Recommended: Import auto-creates the data directory on first run
        finjuice import ~/Downloads/뱅크샐러드_2024-01-01~2024-12-31.xlsx

        # Advanced: Custom location with git and save to config
        finjuice --data-dir ~/my-finance-data init --save-config

        # Advanced: Skip git initialization
        finjuice init --no-git

        # Advanced: Include AI agent configuration
        finjuice init --with-agents
    """
    config = get_config(ctx)

    # Check if already initialized
    already_initialized = (
        config.data_dir.exists()
        and (config.data_dir / "imports").exists()
        and (config.data_dir / "transactions").exists()
        and (config.data_dir / "rules.yaml").exists()
    )

    if already_initialized:
        if json_output:
            emit(
                {
                    "status": "ok",
                    "data_dir": str(config.data_dir),
                    "already_initialized": True,
                },
                json_output=True,
                render_fn=lambda _: None,
                command="init",
            )
            return
        output.success(f"Directory {config.data_dir} is already initialized")
        output.info("   Skipping initialization (idempotent)")
        return

    try:
        # Use helper function to perform initialization
        result = initialize_data_directory(config, with_git=with_git, with_agents=with_agents)

        if json_output:
            emit(
                {
                    "status": "ok",
                    "data_dir": result["data_dir"],
                    "created_dirs": result["created_dirs"],
                    "copied_files": result["copied_files"],
                    "skipped_files": result["skipped_files"],
                    "git_initialized": result["git_initialized"],
                },
                json_output=True,
                render_fn=lambda _: None,
                command="init",
            )
            return

        # Show success message
        output.success("Initialization complete!")
        output.info(f"📁 Initialized data directory: {config.data_dir}")

        # Save config if requested
        if save_config:
            output.newline()
            output.info("💾 Saving config file...")
            try:
                from finjuice.pipeline.config_file import (
                    get_config_path,
                )
                from finjuice.pipeline.config_file import (
                    save_config as save_config_file,
                )
                from finjuice.pipeline.config_schema import (
                    DataConfig,
                    PreferencesConfig,
                    UserConfig,
                )

                user_config = UserConfig(
                    data=DataConfig(directory=str(config.data_dir)),
                    preferences=PreferencesConfig(
                        auto_init=True, interactive_mode=True, language="ko"
                    ),
                )
                save_config_file(user_config)
                config_path = get_config_path()
                output.success(f"Config saved to {config_path}")
                output.info("✨ 다음부터 --data-dir 없이 'finjuice refresh'만 실행하면 됩니다!")
            except (OSError, ValueError) as e:
                output.warning(f"Config 저장 실패: {e}")
                logger.warning("Failed to save config file (%s)", type(e).__name__)

        # Show next steps
        output.newline()
        console.print("[bold]📝 Next steps:[/bold]")
        console.print("  1. Place Banksalad XLSX files in imports/")
        console.print("  2. Edit rules.yaml to customize tagging rules")
        if save_config:
            console.print("  3. Run: [cyan]finjuice refresh[/cyan]")
        else:
            console.print(f"  3. Run: [cyan]finjuice --data-dir {config.data_dir} refresh[/cyan]")
            output.newline()
            output.info(
                "💡 Tip: --save-config 옵션으로 위치를 저장하면 --data-dir 없이 사용 가능합니다."
            )

        if with_agents:
            output.newline()
            console.print("[bold]🤖 AI Integration:[/bold]")
            console.print("  - AGENTS.md created for AI tool integration")
            console.print("  - Use with Claude Code, Gemini Code Assist, or Cursor")

    except PermissionError as e:
        if json_output:
            emit(
                {"status": "error", "message": str(e)},
                json_output=True,
                render_fn=lambda _: None,
                command="init",
            )
            raise typer.Exit(code=1) from e
        output.error(f"Permission denied: {e}")
        output.info("💡 해결 방법:")
        output.info("  1. 다른 위치 사용: finjuice init ~/Documents/finjuice --save-config")
        output.info("  2. 권한 확인: sudo chown -R $USER ~/Library/Application\\ Support/")
        raise typer.Exit(code=1)
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Initialization failed: {e}", exc_info=True)
        if json_output:
            emit(
                {"status": "error", "message": str(e)},
                json_output=True,
                render_fn=lambda _: None,
                command="init",
            )
            raise typer.Exit(code=1) from e
        output.error(f"Initialization failed: {e}")
        raise typer.Exit(code=1)
