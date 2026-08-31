"""Report-filters YAML parsing helpers.

Owns typed parsing of the ``report_filters`` block in ``rules.yaml``.
Leaf string/date/mapping/list checks live in
:mod:`finjuice.pipeline.tagging.rules_yaml_filters_helpers`. Excluded-entry
parsers live in :mod:`finjuice.pipeline.tagging.rules_yaml_filters_entries`.
Both clusters are re-exported here so existing callers can keep importing
from this module. Document loading and the public
:func:`load_report_filters` entrypoint stay in
:mod:`finjuice.pipeline.tagging.rules_yaml_io`, which imports these
helpers so existing callers keep using that module.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.tagging.models import (
    VALID_REPORT_FILTER_KEYS,
    ReportFilters,
)
from finjuice.pipeline.tagging.rules_yaml_filters_entries import (
    _parse_excluded_category_filter,
    _parse_excluded_date_range_filter,
    _parse_excluded_merchant_filter,
)
from finjuice.pipeline.tagging.rules_yaml_filters_helpers import (
    _normalize_filter_date,  # noqa: F401 — re-exported for existing filters imports
    _raise_filters_validation_error,
    _validate_filter_list,
    _validate_filter_mapping,  # noqa: F401 — re-exported for existing filters imports
    _validate_filter_required_string,  # noqa: F401 — re-exported for existing filters imports
)


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
