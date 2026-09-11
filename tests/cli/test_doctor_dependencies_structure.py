"""Structure tests for the doctor dependency vs analytics DuckDB split.

Required-package checks live in ``dependencies`` and analytics DuckDB checks
live in ``analytics_duckdb``. Both must stay identity-equal when re-exported
from ``checks``, so existing import paths and monkeypatches keep working
after the split. ``_build_doctor_result`` stays defined on ``checks``.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

DOCTOR_DIR = Path("src/finjuice/pipeline/doctor")
CHECKS_MODULE = "finjuice.pipeline.doctor.checks"

CHECK_SURFACES = (
    (
        "_check_dependencies",
        "dependencies.py",
        "finjuice.pipeline.doctor.dependencies",
    ),
    (
        "_check_analytics_duckdb",
        "analytics_duckdb.py",
        "finjuice.pipeline.doctor.analytics_duckdb",
    ),
)


def _function_def_names(path: Path) -> set[str]:
    """Return FunctionDef names defined in a module file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_checks_reexports_dependency_and_analytics_identity() -> None:
    """Dependency and analytics checks stay on checks as re-exports after the split."""
    checks = importlib.import_module(CHECKS_MODULE)
    checks_text = (DOCTOR_DIR / "checks.py").read_text(encoding="utf-8")

    for name, _filename, module_name in CHECK_SURFACES:
        sibling = importlib.import_module(module_name)
        assert name in checks_text
        assert getattr(checks, name) is getattr(sibling, name)

    assert callable(checks._build_doctor_result)


def test_each_check_is_the_unique_home_for_its_policy() -> None:
    """Each moved check is defined exactly once, in its sibling module."""
    checks = importlib.import_module(CHECKS_MODULE)

    for name, _filename, module_name in CHECK_SURFACES:
        sibling = importlib.import_module(module_name)
        assert getattr(sibling, name).__module__ == module_name
        assert getattr(checks, name).__module__ == module_name

    assert checks._build_doctor_result.__module__ == CHECKS_MODULE


def test_check_function_bodies_do_not_leak_into_checks() -> None:
    """Check function bodies belong to sibling modules, not checks.py."""
    checks_path = DOCTOR_DIR / "checks.py"
    checks_defs = _function_def_names(checks_path)
    checks_text = checks_path.read_text(encoding="utf-8")

    assert "_build_doctor_result" in checks_defs
    assert "def _build_doctor_result" in checks_text

    for name, filename, _module_name in CHECK_SURFACES:
        sibling_path = DOCTOR_DIR / filename
        sibling_defs = _function_def_names(sibling_path)
        sibling_text = sibling_path.read_text(encoding="utf-8")

        assert name not in checks_defs
        assert f"def {name}" not in checks_text
        assert name in sibling_defs
        assert f"def {name}" in sibling_text
        assert name in checks_text
        assert "def _build_doctor_result" not in sibling_text


def test_sibling_modules_import_without_parent_first() -> None:
    """Each check module is importable in a fresh interpreter before parent."""
    import subprocess
    import sys

    for _name, _filename, module_name in CHECK_SURFACES:
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module_name}"],
            check=False,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stderr
