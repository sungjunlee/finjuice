"""In-tree version surfaces stay aligned for tagged releases."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_version_surfaces_agree() -> None:
    """pyproject, lock, runtime, skills, and CHANGELOG must share one version."""
    result = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "check_version_surfaces.py")],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout


def test_release_doc_states_current_rules() -> None:
    """Release docs should describe bump_version, lockfile, and annotated tags."""
    text = (REPO_ROOT / "docs" / "development" / "release.md").read_text(encoding="utf-8")

    for phrase in (
        "scripts/bump_version.py",
        "uv lock",
        "just version-check",
        "git tag -a vX.Y.Z",
        "Do **not** tag a version string that already shipped",
        "## [Unreleased]",
    ):
        assert phrase in text
    assert "0.7.x line" not in text
