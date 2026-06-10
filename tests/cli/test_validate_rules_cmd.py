"""
Tests for CLI rules validate command.

Tests:
- finjuice rules validate: Validate tagging rules for conflicts
- Duplicate name detection
- Priority conflict detection
- Invalid regex detection
- Rules file not found handling
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


@pytest.fixture
def data_dir_with_valid_rules(tmp_path: Path) -> Path:
    """Create data directory with valid rules.yaml."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    rules_file = data_dir / "rules.yaml"
    rules_file.write_text("""version: 1
rules:
  - name: cafe_starbucks
    match: "스타벅스|STARBUCKS"
    fields: [merchant_raw]
    tags: ["카페", "커피"]
    priority: 85

  - name: convenience_gs25
    match: "GS25|GS리테일"
    fields: [merchant_raw]
    tags: ["편의점", "생활용품"]
    priority: 75

  - name: hospital_general
    match: "종합병원|대학병원"
    fields: [merchant_raw, minor_raw]
    tags: ["의료", "종합병원"]
    priority: 90
""")

    return data_dir


@pytest.fixture
def data_dir_with_duplicate_names(tmp_path: Path) -> Path:
    """Create data directory with duplicate rule names."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    rules_file = data_dir / "rules.yaml"
    rules_file.write_text("""version: 1
rules:
  - name: cafe
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 85

  - name: cafe
    match: "투썸플레이스"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 85
""")

    return data_dir


@pytest.fixture
def data_dir_with_invalid_regex(tmp_path: Path) -> Path:
    """Create data directory with invalid regex pattern."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    rules_file = data_dir / "rules.yaml"
    rules_file.write_text("""version: 1
rules:
  - name: invalid_pattern
    match: "[unclosed"
    fields: [merchant_raw]
    tags: ["test"]
    priority: 80
""")

    return data_dir


@pytest.fixture
def data_dir_with_priority_conflicts(tmp_path: Path) -> Path:
    """Create data directory with priority conflicts."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    rules_file = data_dir / "rules.yaml"
    rules_file.write_text("""version: 1
rules:
  - name: broad_pattern
    match: "병원"
    fields: [merchant_raw]
    tags: ["의료"]
    priority: 90

  - name: specific_pattern
    match: "종합병원"
    fields: [merchant_raw]
    tags: ["의료", "종합병원"]
    priority: 85
""")

    return data_dir


@pytest.fixture
def data_dir_with_multiple_invalid_rules(tmp_path: Path) -> Path:
    """Create data directory with multiple malformed rules for collection tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    rules_file = data_dir / "rules.yaml"
    rules_file.write_text("""version: 1
rules:
  - name: invalid_operator
    conditions:
      - field: merchant_raw
        op: startswith
        value: "스타벅스"
    tags: ["카페"]

  - name: missing_tags
    match: "보험"
    fields: [merchant_raw]
""")

    return data_dir


class TestValidateRulesCommand:
    """Tests for finjuice rules validate command."""

    def test_validate_rules_success(self, data_dir_with_valid_rules: Path) -> None:
        """Test validation with valid rules passes."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_valid_rules), "rules", "validate"],
        )

        assert result.exit_code == 0
        assert "✅" in result.output
        assert "모든 규칙 검증 통과" in result.output or "통과" in result.output

    def test_validate_rules_shows_rule_count(self, data_dir_with_valid_rules: Path) -> None:
        """Test that validation shows number of rules checked."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_valid_rules), "rules", "validate"],
        )

        assert result.exit_code == 0
        # Should show "3개 규칙" or similar
        assert "규칙" in result.output

    def test_validate_rules_duplicate_names(self, data_dir_with_duplicate_names: Path) -> None:
        """Test validation detects duplicate rule names."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_duplicate_names), "rules", "validate"],
        )

        assert result.exit_code == 1  # Should fail
        assert "❌" in result.output
        assert "cafe" in result.output.lower()  # Rule name should appear

    def test_validate_rules_invalid_regex(self, data_dir_with_invalid_regex: Path) -> None:
        """Test validation detects invalid regex patterns."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_invalid_regex), "rules", "validate"],
        )

        # Invalid regex is reported but may be warning, not error
        # Just check that it's detected in output
        assert (
            "❌" in result.output
            or "⚠️" in result.output
            or "오류" in result.output
            or "경고" in result.output
        )

    def test_validate_rules_priority_conflicts(
        self, data_dir_with_priority_conflicts: Path
    ) -> None:
        """Test validation detects priority inversions."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_priority_conflicts), "rules", "validate"],
        )

        # Priority conflicts are warnings, not errors
        # So exit code should be 0, but warnings should be shown
        assert "⚠️" in result.output or "경고" in result.output

    def test_validate_rules_no_rules_file(self, tmp_path: Path) -> None:
        """Test validation when rules.yaml doesn't exist."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "validate"],
        )

        assert result.exit_code == 2  # USAGE_ERROR (missing rules file)
        assert "not found" in result.output.lower() or "찾을 수 없습니다" in result.output

    def test_validate_rules_empty_rules(self, tmp_path: Path) -> None:
        """Test validation with empty rules file."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)

        rules_file = data_dir / "rules.yaml"
        rules_file.write_text("""version: 1
rules: []
""")

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "validate"],
        )

        assert result.exit_code == 0  # Empty is okay
        assert "No rules" in result.output or "규칙" in result.output

    def test_validate_rules_malformed_yaml(self, tmp_path: Path) -> None:
        """Test validation with malformed YAML."""
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)

        rules_file = data_dir / "rules.yaml"
        rules_file.write_text("""version: 1
rules:
  - name: test
    match: "test"
      invalid_indent: true
""")

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "validate"],
        )

        assert result.exit_code == 3  # VALIDATION_ERROR (malformed YAML)
        assert "❌" in result.output or "Failed to load" in result.output

    def test_validate_rules_shows_summary_table(self, data_dir_with_valid_rules: Path) -> None:
        """Test that validation shows summary table."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_valid_rules), "rules", "validate"],
        )

        assert result.exit_code == 0
        # Summary should show total rules, errors, warnings, passed
        assert "총 규칙" in result.output or "Total" in result.output
        assert "통과" in result.output or "Passed" in result.output

    def test_validate_rules_errors_and_warnings_combined(self, tmp_path: Path) -> None:
        """Test validation shows both errors and warnings when present."""
        # Create rules with both duplicate names (error) and priority inversions (warning)
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)

        rules_file = data_dir / "rules.yaml"
        rules_file.write_text("""version: 1
rules:
  - name: duplicate
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 85

  - name: duplicate
    match: "투썸"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 85

  - name: broad_pattern
    match: "병원"
    fields: [merchant_raw]
    tags: ["의료"]
    priority: 90

  - name: specific_pattern
    match: "종합병원"
    fields: [merchant_raw]
    tags: ["의료", "종합병원"]
    priority: 85
""")

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "validate"],
        )

        # Should show both errors and warnings
        assert "❌" in result.output  # Errors
        assert "⚠️" in result.output  # Warnings
        assert result.exit_code == 1  # Fails due to errors

    def test_validate_rules_info_with_errors(self, tmp_path: Path) -> None:
        """Test validation shows info issues alongside errors."""
        # Create rules with duplicate names (error) and invalid regex (info)
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True)

        rules_file = data_dir / "rules.yaml"
        rules_file.write_text("""version: 1
rules:
  - name: duplicate
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 85

  - name: duplicate
    match: "투썸"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 85

  - name: invalid_pattern
    match: "[unclosed"
    fields: [merchant_raw]
    tags: ["test"]
    priority: 80
""")

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "validate"],
        )

        # Should show errors and info
        assert "❌" in result.output  # Errors
        assert "ℹ️" in result.output or "정보" in result.output  # Info
        assert result.exit_code == 1  # Fails due to errors

    def test_validate_collects_multiple_errors(
        self, data_dir_with_multiple_invalid_rules: Path
    ) -> None:
        """Default validate should report every malformed rule in one pass."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_multiple_invalid_rules), "rules", "validate"],
        )

        assert result.exit_code == 1
        assert "invalid_operator" in result.output
        assert "missing_tags" in result.output
        assert "Did you mean: 'starts_with'?" in result.output

    def test_validate_strict_flag_stops_at_first(
        self, data_dir_with_multiple_invalid_rules: Path
    ) -> None:
        """Strict mode should preserve the old fail-fast behavior."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir_with_multiple_invalid_rules),
                "rules",
                "validate",
                "--strict",
            ],
        )

        assert result.exit_code == 3
        assert "Failed to load rules" in result.output
        assert "invalid_operator" in result.output
        assert "missing_tags" not in result.output

    def test_validate_json_structured_errors(
        self, data_dir_with_multiple_invalid_rules: Path
    ) -> None:
        """JSON output should expose collected rule-load errors as structured arrays."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir_with_multiple_invalid_rules),
                "rules",
                "validate",
                "--json",
            ],
        )

        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["status"] == "issues"
        assert payload["total_rules"] == 2
        assert payload["errors"] == 2
        assert payload["warnings"] == 0
        problems = payload["problems"]
        error_problems = [p for p in problems if p["severity"] == "error"]
        assert len(error_problems) == 2
        assert error_problems[0]["rule_index"] == 0
        assert error_problems[0]["rule_name"] == "invalid_operator"
        assert error_problems[0]["suggestion"] == "Did you mean: 'starts_with'?"
        assert error_problems[1]["rule_name"] == "missing_tags"
