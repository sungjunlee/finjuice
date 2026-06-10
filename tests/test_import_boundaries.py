"""Import-boundary tests keeping core pipeline code independent of the CLI.

Non-CLI modules under ``finjuice.pipeline`` must not import
``finjuice.pipeline.cli.*``. Keeping the dependency direction one-way (CLI
depends on core, never the reverse) lets the pipeline be reused as a library
and tested without Typer/output modules. See issue #700.
"""

from __future__ import annotations

import ast
from pathlib import Path

_PIPELINE_ROOT = Path(__file__).resolve().parents[1] / "src" / "finjuice" / "pipeline"
_CLI_PREFIX = "finjuice.pipeline.cli"
_CLI_COMMANDS_PREFIX = "finjuice.pipeline.cli.commands"


def _core_module_paths() -> list[Path]:
    """Return every non-CLI Python module under finjuice.pipeline."""
    return sorted(
        path
        for path in _PIPELINE_ROOT.rglob("*.py")
        if "cli" not in path.relative_to(_PIPELINE_ROOT).parts
    )


def _imported_modules(tree: ast.Module) -> list[str]:
    """Collect fully-qualified module names referenced by import statements."""
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            modules.append(node.module)
    return modules


def _cli_imports(path: Path) -> list[str]:
    """Return CLI module imports found in one core module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        module
        for module in _imported_modules(tree)
        if module == _CLI_PREFIX or module.startswith(f"{_CLI_PREFIX}.")
    ]


def _cli_command_imports(path: Path) -> list[str]:
    """Return CLI command imports found in one module."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        module
        for module in _imported_modules(tree)
        if module == _CLI_COMMANDS_PREFIX or module.startswith(f"{_CLI_COMMANDS_PREFIX}.")
    ]


def test_core_modules_exist() -> None:
    """The boundary scan should find core modules to check (guards against a no-op test)."""
    # Arrange / Act
    core_modules = _core_module_paths()

    # Assert
    assert len(core_modules) > 10


def test_core_modules_do_not_import_cli() -> None:
    """No non-CLI pipeline module may import finjuice.pipeline.cli.*."""
    # Arrange
    core_modules = _core_module_paths()

    # Act
    violations = {
        str(path.relative_to(_PIPELINE_ROOT)): cli_imports
        for path in core_modules
        if (cli_imports := _cli_imports(path))
    }

    # Assert
    assert violations == {}, f"core modules importing CLI packages: {violations}"


def test_full_pipeline_orchestrator_does_not_import_cli_commands() -> None:
    """The shared pipeline orchestrator must not depend on CLI command modules."""
    # Arrange
    orchestrator_path = _PIPELINE_ROOT / "cli" / "commands" / "full_pipeline_orchestrator.py"

    # Act
    violations = _cli_command_imports(orchestrator_path)

    # Assert
    assert violations == [], f"full_pipeline_orchestrator imports CLI commands: {violations}"
