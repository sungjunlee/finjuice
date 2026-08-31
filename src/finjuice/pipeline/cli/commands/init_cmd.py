"""finjuice CLI: ``init`` command."""

import logging

import typer

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.init_helpers import initialize_data_directory
from finjuice.pipeline.cli.output import console, emit
from finjuice.pipeline.cli.utils import get_config

logger = logging.getLogger(__name__)


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
