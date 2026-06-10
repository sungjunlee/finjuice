#!/usr/bin/env python3
"""Build package artifacts and verify packaged resources are present once."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
import zipfile
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = PROJECT_ROOT / "dist"

FORBIDDEN_ARCHIVE_PREFIXES = (
    ".claude/",
    ".codex/",
    ".mypy_cache/",
    ".pytest_cache/",
    ".ruff_cache/",
    ".serena/",
    ".venv/",
    "_journal/",
    "data/",
    "dist/",
    "exports/",
    "htmlcov/",
)
FORBIDDEN_ARCHIVE_NAMES = {
    ".coverage",
    ".DS_Store",
    ".env",
    "audit-report.json",
    "bandit-report.json",
}


class PackageContentError(RuntimeError):
    """Raised when built package artifacts do not contain the expected resources."""


def _source_files(root: Path) -> list[Path]:
    if not root.is_dir():
        raise PackageContentError(f"Expected source directory does not exist: {root}")
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file()
        and "__pycache__" not in path.parts
        and path.suffix not in {".pyc", ".pyo"}
    )


def expected_wheel_resource_paths(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return runtime resources that must be present in the built wheel."""
    mappings = (
        (project_root / "schemas", "finjuice/schemas"),
        (project_root / "src" / "finjuice" / "templates", "finjuice/templates"),
    )

    expected: list[str] = []
    for source_root, wheel_prefix in mappings:
        for source_file in _source_files(source_root):
            relative_path = source_file.relative_to(source_root).as_posix()
            expected.append(f"{wheel_prefix}/{relative_path}")
    return sorted(expected)


def expected_sdist_source_paths(project_root: Path = PROJECT_ROOT) -> list[str]:
    """Return source resources that must stay present in the built sdist."""
    source_roots = (
        project_root / "schemas",
        project_root / "src" / "finjuice" / "templates",
        project_root / "templates",
    )

    expected: list[str] = []
    for source_root in source_roots:
        source_root_name = source_root.relative_to(project_root).as_posix()
        for source_file in _source_files(source_root):
            relative_path = source_file.relative_to(source_root).as_posix()
            expected.append(f"{source_root_name}/{relative_path}")
    return sorted(expected)


def zip_members(path: Path) -> list[str]:
    """Return non-directory archive member names from a zip/wheel file."""
    with zipfile.ZipFile(path) as archive:
        return [name for name in archive.namelist() if not name.endswith("/")]


def tar_members(path: Path) -> list[str]:
    """Return non-directory archive member names from a tar file."""
    with tarfile.open(path, "r:gz") as archive:
        return [member.name for member in archive.getmembers() if member.isfile()]


def strip_sdist_root(members: list[str]) -> list[str]:
    """Remove the generated top-level sdist directory from member names."""
    roots = {member.split("/", 1)[0] for member in members}
    if len(roots) != 1:
        raise PackageContentError(
            "Expected sdist to contain a single top-level directory, found: "
            + ", ".join(sorted(roots))
        )
    return sorted(member.split("/", 1)[1] for member in members if "/" in member)


def check_paths_once(*, archive_name: str, members: list[str], expected_paths: list[str]) -> None:
    """Verify expected archive paths are present exactly once."""
    counts = Counter(members)

    missing_paths = [path for path in expected_paths if counts[path] == 0]
    duplicate_paths = [path for path in expected_paths if counts[path] > 1]

    if missing_paths:
        preview = "\n".join(f"  - {path}" for path in missing_paths[:20])
        extra = "" if len(missing_paths) <= 20 else f"\n  ... {len(missing_paths) - 20} more"
        message = f"{archive_name} is missing expected resources:\n{preview}{extra}"
        raise PackageContentError(message)

    if duplicate_paths:
        preview = "\n".join(f"  - {path}" for path in duplicate_paths[:20])
        extra = "" if len(duplicate_paths) <= 20 else f"\n  ... {len(duplicate_paths) - 20} more"
        raise PackageContentError(
            f"{archive_name} contains expected resources more than once:\n{preview}{extra}"
        )


def check_forbidden_paths(*, archive_name: str, members: list[str]) -> None:
    """Fail when local state, private data, or generated artifacts enter packages."""
    forbidden = [
        path
        for path in members
        if path in FORBIDDEN_ARCHIVE_NAMES
        or any(path.startswith(prefix) for prefix in FORBIDDEN_ARCHIVE_PREFIXES)
    ]
    if forbidden:
        preview = "\n".join(f"  - {path}" for path in forbidden[:20])
        extra = "" if len(forbidden) <= 20 else f"\n  ... {len(forbidden) - 20} more"
        raise PackageContentError(
            f"{archive_name} contains forbidden local/private paths:\n{preview}{extra}"
        )


def find_single_artifact(pattern: str, *, dist_dir: Path = DIST_DIR) -> Path:
    """Find one built artifact matching the pattern."""
    matches = sorted(dist_dir.glob(pattern))
    if len(matches) != 1:
        names = ", ".join(path.name for path in matches) or "none"
        raise PackageContentError(f"Expected exactly one {pattern} artifact, found: {names}")
    return matches[0]


def run_package_build(project_root: Path = PROJECT_ROOT) -> None:
    """Build the package from a clean dist directory and fail on build warnings."""
    dist_dir = project_root / "dist"
    if dist_dir.exists():
        shutil.rmtree(dist_dir)

    # Avoid syncing the project before the artifact check builds it.
    result = subprocess.run(
        ["uv", "run", "--no-project", "--with", "hatchling", "python", "-m", "hatchling", "build"],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )

    build_output = "\n".join(part for part in (result.stdout, result.stderr) if part)
    if build_output:
        print(build_output, end="" if build_output.endswith("\n") else "\n")

    if result.returncode != 0:
        raise PackageContentError(f"package build failed with exit code {result.returncode}")

    if "warning" in build_output.lower():
        raise PackageContentError("package build emitted warning output")


def check_built_artifacts(project_root: Path = PROJECT_ROOT) -> None:
    """Verify the built wheel and sdist contain the expected resources once."""
    dist_dir = project_root / "dist"
    wheel_path = find_single_artifact("*.whl", dist_dir=dist_dir)
    sdist_path = find_single_artifact("*.tar.gz", dist_dir=dist_dir)
    wheel_members = zip_members(wheel_path)
    sdist_members = strip_sdist_root(tar_members(sdist_path))

    check_forbidden_paths(archive_name=wheel_path.name, members=wheel_members)
    check_forbidden_paths(archive_name=sdist_path.name, members=sdist_members)

    check_paths_once(
        archive_name=wheel_path.name,
        members=wheel_members,
        expected_paths=expected_wheel_resource_paths(project_root),
    )
    check_paths_once(
        archive_name=sdist_path.name,
        members=sdist_members,
        expected_paths=expected_sdist_source_paths(project_root),
    )

    print(f"Package contents OK: {wheel_path.name}, {sdist_path.name}")


def main() -> int:
    """Build package artifacts and verify package contents."""
    try:
        run_package_build()
        check_built_artifacts()
    except PackageContentError as exc:
        print(f"Package contents check failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
