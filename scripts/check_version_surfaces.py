#!/usr/bin/env python3
"""Check that in-tree version surfaces agree.

Run from the repository root:

    uv run python scripts/check_version_surfaces.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _pyproject_version() -> str:
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', _read("pyproject.toml"))
    if match is None:
        raise SystemExit("pyproject.toml: missing [project].version")
    return match.group(1)


def _init_version() -> str:
    match = re.search(r'(?m)^__version__\s*=\s*"([^"]+)"', _read("src/finjuice/__init__.py"))
    if match is None:
        raise SystemExit("src/finjuice/__init__.py: missing __version__")
    return match.group(1)


def _skill_runtime_version() -> str:
    match = re.search(
        r'(?m)^SKILL_RUNTIME_REQUIRED_VERSION\s*=\s*"([^"]+)"',
        _read("src/finjuice/pipeline/doctor/skill_runtime.py"),
    )
    if match is None:
        raise SystemExit("skill_runtime.py: missing SKILL_RUNTIME_REQUIRED_VERSION")
    return match.group(1)


def _lock_version() -> str:
    lines = _read("uv.lock").splitlines()
    for index, line in enumerate(lines):
        if line == 'name = "finjuice"':
            for follow in lines[index + 1 : index + 6]:
                match = re.match(r'^version = "([^"]+)"', follow)
                if match:
                    return match.group(1)
            break
    raise SystemExit("uv.lock: missing package finjuice version")


def _changelog_has_heading(changelog: str, heading: str) -> bool:
    return re.search(rf"(?m)^## \[{re.escape(heading)}\](?: |$)", changelog) is not None


def main() -> int:
    version = _pyproject_version()
    if not VERSION_RE.match(version):
        print(f"error: invalid pyproject version {version!r}", file=sys.stderr)
        return 1

    errors: list[str] = []
    surfaces = {
        "src/finjuice/__init__.py": _init_version(),
        "skill_runtime.py": _skill_runtime_version(),
        "uv.lock": _lock_version(),
    }
    for name, found in surfaces.items():
        if found != version:
            errors.append(f"{name}: {found} != {version}")

    changelog = _read("CHANGELOG.md")
    if not _changelog_has_heading(changelog, "Unreleased"):
        errors.append("CHANGELOG.md: missing ## [Unreleased]")
    if not _changelog_has_heading(changelog, version):
        errors.append(f"CHANGELOG.md: missing ## [{version}]")

    unreleased_link = (
        f"[Unreleased]: https://github.com/sungjunlee/finjuice/compare/v{version}...HEAD"
    )
    if unreleased_link not in changelog:
        errors.append(f"CHANGELOG.md: missing compare link {unreleased_link}")

    skill = _read("skills/finjuice/SKILL.md")
    if f"Minimum finjuice: `{version}`" not in skill:
        errors.append("skills/finjuice/SKILL.md: Minimum finjuice does not match pyproject")
    if f"--require-version {version}" not in skill:
        errors.append("skills/finjuice/SKILL.md: --require-version does not match pyproject")

    if errors:
        print("Version surfaces disagree:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"Version surfaces agree: {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
