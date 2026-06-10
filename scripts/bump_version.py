#!/usr/bin/env python3
"""Bump finjuice version across all source locations atomically.

Usage:
    uv run python scripts/bump_version.py 0.7.0
    uv run python scripts/bump_version.py --dry-run 0.7.0
"""

import argparse
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Files and their version update rules.
# Each entry is a (path, pattern, replacement_template) tuple.
# pattern: regex matching the line containing the version
# replacement_template: the new line, with {version} placeholder
VERSION_LOCATIONS = [
    (
        "pyproject.toml",
        r'^version\s*=\s*"[^"]*"',
        'version = "{version}"',
    ),
    (
        "src/finjuice/__init__.py",
        r'^__version__\s*=\s*"[^"]*"',
        '__version__ = "{version}"',
    ),
    (
        "src/finjuice/pipeline/cli/commands/doctor.py",
        r'^SKILL_RUNTIME_REQUIRED_VERSION\s*=\s*"[^"]*"',
        'SKILL_RUNTIME_REQUIRED_VERSION = "{version}"',
    ),
    (
        "skills/finjuice/SKILL.md",
        r"^- Minimum finjuice: `[^`]+`",
        "- Minimum finjuice: `{version}`",
    ),
    (
        "skills/finjuice/SKILL.md",
        r"^  --require-version [0-9.]+ ",
        "  --require-version {version} \\",
    ),
    (
        "skills/finjuice/references/runtime-preflight.md",
        r"^  --require-version [0-9.]+$",
        "  --require-version {version}",
    ),
]

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def validate_version(version: str) -> None:
    """Validate that version string is semver-ish (X.Y.Z)."""
    if not SEMVER_RE.match(version):
        print(f"error: invalid version format '{version}' — expected X.Y.Z", file=sys.stderr)
        sys.exit(1)


def bump_version(version: str, dry_run: bool = False) -> dict[str, str]:
    """Update all version locations. Returns a mapping of file → old version."""
    updated: dict[str, str] = {}
    errors: list[str] = []

    for rel_path, pattern, template in VERSION_LOCATIONS:
        full_path = PROJECT_ROOT / rel_path

        if not full_path.exists():
            errors.append(f"file not found: {rel_path}")
            continue

        content = full_path.read_text(encoding="utf-8")
        lines = content.splitlines(keepends=True)
        new_lines: list[str] = []
        found = False
        old_version = ""

        for line in lines:
            m = re.match(pattern, line)
            if m:
                found = True
                old_version_match = re.search(r"[0-9]+\.[0-9]+\.[0-9]+", line)
                old_version = old_version_match.group(0) if old_version_match else "?"
                new_lines.append(template.format(version=version) + "\n")
            else:
                new_lines.append(line)

        if not found:
            errors.append(f"version pattern not found in {rel_path}")
            continue

        new_content = "".join(new_lines)

        if dry_run:
            print(f"[dry-run] {rel_path}: {old_version} → {version}")
        else:
            full_path.write_text(new_content, encoding="utf-8")

        updated[rel_path] = old_version

    if errors:
        for err in errors:
            print(f"error: {err}", file=sys.stderr)
        sys.exit(1)

    return updated


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Bump finjuice version across all source locations."
    )
    parser.add_argument(
        "version",
        nargs="?",
        help="New version in X.Y.Z format",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without modifying files",
    )
    args = parser.parse_args()

    if not args.version:
        parser.print_help()
        sys.exit(1)

    validate_version(args.version)
    updated = bump_version(args.version, dry_run=args.dry_run)

    if not args.dry_run:
        print(f"✅ Version bumped to {args.version}")
        for path, old in updated.items():
            print(f"   {path}: {old} → {args.version}")
    else:
        print(f"[dry-run] Would bump version to {args.version} ({len(updated)} files)")


if __name__ == "__main__":
    main()
