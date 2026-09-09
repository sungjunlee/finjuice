"""Structure tests for the validator_conflicts check-policy split.

Overlap, priority-inversion, regex-validity, and duplicate-name checks live
in sibling modules and must stay identity-equal when re-exported from
``validator_conflicts``, so existing import paths and monkeypatches keep
working after the split. ``validate_rules`` stays defined on
``validator_conflicts``.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")
CONFLICTS_MODULE = "finjuice.pipeline.tagging.validator_conflicts"

CHECK_SURFACES = (
    (
        "check_duplicate_names",
        "validator_conflicts_duplicates.py",
        "finjuice.pipeline.tagging.validator_conflicts_duplicates",
    ),
    (
        "check_pattern_overlaps",
        "validator_conflicts_overlaps.py",
        "finjuice.pipeline.tagging.validator_conflicts_overlaps",
    ),
    (
        "check_priority_inversions",
        "validator_conflicts_inversions.py",
        "finjuice.pipeline.tagging.validator_conflicts_inversions",
    ),
    (
        "check_regex_validity",
        "validator_conflicts_regex.py",
        "finjuice.pipeline.tagging.validator_conflicts_regex",
    ),
)


def _function_def_names(path: Path) -> set[str]:
    """Return FunctionDef names defined in a module file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)}


def test_conflicts_reexports_check_policies_identity() -> None:
    """Check policies stay on validator_conflicts as re-exports after the split."""
    conflicts = importlib.import_module(CONFLICTS_MODULE)
    conflicts_text = (TAGGING_DIR / "validator_conflicts.py").read_text(encoding="utf-8")

    for name, _filename, module_name in CHECK_SURFACES:
        sibling = importlib.import_module(module_name)
        assert name in conflicts_text
        assert getattr(conflicts, name) is getattr(sibling, name)

    assert callable(conflicts.validate_rules)
    assert conflicts.ValidationIssue.__name__ == "ValidationIssue"
    assert conflicts.ValidationResult.__name__ == "ValidationResult"


def test_each_check_is_the_unique_home_for_its_policy() -> None:
    """Each moved check is defined exactly once, in its sibling module."""
    conflicts = importlib.import_module(CONFLICTS_MODULE)

    for name, _filename, module_name in CHECK_SURFACES:
        sibling = importlib.import_module(module_name)
        assert getattr(sibling, name).__module__ == module_name
        assert getattr(conflicts, name).__module__ == module_name

    assert conflicts.validate_rules.__module__ == CONFLICTS_MODULE


def test_check_function_bodies_do_not_leak_into_validator_conflicts() -> None:
    """Check function bodies belong to sibling modules, not validator_conflicts."""
    conflicts_path = TAGGING_DIR / "validator_conflicts.py"
    conflicts_defs = _function_def_names(conflicts_path)
    conflicts_text = conflicts_path.read_text(encoding="utf-8")

    assert "validate_rules" in conflicts_defs
    assert "def validate_rules" in conflicts_text

    for name, filename, _module_name in CHECK_SURFACES:
        sibling_path = TAGGING_DIR / filename
        sibling_defs = _function_def_names(sibling_path)
        sibling_text = sibling_path.read_text(encoding="utf-8")

        assert name not in conflicts_defs
        assert f"def {name}" not in conflicts_text
        assert name in sibling_defs
        assert f"def {name}" in sibling_text
        assert name in conflicts_text
        assert "def validate_rules" not in sibling_text


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

