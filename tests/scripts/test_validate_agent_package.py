"""Tests for agent skill package validation."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from scripts.validate_agent_package import validate_agent_package

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_current_agent_package_validates() -> None:
    """The checked-in finjuice skill suite should satisfy package validation."""
    assert validate_agent_package(REPO_ROOT) == []


def test_validator_fails_on_missing_referenced_file(tmp_path: Path) -> None:
    """Stale skill references should fail with a useful error."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "skills", root / "skills")
    skill = root / "skills/finjuice/SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8")
        + "\nBroken reference for test: [missing](references/does-not-exist.md)\n",
        encoding="utf-8",
    )

    errors = validate_agent_package(root)

    assert any("missing markdown link target" in error.message for error in errors)
    assert any("references/does-not-exist.md" in error.message for error in errors)


def test_validator_cli_returns_nonzero_on_stale_reference(tmp_path: Path) -> None:
    """The script should be usable from CI and fail on broken package references."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "skills", root / "skills")
    skill = root / "skills/finjuice-review/SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8")
        + "\nBroken literal reference for test: `../finjuice-missing/SKILL.md`\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts/validate_agent_package.py"), "--root", str(root)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "missing referenced file" in result.stderr
    assert "../finjuice-missing/SKILL.md" in result.stderr


def test_validator_checks_reference_file_internal_links(tmp_path: Path) -> None:
    """Reference files should be validated, not only SKILL.md files."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "skills", root / "skills")
    reference = root / "skills/finjuice-report/references/report-recipes.md"
    reference.write_text(
        reference.read_text(encoding="utf-8")
        + "\nBroken reference-local link for test: `../../finjuice-missing/SKILL.md`\n",
        encoding="utf-8",
    )

    errors = validate_agent_package(root)

    assert any("missing referenced file" in error.message for error in errors)
    assert any(error.path == reference for error in errors)
    assert any("../../finjuice-missing/SKILL.md" in error.message for error in errors)


def test_validator_fails_when_runtime_helper_is_missing(tmp_path: Path) -> None:
    """The shared runtime helper path is part of the skill package contract."""
    root = tmp_path / "repo"
    shutil.copytree(REPO_ROOT / "skills", root / "skills")
    helper = root / "skills/finjuice/scripts/ensure_finjuice_cli.sh"
    helper.unlink()

    errors = validate_agent_package(root)

    assert any("missing runtime helper" in error.message for error in errors)
    assert any(
        "skills/finjuice/scripts/ensure_finjuice_cli.sh" in error.message for error in errors
    )
