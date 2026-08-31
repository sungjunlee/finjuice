"""Next-step suggestion helpers for doctor check results.

Extracted from :mod:`finjuice.pipeline.doctor.checks`. The assembler
re-exports these names so existing callers can keep importing from that
module.
"""

from __future__ import annotations

from finjuice.pipeline.doctor.models import CheckResult


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
