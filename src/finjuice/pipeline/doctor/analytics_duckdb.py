"""Optional analytics DuckDB doctor checks.

Owns :func:`_check_analytics_duckdb`. The assembler
:func:`~finjuice.pipeline.doctor.checks._build_doctor_result` stays in
:mod:`finjuice.pipeline.doctor.checks` and re-exports this check so existing
callers can keep importing from that module.
"""

from __future__ import annotations

import importlib
from pathlib import Path

from finjuice.pipeline.analytics.install_hints import (
    ANALYTICS_EXTRA,
    detect_analytics_install_command,
)
from finjuice.pipeline.doctor.models import CheckResult


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
