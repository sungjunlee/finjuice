"""
Tests for finjuice rules export CLI command.

Tests cover:
- Basic invocation
- Different output formats (yaml, banksalad, markdown)
- File output
- No rules scenario
"""

import re
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


class TestExportRulesCommand:
    """Tests for rules export CLI command."""

    def test_no_rules_file(self, tmp_path: Path):
        """Shows error when rules.yaml doesn't exist."""
        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "export"])

        assert result.exit_code == 1
        assert "not found" in result.output.lower()

    def test_help_option(self):
        """Shows help text correctly."""
        result = runner.invoke(app, ["rules", "export", "--help"])

        assert result.exit_code == 0
        clean_output = strip_ansi(result.output)
        assert "Export tagging rules" in clean_output
        assert "--format" in clean_output
        assert "--output" in clean_output
        assert "--stats" in clean_output

    def test_empty_rules_file(self, tmp_path: Path):
        """Shows message when rules.yaml has no rules."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "export"])

        assert result.exit_code == 0
        assert "등록된 규칙이 없습니다" in result.output

    def test_yaml_format(self, tmp_path: Path):
        """Outputs raw YAML for --format yaml."""
        rules_path = tmp_path / "rules.yaml"
        rules_content = """version: 1
rules:
  - name: test_rule
    match: "테스트"
    fields: [merchant_raw]
    tags: ["테스트"]
    priority: 80
"""
        rules_path.write_text(rules_content, encoding="utf-8")

        result = runner.invoke(
            app, ["--data-dir", str(tmp_path), "rules", "export", "--format", "yaml"]
        )

        assert result.exit_code == 0
        assert "test_rule" in result.output
        assert "테스트" in result.output

    def test_banksalad_format(self, tmp_path: Path):
        """Outputs Banksalad guide for --format banksalad."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text(
            """version: 1
rules:
  - name: cafe_starbucks
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페", "커피"]
    priority: 80
""",
            encoding="utf-8",
        )

        result = runner.invoke(
            app, ["--data-dir", str(tmp_path), "rules", "export", "--format", "banksalad"]
        )

        assert result.exit_code == 0
        assert "뱅크샐러드 카테고리 매핑 가이드" in result.output
        assert "식비:카페" in result.output
        assert "스타벅스" in result.output

    def test_markdown_format(self, tmp_path: Path):
        """Outputs markdown table for --format markdown."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text(
            """version: 1
rules:
  - name: test_rule
    match: "테스트"
    fields: [merchant_raw]
    tags: ["테스트"]
    priority: 80
""",
            encoding="utf-8",
        )

        result = runner.invoke(
            app, ["--data-dir", str(tmp_path), "rules", "export", "--format", "markdown"]
        )

        assert result.exit_code == 0
        assert "| 규칙명 | 패턴 |" in result.output
        assert "| test_rule |" in result.output

    def test_unknown_format(self, tmp_path: Path):
        """Shows error for unknown format."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text(
            """version: 1
rules:
  - name: test_rule
    match: "테스트"
    fields: [merchant_raw]
    tags: ["테스트"]
    priority: 80
""",
            encoding="utf-8",
        )

        result = runner.invoke(
            app, ["--data-dir", str(tmp_path), "rules", "export", "--format", "json"]
        )

        assert result.exit_code == 1
        assert "Unknown format" in result.output

    def test_save_to_file(self, tmp_path: Path):
        """Saves output to file when --output specified."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text(
            """version: 1
rules:
  - name: test_rule
    match: "테스트"
    fields: [merchant_raw]
    tags: ["테스트"]
    priority: 80
""",
            encoding="utf-8",
        )
        output_file = tmp_path / "output.md"

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "rules",
                "export",
                "--format",
                "markdown",
                "-o",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert "저장되었습니다" in result.output
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "| 규칙명 |" in content

    def test_rule_count_in_output(self, tmp_path: Path):
        """Shows rule count in output."""
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text(
            """version: 1
rules:
  - name: rule1
    match: "패턴1"
    fields: [merchant_raw]
    tags: ["태그1"]
    priority: 80
  - name: rule2
    match: "패턴2"
    fields: [merchant_raw]
    tags: ["태그2"]
    priority: 80
""",
            encoding="utf-8",
        )

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "export"])

        assert result.exit_code == 0
        assert "2개의 규칙을 내보냅니다" in result.output
