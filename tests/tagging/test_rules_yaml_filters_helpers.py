"""Identity coverage for the rules_yaml_filters schema-check helper split."""

from __future__ import annotations

from pathlib import Path

from finjuice.pipeline.tagging import rules_yaml_filters, rules_yaml_filters_helpers

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

SCHEMA_CHECK_HELPER_NAMES = (
    "_raise_filters_validation_error",
    "_validate_filter_required_string",
    "_normalize_filter_date",
    "_validate_filter_mapping",
    "_validate_filter_list",
)


def test_schema_check_helpers_live_in_sibling_module() -> None:
    """YAML field schema-check helpers should not live in the entry-parser module."""
    filters_text = (TAGGING_DIR / "rules_yaml_filters.py").read_text(encoding="utf-8")
    helpers_text = (TAGGING_DIR / "rules_yaml_filters_helpers.py").read_text(encoding="utf-8")

    assert "def _parse_report_filters" in filters_text

    for name in SCHEMA_CHECK_HELPER_NAMES:
        assert f"def {name}" not in filters_text
        assert f"def {name}" in helpers_text


def test_schema_check_helpers_reexport_from_rules_yaml_filters() -> None:
    """Existing rules_yaml_filters imports should keep resolving to the helpers."""
    filters_text = (TAGGING_DIR / "rules_yaml_filters.py").read_text(encoding="utf-8")

    for name in SCHEMA_CHECK_HELPER_NAMES:
        assert name in filters_text
        assert getattr(rules_yaml_filters, name) is getattr(rules_yaml_filters_helpers, name)

    assert callable(rules_yaml_filters._parse_report_filters)
