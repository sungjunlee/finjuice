"""Report-filters YAML parsing helpers.

Owns schema checks and typed parsing for the ``report_filters`` block in
``rules.yaml``. Leaf string/date/mapping/list checks live in
:mod:`finjuice.pipeline.tagging.rules_yaml_filters_helpers` and are
re-exported here so existing callers can keep importing from this module.
Document loading and the public :func:`load_report_filters` entrypoint stay
in :mod:`finjuice.pipeline.tagging.rules_yaml_io`, which imports these
helpers so existing callers keep using that module.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from finjuice.pipeline.tagging.models import (
    VALID_EXCLUDED_CATEGORY_FIELDS,
    VALID_EXCLUDED_DATE_RANGE_FIELDS,
    VALID_EXCLUDED_MERCHANT_FIELDS,
    VALID_REPORT_FILTER_KEYS,
    VALID_REPORT_FILTER_MATCH_TYPES,
    ExcludedCategoryFilter,
    ExcludedDateRangeFilter,
    ExcludedMerchantFilter,
    ReportFilters,
)
from finjuice.pipeline.tagging.rules_yaml_filters_helpers import (
    _normalize_filter_date,
    _raise_filters_validation_error,
    _validate_filter_list,
    _validate_filter_mapping,
    _validate_filter_required_string,
)


def _parse_excluded_merchant_filter(
    value: Any,
    *,
    rules_path: Path,
    index: int,
) -> ExcludedMerchantFilter:
    """Parse one excluded_merchants entry."""
    key_path = f"report_filters.excluded_merchants[{index}]"
    entry = _validate_filter_mapping(
        value,
        rules_path=rules_path,
        key_path=key_path,
        allowed_keys=VALID_EXCLUDED_MERCHANT_FIELDS,
    )

    pattern = _validate_filter_required_string(
        entry.get("pattern"),
        rules_path=rules_path,
        key_path=f"{key_path}.pattern",
    )
    reason = _validate_filter_required_string(
        entry.get("reason"),
        rules_path=rules_path,
        key_path=f"{key_path}.reason",
    )

    raw_match_type = entry.get("match_type", "contains")
    match_type = _validate_filter_required_string(
        raw_match_type,
        rules_path=rules_path,
        key_path=f"{key_path}.match_type",
    )
    if match_type not in VALID_REPORT_FILTER_MATCH_TYPES:
        _raise_filters_validation_error(
            rules_path,
            f"{key_path}.match_type",
            f"invalid value {match_type!r}",
            accepted_values=VALID_REPORT_FILTER_MATCH_TYPES,
        )

    since_raw = entry.get("since")
    since = (
        _normalize_filter_date(
            since_raw,
            rules_path=rules_path,
            key_path=f"{key_path}.since",
        )
        if since_raw is not None
        else None
    )

    compiled_pattern: re.Pattern[str] | None = None
    if match_type == "regex":
        try:
            compiled_pattern = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            _raise_filters_validation_error(
                rules_path,
                f"{key_path}.pattern",
                f"invalid regex pattern ({exc})",
            )

    return ExcludedMerchantFilter(
        pattern=pattern,
        reason=reason,
        match_type=match_type,
        since=since,
        compiled_pattern=compiled_pattern,
    )


def _parse_excluded_category_filter(
    value: Any,
    *,
    rules_path: Path,
    index: int,
) -> ExcludedCategoryFilter:
    """Parse one excluded_categories entry."""
    key_path = f"report_filters.excluded_categories[{index}]"
    entry = _validate_filter_mapping(
        value,
        rules_path=rules_path,
        key_path=key_path,
        allowed_keys=VALID_EXCLUDED_CATEGORY_FIELDS,
    )

    name = _validate_filter_required_string(
        entry.get("name"),
        rules_path=rules_path,
        key_path=f"{key_path}.name",
    )
    reason = _validate_filter_required_string(
        entry.get("reason"),
        rules_path=rules_path,
        key_path=f"{key_path}.reason",
    )
    return ExcludedCategoryFilter(name=name, reason=reason)


def _parse_excluded_date_range_filter(
    value: Any,
    *,
    rules_path: Path,
    index: int,
) -> ExcludedDateRangeFilter:
    """Parse one excluded_date_ranges entry."""
    key_path = f"report_filters.excluded_date_ranges[{index}]"
    entry = _validate_filter_mapping(
        value,
        rules_path=rules_path,
        key_path=key_path,
        allowed_keys=VALID_EXCLUDED_DATE_RANGE_FIELDS,
    )

    start = _normalize_filter_date(
        entry.get("start"),
        rules_path=rules_path,
        key_path=f"{key_path}.start",
    )
    end = _normalize_filter_date(
        entry.get("end"),
        rules_path=rules_path,
        key_path=f"{key_path}.end",
    )
    reason = _validate_filter_required_string(
        entry.get("reason"),
        rules_path=rules_path,
        key_path=f"{key_path}.reason",
    )

    if end < start:
        _raise_filters_validation_error(
            rules_path,
            key_path,
            "'end' must be greater than or equal to 'start'",
        )

    return ExcludedDateRangeFilter(start=start, end=end, reason=reason)


def _parse_report_filters(data: Any, rules_path: Path) -> ReportFilters:
    """Parse a loaded YAML document's report_filters block."""
    if not data or not isinstance(data, dict) or "report_filters" not in data:
        return ReportFilters()

    raw_filters = data.get("report_filters")
    if raw_filters is None:
        return ReportFilters()
    if not isinstance(raw_filters, dict):
        _raise_filters_validation_error(
            rules_path,
            "report_filters",
            "must be a mapping",
            accepted_values=VALID_REPORT_FILTER_KEYS,
        )

    unknown_keys = set(raw_filters) - VALID_REPORT_FILTER_KEYS
    if unknown_keys:
        unknown_key = sorted(unknown_keys)[0]
        _raise_filters_validation_error(
            rules_path,
            f"report_filters.{unknown_key}",
            "unknown field",
            accepted_values=VALID_REPORT_FILTER_KEYS,
        )

    excluded_merchants = [
        _parse_excluded_merchant_filter(value, rules_path=rules_path, index=index)
        for index, value in enumerate(
            _validate_filter_list(
                raw_filters.get("excluded_merchants"),
                rules_path=rules_path,
                key_path="report_filters.excluded_merchants",
            )
        )
    ]
    excluded_categories = [
        _parse_excluded_category_filter(value, rules_path=rules_path, index=index)
        for index, value in enumerate(
            _validate_filter_list(
                raw_filters.get("excluded_categories"),
                rules_path=rules_path,
                key_path="report_filters.excluded_categories",
            )
        )
    ]
    excluded_date_ranges = [
        _parse_excluded_date_range_filter(value, rules_path=rules_path, index=index)
        for index, value in enumerate(
            _validate_filter_list(
                raw_filters.get("excluded_date_ranges"),
                rules_path=rules_path,
                key_path="report_filters.excluded_date_ranges",
            )
        )
    ]

    return ReportFilters(
        excluded_merchants=excluded_merchants,
        excluded_categories=excluded_categories,
        excluded_date_ranges=excluded_date_ranges,
    )
