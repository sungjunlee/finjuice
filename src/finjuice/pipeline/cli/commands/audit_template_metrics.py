"""Template-run metrics helpers for ``finjuice audit``.

Owns template domain resolution, retry attribution, aggregate metrics, and
usage counters. Typer commands stay in
:mod:`finjuice.pipeline.cli.commands.audit`. JSONL I/O lives in
:mod:`finjuice.pipeline.cli.commands.audit_io`. Human rendering lives in
:mod:`finjuice.pipeline.cli.commands.audit_rendering`.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any, Literal, cast

logger = logging.getLogger(__name__)

TemplateDomain = Literal["asset", "transaction"]


@dataclass(frozen=True)
class TemplateMetrics:
    """Aggregated metrics for template_run events."""

    total: int
    success: int
    failed: int
    success_rate: float
    avg_duration: float
    retry_attempts: int
    retry_recovery: float


@dataclass(frozen=True)
class TemplateRunSummary:
    """Computed metrics and usage counters for template_run output rendering."""

    overall: TemplateMetrics
    asset: TemplateMetrics
    transaction: TemplateMetrics
    usage_counts: dict[str, int]
    domain_usage_counts: dict[TemplateDomain, dict[str, int]]


def _parse_duration(event: dict[str, Any]) -> float | None:
    """Parse duration value from audit event."""
    raw = event.get("duration")
    if raw is None:
        return 0.0
    try:
        return float(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid duration value in audit event: %r", raw)
        return None


def _compute_template_retry_stats(template_runs: list[dict[str, Any]]) -> tuple[int, int]:
    """Compute retry attempts and recovered retries from ordered template_run events.

    Retry attempt is counted when a failed run is immediately followed by another run
    with the same template_name and param_fingerprint.
    """
    retry_attempts = 0
    recovered_retries = 0
    for previous, current in zip(template_runs, template_runs[1:]):
        same_template = previous.get("template_name") == current.get("template_name")
        same_params = previous.get("param_fingerprint") == current.get("param_fingerprint")
        if same_template and same_params and previous.get("success") is False:
            retry_attempts += 1
            if current.get("success") is True:
                recovered_retries += 1
    return retry_attempts, recovered_retries


def _resolve_template_domain(event: dict[str, Any]) -> TemplateDomain:
    """Resolve template domain, falling back to a default when unset."""
    raw_domain = event.get("template_domain")
    if isinstance(raw_domain, str):
        normalized = raw_domain.strip().lower()
        if normalized in {"asset", "transaction"}:
            return cast(TemplateDomain, normalized)
        logger.debug(
            "Invalid template_domain value '%s'; falling back to template_name prefix",
            raw_domain,
        )

    template_name = str(event.get("template_name", ""))
    return "asset" if template_name.startswith("asset_") else "transaction"


def _compute_domain_template_retry_stats(
    template_runs: list[dict[str, Any]],
) -> dict[TemplateDomain, tuple[int, int]]:
    """Compute domain retry stats from the full ordered template event stream."""
    attempts: dict[TemplateDomain, int] = {"asset": 0, "transaction": 0}
    recovered: dict[TemplateDomain, int] = {"asset": 0, "transaction": 0}

    for previous, current in zip(template_runs, template_runs[1:]):
        same_template = previous.get("template_name") == current.get("template_name")
        same_params = previous.get("param_fingerprint") == current.get("param_fingerprint")
        if same_template and same_params and previous.get("success") is False:
            domain = _resolve_template_domain(previous)
            attempts[domain] += 1
            if current.get("success") is True:
                recovered[domain] += 1

    return {
        "asset": (attempts["asset"], recovered["asset"]),
        "transaction": (attempts["transaction"], recovered["transaction"]),
    }


def _count_template_outcomes(template_runs: list[dict[str, Any]]) -> tuple[int, int, int]:
    """Count total/success/failed outcomes from template events."""
    total = len(template_runs)
    success = sum(1 for event in template_runs if event.get("success") is True)
    failed = total - success
    return total, success, failed


def _compute_success_rate(success: int, total: int) -> float:
    """Compute success rate percentage."""
    return (success / total) * 100 if total > 0 else 0.0


def _compute_average_duration(template_runs: list[dict[str, Any]], total: int) -> float:
    """Compute average duration for template events."""
    if total == 0:
        return 0.0
    durations = [value for event in template_runs if (value := _parse_duration(event)) is not None]
    return sum(durations) / len(durations) if durations else 0.0


def _resolve_retry_stats(
    template_runs: list[dict[str, Any]],
    retry_stats: tuple[int, int] | None,
) -> tuple[int, int]:
    """Resolve retry stats from override or by computing from event stream."""
    return _compute_template_retry_stats(template_runs) if retry_stats is None else retry_stats


def _compute_retry_recovery_rate(retry_attempts: int, recovered_retries: int) -> float:
    """Compute retry recovery percentage."""
    return (recovered_retries / retry_attempts) * 100 if retry_attempts > 0 else 0.0


def _build_template_metrics(
    *,
    total: int,
    success: int,
    failed: int,
    avg_duration: float,
    retry_attempts: int,
    recovered_retries: int,
) -> TemplateMetrics:
    """Build TemplateMetrics from computed scalar values."""
    return TemplateMetrics(
        total=total,
        success=success,
        failed=failed,
        success_rate=_compute_success_rate(success, total),
        avg_duration=avg_duration,
        retry_attempts=retry_attempts,
        retry_recovery=_compute_retry_recovery_rate(retry_attempts, recovered_retries),
    )


def _compute_template_metrics(
    template_runs: list[dict[str, Any]],
    retry_stats: tuple[int, int] | None = None,
) -> TemplateMetrics:
    """Compute aggregate metrics for a template_run event group."""
    total, success, failed = _count_template_outcomes(template_runs)
    retry_attempts, recovered_retries = _resolve_retry_stats(template_runs, retry_stats)
    return _build_template_metrics(
        total=total,
        success=success,
        failed=failed,
        avg_duration=_compute_average_duration(template_runs, total),
        retry_attempts=retry_attempts,
        recovered_retries=recovered_retries,
    )


def _collect_template_usage(
    template_runs: list[dict[str, Any]],
) -> tuple[
    dict[TemplateDomain, list[dict[str, Any]]],
    dict[str, int],
    dict[TemplateDomain, dict[str, int]],
]:
    """Collect per-domain runs and usage counters in a single pass."""
    domain_runs: dict[TemplateDomain, list[dict[str, Any]]] = {"asset": [], "transaction": []}
    usage_counts: dict[str, int] = {}
    domain_usage_counts: dict[TemplateDomain, dict[str, int]] = {"asset": {}, "transaction": {}}
    for event in template_runs:
        template_name = str(event.get("template_name", "unknown"))
        usage_counts[template_name] = usage_counts.get(template_name, 0) + 1
        domain = _resolve_template_domain(event)
        domain_runs[domain].append(event)
        domain_usage = domain_usage_counts[domain]
        domain_usage[template_name] = domain_usage.get(template_name, 0) + 1
    return domain_runs, usage_counts, domain_usage_counts


def _build_domain_metrics(
    template_runs: list[dict[str, Any]],
    domain_runs: dict[TemplateDomain, list[dict[str, Any]]],
) -> tuple[TemplateMetrics, TemplateMetrics]:
    """Build domain-specific template metrics using global-adjacency retry attribution."""
    retry_stats = _compute_domain_template_retry_stats(template_runs)
    asset_metrics = _compute_template_metrics(
        domain_runs["asset"],
        retry_stats=retry_stats["asset"],
    )
    transaction_metrics = _compute_template_metrics(
        domain_runs["transaction"],
        retry_stats=retry_stats["transaction"],
    )
    return asset_metrics, transaction_metrics


def _summarize_template_runs(template_runs: list[dict[str, Any]]) -> TemplateRunSummary:
    """Compute template metrics and usage counters for rendering."""
    domain_runs, usage_counts, domain_usage_counts = _collect_template_usage(template_runs)
    asset_metrics, transaction_metrics = _build_domain_metrics(template_runs, domain_runs)
    return TemplateRunSummary(
        overall=_compute_template_metrics(template_runs),
        asset=asset_metrics,
        transaction=transaction_metrics,
        usage_counts=usage_counts,
        domain_usage_counts=domain_usage_counts,
    )


def _serialize_template_run_summary(summary: TemplateRunSummary) -> dict[str, Any]:
    """Serialize template metrics summary for JSON output."""
    return cast(dict[str, Any], asdict(summary))
