"""Identity coverage for the rules_yaml_filters excluded-entry parser split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.tagging import rules_yaml_filters, rules_yaml_filters_entries

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

EXCLUDED_ENTRY_HELPER_NAMES = (
    "_parse_excluded_merchant_filter",
    "_parse_excluded_category_filter",
    "_parse_excluded_date_range_filter",
)


def test_excluded_entry_parsers_live_in_sibling_module() -> None:
    """Excluded-entry parsers should not live in the report_filters orchestrator."""
    filters_text = (TAGGING_DIR / "rules_yaml_filters.py").read_text(encoding="utf-8")
    entries_text = (TAGGING_DIR / "rules_yaml_filters_entries.py").read_text(encoding="utf-8")

    assert "def _parse_report_filters" in filters_text
    for name in EXCLUDED_ENTRY_HELPER_NAMES:
        assert f"def {name}" not in filters_text
        assert f"def {name}" in entries_text

    assert "def _parse_report_filters" not in entries_text
    assert "def _raise_filters_validation_error" not in entries_text
    assert "def _validate_filter_required_string" not in entries_text


def test_excluded_entry_parsers_reexport_from_rules_yaml_filters() -> None:
    """Existing rules_yaml_filters imports should keep resolving to the parsers."""
    filters_text = (TAGGING_DIR / "rules_yaml_filters.py").read_text(encoding="utf-8")

    for name in EXCLUDED_ENTRY_HELPER_NAMES:
        assert name in filters_text
        assert getattr(rules_yaml_filters, name) is getattr(rules_yaml_filters_entries, name)

    assert callable(rules_yaml_filters._parse_report_filters)
    assert callable(rules_yaml_filters._parse_excluded_merchant_filter)
    assert callable(rules_yaml_filters._parse_excluded_category_filter)
    assert callable(rules_yaml_filters._parse_excluded_date_range_filter)
