#!/usr/bin/env python3
"""Validate finjuice agent skill packaging contracts."""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

SKILL_DIR_PATTERN = "finjuice*"
REQUIRED_FRONTMATTER_KEYS = ("name", "description", "compatibility")
REQUIRED_HEADINGS = ("## Side Effects", "## Runtime Requirements", "## Runtime Preflight")
SHARED_RUNTIME_REFERENCE = "skills/finjuice/references/runtime-preflight.md"
REQUIRED_RUNTIME_HELPER = "skills/finjuice/scripts/ensure_finjuice_cli.sh"
STALE_RUNTIME_HELPER = "../finjuice/scripts/ensure_finjuice_cli.sh"


@dataclass(frozen=True)
class ValidationError:
    """A single file/line validation failure."""

    path: Path
    line: int
    message: str

    def format(self, root: Path) -> str:
        rel_path = self.path.relative_to(root) if self.path.is_relative_to(root) else self.path
        return f"{rel_path}:{self.line}: {self.message}"


def validate_agent_package(root: Path) -> list[ValidationError]:
    """Validate skill frontmatter, references, sibling names, and contract blocks."""
    root = root.resolve()
    skill_files = _skill_files(root)
    errors: list[ValidationError] = []

    if not skill_files:
        return [ValidationError(root / "skills", 1, "no finjuice skill files found")]

    errors.extend(_validate_shared_runtime_assets(root))

    for skill_file in skill_files:
        text = skill_file.read_text(encoding="utf-8")
        frontmatter, _body_start_line = _frontmatter(text)

        errors.extend(_validate_frontmatter(root, skill_file, frontmatter))
        errors.extend(_validate_required_headings(skill_file, text))
        errors.extend(_validate_runtime_helper_contract(skill_file, text))

    for package_file in _package_markdown_files(root):
        text = package_file.read_text(encoding="utf-8")
        _frontmatter_values, body_start_line = _frontmatter(text)

        errors.extend(_validate_stale_runtime_helper(package_file, text))
        errors.extend(_validate_markdown_links(root, package_file, text))
        errors.extend(_validate_literal_file_references(root, package_file, text))
        errors.extend(_validate_sibling_skill_names(root, package_file, text, body_start_line))

    return errors


def _skill_files(root: Path) -> list[Path]:
    skills_root = root / "skills"
    return sorted(
        path for path in skills_root.glob(f"{SKILL_DIR_PATTERN}/SKILL.md") if path.is_file()
    )


def _package_markdown_files(root: Path) -> list[Path]:
    skills_root = root / "skills"
    return sorted(
        path for path in skills_root.glob(f"{SKILL_DIR_PATTERN}/**/*.md") if path.is_file()
    )


def _validate_shared_runtime_assets(root: Path) -> list[ValidationError]:
    errors: list[ValidationError] = []

    runtime_reference = root / SHARED_RUNTIME_REFERENCE
    if not runtime_reference.is_file():
        errors.append(
            ValidationError(
                runtime_reference,
                1,
                f"missing shared runtime preflight reference: {SHARED_RUNTIME_REFERENCE}",
            )
        )

    runtime_helper = root / REQUIRED_RUNTIME_HELPER
    if not runtime_helper.is_file():
        errors.append(
            ValidationError(
                runtime_helper,
                1,
                f"missing runtime helper: {REQUIRED_RUNTIME_HELPER}",
            )
        )
    elif not os.access(runtime_helper, os.X_OK):
        errors.append(
            ValidationError(
                runtime_helper,
                1,
                f"runtime helper is not executable: {REQUIRED_RUNTIME_HELPER}",
            )
        )

    return errors


def _frontmatter(text: str) -> tuple[dict[str, str], int]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, 1

    values: dict[str, str] = {}
    current_key: str | None = None
    for line_number, line in enumerate(lines[1:], start=2):
        if line.strip() == "---":
            return values, line_number + 1
        if not line.strip() or line.startswith(" ") or line.startswith("\t"):
            continue
        match = re.match(r"^(?P<key>[A-Za-z0-9_-]+):\s*(?P<value>.*)$", line)
        if match:
            current_key = match.group("key")
            values[current_key] = match.group("value").strip().strip('"')
        elif current_key:
            values[current_key] = f"{values[current_key]}\n{line}"

    return values, 1


def _validate_frontmatter(
    root: Path, skill_file: Path, frontmatter: dict[str, str]
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    if not frontmatter:
        return [ValidationError(skill_file, 1, "missing YAML-style frontmatter")]

    for key in REQUIRED_FRONTMATTER_KEYS:
        if not frontmatter.get(key):
            errors.append(ValidationError(skill_file, 1, f"missing frontmatter key: {key}"))

    expected_name = skill_file.parent.name
    actual_name = frontmatter.get("name")
    if actual_name and actual_name != expected_name:
        errors.append(
            ValidationError(
                skill_file,
                1,
                f"frontmatter name {actual_name!r} does not match directory {expected_name!r}",
            )
        )

    expected_path = f"skills/{expected_name}/SKILL.md"
    if skill_file.relative_to(root).as_posix() != expected_path:
        errors.append(
            ValidationError(
                skill_file,
                1,
                "skill path is not under skills/<name>/SKILL.md",
            )
        )

    return errors


def _validate_required_headings(skill_file: Path, text: str) -> list[ValidationError]:
    return [
        ValidationError(skill_file, 1, f"missing required heading: {heading}")
        for heading in REQUIRED_HEADINGS
        if heading not in text
    ]


def _validate_runtime_helper_contract(skill_file: Path, text: str) -> list[ValidationError]:
    errors: list[ValidationError] = []

    if SHARED_RUNTIME_REFERENCE not in text:
        errors.append(
            ValidationError(
                skill_file,
                1,
                f"missing shared runtime preflight reference: {SHARED_RUNTIME_REFERENCE}",
            )
        )

    return errors


def _validate_stale_runtime_helper(package_file: Path, text: str) -> list[ValidationError]:
    stale_line = _line_number(text, STALE_RUNTIME_HELPER)
    if not stale_line:
        return []
    return [
        ValidationError(
            package_file,
            stale_line,
            f"stale runtime helper path: {STALE_RUNTIME_HELPER}",
        )
    ]


def _validate_markdown_links(root: Path, skill_file: Path, text: str) -> list[ValidationError]:
    errors: list[ValidationError] = []
    for match in re.finditer(r"\[[^\]]+\]\((?P<target>[^)]+)\)", text):
        target = match.group("target").split("#", maxsplit=1)[0]
        if not target or _is_external_target(target):
            continue
        if not _target_exists(root, skill_file, target):
            errors.append(
                ValidationError(
                    skill_file,
                    _line_number_at(text, match.start()),
                    f"missing markdown link target: {target}",
                )
            )
    return errors


def _validate_literal_file_references(
    root: Path, skill_file: Path, text: str
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    pattern = re.compile(
        r"(?P<target>(?:(?:\.\./)+|skills/|references/)[A-Za-z0-9_./-]+"
        r"(?:SKILL\.md|\.md|\.sh))"
    )

    for match in pattern.finditer(text):
        target = match.group("target")
        if not _target_exists(root, skill_file, target):
            errors.append(
                ValidationError(
                    skill_file,
                    _line_number_at(text, match.start()),
                    f"missing referenced file: {target}",
                )
            )
    return errors


def _validate_sibling_skill_names(
    root: Path, skill_file: Path, text: str, body_start_line: int
) -> list[ValidationError]:
    errors: list[ValidationError] = []
    body = "\n".join(text.splitlines()[body_start_line - 1 :])
    for match in re.finditer(r"\bfinjuice-[a-z0-9-]+\b", body):
        sibling_name = match.group(0)
        if not (root / "skills" / sibling_name / "SKILL.md").exists():
            errors.append(
                ValidationError(
                    skill_file,
                    _line_number_at(text, match.start()),
                    f"unknown sibling skill: {sibling_name}",
                )
            )
    return errors


def _is_external_target(target: str) -> bool:
    return target.startswith(("http://", "https://", "mailto:", "#"))


def _target_exists(root: Path, skill_file: Path, target: str) -> bool:
    if target.startswith("skills/"):
        candidate = root / target
    else:
        candidate = skill_file.parent / target
    return candidate.exists()


def _line_number(text: str, needle: str) -> int | None:
    index = text.find(needle)
    if index == -1:
        return None
    return _line_number_at(text, index)


def _line_number_at(text: str, index: int) -> int:
    return text.count("\n", 0, index) + 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="repository root")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    errors = validate_agent_package(root)
    if errors:
        for error in errors:
            print(error.format(root), file=sys.stderr)
        return 1

    print("Agent package validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
