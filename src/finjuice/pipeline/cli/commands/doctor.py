"""
Doctor command: Environment diagnostic tool.

Diagnoses the user environment and identifies issues:
- System checks (Python, finjuice version, OS)
- Data directory checks (existence, permissions)
- Configuration checks (rules.yaml, env vars)
- Data checks (transactions, imports, processing status)
- Dependency checks (required and optional packages)
"""

import importlib
import importlib.metadata
import inspect
import logging
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import polars as pl
import typer
from rich.panel import Panel

from finjuice import get_version
from finjuice.pipeline.analytics.install_hints import (
    ANALYTICS_EXTRA,
    detect_analytics_install_command,
)
from finjuice.pipeline.cli.output import console, emit
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.schema_registry import (
    PartitionSchemaSummary,
    SchemaCompatibilityState,
    get_schema_migration_guidance,
    summarize_partition_schema_versions,
)
from finjuice.pipeline.tagging.rules_yaml_io import load_rules
from finjuice.pipeline.tagging.validator import validate_rules

logger = logging.getLogger(__name__)

SKILL_RUNTIME_REQUIRED_VERSION = "0.6.2"
SKILL_RUNTIME_UPDATE_COMMAND = "skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json"
KNOWN_SKILL_CAPABILITIES = {
    "tag.edit": "finjuice tag --edit",
}


@dataclass
class CheckResult:
    """Result of a diagnostic check."""

    status: str  # "ok", "warning", "error"
    message: str
    detail: Optional[str] = None
    suggestion: Optional[str] = None
    name: str = ""

    @property
    def icon(self) -> str:
        """Return emoji icon for status."""
        icons = {"ok": "✅", "warning": "⚠️", "error": "❌"}
        return icons.get(self.status, "❓")

    def to_dict(self) -> dict[str, Any]:
        """Convert the check to a JSON-safe dictionary."""
        status_map = {"ok": "pass", "warning": "warn", "error": "fail"}
        return {
            "name": self.name,
            "status": status_map.get(self.status, self.status),
            "message": self.message,
            "detail": self.detail,
            "suggestion": self.suggestion,
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


def _known_skill_capability_checks() -> dict[str, bool]:
    """Return deterministic support checks for known skill runtime capabilities."""
    results: dict[str, bool] = {}

    try:
        from finjuice.pipeline.cli.commands.tag import tag_command

        results["tag.edit"] = "edit" in inspect.signature(tag_command).parameters
    except (ImportError, AttributeError):
        results["tag.edit"] = False

    return results


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


def _check_data_directory(config: Config) -> list[CheckResult]:
    """Check data directory status."""
    results = []
    data_dir = config.data_dir

    # Check existence
    if data_dir.exists():
        results.append(
            CheckResult(
                status="ok",
                message=f"위치: {data_dir}",
                name="data_directory_path",
            )
        )
        results.append(
            CheckResult(status="ok", message="디렉토리 존재", name="data_directory_exists")
        )
    else:
        results.append(
            CheckResult(
                status="warning",
                message=f"위치: {data_dir}",
                detail="디렉토리가 존재하지 않음",
                suggestion="finjuice import 실행 권장",
                name="data_directory_path",
            )
        )
        return results

    # Check write permission with path traversal protection
    try:
        data_dir_resolved = data_dir.resolve()
        test_file = data_dir / ".doctor_test"
        test_file_resolved = test_file.resolve()

        # Validate path is within data_dir (prevent path traversal)
        if not test_file_resolved.is_relative_to(data_dir_resolved):
            logger.warning(f"Path traversal attempt blocked: {test_file}")
            results.append(
                CheckResult(
                    status="error",
                    message="잘못된 경로",
                    detail="경로 검증 실패",
                    name="data_directory_write_access",
                )
            )
            return results

        test_file.touch()
        test_file.unlink()
        results.append(
            CheckResult(status="ok", message="쓰기 권한 확인", name="data_directory_write_access")
        )
    except PermissionError:
        results.append(
            CheckResult(
                status="error",
                message="쓰기 권한 없음",
                detail="데이터 디렉토리에 쓰기 권한이 없습니다",
                suggestion=f"chmod u+w {data_dir}",
                name="data_directory_write_access",
            )
        )
    except OSError as e:
        results.append(
            CheckResult(
                status="warning",
                message="권한 확인 실패",
                detail=str(e),
                name="data_directory_write_access",
            )
        )

    # Check subdirectories
    subdirs = ["imports", "transactions", "exports", "metadata"]
    missing_subdirs = []
    for subdir in subdirs:
        if not (data_dir / subdir).exists():
            missing_subdirs.append(subdir)

    if missing_subdirs:
        results.append(
            CheckResult(
                status="warning",
                message=f"누락된 디렉토리: {', '.join(missing_subdirs)}",
                suggestion="finjuice import 실행 권장",
                name="data_directory_structure",
            )
        )

    return results


def _check_configuration(config: Config) -> list[CheckResult]:
    """Check configuration status."""
    results = []

    # Check rules.yaml
    rules_path = config.rules_file
    if rules_path.exists():
        try:
            import yaml

            with open(rules_path, encoding="utf-8") as f:
                rules_data = yaml.safe_load(f)

            rule_count = 0
            if rules_data and "rules" in rules_data:
                rule_count = len(rules_data["rules"])

            results.append(
                CheckResult(
                    status="ok",
                    message=f"rules.yaml: {rule_count}개 규칙",
                    name="rules_file",
                )
            )

            # Check for rule conflicts using the full validation engine
            if rule_count > 0:
                try:
                    tag_rules = load_rules(rules_path)
                    validation = validate_rules(tag_rules)
                    real_issues = [
                        i for i in validation.issues if i.severity in ("error", "warning")
                    ]
                    if real_issues:
                        overlap_count = sum(
                            1 for i in real_issues if i.issue_type == "pattern_overlap"
                        )
                        inversion_count = sum(
                            1 for i in real_issues if i.issue_type == "priority_inversion"
                        )
                        parts = []
                        if overlap_count:
                            parts.append(f"패턴 중복 {overlap_count}건")
                        if inversion_count:
                            parts.append(f"우선순위 역전 {inversion_count}건")
                        details = ", ".join(parts) if parts else "검증 이슈 발생"
                        results.append(
                            CheckResult(
                                status="warning",
                                message=f"규칙 충돌: {details}",
                                suggestion="finjuice rules validate 실행 권장",
                                name="rule_priority_conflicts",
                            )
                        )
                except (ValueError, RuntimeError):
                    logger.warning("규칙 검증 중 오류 (rules_path=%s)", rules_path, exc_info=True)

        except yaml.YAMLError as e:
            # Sanitize error message to avoid exposing file contents
            error_mark = getattr(e, "problem_mark", None)
            if error_mark:
                safe_detail = f"Line {error_mark.line + 1}, column {error_mark.column + 1}"
            else:
                safe_detail = "YAML 문법 오류"
            results.append(
                CheckResult(
                    status="error",
                    message="rules.yaml 파싱 오류",
                    detail=safe_detail,
                    suggestion="YAML 문법 오류 수정 필요",
                    name="rules_file_parse",
                )
            )
        except (OSError, TypeError, AttributeError) as e:
            results.append(
                CheckResult(
                    status="warning",
                    message="rules.yaml 읽기 실패",
                    detail=str(e),
                    name="rules_file_read",
                )
            )
    else:
        results.append(
            CheckResult(
                status="warning",
                message="rules.yaml 없음",
                suggestion="finjuice import 실행 권장",
                name="rules_file",
            )
        )

    # Check environment variables
    env_var = os.getenv("FINJUICE_DATA_DIR")
    if env_var:
        results.append(
            CheckResult(
                status="ok",
                message=f"FINJUICE_DATA_DIR: {env_var}",
                name="env_finjuice_data_dir",
            )
        )

    return results


def _check_data_status(config: Config) -> list[CheckResult]:
    """Check data status."""
    results = []

    transactions_dir = config.csv_base_dir
    if not transactions_dir.exists():
        results.append(
            CheckResult(
                status="warning",
                message="트랜잭션 데이터 없음",
                suggestion="finjuice import 실행 필요",
                name="transactions_directory",
            )
        )
        return results

    # Count partitions and rows
    partitions = list(transactions_dir.rglob("*.csv"))
    if not partitions:
        results.append(
            CheckResult(
                status="warning",
                message="CSV 파티션 없음",
                suggestion="finjuice import 실행 필요",
                name="transaction_partitions",
            )
        )
        return results

    schema_summary = summarize_partition_schema_versions(
        partitions,
        metadata_dir=config.data_dir / "metadata",
    )
    results.append(_schema_summary_check(schema_summary, config.data_dir))

    total_rows = 0
    min_date = None
    max_date = None

    for partition_path in partitions:
        try:
            df = pl.read_csv(partition_path)
            total_rows += len(df)

            if len(df) > 0 and "date" in df.columns:
                partition_min = df.select(pl.col("date").min()).item()
                partition_max = df.select(pl.col("date").max()).item()

                if min_date is None or partition_min < min_date:
                    min_date = partition_min
                if max_date is None or partition_max > max_date:
                    max_date = partition_max
        except (OSError, pl.exceptions.ComputeError):
            pass

    # Calculate period in months
    month_count = len(partitions)
    date_range = ""
    if min_date and max_date:
        date_range = f" ({min_date} ~ {max_date})"

    results.append(
        CheckResult(
            status="ok",
            message=f"transactions/: {total_rows:,}건 ({month_count}개월){date_range}",
            name="transactions_summary",
        )
    )

    # Check imports
    imports_dir = config.import_dir
    if imports_dir.exists():
        xlsx_files = list(imports_dir.glob("*.xlsx"))
        if xlsx_files:
            results.append(
                CheckResult(
                    status="ok",
                    message=f"imports/: {len(xlsx_files)}개 XLSX 파일",
                    name="imports_directory",
                )
            )

            # Check for unprocessed XLSX (compare with import history)
            import_history_path = config.data_dir / "metadata" / "import_history.csv"
            if import_history_path.exists():
                try:
                    history_df = pl.read_csv(import_history_path)
                    processed_files = set(
                        history_df["original_filename"].to_list()
                        if "original_filename" in history_df.columns
                        else []
                    )
                    unprocessed = [f for f in xlsx_files if f.name not in processed_files]
                    if unprocessed:
                        results.append(
                            CheckResult(
                                status="warning",
                                message=f"처리되지 않은 XLSX {len(unprocessed)}개",
                                suggestion="finjuice refresh 실행 권장",
                                name="unprocessed_imports",
                            )
                        )
                except (OSError, pl.exceptions.ComputeError):
                    pass
        else:
            results.append(
                CheckResult(
                    status="ok",
                    message="imports/: XLSX 파일 없음",
                    name="imports_directory",
                )
            )

    return results


def _schema_summary_check(schema_summary: PartitionSchemaSummary, data_dir: Path) -> CheckResult:
    """Render transaction partition schema compatibility as a doctor check."""
    guidance = get_schema_migration_guidance(schema_summary, metadata_dir=data_dir / "metadata")

    if schema_summary.state is SchemaCompatibilityState.ACTIVE:
        version = (
            schema_summary.active_versions[-1] if schema_summary.active_versions else "unknown"
        )
        return CheckResult(
            status="ok",
            message=f"CSV schema: active v{version}",
            name="transaction_schema_compatibility",
        )

    if schema_summary.state is SchemaCompatibilityState.COMPATIBLE_LEGACY:
        versions = ", ".join(f"v{version}" for version in schema_summary.compatible_legacy_versions)
        return CheckResult(
            status="warning",
            message=f"CSV schema: compatible legacy schema {versions} detected",
            detail=guidance["message"],
            suggestion=guidance["command"],
            name="transaction_schema_compatibility",
        )

    unsupported_versions = ", ".join(
        f"v{version}" if version is not None else "unknown"
        for version in schema_summary.unsupported_versions
    )
    return CheckResult(
        status="error",
        message=f"CSV schema: unsupported partitions detected ({unsupported_versions})",
        detail=guidance["message"],
        suggestion=guidance["command"],
        name="transaction_schema_compatibility",
    )


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


def _build_doctor_result(config: Config) -> dict[str, Any]:
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

    return {
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
        "_sections": [
            ("시스템", system_checks),
            ("스킬 런타임", skill_runtime_results),
            ("데이터 디렉토리", data_dir_results),
            ("설정", config_results),
            ("데이터", data_results),
            ("의존성", dep_results),
            ("Analytics / DuckDB", analytics_results),
        ],
        "_next_step": next_step,
    }


def _render_doctor_result(result: dict[str, Any]) -> None:
    """Render the human-readable doctor report."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]🔍 finjuice 환경 진단[/bold cyan]",
            border_style="cyan",
        )
    )
    console.print()

    for title, checks in result["_sections"]:
        console.print(f"[bold cyan]{title}:[/bold cyan]")
        for check in checks:
            _print_check_result(check)
        console.print()

    console.print(f"[bold green]💡 다음 단계:[/bold green] [cyan]{result['_next_step']}[/cyan]")
    console.print()


def doctor(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Diagnose environment and identify issues.

    Performs comprehensive checks on:
    - System (Python version, finjuice version, OS)
    - Data directory (existence, permissions, structure)
    - Configuration (rules.yaml, environment variables)
    - Data (transactions, imports, processing status)
    - Dependencies (required and optional packages)
    """
    config: Config = ctx.obj["config"]
    result = _build_doctor_result(config)
    json_result = {k: v for k, v in result.items() if not k.startswith("_")}
    emit(json_result, json_output, lambda _: _render_doctor_result(result), command="doctor")


def _print_check_result(result: CheckResult) -> None:
    """Print a check result with proper formatting."""
    # Main message
    if result.status == "ok":
        console.print(f"  {result.icon} {result.message}")
    elif result.status == "warning":
        console.print(f"  {result.icon} [yellow]{result.message}[/yellow]")
    else:
        console.print(f"  {result.icon} [red]{result.message}[/red]")

    # Detail (indented)
    if result.detail:
        console.print(f"     [dim]{result.detail}[/dim]")

    # Suggestion (indented with arrow)
    if result.suggestion:
        console.print(f"     → [green]{result.suggestion}[/green]")


def register_doctor_command(app: typer.Typer) -> None:
    """Register the doctor command with the main app."""
    app.command(name="doctor", rich_help_panel="Admin")(doctor)
