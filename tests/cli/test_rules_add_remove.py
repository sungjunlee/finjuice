"""Tests for CLI rules add/remove commands."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.tagging.rules import load_rules

runner = CliRunner()


def _write_rules(data_dir: Path, content: str) -> Path:
    """Write rules.yaml into a test data directory."""
    data_dir.mkdir(parents=True, exist_ok=True)
    rules_file = data_dir / "rules.yaml"
    rules_file.write_text(content, encoding="utf-8")
    return rules_file


def _write_transactions(data_dir: Path) -> None:
    """Write a minimal CSV partition compatible with DuckDBAnalytics."""
    month_dir = data_dir / "transactions" / "2024" / "10"
    month_dir.mkdir(parents=True, exist_ok=True)

    df = pl.DataFrame(
        {
            "date": ["2024-10-01", "2024-10-02", "2024-10-03"],
            "time": ["08:30", "12:00", "18:15"],
            "merchant_raw": ["Netflix", "Netflix Korea", "Coupang"],
            "amount": [-15000, -13000, -30000],
            "memo_raw": ["Subscription", "Monthly plan", "Shopping"],
            "major_raw": ["Living", "Living", "Shopping"],
            "minor_raw": ["Sub", "Sub", "Online"],
            "type_norm": ["expense", "expense", "expense"],
            "is_transfer": [0, 0, 0],
            "tags_final": [json.dumps([]), json.dumps(["streaming"]), json.dumps(["shopping"])],
            "category_final": ["Entertainment", "Entertainment", "Shopping"],
            "account": ["Card A", "Card A", "Card B"],
        }
    )
    df.write_csv(month_dir / "transactions.csv")


def _read_audit_events(data_dir: Path) -> list[dict[str, object]]:
    """Read JSONL audit events from a test data directory."""
    audit_path = data_dir / ".execution_audit.jsonl"
    if not audit_path.exists():
        return []
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]


class TestRulesAddRemoveCommand:
    """Tests for `finjuice rules add/remove`."""

    def test_add_rule_basic(self, tmp_path: Path) -> None:
        """Add creates a new rules.yaml entry."""
        data_dir = tmp_path / "data"

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "netflix_streaming",
                "--match",
                "Netflix",
                "--tags",
                "streaming",
            ],
        )

        assert result.exit_code == 0
        rules = load_rules(data_dir / "rules.yaml")
        assert len(rules) == 1
        assert rules[0].name == "netflix_streaming"
        assert rules[0].match == "Netflix"
        assert rules[0].fields == ["merchant_raw"]
        assert rules[0].tags == ["streaming"]
        assert rules[0].priority == 50

    def test_add_rule_appends_privacy_safe_audit_event(self, tmp_path: Path) -> None:
        """Successful rules add should append only stable rule identifiers."""
        data_dir = tmp_path / "data"

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "netflix_streaming",
                "--match",
                "Netflix",
                "--tags",
                "paid_media",
            ],
        )

        assert result.exit_code == 0, result.output
        events = _read_audit_events(data_dir)
        assert events == [
            {
                "event": "financial_mutation",
                "command": "rules add",
                "action": "added",
                "rule_name": "netflix_streaming",
                "fields_changed": ["rule"],
                "change_summary": "rule added",
                "success": True,
                "timestamp": events[0]["timestamp"],
            }
        ]
        assert "Netflix" not in json.dumps(events, ensure_ascii=False)
        assert "paid_media" not in json.dumps(events, ensure_ascii=False)

    def test_add_rule_with_all_options(self, tmp_path: Path) -> None:
        """Add respects category, priority, and custom field list."""
        data_dir = tmp_path / "data"
        _write_rules(data_dir, "version: 1\nrules: []\n")

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "monthly_subscription",
                "--match",
                "Netflix|Subscription",
                "--tags",
                "streaming,subscription",
                "--category",
                "구독",
                "--priority",
                "88",
                "--fields",
                "merchant_raw,memo_raw",
            ],
        )

        assert result.exit_code == 0
        rules = load_rules(data_dir / "rules.yaml")
        assert len(rules) == 1
        assert rules[0].name == "monthly_subscription"
        assert rules[0].fields == ["merchant_raw", "memo_raw"]
        assert rules[0].tags == ["streaming", "subscription"]
        assert rules[0].category == "구독"
        assert rules[0].priority == 88

    def test_add_rule_dry_run(self, tmp_path: Path) -> None:
        """Dry-run returns impact stats and does not write rules.yaml."""
        data_dir = tmp_path / "data"
        _write_transactions(data_dir)

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "netflix_preview",
                "--match",
                "Netflix",
                "--tags",
                "streaming",
                "--dry-run",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "rules add"
        assert payload["action"] == "added"
        assert payload["dry_run"] is True
        assert payload["dry_run_action"] == "added"
        assert payload["preview_action"] == "would_add"
        assert payload["rules_file_modified"] is False
        assert payload["impact"]["matched_transactions"] == 2
        assert payload["impact"]["total_amount"] == -28000.0
        assert "total_matches" not in payload["impact"]
        assert payload["coverage_after"] == pytest.approx(100.0)
        assert not (data_dir / "rules.yaml").exists()
        assert _read_audit_events(data_dir) == []

    def test_add_rule_allows_unicode_name(self, tmp_path: Path) -> None:
        """Unicode rule names should be accepted for rules suggest compatibility."""
        data_dir = tmp_path / "data"

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "suggested_스타벅스_강남점",
                "--match",
                "스타벅스",
                "--tags",
                "카페,커피",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["rule"]["name"] == "suggested_스타벅스_강남점"

        rules = load_rules(data_dir / "rules.yaml")
        assert [rule.name for rule in rules] == ["suggested_스타벅스_강남점"]

    def test_add_rule_duplicate_name_updates(self, tmp_path: Path) -> None:
        """Adding an existing name updates it instead of duplicating."""
        data_dir = tmp_path / "data"
        _write_rules(
            data_dir,
            """version: 1
rules:
  - name: netflix_streaming
    match: "Netflix"
    fields: [merchant_raw]
    tags: ["streaming"]
    priority: 50
""",
        )

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "netflix_streaming",
                "--match",
                "Netflix|Subscription",
                "--tags",
                "streaming,subscription",
                "--priority",
                "72",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["action"] == "updated"

        rules = load_rules(data_dir / "rules.yaml")
        assert len([rule for rule in rules if rule.name == "netflix_streaming"]) == 1
        assert rules[0].match == "Netflix|Subscription"
        assert rules[0].tags == ["streaming", "subscription"]
        assert rules[0].priority == 72

    def test_add_rule_invalid_regex(self, tmp_path: Path) -> None:
        """Invalid regex input returns a structured JSON error."""
        data_dir = tmp_path / "data"

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "broken_regex",
                "--match",
                "[unclosed",
                "--tags",
                "test",
                "--json",
            ],
        )

        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "rules add"
        assert payload["error"]["code"] == "INVALID_ARGS"
        assert "Invalid regex pattern" in payload["error"]["message"]
        assert payload["error"]["suggestion"] == "finjuice rules add --help"

    def test_add_rule_invalid_priority(self, tmp_path: Path) -> None:
        """Out-of-range priority returns a structured JSON error."""
        data_dir = tmp_path / "data"

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "bad_priority",
                "--match",
                "Netflix",
                "--tags",
                "streaming",
                "--priority",
                "101",
                "--json",
            ],
        )

        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "rules add"
        assert payload["error"]["code"] == "INVALID_ARGS"
        assert "Priority must be 0-100" in payload["error"]["message"]

    def test_add_rule_preserves_comments(self, tmp_path: Path) -> None:
        """Round-trip add preserves existing YAML comments."""
        data_dir = tmp_path / "data"
        rules_file = _write_rules(
            data_dir,
            """# Top-level comment
version: 1
rules:
  # Existing rule comment
  - name: coffee
    match: "Starbucks"  # inline comment
    fields: [merchant_raw]
    tags: ["cafe"]
    priority: 80
""",
        )

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "netflix_streaming",
                "--match",
                "Netflix",
                "--tags",
                "streaming",
            ],
        )

        assert result.exit_code == 0
        content = rules_file.read_text(encoding="utf-8")
        assert "# Top-level comment" in content
        assert "# Existing rule comment" in content
        assert "# inline comment" in content
        assert "name: netflix_streaming" in content

    def test_update_rule_preserves_comments_on_unchanged_fields(self, tmp_path: Path) -> None:
        """Updating a rule should keep comments attached to unchanged fields."""
        data_dir = tmp_path / "data"
        rules_file = _write_rules(
            data_dir,
            """version: 1
rules:
  - name: netflix_streaming  # name comment
    match: "Netflix"
    fields: [merchant_raw]  # fields comment
    tags: ["streaming"]
    priority: 50  # priority comment
""",
        )

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "netflix_streaming",
                "--match",
                "Netflix|Subscription",
                "--tags",
                "streaming,subscription",
                "--priority",
                "50",
            ],
        )

        assert result.exit_code == 0
        content = rules_file.read_text(encoding="utf-8")
        assert "# name comment" in content
        assert "# fields comment" in content
        assert "# priority comment" in content
        assert "Netflix|Subscription" in content

        rules = load_rules(rules_file)
        assert rules[0].match == "Netflix|Subscription"
        assert rules[0].tags == ["streaming", "subscription"]

    def test_remove_rule_basic(self, tmp_path: Path) -> None:
        """Remove deletes the named rule."""
        data_dir = tmp_path / "data"
        _write_rules(
            data_dir,
            """version: 1
rules:
  - name: coffee
    match: "Starbucks"
    fields: [merchant_raw]
    tags: ["cafe"]
    priority: 80
  - name: streaming
    match: "Netflix"
    fields: [merchant_raw]
    tags: ["streaming"]
    priority: 70
""",
        )

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "remove",
                "--name",
                "coffee",
            ],
        )

        assert result.exit_code == 0
        rules = load_rules(data_dir / "rules.yaml")
        assert [rule.name for rule in rules] == ["streaming"]

        events = _read_audit_events(data_dir)
        assert len(events) == 1
        assert events[0]["event"] == "financial_mutation"
        assert events[0]["command"] == "rules remove"
        assert events[0]["action"] == "removed"
        assert events[0]["rule_name"] == "coffee"
        assert events[0]["fields_changed"] == ["rule"]
        assert events[0]["change_summary"] == "rule removed"
        assert events[0]["success"] is True
        assert "Starbucks" not in json.dumps(events, ensure_ascii=False)
        assert "cafe" not in json.dumps(events, ensure_ascii=False)

    def test_remove_rule_not_found(self, tmp_path: Path) -> None:
        """Removing a missing rule returns a structured JSON error."""
        data_dir = tmp_path / "data"
        _write_rules(data_dir, "version: 1\nrules: []\n")

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "remove",
                "--name",
                "missing_rule",
                "--json",
            ],
        )

        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "rules remove"
        assert payload["error"]["code"] == "RULE_NOT_FOUND"
        assert "Rule not found: missing_rule" in payload["error"]["message"]
        assert _read_audit_events(data_dir) == []

    def test_add_and_remove_json_output(self, tmp_path: Path) -> None:
        """Both add and remove emit `_meta`-wrapped JSON payloads."""
        data_dir = tmp_path / "data"

        add_result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "json_rule",
                "--match",
                "JSON_RULE",
                "--tags",
                "test",
                "--json",
            ],
        )
        remove_result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "remove",
                "--name",
                "json_rule",
                "--json",
            ],
        )

        assert add_result.exit_code == 0
        assert remove_result.exit_code == 0

        add_payload = json.loads(add_result.output)
        remove_payload = json.loads(remove_result.output)
        assert add_payload["_meta"]["command"] == "rules add"
        assert add_payload["action"] == "added"
        assert remove_payload["_meta"]["command"] == "rules remove"
        assert remove_payload["action"] == "removed"

    def test_add_rule_validation_on_write(self, tmp_path: Path) -> None:
        """Validation warnings are included when the new rule overlaps existing ones."""
        data_dir = tmp_path / "data"
        _write_rules(
            data_dir,
            """version: 1
rules:
  - name: coffee_general
    match: "Star"
    fields: [merchant_raw]
    tags: ["cafe"]
    priority: 90
""",
        )

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "add",
                "--name",
                "coffee_specific",
                "--match",
                "Starbucks",
                "--tags",
                "cafe,coffee",
                "--priority",
                "80",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["validation"]["warnings"] >= 1
        problem_types = {problem["type"] for problem in payload["validation"]["problems"]}
        assert "pattern_overlap" in problem_types or "priority_inversion" in problem_types
