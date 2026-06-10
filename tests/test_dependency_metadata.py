"""Runtime dependency metadata checks."""

from __future__ import annotations

import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


def _dependency_names(project_root: Path) -> set[str]:
    pyproject = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    names: set[str] = set()
    for dependency in dependencies:
        requirement = dependency.split(";", maxsplit=1)[0].split("[", maxsplit=1)[0].strip()
        names.add(requirement.split("<", maxsplit=1)[0].split(">", maxsplit=1)[0].strip().lower())
    return names


def test_click_is_declared_as_direct_runtime_dependency() -> None:
    """finjuice imports click directly, so uv tool installs must not rely on Typer transitives."""
    project_root = Path(__file__).resolve().parents[1]

    assert "click" in _dependency_names(project_root)
