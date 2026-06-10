#!/usr/bin/env python3
"""Build, install, and smoke test packaged finjuice artifacts."""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Sequence

try:
    from scripts import check_package_contents
except ImportError:  # pragma: no cover - used when run as scripts/foo.py
    import check_package_contents  # type: ignore[no-redef]

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ArtifactChoice = Literal["wheel", "sdist", "both"]
ArtifactName = Literal["wheel", "sdist"]

ARTIFACT_PATTERNS: dict[ArtifactName, str] = {
    "wheel": "*.whl",
    "sdist": "*.tar.gz",
}

SMOKE_TRANSACTION_COLUMNS = [
    "row_hash",
    "date",
    "time",
    "type_raw",
    "type_norm",
    "major_raw",
    "minor_raw",
    "merchant_raw",
    "memo_raw",
    "amount",
    "account",
    "currency",
    "counterparty",
    "datetime",
    "category_rule",
    "category_final",
    "tags_rule",
    "tags_ai",
    "tags_manual",
    "tags_final",
    "confidence",
    "needs_review",
    "is_transfer",
    "transfer_group_id",
    "file_id",
    "source_row",
]

SMOKE_TRANSACTION_ROW = [
    "smoke0000000001",
    "2024-10-01",
    "12:00",
    "expense",
    "expense",
    "smoke",
    "smoke",
    "Smoke Merchant",
    "",
    "-1.0",
    "Smoke Account",
    "KRW",
    "",
    "2024-10-01T12:00:00",
    "smoke",
    "smoke",
    '["smoke"]',
    "[]",
    "[]",
    '["smoke"]',
    "1.0",
    "0",
    "0",
    "",
    "smoke_1",
    "1",
]

RESOURCE_PROBE_CODE = """
from importlib.resources import files

checks = {
    "schema": files("finjuice.schemas").joinpath("status.schema.json").is_file(),
    "template": files("finjuice.templates").joinpath("schema.yaml").is_file(),
}
missing = [name for name, ok in checks.items() if not ok]
if missing:
    raise SystemExit("missing packaged resources: " + ", ".join(missing))
print("schema: PASS")
print("template: PASS")
""".strip()


class SmokeArtifactError(RuntimeError):
    """Raised when an installed artifact smoke step fails."""


@dataclass(frozen=True)
class CommandProbe:
    """CLI or Python command that must pass against an installed artifact."""

    name: str
    args: tuple[str, ...]
    json_output: bool = False
    expected_stdout: str | None = None


@dataclass(frozen=True)
class Artifact:
    """Built artifact selected for installation smoke testing."""

    name: ArtifactName
    path: Path


def read_project_version(project_root: Path = PROJECT_ROOT) -> str:
    """Read the package version from pyproject.toml's ``[project]`` table."""
    pyproject_path = project_root / "pyproject.toml"
    in_project_table = False

    for raw_line in pyproject_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            in_project_table = line == "[project]"
            continue
        if in_project_table and line.startswith("version"):
            key, separator, value = line.partition("=")
            if separator and key.strip() == "version":
                return value.strip().strip('"').strip("'")

    raise SmokeArtifactError(f"Could not find [project].version in {pyproject_path}")


def selected_artifact_names(choice: ArtifactChoice) -> tuple[ArtifactName, ...]:
    """Return concrete artifact names for a CLI artifact choice."""
    if choice == "both":
        return ("wheel", "sdist")
    return (choice,)


def format_process_failure(message: str, result: subprocess.CompletedProcess[str]) -> str:
    """Format a subprocess failure with full captured output."""
    command = " ".join(str(arg) for arg in result.args)
    stdout = result.stdout if result.stdout else "<empty>"
    stderr = result.stderr if result.stderr else "<empty>"
    return (
        f"{message}\n"
        f"Command: {command}\n"
        f"Exit code: {result.returncode}\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def run_command(
    args: Sequence[str | Path],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Run a command with captured text output."""
    try:
        return subprocess.run(
            [str(arg) for arg in args],
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
        return subprocess.CompletedProcess(
            args=[str(arg) for arg in args],
            returncode=124,
            stdout=stdout,
            stderr=f"{stderr}\nTimed out after {timeout} seconds".strip(),
        )


def build_artifacts(
    *,
    project_root: Path,
    build_root: Path,
    artifact_names: Sequence[ArtifactName],
) -> dict[ArtifactName, Path]:
    """Build selected artifacts into a temporary dist directory."""
    dist_dir = build_root / "dist"
    dist_dir.mkdir(parents=True, exist_ok=True)

    build_args: list[str | Path] = [
        "uv",
        "build",
        "--out-dir",
        dist_dir,
        "--clear",
        "--color=never",
    ]
    if len(artifact_names) == 1:
        build_args.append(f"--{artifact_names[0]}")

    result = run_command(build_args, cwd=project_root, timeout=240)
    if result.returncode != 0:
        raise SmokeArtifactError(format_process_failure("artifact build failed", result))

    artifacts: dict[ArtifactName, Path] = {}
    for artifact_name in artifact_names:
        artifacts[artifact_name] = check_package_contents.find_single_artifact(
            ARTIFACT_PATTERNS[artifact_name],
            dist_dir=dist_dir,
        )
    return artifacts


def check_selected_artifact_contents(
    *,
    project_root: Path,
    artifacts: dict[ArtifactName, Path],
) -> None:
    """Reuse package content checks for artifacts built in the smoke temp dir."""
    try:
        if wheel_path := artifacts.get("wheel"):
            check_package_contents.check_paths_once(
                archive_name=wheel_path.name,
                members=check_package_contents.zip_members(wheel_path),
                expected_paths=check_package_contents.expected_wheel_resource_paths(project_root),
            )
        if sdist_path := artifacts.get("sdist"):
            check_package_contents.check_paths_once(
                archive_name=sdist_path.name,
                members=check_package_contents.strip_sdist_root(
                    check_package_contents.tar_members(sdist_path)
                ),
                expected_paths=check_package_contents.expected_sdist_source_paths(project_root),
            )
    except check_package_contents.PackageContentError as exc:
        raise SmokeArtifactError(f"package content check failed: {exc}") from exc


def venv_python_path(venv_dir: Path) -> Path:
    """Return the Python executable inside a stdlib venv."""
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def venv_bin_dir(venv_dir: Path) -> Path:
    """Return the executable directory inside a stdlib venv."""
    if os.name == "nt":
        return venv_dir / "Scripts"
    return venv_dir / "bin"


def create_stdlib_venv(venv_dir: Path) -> Path:
    """Create a fresh virtual environment with pip using stdlib ``venv``."""
    try:
        venv.EnvBuilder(with_pip=True, clear=True, symlinks=os.name != "nt").create(venv_dir)
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout or ""
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr or ""
        result = subprocess.CompletedProcess(
            args=exc.cmd,
            returncode=exc.returncode,
            stdout=stdout,
            stderr=stderr,
        )
        raise SmokeArtifactError(
            format_process_failure("stdlib venv creation failed", result)
        ) from exc
    except OSError as exc:
        raise SmokeArtifactError(f"stdlib venv creation failed: {exc}") from exc
    return venv_python_path(venv_dir)


def isolated_runtime_env(*, venv_dir: Path, runtime_root: Path) -> dict[str, str]:
    """Return an environment that avoids user config and checkout imports."""
    home_dir = runtime_root / "home"
    xdg_config_dir = runtime_root / "xdg-config"
    xdg_cache_dir = runtime_root / "xdg-cache"
    xdg_data_dir = runtime_root / "xdg-data"
    for path in (home_dir, xdg_config_dir, xdg_cache_dir, xdg_data_dir):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    env["HOME"] = str(home_dir)
    env["XDG_CONFIG_HOME"] = str(xdg_config_dir)
    env["XDG_CACHE_HOME"] = str(xdg_cache_dir)
    env["XDG_DATA_HOME"] = str(xdg_data_dir)
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PIP_NO_INPUT"] = "1"
    env["PYTHONNOUSERSITE"] = "1"
    env["PATH"] = f"{venv_bin_dir(venv_dir)}{os.pathsep}{env.get('PATH', '')}"
    return env


def install_artifact(
    *,
    python_path: Path,
    artifact_path: Path,
    cwd: Path,
    env: dict[str, str],
) -> None:
    """Install one built artifact into a fresh venv with pip."""
    result = run_command(
        [python_path, "-m", "pip", "install", artifact_path],
        cwd=cwd,
        env=env,
        timeout=240,
    )
    if result.returncode != 0:
        raise SmokeArtifactError(format_process_failure("pip install failed", result))


def prepare_smoke_data_dir(data_dir: Path) -> None:
    """Create a tiny synthetic data directory so ``status --json`` exits 0."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "metadata").mkdir(parents=True, exist_ok=True)
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    with (partition_dir / "transactions.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(SMOKE_TRANSACTION_COLUMNS)
        writer.writerow(SMOKE_TRANSACTION_ROW)


def command_probes(*, expected_version: str, data_dir: Path) -> tuple[CommandProbe, ...]:
    """Return CLI smoke probes run against the installed console script."""
    return (
        CommandProbe(
            name="version",
            args=("finjuice", "--version"),
            expected_stdout=f"finjuice {expected_version}",
        ),
        CommandProbe(
            name="doctor-json",
            args=("finjuice", "--data-dir", str(data_dir), "doctor", "--json"),
            json_output=True,
        ),
        CommandProbe(
            name="status-json",
            args=("finjuice", "--data-dir", str(data_dir), "status", "--json"),
            json_output=True,
        ),
        CommandProbe(
            name="manifest-json",
            args=("finjuice", "manifest", "--commands-only", "--json"),
            json_output=True,
        ),
    )


def validate_probe_result(
    probe: CommandProbe,
    result: subprocess.CompletedProcess[str],
    *,
    expected_version: str,
) -> None:
    """Validate exit code, stdout, JSON shape, and version output for a probe."""
    del expected_version

    if result.returncode != 0:
        raise SmokeArtifactError(format_process_failure(f"{probe.name} failed", result))

    stdout = result.stdout.strip()
    if not stdout:
        raise SmokeArtifactError(
            format_process_failure(f"{probe.name} produced empty stdout", result)
        )

    if probe.expected_stdout is not None and stdout != probe.expected_stdout:
        raise SmokeArtifactError(
            f"{probe.name} expected stdout {probe.expected_stdout!r}, got {stdout!r}"
        )

    if probe.json_output:
        try:
            json.loads(stdout)
        except json.JSONDecodeError as exc:
            raise SmokeArtifactError(
                f"{probe.name} did not produce valid JSON: {exc}\nstdout:\n{result.stdout}"
            ) from exc


def run_probe(probe: CommandProbe, *, cwd: Path, env: dict[str, str]) -> None:
    """Run and validate one command probe."""
    result = run_command(probe.args, cwd=cwd, env=env)
    validate_probe_result(probe, result, expected_version="")


def run_resource_probe(*, python_path: Path, cwd: Path, env: dict[str, str]) -> None:
    """Verify installed schema and template resources resolve via importlib.resources."""
    probe = CommandProbe(
        name="resource-probe",
        args=(str(python_path), "-I", "-c", RESOURCE_PROBE_CODE),
    )
    result = run_command(probe.args, cwd=cwd, env=env)
    validate_probe_result(probe, result, expected_version="")


def smoke_artifact(
    artifact: Artifact,
    *,
    expected_version: str,
    temp_root: Path,
) -> None:
    """Install one artifact into a fresh venv and run smoke probes."""
    artifact_root = temp_root / artifact.name
    venv_dir = artifact_root / "venv"
    runtime_root = artifact_root / "runtime"
    work_dir = artifact_root / "work"
    data_dir = runtime_root / "data"
    work_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    python_path = create_stdlib_venv(venv_dir)
    env = isolated_runtime_env(venv_dir=venv_dir, runtime_root=runtime_root)
    install_artifact(python_path=python_path, artifact_path=artifact.path, cwd=work_dir, env=env)
    prepare_smoke_data_dir(data_dir)

    for probe in command_probes(expected_version=expected_version, data_dir=data_dir):
        result = run_command(probe.args, cwd=work_dir, env=env)
        validate_probe_result(probe, result, expected_version=expected_version)
    run_resource_probe(python_path=python_path, cwd=work_dir, env=env)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Build finjuice artifacts, install them in fresh stdlib venvs, and smoke test."
    )
    parser.add_argument(
        "--artifact",
        choices=("wheel", "sdist", "both"),
        default="both",
        help="Artifact type to smoke test (default: both).",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary build and venv directories for debugging.",
    )
    return parser.parse_args(argv)


def temp_parent_dir() -> Path | None:
    """Return a stable temp parent when the platform provides one."""
    private_tmp = Path("/private/tmp")
    if private_tmp.is_dir() and os.access(private_tmp, os.W_OK):
        return private_tmp
    return None


def run_smoke(
    *,
    project_root: Path,
    temp_root: Path,
    artifact_choice: ArtifactChoice,
) -> list[ArtifactName]:
    """Build selected artifacts and smoke test each one."""
    artifact_names = selected_artifact_names(artifact_choice)
    artifacts = build_artifacts(
        project_root=project_root,
        build_root=temp_root / "build",
        artifact_names=artifact_names,
    )
    check_selected_artifact_contents(project_root=project_root, artifacts=artifacts)

    expected_version = read_project_version(project_root)
    passed: list[ArtifactName] = []
    for artifact_name in artifact_names:
        smoke_artifact(
            Artifact(name=artifact_name, path=artifacts[artifact_name]),
            expected_version=expected_version,
            temp_root=temp_root,
        )
        passed.append(artifact_name)
    return passed


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    artifact_choice: ArtifactChoice = args.artifact

    temp_path = Path(tempfile.mkdtemp(prefix="finjuice-artifact-smoke-", dir=temp_parent_dir()))
    try:
        passed = run_smoke(
            project_root=PROJECT_ROOT,
            temp_root=temp_path,
            artifact_choice=artifact_choice,
        )
    except SmokeArtifactError as exc:
        print(f"Installed artifact smoke failed: {exc}", file=sys.stderr)
        if args.keep_temp:
            print(f"Kept temp directory: {temp_path}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_temp:
            shutil.rmtree(temp_path, ignore_errors=True)

    print(" / ".join(f"{artifact_name}: PASS" for artifact_name in passed))
    if args.keep_temp:
        print(f"Kept temp directory: {temp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
