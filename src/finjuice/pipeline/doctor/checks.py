"""Doctor check implementations and result assembly.

Data-directory existence, permission, and structure checks live in
:mod:`finjuice.pipeline.doctor.data_directory` and are re-exported here so
existing callers can keep importing from this module.
"""

from __future__ import annotations

import importlib
import importlib.metadata
import platform
import sys
from pathlib import Path
from typing import Any

from finjuice import get_version
from finjuice.pipeline.analytics.install_hints import (
    ANALYTICS_EXTRA,
    detect_analytics_install_command,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor.configuration import _check_configuration
from finjuice.pipeline.doctor.data_directory import _check_data_directory
from finjuice.pipeline.doctor.data_status import _check_data_status
from finjuice.pipeline.doctor.models import CheckResult, DoctorResult

SKILL_RUNTIME_REQUIRED_VERSION = "0.7.1"
SKILL_RUNTIME_UPDATE_COMMAND = "skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json"
KNOWN_SKILL_CAPABILITIES = {
    "tag.edit": "finjuice tag --edit",
}


def _check_python_version() -> CheckResult:
    """Check Python version meets requirements (3.10+)."""
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"

    if version >= (3, 10):
        return CheckResult(status="ok", message=f"Python {version_str}", name="python_version")
    else:
        return CheckResult(
            status="error",
            message=f"Python {version_str}",
            detail="Python 3.10+ required",
            suggestion="Install Python 3.10 or higher",
            name="python_version",
        )


def _check_finjuice_version() -> CheckResult:
    """Check finjuice version."""
    version = get_version()
    return CheckResult(status="ok", message=f"finjuice v{version}", name="finjuice_version")


def _check_os_info() -> CheckResult:
    """Get OS information."""
    system = platform.system()
    release = platform.release()

    os_names = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}
    os_display = os_names.get(system, system)

    return CheckResult(status="ok", message=f"OS: {os_display} {release}", name="operating_system")


def _parse_version_tuple(version: str) -> tuple[int, int, int] | None:
    """Parse a semantic version-ish string into a comparable three-part tuple."""
    parts: list[int] = []
    for raw_part in version.lstrip("vV").split("."):
        digits = ""
        for char in raw_part:
            if not char.isdigit():
                break
            digits += char
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) == 3:
            break

    if not parts:
        return None

    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def _version_gte(local_version: str, required_version: str) -> bool:
    """Return whether *local_version* satisfies *required_version*."""
    local = _parse_version_tuple(local_version)
    required = _parse_version_tuple(required_version)
    if local is None or required is None:
        return False
    return local >= required


def _discover_skill_runtime_helper() -> Path | None:
    """Find the shared skill runtime helper without running it."""
    candidate_paths = [
        Path("skills/finjuice/scripts/ensure_finjuice_cli.sh"),
        Path.cwd() / "skills/finjuice/scripts/ensure_finjuice_cli.sh",
        Path.home() / ".codex/skills/finjuice/scripts/ensure_finjuice_cli.sh",
        Path.home() / ".claude/skills/finjuice/scripts/ensure_finjuice_cli.sh",
        Path(".claude/skills/finjuice/scripts/ensure_finjuice_cli.sh"),
        Path("scripts/ensure_finjuice_cli.sh"),
    ]

    for candidate in candidate_paths:
        if candidate.is_file():
            return candidate
    return None


def _probe_cli_capabilities() -> dict[str, bool]:
    """CLI-layer capability probe.

    The doctor command injects a real probe that may inspect Typer commands.
    Core doctor checks must not import ``finjuice.pipeline.cli``.
    """
    return {name: False for name in KNOWN_SKILL_CAPABILITIES}


def _known_skill_capability_checks() -> dict[str, bool]:
    """Return deterministic support checks for known skill runtime capabilities."""
    return _probe_cli_capabilities()


def _capability_check_name(capability: str) -> str:
    """Return a stable CheckResult name for a skill runtime capability."""
    normalized = capability.replace(".", "_").replace("-", "_")
    return f"skill_runtime_capability_{normalized}"


def _check_skill_runtime() -> list[CheckResult]:
    """Check finjuice skill runtime support without network or mutation."""
    results: list[CheckResult] = []
    local_version = get_version()
    version_message = (
        f"finjuice {local_version} (skills require >= {SKILL_RUNTIME_REQUIRED_VERSION})"
    )

    if _version_gte(local_version, SKILL_RUNTIME_REQUIRED_VERSION):
        results.append(
            CheckResult(
                status="ok",
                message=version_message,
                name="skill_runtime_finjuice_version",
            )
        )
    else:
        results.append(
            CheckResult(
                status="warning",
                message=version_message,
                detail="Skill runtime support may be stale.",
                suggestion=f"Run {SKILL_RUNTIME_UPDATE_COMMAND} explicitly.",
                name="skill_runtime_finjuice_version",
            )
        )

    helper_path = _discover_skill_runtime_helper()
    if helper_path is not None:
        results.append(
            CheckResult(
                status="ok",
                message=f"ensure_finjuice_cli.sh: {helper_path}",
                name="skill_runtime_helper",
            )
        )
    else:
        results.append(
            CheckResult(
                status="warning",
                message="ensure_finjuice_cli.sh not found",
                detail="Skill helper is not discoverable from this checkout or global skill paths.",
                suggestion="Install/update finjuice skills before running skill CLI preflight.",
                name="skill_runtime_helper",
            )
        )

    capability_support = _known_skill_capability_checks()
    for capability, cli_path in KNOWN_SKILL_CAPABILITIES.items():
        if capability_support.get(capability, False):
            results.append(
                CheckResult(
                    status="ok",
                    message=f"{capability}: supported",
                    detail=cli_path,
                    name=_capability_check_name(capability),
                )
            )
        else:
            results.append(
                CheckResult(
                    status="warning",
                    message=f"{capability}: missing",
                    detail=f"{cli_path} is stale or unsupported by this finjuice runtime.",
                    suggestion=f"Run {SKILL_RUNTIME_UPDATE_COMMAND} explicitly.",
                    name=_capability_check_name(capability),
                )
            )

    return results


def _check_dependencies() -> list[CheckResult]:
    """Check package dependencies."""
    results = []

    # Required packages
    required_packages = {
        "polars": "polars",
        "typer": "typer",
        "rich": "rich",
        "pyyaml": "PyYAML",
        "openpyxl": "openpyxl",
    }

    for import_name, package_name in required_packages.items():
        try:
            version = importlib.metadata.version(package_name)
            results.append(
                CheckResult(
                    status="ok",
                    message=f"{package_name} {version}",
                    name=f"dependency_{import_name}",
                )
            )
        except importlib.metadata.PackageNotFoundError:
            results.append(
                CheckResult(
                    status="error",
                    message=f"{package_name} 미설치",
                    suggestion=f"uv pip install {package_name}",
                    name=f"dependency_{import_name}",
                )
            )

    return results


def _check_analytics_duckdb(
    sys_prefix: str | Path | None = None,
) -> tuple[list[CheckResult], list[str], str]:
    """Check whether the optional analytics extra is available."""
    install_hint = detect_analytics_install_command(sys_prefix)

    try:
        duckdb_module = importlib.import_module("duckdb")
    except ImportError:
        return (
            [
                CheckResult(
                    status="warning",
                    message=f"{ANALYTICS_EXTRA} extra 누락: duckdb 미설치",
                    detail="query/template/explain 같은 분석 명령에는 DuckDB가 필요합니다.",
                    suggestion=install_hint,
                    name="analytics_duckdb",
                )
            ],
            [ANALYTICS_EXTRA],
            install_hint,
        )

    version = getattr(duckdb_module, "__version__", "installed")
    return (
        [
            CheckResult(
                status="ok",
                message=f"duckdb {version} (analytics 사용 가능)",
                name="analytics_duckdb",
            )
        ],
        [],
        install_hint,
    )


def _next_step_from_schema(data_results: list[CheckResult]) -> str | None:
    """Suggest a step when a transaction schema compatibility warning is set."""
    for result in data_results:
        if (
            result.name == "transaction_schema_compatibility"
            and result.status == "warning"
            and result.suggestion
        ):
            return result.suggestion
    return None


def _next_step_from_data_dir(data_dir_results: list[CheckResult]) -> str | None:
    """Suggest a step when the data directory is missing."""
    for result in data_dir_results:
        if "존재하지 않음" in result.message or (
            result.detail and "존재하지 않음" in result.detail
        ):
            return "finjuice import"
    return None


def _next_step_from_data_status(data_results: list[CheckResult]) -> str | None:
    """Suggest a step based on transaction data availability."""
    for result in data_results:
        if "트랜잭션 데이터 없음" in result.message or "CSV 파티션 없음" in result.message:
            return "finjuice import"
    for result in data_results:
        if "처리되지 않은 XLSX" in result.message:
            return "finjuice refresh"
    return None


def _suggest_next_step(
    data_dir_results: list[CheckResult],
    config_results: list[CheckResult],
    data_results: list[CheckResult],
) -> str:
    """Determine the suggested next step based on check results."""
    step = (
        _next_step_from_schema(data_results)
        or _next_step_from_data_dir(data_dir_results)
        or _next_step_from_data_status(data_results)
    )
    if step:
        return step

    for result in config_results:
        if "규칙 충돌" in result.message:
            return "finjuice rules validate"

    return "finjuice status"


def _build_doctor_result(config: Config) -> DoctorResult:
    """Build doctor output for both JSON and text renderers."""
    system_checks = [
        _check_python_version(),
        _check_finjuice_version(),
        _check_os_info(),
    ]
    skill_runtime_results = _check_skill_runtime()
    data_dir_results = _check_data_directory(config)
    config_results = _check_configuration(config)
    data_results = _check_data_status(config)
    dep_results = _check_dependencies()
    analytics_results, missing_extras, install_hint = _check_analytics_duckdb()

    all_checks = [
        *system_checks,
        *skill_runtime_results,
        *data_dir_results,
        *config_results,
        *data_results,
        *dep_results,
        *analytics_results,
    ]
    next_step = _suggest_next_step(data_dir_results, config_results, data_results)

    payload: dict[str, Any] = {
        "checks": [check.to_dict() for check in all_checks],
        "summary": {
            "total": len(all_checks),
            "passed": sum(1 for check in all_checks if check.status == "ok"),
            "warnings": sum(1 for check in all_checks if check.status == "warning"),
            "errors": sum(1 for check in all_checks if check.status == "error"),
        },
        "skill_runtime": {
            "required_version": SKILL_RUNTIME_REQUIRED_VERSION,
            "local_version": get_version(),
            "helper_path": next(
                (
                    check.message.split(": ", maxsplit=1)[1]
                    for check in skill_runtime_results
                    if check.name == "skill_runtime_helper" and check.status == "ok"
                ),
                None,
            ),
            "capabilities": list(KNOWN_SKILL_CAPABILITIES),
        },
        "missing_extras": missing_extras,
        "install_hint": install_hint,
    }
    return DoctorResult(
        payload=payload,
        sections=[
            ("시스템", system_checks),
            ("스킬 런타임", skill_runtime_results),
            ("데이터 디렉토리", data_dir_results),
            ("설정", config_results),
            ("데이터", data_results),
            ("의존성", dep_results),
            ("Analytics / DuckDB", analytics_results),
        ],
        next_step=next_step,
    )
