#!/usr/bin/env python3
"""Run the public sample agent-first smoke workflow in an isolated temp workspace."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SAMPLE_XLSX = PROJECT_ROOT / "tests" / "fixtures" / "sample_banksalad.xlsx"


class AgentSmokeError(RuntimeError):
    """Raised when the public agent smoke workflow fails."""


@dataclass(frozen=True)
class SmokeStep:
    """One source-checkout CLI smoke step."""

    name: str
    args: tuple[str, ...]
    json_output: bool = True


def smoke_steps(*, data_dir: Path, sample_xlsx: Path) -> tuple[SmokeStep, ...]:
    """Return the public sample workflow command sequence."""
    data_dir_arg = str(data_dir)
    sample_arg = str(sample_xlsx)
    return (
        SmokeStep(
            name="init-workspace",
            args=("finjuice", "--data-dir", data_dir_arg, "init", "--no-git", "--with-agents"),
            json_output=False,
        ),
        SmokeStep(
            name="import-sample",
            args=("finjuice", "--data-dir", data_dir_arg, "import", "--file", sample_arg, "--json"),
        ),
        SmokeStep(
            name="status-json",
            args=("finjuice", "--data-dir", data_dir_arg, "status", "--json"),
        ),
        SmokeStep(
            name="index-compact",
            args=(
                "finjuice",
                "--data-dir",
                data_dir_arg,
                "index",
                "--json",
                "--privacy",
                "compact",
            ),
        ),
        SmokeStep(
            name="checkup-compact",
            args=(
                "finjuice",
                "--data-dir",
                data_dir_arg,
                "checkup",
                "--json",
                "--privacy",
                "compact",
            ),
        ),
        SmokeStep(
            name="review-template",
            args=(
                "finjuice",
                "--data-dir",
                data_dir_arg,
                "template",
                "run",
                "monthly_spend",
                "--json",
            ),
        ),
        SmokeStep(
            name="report-markdown",
            args=("finjuice", "--data-dir", data_dir_arg, "export", "--format", "md", "--json"),
        ),
    )


def isolated_env(*, runtime_root: Path) -> dict[str, str]:
    """Return an environment that keeps the smoke away from real user state."""
    home_dir = runtime_root / "home"
    xdg_config_dir = runtime_root / "xdg-config"
    xdg_cache_dir = runtime_root / "xdg-cache"
    xdg_data_dir = runtime_root / "xdg-data"
    for path in (home_dir, xdg_config_dir, xdg_cache_dir, xdg_data_dir):
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["HOME"] = str(home_dir)
    env["XDG_CONFIG_HOME"] = str(xdg_config_dir)
    env["XDG_CACHE_HOME"] = str(xdg_cache_dir)
    env["XDG_DATA_HOME"] = str(xdg_data_dir)
    env["FINJUICE_RUNTIME_UPDATE_CHECK"] = "0"
    return env


def run_command(
    args: Sequence[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: int = 180,
) -> subprocess.CompletedProcess[str]:
    """Run a finjuice smoke command through the checkout's uv environment."""
    command = ("uv", "run", *args)
    try:
        return subprocess.run(
            command,
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
            args=command,
            returncode=124,
            stdout=stdout,
            stderr=f"{stderr}\nTimed out after {timeout} seconds".strip(),
        )


def validate_step_result(step: SmokeStep, result: subprocess.CompletedProcess[str]) -> None:
    """Validate exit code and JSON stdout for a smoke step."""
    if result.returncode != 0:
        raise AgentSmokeError(_format_failure(step, result))

    if not step.json_output:
        return

    stdout = result.stdout.strip()
    if not stdout:
        raise AgentSmokeError(f"{step.name} produced empty stdout")

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise AgentSmokeError(f"{step.name} did not produce valid JSON: {exc}") from exc

    if not isinstance(payload, (dict, list)):
        raise AgentSmokeError(f"{step.name} JSON stdout must be an object or array")


def _format_failure(step: SmokeStep, result: subprocess.CompletedProcess[str]) -> str:
    command = " ".join(str(arg) for arg in result.args)
    stdout = result.stdout if result.stdout else "<empty>"
    stderr = result.stderr if result.stderr else "<empty>"
    return (
        f"{step.name} failed\n"
        f"Command: {command}\n"
        f"Exit code: {result.returncode}\n"
        f"stdout:\n{stdout}\n"
        f"stderr:\n{stderr}"
    )


def run_smoke(
    *,
    project_root: Path = PROJECT_ROOT,
    sample_xlsx: Path = PUBLIC_SAMPLE_XLSX,
    temp_root: Path,
) -> list[str]:
    """Run the public sample smoke workflow and return passed step names."""
    if not sample_xlsx.is_file():
        raise AgentSmokeError(f"public sample XLSX not found: {sample_xlsx}")

    runtime_root = temp_root / "runtime"
    data_dir = runtime_root / "data"
    work_dir = runtime_root / "work"
    data_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)
    env = isolated_env(runtime_root=runtime_root)

    passed: list[str] = []
    for step in smoke_steps(data_dir=data_dir, sample_xlsx=sample_xlsx):
        result = run_command(step.args, cwd=project_root, env=env)
        validate_step_result(step, result)
        passed.append(step.name)
    return passed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        type=Path,
        default=PUBLIC_SAMPLE_XLSX,
        help="Public-safe Banksalad XLSX fixture to import.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep the isolated HOME/XDG/data workspace after the run.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    temp_path = Path(tempfile.mkdtemp(prefix="finjuice-agent-smoke-"))
    try:
        passed = run_smoke(sample_xlsx=args.sample, temp_root=temp_path)
    except AgentSmokeError as exc:
        print(f"Agent workflow smoke failed: {exc}", file=sys.stderr)
        if args.keep_temp:
            print(f"Kept temp directory: {temp_path}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_temp:
            shutil.rmtree(temp_path, ignore_errors=True)

    print(f"agent workflow smoke: PASS ({', '.join(passed)})")
    if args.keep_temp:
        print(f"Kept temp directory: {temp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
