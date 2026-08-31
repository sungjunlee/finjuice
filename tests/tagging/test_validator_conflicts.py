"""Identity coverage for the validator_conflicts split out of validator."""

from __future__ import annotations

import importlib

from finjuice.pipeline.tagging.models import TagRule


def _import_modules():
    validator = importlib.import_module("finjuice.pipeline.tagging.validator")
    conflicts = importlib.import_module("finjuice.pipeline.tagging.validator_conflicts")
    return validator, conflicts


def test_validator_reexports_conflict_cluster_identity() -> None:
    """Conflict-detection names stay importable from validator as the same objects."""
    validator, conflicts = _import_modules()

    for name in (
        "ValidationIssue",
        "ValidationResult",
        "_get_patterns",
        "_patterns_overlap",
        "_is_broader_pattern",
        "check_duplicate_names",
        "check_pattern_overlaps",
        "check_priority_inversions",
        "check_regex_validity",
        "validate_rules",
    ):
        assert getattr(validator, name) is getattr(conflicts, name), name


def test_validator_keeps_schema_orchestrator() -> None:
    """The per-rule schema orchestrator stays defined on validator itself."""
    validator, conflicts = _import_modules()

    assert callable(validator._validate_rule)
    assert not hasattr(conflicts, "_validate_rule")


def test_reexported_validate_rules_runs_checks() -> None:
    """Re-exported entrypoint behaves identically (same object, same result)."""
    validator, conflicts = _import_modules()

    rules = [
        TagRule(name="dup", match="스타벅스", fields=["merchant_raw"], tags=["t1"]),
        TagRule(name="dup", match="맥도날드", fields=["merchant_raw"], tags=["t2"]),
    ]

    result = validator.validate_rules(rules)

    assert isinstance(result, conflicts.ValidationResult)
    assert result.total_rules == 2
    assert any(issue.issue_type == "duplicate_name" for issue in result.errors)
