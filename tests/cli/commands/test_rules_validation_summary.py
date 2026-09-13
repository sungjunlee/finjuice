"""Unit tests for focused rules mutation validation JSON summaries."""

from __future__ import annotations

from finjuice.pipeline.cli.commands.rules_cmd.shared import (
    _problem_involves_rule,
    _serialize_validation_summary,
)
from finjuice.pipeline.tagging.validator_conflicts_types import (
    ValidationIssue,
    ValidationResult,
)


def _issue(
    *,
    rules: list[str],
    issue_type: str = "pattern_overlap",
    severity: str = "warning",
    message: str | None = None,
) -> ValidationIssue:
    """Build a validation issue for serializer tests."""
    return ValidationIssue(
        severity=severity,
        issue_type=issue_type,
        message=message or f"{issue_type}: {' vs '.join(rules)}",
        rules_involved=list(rules),
        suggestion="adjust priorities",
    )


def _result(*issues: ValidationIssue, total_rules: int = 3, passed: int = 1) -> ValidationResult:
    """Build a validation result with the given issues."""
    return ValidationResult(total_rules=total_rules, issues=list(issues), passed=passed)


class TestSerializeValidationSummary:
    """Focused mutation JSON should hide unrelated problems without dropping counts."""

    def test_focus_rule_hides_unrelated_overlaps_and_keeps_full_counts(self) -> None:
        """Non-overlapping add yields empty problems while total_problems stays 32."""
        # Arrange
        issues = [
            _issue(rules=[f"left_{index}", f"right_{index}"], message=f"overlap {index}")
            for index in range(32)
        ]
        result = _result(*issues, total_rules=65, passed=1)

        # Act
        payload = _serialize_validation_summary(result, focus_rule="unique_widget")

        # Assert
        assert payload["problems"] == []
        assert payload["total_problems"] == 32
        assert payload["warnings"] == 32
        assert payload["errors"] == 0
        assert payload["status"] == "issues"
        assert payload["total_rules"] == 65
        assert payload["passed"] == 1

    def test_focus_rule_keeps_problems_that_name_the_rule_on_either_side(self) -> None:
        """Overlapping add still surfaces only problems that mention the new rule."""
        # Arrange
        preexisting = _issue(rules=["coffee_general", "coffee_specific"])
        left_side = _issue(rules=["unique_widget", "coffee_general"])
        right_side = _issue(rules=["coffee_specific", "unique_widget"])
        error = _issue(
            rules=["other"],
            issue_type="duplicate_name",
            severity="error",
            message="Duplicate rule name: 'other'",
        )
        result = _result(preexisting, left_side, right_side, error, total_rules=4, passed=0)

        # Act
        payload = _serialize_validation_summary(result, focus_rule="unique_widget")

        # Assert
        assert payload["status"] == "issues"
        assert payload["errors"] == 1
        assert payload["warnings"] == 3
        assert payload["total_problems"] == 4
        assert [problem["rules"] for problem in payload["problems"]] == [
            ["unique_widget", "coffee_general"],
            ["coffee_specific", "unique_widget"],
        ]

    def test_without_focus_rule_lists_every_problem_and_omits_total_problems(self) -> None:
        """Explicit rules validate keeps the full report and no total_problems field."""
        # Arrange
        result = _result(
            _issue(rules=["coffee_general", "coffee_specific"]),
            _issue(rules=["unique_widget", "coffee_general"]),
            total_rules=3,
            passed=0,
        )

        # Act
        payload = _serialize_validation_summary(result)

        # Assert
        assert "total_problems" not in payload
        assert len(payload["problems"]) == 2
        assert payload["warnings"] == 2
        assert payload["status"] == "issues"

    def test_serializer_is_idempotent_for_the_same_result(self) -> None:
        """The same validation result yields the same focused payload twice."""
        # Arrange
        result = _result(
            _issue(rules=["coffee_general", "coffee_specific"]),
            _issue(rules=["unique_widget", "coffee_general"]),
            total_rules=3,
            passed=0,
        )

        # Act
        first = _serialize_validation_summary(result, focus_rule="unique_widget")
        second = _serialize_validation_summary(result, focus_rule="unique_widget")

        # Assert
        assert first == second
        assert first["total_problems"] == 2
        assert len(first["problems"]) == 1


class TestProblemInvolvesRule:
    """A problem involves a rule when that name appears on either side."""

    def test_matches_either_side_of_the_rules_list(self) -> None:
        """Either named rule counts as related."""
        # Arrange
        problem = {"rules": ["coffee_general", "coffee_specific"]}

        # Act / Assert
        assert _problem_involves_rule(problem, "coffee_general") is True
        assert _problem_involves_rule(problem, "coffee_specific") is True
        assert _problem_involves_rule(problem, "unique_widget") is False

    def test_missing_rules_are_not_related(self) -> None:
        """Problems without a rules list do not match a focus rule."""
        # Arrange
        problem: dict[str, object] = {}

        # Act
        related = _problem_involves_rule(problem, "unique_widget")

        # Assert
        assert related is False
