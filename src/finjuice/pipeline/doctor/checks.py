"""Doctor check implementations and result assembly.

Data-directory existence, permission, and structure checks live in
:mod:`finjuice.pipeline.doctor.data_directory` and are re-exported here so
existing callers can keep importing from this module.

Next-step suggestion helpers live in
:mod:`finjuice.pipeline.doctor.next_step` and are re-exported here so
existing callers can keep importing from this module.

System environment checks live in
:mod:`finjuice.pipeline.doctor.system` and are re-exported here so
existing callers can keep importing from this module.

Skill runtime checks live in
:mod:`finjuice.pipeline.doctor.skill_runtime` and are re-exported here so
existing callers can keep importing from this module.

Required package dependency checks live in
:mod:`finjuice.pipeline.doctor.dependencies` and are re-exported here so
existing callers can keep importing from this module.

Optional analytics DuckDB checks live in
:mod:`finjuice.pipeline.doctor.analytics_duckdb` and are re-exported here so
existing callers can keep importing from this module.
"""

from __future__ import annotations

from typing import Any

from finjuice import get_version
from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor.analytics_duckdb import _check_analytics_duckdb
from finjuice.pipeline.doctor.configuration import _check_configuration
from finjuice.pipeline.doctor.data_directory import _check_data_directory
from finjuice.pipeline.doctor.data_status import _check_data_status
from finjuice.pipeline.doctor.dependencies import _check_dependencies
from finjuice.pipeline.doctor.models import (
    CheckResult,  # noqa: F401 — re-exported for existing checks imports
    DoctorResult,
)
from finjuice.pipeline.doctor.next_step import (
    _next_step_from_data_dir,  # noqa: F401 — re-exported for existing checks imports
    _next_step_from_data_status,  # noqa: F401 — re-exported for existing checks imports
    _next_step_from_schema,  # noqa: F401 — re-exported for existing checks imports
    _suggest_next_step,
)
from finjuice.pipeline.doctor.skill_runtime import (
    KNOWN_SKILL_CAPABILITIES,
    SKILL_RUNTIME_REQUIRED_VERSION,
    SKILL_RUNTIME_UPDATE_COMMAND,  # noqa: F401 — re-exported for existing checks imports
    _capability_check_name,  # noqa: F401 — re-exported for existing checks imports
    _check_skill_runtime,
    _discover_skill_runtime_helper,  # noqa: F401 — re-exported for existing checks imports
    _known_skill_capability_checks,  # noqa: F401 — re-exported for existing checks imports
    _parse_version_tuple,  # noqa: F401 — re-exported for existing checks imports
    _probe_cli_capabilities,  # noqa: F401 — re-exported for existing checks imports
    _version_gte,  # noqa: F401 — re-exported for existing checks imports
)
from finjuice.pipeline.doctor.system import (
    _check_finjuice_version,
    _check_os_info,
    _check_python_version,
)


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
