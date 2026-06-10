"""
Backwards-compatibility shim for the tagging-rules public API.

The matching logic lives in :mod:`finjuice.pipeline.tagging.matcher` since the
Epic #707 ``models + matcher`` split. This module exists so existing external
callers can keep importing the documented public surface from
``finjuice.pipeline.tagging.rules``. New code should import from the owning
module directly.

Sibling modules own the other concerns:

* :mod:`finjuice.pipeline.tagging.models` — data models and schema constants.
* :mod:`finjuice.pipeline.tagging.matcher` — pattern/condition matching engine.
* :mod:`finjuice.pipeline.tagging.validator` — per-rule schema validation and
  conflict detection.
* :mod:`finjuice.pipeline.tagging.rules_yaml_io` — reading/writing
  ``rules.yaml`` and loading the ``report_filters`` block.
"""

from finjuice.pipeline.tagging.matcher import (
    apply_tagging_rules,  # noqa: F401 — legacy v1 entrypoint, importable but not in public __all__.
    apply_tagging_rules_v3,
)
from finjuice.pipeline.tagging.models import (
    FiltersValidationError,
    ReportFilters,
    TagRule,
)
from finjuice.pipeline.tagging.rules_yaml_io import (
    load_report_filters,
    load_rules,
    summarize_rule_notes,
)

__all__ = [
    "TagRule",  # Public API — rule model used by external callers.
    "ReportFilters",  # Public API — used by analytics/report-filter callers.
    "FiltersValidationError",  # Public API — structured report_filters validation error.
    "apply_tagging_rules_v3",  # Public API — v3 rule matcher entrypoint.
    "load_rules",  # Public API — rules.yaml loader.
    "load_report_filters",  # Public API — report_filters loader.
    "summarize_rule_notes",  # Public API — compact rule-note context helper.
]
