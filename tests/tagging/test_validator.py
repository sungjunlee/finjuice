"""Tests for rule validation and conflict detection."""

from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.validator import (
    ValidationIssue,
    ValidationResult,
    check_duplicate_names,
    check_pattern_overlaps,
    check_priority_inversions,
    check_regex_validity,
    validate_rules,
)


class TestValidationIssue:
    """Tests for ValidationIssue dataclass."""

    def test_creation(self):
        """Test creating a validation issue."""
        issue = ValidationIssue(
            severity="warning",
            issue_type="pattern_overlap",
            message="Test message",
            rules_involved=["rule1", "rule2"],
            suggestion="Fix it",
        )

        assert issue.severity == "warning"
        assert issue.issue_type == "pattern_overlap"
        assert issue.message == "Test message"
        assert issue.rules_involved == ["rule1", "rule2"]
        assert issue.suggestion == "Fix it"

    def test_default_values(self):
        """Test default values for optional fields."""
        issue = ValidationIssue(
            severity="error",
            issue_type="duplicate_name",
            message="Test",
        )

        assert issue.rules_involved == []
        assert issue.suggestion is None


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_errors_property(self):
        """Test filtering error-level issues."""
        result = ValidationResult(
            total_rules=5,
            issues=[
                ValidationIssue("error", "dup", "Error 1"),
                ValidationIssue("warning", "overlap", "Warning 1"),
                ValidationIssue("error", "dup", "Error 2"),
            ],
        )

        assert len(result.errors) == 2
        assert all(i.severity == "error" for i in result.errors)

    def test_warnings_property(self):
        """Test filtering warning-level issues."""
        result = ValidationResult(
            total_rules=5,
            issues=[
                ValidationIssue("error", "dup", "Error 1"),
                ValidationIssue("warning", "overlap", "Warning 1"),
                ValidationIssue("warning", "inversion", "Warning 2"),
            ],
        )

        assert len(result.warnings) == 2
        assert all(i.severity == "warning" for i in result.warnings)

    def test_has_errors(self):
        """Test has_errors property."""
        result_with_errors = ValidationResult(
            total_rules=1,
            issues=[ValidationIssue("error", "dup", "Error")],
        )
        result_without_errors = ValidationResult(
            total_rules=1,
            issues=[ValidationIssue("warning", "overlap", "Warning")],
        )

        assert result_with_errors.has_errors is True
        assert result_without_errors.has_errors is False

    def test_has_warnings(self):
        """Test has_warnings property."""
        result_with_warnings = ValidationResult(
            total_rules=1,
            issues=[ValidationIssue("warning", "overlap", "Warning")],
        )
        result_without_warnings = ValidationResult(
            total_rules=1,
            issues=[ValidationIssue("error", "dup", "Error")],
        )

        assert result_with_warnings.has_warnings is True
        assert result_without_warnings.has_warnings is False


class TestCheckDuplicateNames:
    """Tests for check_duplicate_names function."""

    def test_no_duplicates(self):
        """Test with unique rule names."""
        rules = [
            TagRule(name="rule1", match="a", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="rule2", match="b", fields=["merchant_raw"], tags=["t2"]),
        ]

        issues = check_duplicate_names(rules)

        assert len(issues) == 0

    def test_with_duplicates(self):
        """Test with duplicate rule names."""
        rules = [
            TagRule(name="duplicate", match="a", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="duplicate", match="b", fields=["merchant_raw"], tags=["t2"]),
        ]

        issues = check_duplicate_names(rules)

        assert len(issues) == 1
        assert issues[0].severity == "error"
        assert issues[0].issue_type == "duplicate_name"
        assert "duplicate" in issues[0].message

    def test_multiple_duplicates(self):
        """Test with multiple duplicate rule names."""
        rules = [
            TagRule(name="dup1", match="a", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="dup1", match="b", fields=["merchant_raw"], tags=["t2"]),
            TagRule(name="dup2", match="c", fields=["merchant_raw"], tags=["t3"]),
            TagRule(name="dup2", match="d", fields=["merchant_raw"], tags=["t4"]),
        ]

        issues = check_duplicate_names(rules)

        assert len(issues) == 2


class TestCheckPatternOverlaps:
    """Tests for check_pattern_overlaps function."""

    def test_no_overlap(self):
        """Test rules with no pattern overlap."""
        rules = [
            TagRule(name="rule1", match="스타벅스", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="rule2", match="맥도날드", fields=["merchant_raw"], tags=["t2"]),
        ]

        issues = check_pattern_overlaps(rules)

        assert len(issues) == 0

    def test_exact_overlap(self):
        """Test rules with exact pattern overlap."""
        rules = [
            TagRule(
                name="rule1",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["t1"],
                priority=90,
            ),
            TagRule(
                name="rule2",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["t2"],
                priority=80,
            ),
        ]

        issues = check_pattern_overlaps(rules)

        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].issue_type == "pattern_overlap"
        assert "rule1" in issues[0].rules_involved
        assert "rule2" in issues[0].rules_involved

    def test_substring_overlap(self):
        """Test rules where one pattern is substring of another."""
        rules = [
            TagRule(name="rule1", match="카페", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="rule2", match="스타벅스 카페", fields=["merchant_raw"], tags=["t2"]),
        ]

        issues = check_pattern_overlaps(rules)

        assert len(issues) == 1
        assert "rule1" in issues[0].rules_involved
        assert "rule2" in issues[0].rules_involved

    def test_different_fields_no_overlap(self):
        """Test rules with same pattern but different fields are not considered overlap."""
        rules = [
            TagRule(name="rule1", match="테스트", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="rule2", match="테스트", fields=["memo_raw"], tags=["t2"]),
        ]

        issues = check_pattern_overlaps(rules)

        assert len(issues) == 0

    def test_or_pattern_overlap(self):
        """Test rules with OR patterns that overlap."""
        rules = [
            TagRule(name="rule1", match="a|b", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="rule2", match="b|c", fields=["merchant_raw"], tags=["t2"]),
        ]

        issues = check_pattern_overlaps(rules)

        assert len(issues) == 1


class TestCheckPriorityInversions:
    """Tests for check_priority_inversions function."""

    def test_no_inversion(self):
        """Test rules without priority inversion."""
        rules = [
            TagRule(
                name="specific",
                match="스타벅스 강남점",
                fields=["merchant_raw"],
                tags=["t1"],
                priority=90,  # Higher priority for specific pattern
            ),
            TagRule(
                name="general",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["t2"],
                priority=80,  # Lower priority for broad pattern
            ),
        ]

        issues = check_priority_inversions(rules)

        assert len(issues) == 0

    def test_with_inversion(self):
        """Test rules with priority inversion (broad pattern has higher priority)."""
        rules = [
            TagRule(
                name="broad",
                match="카페",
                fields=["merchant_raw"],
                tags=["t1"],
                priority=90,  # High priority for broad pattern - problem!
            ),
            TagRule(
                name="specific",
                match="스타벅스 카페",
                fields=["merchant_raw"],
                tags=["t2"],
                priority=80,  # Low priority for specific pattern
            ),
        ]

        issues = check_priority_inversions(rules)

        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].issue_type == "priority_inversion"

    def test_different_fields_no_inversion(self):
        """Test that different fields don't trigger inversion warnings."""
        rules = [
            TagRule(
                name="broad",
                match="카페",
                fields=["merchant_raw"],
                tags=["t1"],
                priority=90,
            ),
            TagRule(
                name="specific",
                match="스타벅스 카페",
                fields=["memo_raw"],
                tags=["t2"],
                priority=80,
            ),
        ]

        issues = check_priority_inversions(rules)

        assert len(issues) == 0

    def test_with_reverse_order_inversion(self):
        """Test priority inversion when rule2 is broader (rule order reversed)."""
        # When rules are in reverse order: specific first, broad second
        # The check should still detect the inversion
        rules = [
            TagRule(
                name="specific",
                match="스타벅스 카페",
                fields=["merchant_raw"],
                tags=["t1"],
                priority=80,  # Lower priority for specific
            ),
            TagRule(
                name="broad",
                match="카페",
                fields=["merchant_raw"],
                tags=["t2"],
                priority=90,  # Higher priority for broad - problem!
            ),
        ]

        issues = check_priority_inversions(rules)

        assert len(issues) == 1
        assert issues[0].severity == "warning"
        assert issues[0].issue_type == "priority_inversion"
        assert "broad" in issues[0].rules_involved
        assert "specific" in issues[0].rules_involved


class TestCheckRegexValidity:
    """Tests for check_regex_validity function."""

    def test_valid_regex(self):
        """Test valid regex patterns."""
        rules = [
            TagRule(
                name="rule1",
                match="스타벅스|STARBUCKS",
                fields=["merchant_raw"],
                tags=["t1"],
            ),
        ]

        issues = check_regex_validity(rules)

        assert len(issues) == 0

    def test_invalid_regex(self):
        """Test invalid regex patterns generate info-level issues."""
        rules = [
            TagRule(
                name="rule1",
                match="[invalid(regex",
                fields=["merchant_raw"],
                tags=["t1"],
            ),
        ]

        issues = check_regex_validity(rules)

        assert len(issues) == 1
        assert issues[0].severity == "info"
        assert issues[0].issue_type == "invalid_regex"


class TestValidateRules:
    """Tests for validate_rules main function."""

    def test_empty_rules(self):
        """Test validation with empty rules list."""
        result = validate_rules([])

        assert result.total_rules == 0
        assert len(result.issues) == 0
        assert result.passed == 0

    def test_all_valid_rules(self):
        """Test validation with all valid rules."""
        rules = [
            TagRule(name="rule1", match="a", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="rule2", match="b", fields=["merchant_raw"], tags=["t2"]),
        ]

        result = validate_rules(rules)

        assert result.total_rules == 2
        assert len(result.issues) == 0
        assert result.passed == 2
        assert result.has_errors is False
        assert result.has_warnings is False

    def test_mixed_issues(self):
        """Test validation with multiple types of issues."""
        rules = [
            TagRule(name="dup", match="a", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="dup", match="b", fields=["merchant_raw"], tags=["t2"]),  # Duplicate
            TagRule(name="overlap", match="a", fields=["merchant_raw"], tags=["t3"]),  # Overlap
        ]

        result = validate_rules(rules)

        assert result.total_rules == 3
        assert len(result.issues) > 0
        assert result.has_errors is True  # From duplicate

    def test_passed_count(self):
        """Test that passed count excludes rules with issues."""
        rules = [
            TagRule(name="good1", match="x", fields=["merchant_raw"], tags=["t1"]),
            TagRule(name="good2", match="y", fields=["merchant_raw"], tags=["t2"]),
            TagRule(name="dup", match="z", fields=["merchant_raw"], tags=["t3"]),
            TagRule(name="dup", match="w", fields=["merchant_raw"], tags=["t4"]),  # Duplicate
        ]

        result = validate_rules(rules)

        # Only "dup" name is in rules_involved, so 3 rules pass (good1, good2, and first dup)
        # The duplicate check only records the name once in rules_involved
        assert result.passed == 3
        assert result.total_rules == 4
        assert len(result.errors) == 1  # One duplicate error
