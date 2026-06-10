"""
Unit tests for rule-based tagging engine.

Tests cover:
- YAML parsing (valid, empty, malformed)
- Pattern matching (single, multiple, Korean, case-insensitive)
- Priority ordering
- Tag deduplication
- Edge cases (disabled rules, missing fields, special characters)
"""

from pathlib import Path

from finjuice.pipeline.tagging.models import (
    Condition,
    TaggingResult,
    TagRule,
)
from finjuice.pipeline.tagging.rules import (
    apply_tagging_rules,
    apply_tagging_rules_v3,
)
from finjuice.pipeline.tagging.rules_yaml_io import (
    load_rules,
    load_rules_collecting,
    save_rules,
)
from finjuice.pipeline.tagging.validator import _validate_condition


class TestTaggingResult:
    """Tests for TaggingResult dataclass (v3 schema)."""

    def test_tagging_result_has_category_true(self):
        """Test has_category returns True when category_rule is set."""
        # Arrange & Act
        result = TaggingResult(tags=["보험", "정기지출"], category_rule="보험료")

        # Assert
        assert result.has_category is True
        assert result.category_rule == "보험료"
        assert result.tags == ["보험", "정기지출"]

    def test_tagging_result_has_category_false_when_empty(self):
        """Test has_category returns False when category_rule is empty string."""
        # Arrange & Act
        result = TaggingResult(tags=["카페"], category_rule="")

        # Assert
        assert result.has_category is False
        assert result.category_rule == ""

    def test_tagging_result_empty_tags_and_category(self):
        """Test TaggingResult with no tags and no category."""
        # Arrange & Act
        result = TaggingResult(tags=[], category_rule="")

        # Assert
        assert result.tags == []
        assert result.category_rule == ""
        assert result.has_category is False


class TestApplyTaggingRulesV3:
    """Tests for apply_tagging_rules_v3() with category support (v3 schema)."""

    def test_returns_tagging_result_with_category(self):
        """Test that matching rule with category sets category_rule."""
        # Arrange
        transaction = {"merchant_raw": "METLIFE 보험", "memo_raw": ""}
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw"],
                tags=["보험"],
                category="보험료",
                priority=95,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert isinstance(result, TaggingResult)
        assert result.tags == ["보험"]
        assert result.category_rule == "보험료"
        assert result.has_category is True

    def test_first_rule_with_category_wins(self):
        """Test that the highest-priority matching category wins."""
        # Arrange
        transaction = {"merchant_raw": "스타벅스 커피", "memo_raw": ""}
        rules = [
            TagRule(
                name="starbucks",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페", "스타벅스"],
                category="카페",  # Highest-priority matching category
                priority=90,
            ),
            TagRule(
                name="coffee",
                match="커피",
                fields=["merchant_raw"],
                tags=["커피"],
                category="음료",  # Should NOT override
                priority=80,
            ),
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        # Both rules contribute tags
        assert "카페" in result.tags
        assert "스타벅스" in result.tags
        assert "커피" in result.tags
        # Highest-priority category wins
        assert result.category_rule == "카페"

    def test_priority_order_merges_all_matching_tags_but_highest_category_wins(
        self, tmp_path: Path
    ):
        """All matching rules add tags, while the top matching category wins."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: generic_cafe
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페", "일반"]
    category: "카페"
    priority: 40
  - name: brand_specific
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["브랜드", "카페"]
    priority: 90
  - name: subscription_category
    match: "정기구독"
    fields: [memo_raw]
    tags: ["정기결제", "브랜드"]
    category: "구독"
    priority: 70
""",
            encoding="utf-8",
        )
        transaction = {
            "merchant_raw": "스타벅스 강남점",
            "memo_raw": "정기구독 커피",
        }

        # Act
        rules = load_rules(rules_file)
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.matching_rules == [
            "brand_specific",
            "subscription_category",
            "generic_cafe",
        ]
        assert result.tags == ["브랜드", "카페", "정기결제", "일반"]
        assert result.category_rule == "구독"

    def test_no_category_when_rules_lack_category_field(self):
        """Test category_rule is empty when matching rules have no category."""
        # Arrange
        transaction = {"merchant_raw": "GS25", "memo_raw": ""}
        rules = [
            TagRule(
                name="convenience",
                match="GS25",
                fields=["merchant_raw"],
                tags=["편의점"],
                # No category field set (defaults to "")
                priority=80,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["편의점"]
        assert result.category_rule == ""
        assert result.has_category is False

    def test_later_rule_with_category_wins_if_first_has_no_category(self):
        """Test that if first rule has no category, second rule's category is used."""
        # Arrange
        transaction = {"merchant_raw": "스타벅스 커피", "memo_raw": ""}
        rules = [
            TagRule(
                name="starbucks",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["스타벅스"],
                # No category
                priority=90,
            ),
            TagRule(
                name="coffee",
                match="커피",
                fields=["merchant_raw"],
                tags=["커피"],
                category="음료",  # This one sets category
                priority=80,
            ),
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["스타벅스", "커피"]
        assert result.category_rule == "음료"  # Second rule's category

    def test_no_match_returns_empty_result(self):
        """Test that no matching rules returns empty TaggingResult."""
        # Arrange
        transaction = {"merchant_raw": "Unknown Merchant", "memo_raw": ""}
        rules = [
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페"],
                category="카페",
                priority=80,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == []
        assert result.category_rule == ""
        assert result.has_category is False

    def test_disabled_rules_not_applied(self):
        """Test that disabled rules don't contribute tags or category."""
        # Arrange
        transaction = {"merchant_raw": "METLIFE", "memo_raw": ""}
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw"],
                tags=["보험"],
                category="보험료",
                priority=95,
                enabled=False,  # Disabled
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == []
        assert result.category_rule == ""

    def test_tags_deduplicated_across_rules(self):
        """Test that tags from multiple rules are deduplicated."""
        # Arrange
        transaction = {"merchant_raw": "스타벅스", "memo_raw": "커피"}
        rules = [
            TagRule(
                name="starbucks",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페", "커피", "외식"],
                category="카페",
                priority=90,
            ),
            TagRule(
                name="coffee",
                match="커피",
                fields=["memo_raw"],
                tags=["커피", "외식"],  # Duplicate tags
                priority=80,
            ),
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["카페", "커피", "외식"]  # No duplicates
        assert len(result.tags) == 3


class TestLoadRulesWithCategory:
    """Tests for loading rules with category field (v3 schema)."""

    def test_load_rules_with_category_field(self, tmp_path: Path):
        """Test that rules with category field load correctly."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: insurance
    match: "METLIFE"
    fields: [merchant_raw]
    tags: ["보험"]
    category: "보험료"
    priority: 95
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 1
        assert rules[0].category == "보험료"

    def test_load_rules_default_category_empty(self, tmp_path: Path):
        """Test that rules without category field default to empty string."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: cafe
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 1
        assert rules[0].category == ""


class TestSaveRulesWithCategory:
    """Tests for saving rules with category field."""

    def test_save_rules_includes_non_empty_category(self, tmp_path: Path):
        """Test that rules with category preserve it in YAML output."""
        # Arrange
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw"],
                tags=["보험"],
                category="보험료",
                priority=95,
            )
        ]
        rules_file = tmp_path / "output.yaml"

        # Act
        save_rules(rules, rules_file)

        # Assert
        content = rules_file.read_text(encoding="utf-8")
        assert "category: 보험료" in content

    def test_save_rules_excludes_empty_category(self, tmp_path: Path):
        """Test that rules with empty category don't have category in YAML output."""
        # Arrange
        rules = [
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페"],
                category="",  # Empty
                priority=80,
            )
        ]
        rules_file = tmp_path / "output.yaml"

        # Act
        save_rules(rules, rules_file)

        # Assert
        content = rules_file.read_text(encoding="utf-8")
        assert "category:" not in content  # Should not appear

    def test_save_rules_roundtrip_with_category(self, tmp_path: Path):
        """Test save/load roundtrip preserves category field."""
        # Arrange
        original_rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw"],
                tags=["보험"],
                category="보험료",
                priority=95,
            ),
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페"],
                category="",  # No category
                priority=80,
            ),
        ]
        rules_file = tmp_path / "roundtrip.yaml"

        # Act
        save_rules(original_rules, rules_file)
        loaded_rules = load_rules(rules_file)

        # Assert
        assert len(loaded_rules) == 2
        # Insurance rule preserves category
        insurance = next(r for r in loaded_rules if r.name == "insurance")
        assert insurance.category == "보험료"
        # Cafe rule has empty category (default)
        cafe = next(r for r in loaded_rules if r.name == "cafe")
        assert cafe.category == ""


class TestLoadRules:
    """Tests for load_rules() function."""

    def test_load_rules_valid_yaml(self, tmp_path: Path):
        """Test loading valid rules from YAML file."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: insurance
    match: "METLIFE|메트라이프"
    fields: [merchant_raw, memo_raw]
    tags: ["보험", "정기지출"]
    priority: 95
  - name: cafe
    match: "스타벅스|STARBUCKS"
    fields: [merchant_raw]
    tags: ["카페", "커피"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 2
        assert rules[0].name == "insurance"  # Higher priority first
        assert rules[0].priority == 95
        assert rules[0].tags == ["보험", "정기지출"]
        assert rules[1].name == "cafe"
        assert rules[1].priority == 80

    def test_load_rules_empty_file(self, tmp_path: Path):
        """Test loading from empty YAML file."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text("", encoding="utf-8")

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert rules == []

    def test_load_rules_no_rules_key(self, tmp_path: Path):
        """Test loading YAML without 'rules' key."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text("version: 1\n", encoding="utf-8")

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert rules == []

    def test_load_rules_nonexistent_file(self, tmp_path: Path):
        """Test loading from non-existent file."""
        # Arrange
        rules_file = tmp_path / "nonexistent.yaml"

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert rules == []

    def test_load_rules_default_values(self, tmp_path: Path):
        """Test that optional fields get default values."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: minimal
    match: "TEST"
    fields: [merchant_raw]
    tags: ["test"]
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 1
        assert rules[0].priority == 50  # Default
        assert rules[0].enabled is True  # Default
        assert rules[0].created_by == "manual"  # Default
        assert rules[0].confidence == 1.0  # Default

    def test_load_rules_priority_sorting(self, tmp_path: Path):
        """Test that rules are sorted by priority (descending)."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: low
    match: "A"
    fields: [merchant_raw]
    tags: ["a"]
    priority: 10
  - name: high
    match: "B"
    fields: [merchant_raw]
    tags: ["b"]
    priority: 90
  - name: medium
    match: "C"
    fields: [merchant_raw]
    tags: ["c"]
    priority: 50
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 3
        assert rules[0].name == "high"
        assert rules[0].priority == 90
        assert rules[1].name == "medium"
        assert rules[1].priority == 50
        assert rules[2].name == "low"
        assert rules[2].priority == 10

    def test_load_rules_fixture(self):
        """Test loading the actual sample_rules.yaml fixture."""
        # Arrange
        fixture_path = Path(__file__).parent / "fixtures" / "sample_rules.yaml"
        assert fixture_path.exists(), "Sample fixture should exist"

        # Act
        rules = load_rules(fixture_path)

        # Assert
        assert len(rules) > 0
        # Insurance rules should be at the top (priority 95)
        insurance_rules = [r for r in rules if "보험" in r.tags]
        assert len(insurance_rules) >= 2
        assert all(r.priority == 95 for r in insurance_rules)


class TestLoadRulesCollecting:
    """Tests for load_rules_collecting() partial-success loading."""

    def test_load_rules_collects_multiple_invalid_rules(self, tmp_path: Path):
        """Multiple malformed rules should be collected in one pass."""
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: valid_rule
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 80
  - name: invalid_operator
    conditions:
      - field: merchant_raw
        op: startswith
        value: "스타벅스"
    tags: ["카페"]
  - name: missing_tags
    match: "보험"
    fields: [merchant_raw]
""",
            encoding="utf-8",
        )

        result = load_rules_collecting(rules_file)

        assert len(result.rules) == 1
        assert result.rules[0].name == "valid_rule"
        assert [error.rule_name for error in result.errors] == [
            "invalid_operator",
            "missing_tags",
        ]
        assert len(result.errors) == 2
        assert result.errors[0].rule_index == 1
        assert "Rule 'invalid_operator' (#1)" in result.errors[0].message
        assert result.errors[0].suggestion == "Did you mean: 'starts_with'?"
        assert result.errors[1].suggestion is None

    def test_load_rules_collecting_suggests_aliases(self, tmp_path: Path):
        """Common operator aliases (equal, startswith) should produce suggestions."""
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: typo_equal
    conditions:
      - field: merchant_raw
        op: equal
        value: "스타벅스"
    tags: ["카페"]
  - name: typo_matches
    conditions:
      - field: merchant_raw
        op: matches
        value: "스타벅스"
    tags: ["카페"]
""",
            encoding="utf-8",
        )

        result = load_rules_collecting(rules_file)

        assert len(result.rules) == 0
        assert len(result.errors) == 2
        assert result.errors[0].suggestion == "Did you mean: 'is'?"
        assert result.errors[1].suggestion == "Did you mean: 'regex'?"

    def test_load_rules_collecting_returns_valid_subset(self, tmp_path: Path):
        """Valid rules should still load and remain priority-sorted."""
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: low_priority
    match: "A"
    fields: [merchant_raw]
    tags: ["low"]
    priority: 20
  - name: broken_rule
    conditions:
      - field: merchant_raw
        op: contains
    tags: ["broken"]
  - name: high_priority
    match: "B"
    fields: [merchant_raw]
    tags: ["high"]
    priority: 90
""",
            encoding="utf-8",
        )

        result = load_rules_collecting(rules_file)

        assert [rule.name for rule in result.rules] == ["high_priority", "low_priority"]
        assert len(result.errors) == 1
        assert result.errors[0].rule_name == "broken_rule"

    def test_load_rules_collecting_empty_file(self, tmp_path: Path):
        """Empty YAML files should return no rules and no errors."""
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text("", encoding="utf-8")

        result = load_rules_collecting(rules_file)

        assert result.rules == []
        assert result.errors == []

    def test_load_rules_collecting_no_rules_key(self, tmp_path: Path):
        """Files without a rules key should return an empty collected result."""
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text("version: 1\n", encoding="utf-8")

        result = load_rules_collecting(rules_file)

        assert result.rules == []
        assert result.errors == []


class TestApplyTaggingRules:
    """Tests for apply_tagging_rules() function."""

    def test_apply_rules_single_match(self):
        """Test applying rules with single match."""
        # Arrange
        transaction = {
            "merchant_raw": "METLIFE 보험",
            "memo_raw": "",
        }
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE|메트라이프",
                fields=["merchant_raw", "memo_raw"],
                tags=["보험", "정기지출"],
                priority=95,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == ["보험", "정기지출"]

    def test_apply_rules_multiple_matches(self):
        """Test that all matching rules contribute tags."""
        # Arrange
        transaction = {
            "merchant_raw": "스타벅스 강남점",
            "memo_raw": "커피",
        }
        rules = [
            TagRule(
                name="starbucks",
                match="스타벅스|STARBUCKS",
                fields=["merchant_raw"],
                tags=["카페", "스타벅스"],
                priority=90,
            ),
            TagRule(
                name="coffee",
                match="커피|COFFEE",
                fields=["memo_raw"],
                tags=["커피", "외식"],
                priority=80,
            ),
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        # All tags from both rules, deduplicated
        assert "카페" in tags
        assert "스타벅스" in tags
        assert "커피" in tags
        assert "외식" in tags
        assert len(tags) == 4

    def test_apply_rules_no_match(self):
        """Test applying rules when no pattern matches."""
        # Arrange
        transaction = {
            "merchant_raw": "Unknown Merchant",
            "memo_raw": "",
        }
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw"],
                tags=["보험"],
                priority=95,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == []

    def test_apply_rules_case_insensitive(self):
        """Test that pattern matching is case-insensitive."""
        # Arrange
        transaction = {
            "merchant_raw": "starbucks",  # lowercase
            "memo_raw": "",
        }
        rules = [
            TagRule(
                name="cafe",
                match="STARBUCKS",  # uppercase
                fields=["merchant_raw"],
                tags=["카페"],
                priority=80,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == ["카페"]

    def test_apply_rules_pipe_separated_patterns(self):
        """Test pipe-separated pattern matching."""
        # Arrange
        transaction1 = {"merchant_raw": "METLIFE", "memo_raw": ""}
        transaction2 = {"merchant_raw": "메트라이프", "memo_raw": ""}

        rules = [
            TagRule(
                name="insurance",
                match="METLIFE|메트라이프|MetLife",
                fields=["merchant_raw"],
                tags=["보험"],
                priority=95,
            )
        ]

        # Act
        tags1 = apply_tagging_rules(transaction1, rules)
        tags2 = apply_tagging_rules(transaction2, rules)

        # Assert
        assert tags1 == ["보험"]
        assert tags2 == ["보험"]

    def test_apply_rules_multiple_fields(self):
        """Test matching across multiple fields."""
        # Arrange
        transaction = {
            "merchant_raw": "Unknown",
            "memo_raw": "METLIFE 보험료",
        }
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw", "memo_raw"],  # Check both fields
                tags=["보험"],
                priority=95,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == ["보험"]

    def test_apply_rules_disabled_rule(self):
        """Test that disabled rules are not applied."""
        # Arrange
        transaction = {
            "merchant_raw": "TEST_MERCHANT",
            "memo_raw": "",
        }
        rules = [
            TagRule(
                name="disabled",
                match="TEST_MERCHANT",
                fields=["merchant_raw"],
                tags=["테스트"],
                priority=100,
                enabled=False,  # Disabled
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == []

    def test_apply_rules_missing_field(self):
        """Test handling missing fields in transaction."""
        # Arrange
        transaction = {
            "merchant_raw": "스타벅스",
            # memo_raw is missing
        }
        rules = [
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw", "memo_raw"],
                tags=["카페"],
                priority=80,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == ["카페"]  # Should still match on merchant_raw

    def test_apply_rules_empty_field_value(self):
        """Test handling empty string field values."""
        # Arrange
        transaction = {
            "merchant_raw": "",
            "memo_raw": "스타벅스",
        }
        rules = [
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw", "memo_raw"],
                tags=["카페"],
                priority=80,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == ["카페"]  # Should match on memo_raw

    def test_apply_rules_tag_deduplication(self):
        """Test that duplicate tags are removed while preserving order."""
        # Arrange
        transaction = {
            "merchant_raw": "스타벅스",
            "memo_raw": "커피",
        }
        rules = [
            TagRule(
                name="starbucks",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페", "커피", "외식"],
                priority=90,
            ),
            TagRule(
                name="coffee",
                match="커피",
                fields=["memo_raw"],
                tags=["커피", "외식"],  # Duplicate tags
                priority=80,
            ),
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == ["카페", "커피", "외식"]  # No duplicates
        assert len(tags) == 3

    def test_apply_rules_priority_order(self):
        """Test that higher priority rules contribute tags first."""
        # Arrange
        transaction = {
            "merchant_raw": "TEST",
            "memo_raw": "",
        }
        rules = [
            TagRule(
                name="high",
                match="TEST",
                fields=["merchant_raw"],
                tags=["high_priority"],
                priority=100,
            ),
            TagRule(
                name="low",
                match="TEST",
                fields=["merchant_raw"],
                tags=["low_priority"],
                priority=10,
            ),
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        # High priority rule's tags should come first
        assert tags[0] == "high_priority"
        assert tags[1] == "low_priority"

    def test_apply_rules_korean_text(self):
        """Test Korean text pattern matching."""
        # Arrange
        transaction = {
            "merchant_raw": "관리비 납부",
            "memo_raw": "",
        }
        rules = [
            TagRule(
                name="apartment",
                match="관리비|아파트관리비",
                fields=["merchant_raw", "memo_raw"],
                tags=["공과금", "주거"],
                priority=90,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == ["공과금", "주거"]

    def test_apply_rules_empty_rules_list(self):
        """Test applying empty rules list."""
        # Arrange
        transaction = {
            "merchant_raw": "스타벅스",
            "memo_raw": "",
        }
        rules = []

        # Act
        tags = apply_tagging_rules(transaction, rules)

        # Assert
        assert tags == []


class TestConditionsEngine:
    """Tests for conditions-based matching."""

    def test_contains_operator(self):
        """Test contains condition with case-insensitive substring match."""
        # Arrange
        transaction = {
            "merchant_raw": "예금 이자 지급",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
        }
        rules = [
            TagRule(
                name="interest_income",
                tags=["이자수입"],
                conditions=[Condition(field="merchant_raw", op="contains", value="이자")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["이자수입"]

    def test_not_contains_operator(self):
        """Test not_contains condition negates substring match."""
        # Arrange
        transaction = {
            "merchant_raw": "예금 이자 지급",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
        }
        rules = [
            TagRule(
                name="interest_income",
                tags=["이자수입"],
                conditions=[Condition(field="merchant_raw", op="not_contains", value="이자카야")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["이자수입"]

    def test_is_operator(self):
        """Test is condition with case-insensitive exact match."""
        # Arrange
        transaction = {
            "merchant_raw": "STARBUCKS",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
        }
        rules = [
            TagRule(
                name="starbucks",
                tags=["카페"],
                conditions=[Condition(field="merchant_raw", op="is", value="starbucks")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["카페"]

    def test_is_not_operator(self):
        """Test is_not condition negates exact match."""
        # Arrange
        transaction = {
            "merchant_raw": "STARBUCKS",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
        }
        rules = [
            TagRule(
                name="not_twosome",
                tags=["카페"],
                conditions=[Condition(field="merchant_raw", op="is_not", value="twosome")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["카페"]

    def test_starts_with_operator(self):
        """Test starts_with condition with case-insensitive prefix match."""
        # Arrange
        transaction = {
            "merchant_raw": "",
            "memo_raw": "AUTO PAY 보험료",
            "major_raw": "",
            "minor_raw": "",
        }
        rules = [
            TagRule(
                name="autopay",
                tags=["자동이체"],
                conditions=[Condition(field="memo_raw", op="starts_with", value="auto pay")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["자동이체"]

    def test_regex_operator(self):
        """Test regex condition using case-insensitive search."""
        # Arrange
        transaction = {
            "merchant_raw": "이자수익 1234",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
        }
        rules = [
            TagRule(
                name="interest_regex",
                tags=["이자수입"],
                conditions=[Condition(field="merchant_raw", op="regex", value=r"이자수익\s+\d{4}")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["이자수입"]

    def test_less_than_operator(self):
        """Test less_than condition for large expenses."""
        # Arrange
        transaction = {
            "merchant_raw": "서울 병원",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -150000.0,
            "type_norm": "expense",
            "account": "삼성카드",
        }
        rules = [
            TagRule(
                name="large_medical",
                tags=["의료", "대형지출"],
                conditions=[Condition(field="amount", op="less_than", value="-100000")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["의료", "대형지출"]

    def test_greater_than_operator(self):
        """Test greater_than condition for income."""
        # Arrange
        transaction = {
            "merchant_raw": "급여",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": 2500000.0,
            "type_norm": "income",
            "account": "국민은행",
        }
        rules = [
            TagRule(
                name="income",
                tags=["수입"],
                conditions=[Condition(field="amount", op="greater_than", value="0")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["수입"]

    def test_between_operator(self):
        """Test between condition for expense ranges."""
        # Arrange
        transaction = {
            "merchant_raw": "마트",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -30000.0,
            "type_norm": "expense",
            "account": "체크카드",
        }
        rules = [
            TagRule(
                name="medium_expense",
                tags=["중간지출"],
                conditions=[Condition(field="amount", op="between", value="-50000,-10000")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["중간지출"]

    def test_between_accepts_yaml_list(self, tmp_path: Path):
        """Test between accepts YAML lists and tuple values normalize the same way."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: medium_expense
    conditions:
      - field: amount
        op: between
        value: [-50000, -10000]
    tags: ["중간지출"]
    priority: 90
""",
            encoding="utf-8",
        )
        transaction = {
            "merchant_raw": "마트",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -30000.0,
            "type_norm": "expense",
            "account": "체크카드",
        }
        csv_rules = [
            TagRule(
                name="medium_expense_csv",
                tags=["중간지출"],
                conditions=[Condition(field="amount", op="between", value="-50000,-10000")],
                priority=90,
            )
        ]

        # Act
        list_rules = load_rules(rules_file)
        list_result = apply_tagging_rules_v3(transaction, list_rules)
        csv_result = apply_tagging_rules_v3(transaction, csv_rules)
        tuple_condition = _validate_condition(
            "tuple_between",
            {"field": "amount", "op": "between", "value": (-50000, -10000)},
            0,
        )

        # Assert
        assert len(list_rules) == 1
        assert list_rules[0].conditions[0] == Condition(
            field="amount",
            op="between",
            value="-50000,-10000",
        )
        assert tuple_condition == Condition(
            field="amount",
            op="between",
            value="-50000,-10000",
        )
        assert list_result.tags == ["중간지출"]
        assert list_result.tags == csv_result.tags

    def test_type_norm_is_operator(self):
        """Test text operators work on type_norm."""
        # Arrange
        transaction = {
            "merchant_raw": "예금 이자 지급",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": 1200.0,
            "type_norm": "income",
            "account": "신한은행",
        }
        rules = [
            TagRule(
                name="interest_income",
                tags=["이자수입"],
                conditions=[Condition(field="type_norm", op="is", value="income")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["이자수입"]

    def test_account_contains_operator(self):
        """Test text operators work on account."""
        # Arrange
        transaction = {
            "merchant_raw": "편의점",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -4500.0,
            "type_norm": "expense",
            "account": "삼성카드 taptap",
        }
        rules = [
            TagRule(
                name="samsung_card",
                tags=["삼성카드"],
                conditions=[Condition(field="account", op="contains", value="삼성카드")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["삼성카드"]

    def test_combined_type_norm_and_merchant(self):
        """Test type_norm combines with text conditions using default all logic."""
        # Arrange
        transaction = {
            "merchant_raw": "예금 이자 지급",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": 3200.0,
            "type_norm": "income",
            "account": "국민은행",
        }
        rules = [
            TagRule(
                name="interest_income",
                tags=["이자수입"],
                conditions=[
                    Condition(field="type_norm", op="is", value="income"),
                    Condition(field="merchant_raw", op="contains", value="이자"),
                ],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["이자수입"]

    def test_combined_amount_and_merchant(self):
        """Test amount combines with text conditions using default all logic."""
        # Arrange
        transaction = {
            "merchant_raw": "서울 병원",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -125000.0,
            "type_norm": "expense",
            "account": "현대카드",
        }
        rules = [
            TagRule(
                name="large_medical",
                tags=["의료", "대형지출"],
                conditions=[
                    Condition(field="amount", op="less_than", value="-100000"),
                    Condition(field="merchant_raw", op="contains", value="병원"),
                ],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["의료", "대형지출"]

    def test_amount_operator_with_non_numeric_value(self):
        """Test numeric operators fail closed for non-numeric field values."""
        # Arrange
        transaction = {
            "merchant_raw": "서울 병원",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": "not-a-number",
            "type_norm": "expense",
            "account": "현대카드",
        }
        rules = [
            TagRule(
                name="large_medical",
                tags=["의료"],
                conditions=[Condition(field="amount", op="less_than", value="-100000")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == []

    def test_all_logic_requires_all_conditions(self):
        """Test all logic requires every condition to match."""
        # Arrange
        transaction = {
            "merchant_raw": "서울 병원",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "의원",
        }
        rules = [
            TagRule(
                name="hospital_all",
                tags=["의료"],
                conditions=[
                    Condition(field="merchant_raw", op="contains", value="병원"),
                    Condition(field="minor_raw", op="is", value="종합병원"),
                ],
                logic="all",
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == []

    def test_any_logic_matches_when_one_condition_matches(self):
        """Test any logic matches when at least one condition is true."""
        # Arrange
        transaction = {
            "merchant_raw": "서울 의원",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "종합병원",
        }
        rules = [
            TagRule(
                name="hospital_any",
                tags=["의료"],
                conditions=[
                    Condition(field="merchant_raw", op="contains", value="병원"),
                    Condition(field="minor_raw", op="is", value="종합병원"),
                ],
                logic="any",
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["의료"]

    def test_backward_compat_after_phase2(self):
        """Test existing text-only conditions still work with extended transaction fields."""
        # Arrange
        transaction = {
            "merchant_raw": "STARBUCKS 강남점",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -5500.0,
            "type_norm": "expense",
            "account": "체크카드",
        }
        rules = [
            TagRule(
                name="legacy_cafe",
                tags=["카페"],
                conditions=[Condition(field="merchant_raw", op="contains", value="starbucks")],
                priority=80,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == ["카페"]

    def test_legacy_match_fields_rules_remain_compatible(self):
        """Test legacy match/fields rules still behave the same."""
        # Arrange
        transaction = {
            "merchant_raw": "STARBUCKS 강남점",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
        }
        rules = [
            TagRule(
                name="legacy_cafe",
                match="스타벅스|STARBUCKS",
                fields=["merchant_raw"],
                tags=["카페"],
                priority=80,
            )
        ]

        # Act
        tags = apply_tagging_rules(transaction, rules)
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert tags == ["카페"]
        assert result.tags == ["카페"]
        assert result.matching_rules == ["legacy_cafe"]

    def test_conditions_take_precedence_over_match_fields(self):
        """Test conditions override legacy match/fields when both are present."""
        # Arrange
        transaction = {"merchant_raw": "스타벅스", "memo_raw": "", "major_raw": "", "minor_raw": ""}
        rules = [
            TagRule(
                name="mixed_rule",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페"],
                conditions=[Condition(field="memo_raw", op="contains", value="보험")],
                priority=90,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == []
        assert result.matching_rules == []

    def test_load_rules_condition_only(self, tmp_path: Path):
        """Test condition-only YAML rules load into Condition objects."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: hospital_any
    conditions:
      - field: merchant_raw
        op: contains
        value: "병원"
      - field: minor_raw
        op: is
        value: "종합병원"
    logic: any
    tags: ["의료"]
    priority: 85
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 1
        assert rules[0].match == ""
        assert rules[0].fields == []
        assert rules[0].logic == "any"
        assert len(rules[0].conditions) == 2
        assert isinstance(rules[0].conditions[0], Condition)
        assert rules[0].conditions[0].field == "merchant_raw"

    def test_load_rules_conditions_missing_op(self, tmp_path: Path):
        """Test conditions require an op field."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: invalid_condition
    conditions:
      - field: merchant_raw
        value: "이자"
    tags: ["이자수입"]
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "missing required fields" in str(e)
            assert "op" in str(e)

    def test_load_rules_conditions_invalid_op(self, tmp_path: Path):
        """Test conditions reject unsupported operators."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: invalid_condition
    conditions:
      - field: merchant_raw
        op: equals
        value: "이자"
    tags: ["이자수입"]
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "invalid operator" in str(e)
            assert "equals" in str(e)

    def test_between_validation(self, tmp_path: Path):
        """Test between requires a valid min,max numeric range."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: invalid_between
    conditions:
      - field: amount
        op: between
        value: "-100000"
    tags: ["테스트"]
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "invalid 'value' for between" in str(e)

    def test_between_error_message_hints_formats(self, tmp_path: Path):
        """Test between errors mention both supported value formats."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: invalid_between
    conditions:
      - field: amount
        op: between
        value: "-100000"
    tags: ["테스트"]
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "[min, max]" in str(e)
            assert "'min,max'" in str(e)

    def test_between_rejects_wrong_length_list(self, tmp_path: Path):
        """Test between rejects lists that do not contain exactly two values."""
        # Arrange
        invalid_values = ("[-100000]", "[-100000, -50000, -10000]")

        # Act & Assert
        for raw_value in invalid_values:
            rules_file = tmp_path / "rules.yaml"
            rules_file.write_text(
                f"""
version: 1
rules:
  - name: invalid_between
    conditions:
      - field: amount
        op: between
        value: {raw_value}
    tags: [\"테스트\"]
""",
                encoding="utf-8",
            )

            try:
                load_rules(rules_file)
                assert False, "Expected ValueError"
            except ValueError as e:
                assert "must have exactly 2 elements" in str(e)
                assert "[min, max]" in str(e)
                assert "'min,max'" in str(e)

    def test_between_rejects_non_numeric_list(self, tmp_path: Path):
        """Test between rejects non-numeric list values with a format hint."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: invalid_between
    conditions:
      - field: amount
        op: between
        value: ["abc", "xyz"]
    tags: ["테스트"]
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "invalid 'value' for between" in str(e)
            assert "[min, max]" in str(e)
            assert "'min,max'" in str(e)

    def test_unquoted_numeric_value_in_yaml(self, tmp_path: Path):
        """Test that unquoted numeric values in YAML work (int coercion)."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: large_expense
    conditions:
      - field: amount
        op: less_than
        value: -100000
    tags: ["대형지출"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 1
        assert rules[0].conditions[0].value == "-100000"

    def test_none_amount_returns_false(self):
        """Test that None amount does not match numeric conditions."""
        # Arrange
        transaction = {"merchant_raw": "", "memo_raw": "", "amount": None}
        rules = [
            TagRule(
                name="test",
                tags=["test"],
                conditions=[Condition(field="amount", op="greater_than", value="-1")],
                priority=50,
            )
        ]

        # Act
        result = apply_tagging_rules_v3(transaction, rules)

        # Assert
        assert result.tags == []

    def test_load_rules_empty_conditions(self, tmp_path: Path):
        """Test conditions cannot be an empty list."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: invalid_condition
    conditions: []
    tags: ["이자수입"]
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'conditions' cannot be empty" in str(e)

    def test_save_rules_roundtrip_with_conditions(self, tmp_path: Path):
        """Test save/load roundtrip preserves conditions and logic."""
        # Arrange
        original_rules = [
            TagRule(
                name="interest_income",
                tags=["이자수입"],
                conditions=[
                    Condition(field="merchant_raw", op="contains", value="이자"),
                    Condition(field="merchant_raw", op="not_contains", value="이자카야"),
                ],
                logic="any",
                category="금융수입",
                priority=90,
            )
        ]
        rules_file = tmp_path / "conditions.yaml"

        # Act
        save_rules(original_rules, rules_file)
        content = rules_file.read_text(encoding="utf-8")
        loaded_rules = load_rules(rules_file)

        # Assert
        assert "conditions:" in content
        assert "logic: any" in content
        assert len(loaded_rules) == 1
        assert loaded_rules[0].logic == "any"
        assert loaded_rules[0].category == "금융수입"
        assert len(loaded_rules[0].conditions) == 2
        assert loaded_rules[0].conditions[0] == Condition(
            field="merchant_raw",
            op="contains",
            value="이자",
        )


class TestSaveRules:
    """Tests for save_rules() function."""

    def test_save_rules_basic(self, tmp_path: Path):
        """Test saving rules to YAML file."""
        # Arrange
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw"],
                tags=["보험"],
                priority=95,
            ),
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페"],
                priority=80,
            ),
        ]
        rules_file = tmp_path / "output.yaml"

        # Act
        save_rules(rules, rules_file)

        # Assert
        assert rules_file.exists()
        loaded_rules = load_rules(rules_file)
        assert len(loaded_rules) == 2
        assert loaded_rules[0].name == "insurance"
        assert loaded_rules[1].name == "cafe"

    def test_save_rules_roundtrip(self, tmp_path: Path):
        """Test save and load roundtrip preserves data."""
        # Arrange
        original_rules = [
            TagRule(
                name="test",
                match="TEST|테스트",
                fields=["merchant_raw", "memo_raw"],
                tags=["tag1", "tag2"],
                priority=75,
                enabled=True,
                created_by="manual",
                confidence=1.0,
                notes="Test rule",
            )
        ]
        rules_file = tmp_path / "roundtrip.yaml"

        # Act
        save_rules(original_rules, rules_file)
        loaded_rules = load_rules(rules_file)

        # Assert
        assert len(loaded_rules) == 1
        rule = loaded_rules[0]
        assert rule.name == "test"
        assert rule.match == "TEST|테스트"
        assert rule.fields == ["merchant_raw", "memo_raw"]
        assert rule.tags == ["tag1", "tag2"]
        assert rule.priority == 75
        assert rule.enabled is True
        assert rule.created_by == "manual"
        assert rule.confidence == 1.0
        assert rule.notes == "Test rule"

    def test_save_rules_korean_encoding(self, tmp_path: Path):
        """Test that Korean text is properly encoded."""
        # Arrange
        rules = [
            TagRule(
                name="korean_rule",
                match="관리비|공과금",
                fields=["merchant_raw"],
                tags=["주거", "정기지출"],
                priority=90,
            )
        ]
        rules_file = tmp_path / "korean.yaml"

        # Act
        save_rules(rules, rules_file)

        # Assert
        content = rules_file.read_text(encoding="utf-8")
        assert "관리비" in content
        assert "공과금" in content
        assert "주거" in content
        assert "정기지출" in content


class TestRuleValidation:
    """Tests for rule validation logic (Issue #71)."""

    def test_load_rules_missing_required_field_name(self, tmp_path: Path):
        """Test that missing 'name' field raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - match: "TEST"
    fields: [merchant_raw]
    tags: ["test"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "missing required fields" in str(e).lower()
            assert "name" in str(e).lower()

    def test_load_rules_missing_required_field_match(self, tmp_path: Path):
        """Test that missing 'match' field raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: incomplete_rule
    fields: [merchant_raw]
    tags: ["test"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "missing required fields" in str(e).lower()
            assert "match" in str(e).lower()

    def test_load_rules_missing_multiple_fields(self, tmp_path: Path):
        """Test that missing multiple required fields raises ValueError with all missing fields."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: incomplete_rule
    # Missing 'match', 'fields', 'tags', 'priority'
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            error_msg = str(e).lower()
            assert "missing required fields" in error_msg
            # Check that multiple missing fields are mentioned
            assert "match" in error_msg or "fields" in error_msg or "tags" in error_msg

    def test_load_rules_wrong_type_fields_not_list(self, tmp_path: Path):
        """Test that 'fields' must be a list."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_rule
    match: "pattern"
    fields: "not_a_list"
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'fields' must be a list" in str(e)

    def test_load_rules_wrong_type_tags_not_list(self, tmp_path: Path):
        """Test that 'tags' must be a list."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_rule
    match: "pattern"
    fields: [merchant_raw]
    tags: "not_a_list"
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'tags' must be a list" in str(e)

    def test_load_rules_empty_fields_list(self, tmp_path: Path):
        """Test that 'fields' cannot be an empty list."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_rule
    match: "pattern"
    fields: []
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'fields' cannot be empty" in str(e)

    def test_load_rules_empty_tags_list(self, tmp_path: Path):
        """Test that 'tags' cannot be an empty list."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_rule
    match: "pattern"
    fields: [merchant_raw]
    tags: []
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'tags' cannot be empty" in str(e)

    def test_load_rules_invalid_priority_too_high(self, tmp_path: Path):
        """Test that priority out of range (>100) raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_priority
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: 150
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'priority' must be 0-100" in str(e)
            assert "150" in str(e)

    def test_load_rules_invalid_priority_negative(self, tmp_path: Path):
        """Test that negative priority raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_priority
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: -10
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'priority' must be 0-100" in str(e)

    def test_load_rules_invalid_priority_not_int(self, tmp_path: Path):
        """Test that non-integer priority raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_priority
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: 80.5
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'priority' must be an integer" in str(e)

    def test_load_rules_invalid_priority_bool(self, tmp_path: Path):
        """Test that boolean priority raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_priority
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: true
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'priority' must be an integer" in str(e)

    def test_load_rules_empty_name(self, tmp_path: Path):
        """Test that empty name raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: ""
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "name' cannot be empty" in str(e)

    def test_load_rules_whitespace_only_name(self, tmp_path: Path):
        """Test that whitespace-only name raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: "   "
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "name' cannot be empty" in str(e)

    def test_load_rules_empty_match(self, tmp_path: Path):
        """Test that empty match raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_rule
    match: ""
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "match' cannot be empty" in str(e)

    def test_load_rules_whitespace_only_match(self, tmp_path: Path):
        """Test that whitespace-only match raises ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_rule
    match: "   "
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "match' cannot be empty" in str(e)

    def test_load_rules_fields_contains_empty_string(self, tmp_path: Path):
        """Test that fields with empty strings raise ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_fields
    match: "pattern"
    fields: [merchant_raw, ""]
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "fields' cannot contain empty" in str(e)

    def test_load_rules_tags_contains_empty_string(self, tmp_path: Path):
        """Test that tags with empty strings raise ValueError."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_tags
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1", ""]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "tags' cannot contain empty" in str(e)

    def test_load_rules_fields_contains_non_string(self, tmp_path: Path):
        """Test that all items in 'fields' must be strings."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_fields
    match: "pattern"
    fields: [merchant_raw, 123]
    tags: ["tag1"]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "all items in 'fields' must be strings" in str(e)

    def test_load_rules_tags_contains_non_string(self, tmp_path: Path):
        """Test that all items in 'tags' must be strings."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_tags
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1", 456]
    priority: 80
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "all items in 'tags' must be strings" in str(e)

    def test_load_rules_invalid_yaml_syntax(self, tmp_path: Path):
        """Test that invalid YAML raises ValueError with helpful message."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: bad_rule
    match: "pattern
    # Unclosed quote - invalid YAML
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "Invalid YAML syntax" in str(e)

    def test_load_rules_rules_not_list(self, tmp_path: Path):
        """Test that 'rules' must be a list."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules: "not_a_list"
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "'rules' must be a list" in str(e)

    def test_load_rules_rule_not_dict(self, tmp_path: Path):
        """Test that each rule must be a dictionary."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - "not a dict"
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            assert "must be a dictionary" in str(e)

    def test_load_rules_unknown_fields_warning(self, tmp_path: Path, caplog):
        """Test that unknown fields generate warning but don't fail."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: rule_with_extra
    match: "pattern"
    fields: [merchant_raw]
    tags: ["tag1"]
    priority: 80
    unknown_field: "value"
    another_unknown: 123
""",
            encoding="utf-8",
        )

        # Act
        import logging

        with caplog.at_level(logging.WARNING):
            rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 1  # Rule should still load
        assert rules[0].name == "rule_with_extra"
        # Check that warning was logged
        assert any("unknown fields" in record.message.lower() for record in caplog.records)

    def test_load_rules_valid_edge_cases(self, tmp_path: Path):
        """Test that valid edge cases work correctly."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: min_priority
    match: "A"
    fields: [merchant_raw]
    tags: ["a"]
    priority: 0
  - name: max_priority
    match: "B"
    fields: [merchant_raw]
    tags: ["b"]
    priority: 100
""",
            encoding="utf-8",
        )

        # Act
        rules = load_rules(rules_file)

        # Assert
        assert len(rules) == 2
        assert rules[0].priority == 100  # Sorted descending
        assert rules[1].priority == 0

    def test_load_rules_error_mentions_rule_index(self, tmp_path: Path):
        """Test that error message includes rule index for easier debugging."""
        # Arrange
        rules_file = tmp_path / "rules.yaml"
        rules_file.write_text(
            """
version: 1
rules:
  - name: good_rule1
    match: "A"
    fields: [merchant_raw]
    tags: ["a"]
    priority: 80
  - name: bad_rule
    match: "B"
    # Missing fields and tags
    priority: 90
  - name: good_rule2
    match: "C"
    fields: [merchant_raw]
    tags: ["c"]
    priority: 70
""",
            encoding="utf-8",
        )

        # Act & Assert
        try:
            load_rules(rules_file)
            assert False, "Expected ValueError"
        except ValueError as e:
            # Error should mention the index of the bad rule
            assert "index 1" in str(e) or "bad_rule" in str(e)
