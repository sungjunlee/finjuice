#!/usr/bin/env python3
"""Validate representative installed finjuice CLI JSON outputs against schemas."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Sequence

import jsonschema
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

try:
    from scripts import smoke_installed_artifact
except ImportError:  # pragma: no cover - used when run as scripts/foo.py
    import smoke_installed_artifact  # type: ignore[no-redef]

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = PROJECT_ROOT / "schemas"
DATA_DIR_TOKEN = "{data_dir}"
ANALYTICS_EXTRA = "analytics"
FailureCategory = Literal[
    "install-failed",
    "command-failed",
    "json-malformed",
    "schema-drift",
]


@dataclass(frozen=True)
class JsonCommand:
    """Installed CLI command whose JSON stdout must validate against a schema."""

    name: str
    args: tuple[str, ...]
    schema_file: str
    reason: str
    requires_analytics: bool = False


@dataclass(frozen=True)
class CapturedOutput:
    """Captured subprocess output included in smoke diagnostics."""

    stderr: str = ""
    stdout: str | None = None


@dataclass(frozen=True)
class InstalledCliEnvironment:
    """Installed wheel runtime used by JSON smoke commands."""

    artifact: Path
    work_dir: Path
    data_dir: Path
    env: dict[str, str]


class CliJsonSmokeError(RuntimeError):
    """Raised when installed CLI JSON smoke validation fails."""


COMMANDS: dict[str, JsonCommand] = {
    "status": JsonCommand(
        name="status",
        args=("--data-dir", DATA_DIR_TOKEN, "status", "--json"),
        schema_file="status.schema.json",
        reason="Primary machine-readable health/status envelope.",
    ),
    "doctor": JsonCommand(
        name="doctor",
        args=("--data-dir", DATA_DIR_TOKEN, "doctor", "--json"),
        schema_file="doctor.schema.json",
        reason="Installed runtime and dependency diagnostics.",
    ),
    "manifest": JsonCommand(
        name="manifest",
        args=("manifest", "--json"),
        schema_file="manifest.schema.json",
        reason="Self-describing CLI command/API discovery.",
    ),
    "rules-list": JsonCommand(
        name="rules-list",
        args=("--data-dir", DATA_DIR_TOKEN, "rules", "list", "--json"),
        schema_file="rules_list.schema.json",
        reason="Read-only tagging rule registry surface.",
    ),
    "rules-suggest": JsonCommand(
        name="rules-suggest",
        args=("--data-dir", DATA_DIR_TOKEN, "rules", "suggest", "--json", "--top", "1"),
        schema_file="rules_suggest.schema.json",
        reason="Analytics-backed rule suggestion surface used by curation skills.",
        requires_analytics=True,
    ),
    "query": JsonCommand(
        name="query",
        args=(
            "--data-dir",
            DATA_DIR_TOKEN,
            "query",
            "SELECT date, merchant_raw, amount FROM transactions LIMIT 1",
            "--json",
        ),
        schema_file="query.schema.json",
        reason="Arbitrary read-only SQL analysis surface with pagination metadata.",
        requires_analytics=True,
    ),
    "explain": JsonCommand(
        name="explain",
        args=("--data-dir", DATA_DIR_TOKEN, "explain", "Smoke Merchant", "--json"),
        schema_file="explain.schema.json",
        reason="Transaction classification trace surface over synthetic local data.",
        requires_analytics=True,
    ),
    "template-run": JsonCommand(
        name="template-run",
        args=(
            "--data-dir",
            DATA_DIR_TOKEN,
            "template",
            "run",
            "monthly_spend",
            "--json",
            "--limit",
            "1",
        ),
        schema_file="template_run.schema.json",
        reason="Analytics-backed template execution surface used by review skills.",
        requires_analytics=True,
    ),
    "networth-forecast": JsonCommand(
        name="networth-forecast",
        args=(
            "--data-dir",
            DATA_DIR_TOKEN,
            "networth",
            "forecast",
            "--from",
            "2024-10-01",
            "--years",
            "1",
            "--json",
        ),
        schema_file="networth_forecast.schema.json",
        reason="Forward-looking net worth analysis surface with deterministic assumptions.",
    ),
    "checkup-compact": JsonCommand(
        name="checkup-compact",
        args=("--data-dir", DATA_DIR_TOKEN, "checkup", "--json", "--privacy", "compact"),
        schema_file="checkup.schema.json",
        reason="Privacy-profiled sensitive summary surface.",
    ),
}


def _format_command(command: Sequence[str | Path]) -> str:
    return " ".join(str(part) for part in command)


def _stderr_text(stderr: str) -> str:
    return stderr if stderr else "<empty>"


def format_failure(
    *,
    category: FailureCategory,
    artifact: Path,
    command: Sequence[str | Path],
    detail: str,
    output: CapturedOutput | None = None,
) -> str:
    """Format categorized smoke diagnostics with artifact, command, and stderr."""
    captured = output or CapturedOutput()
    lines = [
        f"[{category}] artifact={artifact}",
        f"command={_format_command(command)}",
        f"detail={detail}",
        "stderr:",
        _stderr_text(captured.stderr),
    ]
    if captured.stdout is not None:
        lines.extend(["stdout:", captured.stdout if captured.stdout else "<empty>"])
    return "\n".join(lines)


def select_commands(raw_filter: str | None) -> tuple[JsonCommand, ...]:
    """Return the command matrix, optionally filtered by comma-separated names."""
    if raw_filter is None or not raw_filter.strip():
        return tuple(COMMANDS.values())

    requested = {name.strip() for name in raw_filter.split(",") if name.strip()}
    unknown = sorted(requested - set(COMMANDS))
    if unknown:
        available = ", ".join(COMMANDS)
        raise CliJsonSmokeError(
            f"unknown --commands value(s): {', '.join(unknown)}. Available: {available}"
        )

    return tuple(command for name, command in COMMANDS.items() if name in requested)


def resolve_command_args(command: JsonCommand, *, data_dir: Path) -> tuple[str, ...]:
    """Return executable command args with synthetic data-dir placeholders expanded."""
    return ("finjuice",) + tuple(
        str(data_dir) if arg == DATA_DIR_TOKEN else arg for arg in command.args
    )


def _load_schema(schema_file: str, *, schemas_dir: Path) -> dict[str, Any]:
    schema_path = schemas_dir / schema_file
    return json.loads(schema_path.read_text(encoding="utf-8"))


def _schema_validator(
    schema: dict[str, Any],
    *,
    schemas_dir: Path,
) -> jsonschema.Draft202012Validator:
    resources = []
    for schema_path in schemas_dir.glob("*.schema.json"):
        contents = _load_schema(schema_path.name, schemas_dir=schemas_dir)
        resource = Resource.from_contents(contents, default_specification=DRAFT202012)
        resources.extend(
            [
                (schema_path.name, resource),
                (f"{schemas_dir.as_uri()}/{schema_path.name}", resource),
            ]
        )
    registry = Registry().with_resources(resources)
    return jsonschema.Draft202012Validator(schema, registry=registry)


def _validate_payload(payload: Any, *, schema_file: str, schemas_dir: Path) -> None:
    schema = _load_schema(schema_file, schemas_dir=schemas_dir)
    jsonschema.Draft202012Validator.check_schema(schema)
    _schema_validator(schema, schemas_dir=schemas_dir).validate(payload)


def _current_version_wheel(project_root: Path) -> Path | None:
    """Return a reusable dist wheel when it uniquely matches the project version."""
    dist_dir = project_root / "dist"
    if not dist_dir.is_dir():
        return None

    wheels = sorted(dist_dir.glob("*.whl"))
    if len(wheels) != 1:
        return None

    expected_version = smoke_installed_artifact.read_project_version(project_root)
    wheel = wheels[0]
    if f"-{expected_version}-" not in wheel.name:
        return None
    return wheel


def find_or_build_wheel(*, project_root: Path, temp_root: Path) -> Path:
    """Reuse an existing current dist wheel when available, otherwise build one."""
    if wheel := _current_version_wheel(project_root):
        artifacts = {"wheel": wheel}
    else:
        try:
            artifacts = smoke_installed_artifact.build_artifacts(
                project_root=project_root,
                build_root=temp_root / "build",
                artifact_names=("wheel",),
            )
        except smoke_installed_artifact.SmokeArtifactError as exc:
            raise CliJsonSmokeError(
                format_failure(
                    category="install-failed",
                    artifact=Path("<wheel>"),
                    command=("uv", "build", "--wheel"),
                    detail="Could not build a wheel for installed CLI JSON smoke.",
                    output=CapturedOutput(stderr=str(exc)),
                )
            ) from exc

    try:
        smoke_installed_artifact.check_selected_artifact_contents(
            project_root=project_root,
            artifacts=artifacts,
        )
    except smoke_installed_artifact.SmokeArtifactError as exc:
        raise CliJsonSmokeError(
            format_failure(
                category="install-failed",
                artifact=artifacts["wheel"],
                command=("check_package_contents", artifacts["wheel"]),
                detail="Built wheel is missing packaged resources needed at runtime.",
                output=CapturedOutput(stderr=str(exc)),
            )
        ) from exc
    return artifacts["wheel"]


def _prepare_cli_json_smoke_data_dir(data_dir: Path) -> None:
    """Extend the shared synthetic fixture for analysis-oriented JSON commands."""
    smoke_installed_artifact.prepare_smoke_data_dir(data_dir)
    (data_dir / "rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "rules:",
                "  - name: smoke_merchant",
                '    match: "Smoke Merchant"',
                "    fields: [merchant_raw]",
                '    tags: ["smoke"]',
                '    category: "smoke"',
                "    priority: 90",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "assets.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "manual_assets:",
                "  - name: Smoke Cash",
                "    category: financial",
                "    value: 1000000",
                "liabilities:",
                "  - name: Smoke Loan",
                "    principal: 100000",
                "    rate: 0.0",
                "    type: other",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (data_dir / "scenarios.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "assumptions:",
                "  default_savings_per_month: 10000",
                "  asset_returns:",
                "    financial:",
                "      conservative: 0.0",
                "      neutral: 0.0",
                "      optimistic: 0.0",
                "  liability_rate_delta: 0.0",
                "lifecycle_events: []",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _install_wheel_for_cli_json_smoke(
    *,
    python_path: Path,
    artifact_path: Path,
    cwd: Path,
    env: dict[str, str],
    include_analytics_extra: bool,
) -> None:
    """Install the wheel, including analytics extras only for commands that need them."""
    if not include_analytics_extra:
        smoke_installed_artifact.install_artifact(
            python_path=python_path,
            artifact_path=artifact_path,
            cwd=cwd,
            env=env,
        )
        return

    requirement = f"finjuice[{ANALYTICS_EXTRA}] @ {artifact_path.resolve().as_uri()}"
    install_args: list[str | Path] = [python_path, "-m", "pip", "install", requirement]
    result = smoke_installed_artifact.run_command(
        install_args,
        cwd=cwd,
        env=env,
        timeout=240,
    )
    if result.returncode != 0:
        raise smoke_installed_artifact.SmokeArtifactError(
            smoke_installed_artifact.format_process_failure(
                f"pip install with {ANALYTICS_EXTRA!r} extra failed",
                result,
            )
        )


def install_wheel_environment(
    *,
    wheel_path: Path,
    temp_root: Path,
    include_analytics_extra: bool = False,
) -> InstalledCliEnvironment:
    """Create a stdlib venv, install the wheel, and return work dir plus env."""
    artifact_root = temp_root / "wheel-json"
    venv_dir = artifact_root / "venv"
    runtime_root = artifact_root / "runtime"
    work_dir = artifact_root / "work"
    data_dir = runtime_root / "data"
    work_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    try:
        python_path = smoke_installed_artifact.create_stdlib_venv(venv_dir)
        env = smoke_installed_artifact.isolated_runtime_env(
            venv_dir=venv_dir,
            runtime_root=runtime_root,
        )
        _install_wheel_for_cli_json_smoke(
            python_path=python_path,
            artifact_path=wheel_path,
            cwd=work_dir,
            env=env,
            include_analytics_extra=include_analytics_extra,
        )
    except smoke_installed_artifact.SmokeArtifactError as exc:
        raise CliJsonSmokeError(
            format_failure(
                category="install-failed",
                artifact=wheel_path,
                command=(python_path if "python_path" in locals() else "python", "-m", "pip"),
                detail="Could not install the wheel into a fresh stdlib venv.",
                output=CapturedOutput(stderr=str(exc)),
            )
        ) from exc

    _prepare_cli_json_smoke_data_dir(data_dir)
    return InstalledCliEnvironment(
        artifact=wheel_path,
        work_dir=work_dir,
        data_dir=data_dir,
        env=env,
    )


def validate_installed_command(
    command: JsonCommand,
    *,
    runtime: InstalledCliEnvironment,
    schemas_dir: Path = SCHEMAS_DIR,
) -> None:
    """Run one installed CLI command and validate stdout against its schema."""
    args = resolve_command_args(command, data_dir=runtime.data_dir)
    result = smoke_installed_artifact.run_command(
        args,
        cwd=runtime.work_dir,
        env=runtime.env,
        timeout=60,
    )

    stdout = result.stdout.strip()
    if result.returncode != 0 or not stdout:
        detail = (
            f"CLI exited {result.returncode}."
            if result.returncode != 0
            else "CLI produced no stdout."
        )
        raise CliJsonSmokeError(
            format_failure(
                category="command-failed",
                artifact=runtime.artifact,
                command=args,
                detail=detail,
                output=CapturedOutput(stderr=result.stderr, stdout=result.stdout),
            )
        )

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise CliJsonSmokeError(
            format_failure(
                category="json-malformed",
                artifact=runtime.artifact,
                command=args,
                detail=f"stdout is not valid JSON: {exc}",
                output=CapturedOutput(stderr=result.stderr, stdout=result.stdout),
            )
        ) from exc

    try:
        _validate_payload(payload, schema_file=command.schema_file, schemas_dir=schemas_dir)
    except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
        raise CliJsonSmokeError(
            format_failure(
                category="schema-drift",
                artifact=runtime.artifact,
                command=args,
                detail=f"Could not load/compile {command.schema_file}: {exc}",
                output=CapturedOutput(stderr=result.stderr, stdout=result.stdout),
            )
        ) from exc
    except jsonschema.ValidationError as exc:
        location = exc.json_path or "$"
        raise CliJsonSmokeError(
            format_failure(
                category="schema-drift",
                artifact=runtime.artifact,
                command=args,
                detail=f"{command.schema_file} rejected {location}: {exc.message}",
                output=CapturedOutput(stderr=result.stderr, stdout=result.stdout),
            )
        ) from exc


def run_smoke(
    *,
    project_root: Path,
    temp_root: Path,
    command_filter: str | None,
) -> list[str]:
    """Run installed wheel JSON schema smoke tests and return passed names."""
    selected = select_commands(command_filter)
    wheel_path = find_or_build_wheel(project_root=project_root, temp_root=temp_root)
    runtime = install_wheel_environment(
        wheel_path=wheel_path,
        temp_root=temp_root,
        include_analytics_extra=any(command.requires_analytics for command in selected),
    )

    passed: list[str] = []
    for command in selected:
        validate_installed_command(
            command,
            runtime=runtime,
        )
        print(f"{command.name}: PASS ({command.schema_file})")
        passed.append(command.name)
    return passed


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Install the built finjuice wheel and validate representative CLI JSON."
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary build, venv, and synthetic data directories for debugging.",
    )
    parser.add_argument(
        "--commands",
        help="Comma-separated COMMANDS matrix names to run, e.g. status,query.",
    )
    return parser.parse_args(argv)


def temp_parent_dir() -> Path | None:
    """Return a stable temp parent when the platform provides one."""
    private_tmp = Path("/private/tmp")
    if private_tmp.is_dir() and os.access(private_tmp, os.W_OK):
        return private_tmp
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    args = parse_args(argv)
    temp_path = Path(tempfile.mkdtemp(prefix="finjuice-cli-json-smoke-", dir=temp_parent_dir()))
    try:
        passed = run_smoke(
            project_root=PROJECT_ROOT,
            temp_root=temp_path,
            command_filter=args.commands,
        )
    except CliJsonSmokeError as exc:
        print(f"Installed CLI JSON smoke failed: {exc}", file=sys.stderr)
        if args.keep_temp:
            print(f"Kept temp directory: {temp_path}", file=sys.stderr)
        return 1
    finally:
        if not args.keep_temp:
            shutil.rmtree(temp_path, ignore_errors=True)

    print(f"wheel JSON schema smoke: PASS ({', '.join(passed)})")
    if args.keep_temp:
        print(f"Kept temp directory: {temp_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
