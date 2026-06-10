"""Tests for the Ruff complexity ratchet."""

from __future__ import annotations

import json
from pathlib import Path

from scripts import check_complexity_ratchet

BRANCHY_SOURCE = """
def branchy(value):
    if value == 0:
        return 0
    if value == 1:
        return 1
    if value == 2:
        return 2
    if value == 3:
        return 3
    if value == 4:
        return 4
    if value == 5:
        return 5
    if value == 6:
        return 6
    if value == 7:
        return 7
    if value == 8:
        return 8
    if value == 9:
        return 9
    if value == 10:
        return 10
    return value
"""


def _write_python(path: Path, source: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(source, encoding="utf-8")
    return path


def _write_empty_baseline(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "description": "empty test baseline",
                "rules": list(check_complexity_ratchet.RULES),
                "paths": [],
                "findings": [],
            }
        ),
        encoding="utf-8",
    )


def test_check_passes_when_current_findings_match_generated_baseline(tmp_path: Path) -> None:
    """A generated baseline should cover the same Ruff findings."""
    sample = _write_python(tmp_path / "sample.py", BRANCHY_SOURCE)
    baseline = tmp_path / "baseline.json"

    update_code = check_complexity_ratchet.main(
        [str(sample), "--root", str(tmp_path), "--baseline", str(baseline), "--update-baseline"]
    )
    check_code = check_complexity_ratchet.main(
        [str(sample), "--root", str(tmp_path), "--baseline", str(baseline)]
    )

    assert update_code == 0
    assert check_code == 0


def test_check_fails_for_new_complexity_debt(tmp_path: Path, capsys) -> None:
    """Unbaselined Ruff complexity findings should fail."""
    sample = _write_python(tmp_path / "sample.py", BRANCHY_SOURCE)
    baseline = tmp_path / "baseline.json"
    _write_empty_baseline(baseline)

    exit_code = check_complexity_ratchet.main(
        [str(sample), "--root", str(tmp_path), "--baseline", str(baseline)]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "New complexity findings" in captured.err
    assert "sample.py" in captured.err
    assert "C901" in captured.err


def test_check_fails_when_existing_complexity_gets_worse(tmp_path: Path, capsys) -> None:
    """The ratchet should reject a higher Ruff metric for the same symbol."""
    sample = _write_python(tmp_path / "sample.py", BRANCHY_SOURCE)
    baseline = tmp_path / "baseline.json"
    check_complexity_ratchet.main(
        [str(sample), "--root", str(tmp_path), "--baseline", str(baseline), "--update-baseline"]
    )
    _write_python(
        sample,
        BRANCHY_SOURCE.replace("    return value\n", "    if value == 11:\n        return 11\n"),
    )

    exit_code = check_complexity_ratchet.main(
        [str(sample), "--root", str(tmp_path), "--baseline", str(baseline)]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "Worsened complexity findings" in captured.err
    assert "branchy" in captured.err


def test_rebase_paths_repoints_a_moved_symbol(tmp_path: Path, capsys) -> None:
    """A symbol moved to a new path without worsening should be re-pointed, not failed."""
    old_path = _write_python(tmp_path / "old.py", BRANCHY_SOURCE)
    baseline = tmp_path / "baseline.json"
    check_complexity_ratchet.main(
        [str(old_path), "--root", str(tmp_path), "--baseline", str(baseline), "--update-baseline"]
    )
    # Simulate a refactor: same code, new file path.
    old_path.unlink()
    new_path = _write_python(tmp_path / "new.py", BRANCHY_SOURCE)

    exit_code = check_complexity_ratchet.main(
        [str(new_path), "--root", str(tmp_path), "--baseline", str(baseline), "--rebase-paths"]
    )
    captured = capsys.readouterr()
    rebased = json.loads(baseline.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Re-pointed" in captured.out and "old.py -> new.py" in captured.out
    assert {finding["path"] for finding in rebased["findings"]} == {"new.py"}


def test_rebase_paths_still_fails_for_genuinely_new_debt(tmp_path: Path, capsys) -> None:
    """Rebase mode must not mask a new complexity hotspot that did not just move."""
    sample = _write_python(tmp_path / "sample.py", BRANCHY_SOURCE)
    baseline = tmp_path / "baseline.json"
    _write_empty_baseline(baseline)

    exit_code = check_complexity_ratchet.main(
        [str(sample), "--root", str(tmp_path), "--baseline", str(baseline), "--rebase-paths"]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "No path migrations detected" in captured.out
    assert "New complexity findings" in captured.err
