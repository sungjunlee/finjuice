"""Tests for the `finjuice rules suggest` CLI command."""

import json
import re
from pathlib import Path
from unittest.mock import patch

import polars as pl
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _sample_suggestion(merchant: str = "Netflix") -> dict[str, object]:
    """Create a representative merchant context payload."""
    return {
        "merchant": merchant,
        "transaction_count": 3,
        "total_amount": 51000.0,
        "avg_amount": 17000.0,
        "amount_stddev": 0.0,
        "active_months": ["2024-10"],
        "is_recurring": True,
        "banksalad_category": {"major": "정기지출", "minor": "구독"},
        "payment_method": "신한카드",
        "time_patterns": {"weekday_pct": 0.67, "lunch_pct": 0.0},
        "similar_merchants": [
            {"merchant": "Disney+", "category": "구독", "avg_amount": 9900.0},
        ],
        "pattern": merchant,
        "sample_memos": ["Monthly plan"],
    }


def _read_audit_events(data_dir: Path) -> list[dict[str, object]]:
    """Read JSONL audit events from a test data directory."""
    audit_path = data_dir / ".execution_audit.jsonl"
    if not audit_path.exists():
        return []
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]


def _write_mixed_transfer_suggestion_data(data_dir: Path) -> None:
    """Write untagged rows where only non-transfer rows are suggestable."""
    month_dir = data_dir / "transactions" / "2024" / "10"
    month_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    rows = {
        "row_hash": ["netflix-1", "netflix-2", "transfer-1", "transfer-2"],
        "date": ["2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04"],
        "time": ["10:00", "10:00", "10:00", "10:00"],
        "type_raw": ["지출", "지출", "이체", "이체"],
        "type_norm": ["expense", "expense", "transfer", "transfer"],
        "major_raw": ["정기지출", "정기지출", "이체", "이체"],
        "minor_raw": ["구독", "구독", "내계좌이체", "내계좌이체"],
        "merchant_raw": ["Netflix", "Netflix", "Internal Transfer", "Internal Transfer"],
        "memo_raw": ["Monthly plan", "Monthly plan", "", ""],
        "amount": [-17_000.0, -17_000.0, -50_000.0, 50_000.0],
        "account": ["Card", "Card", "Checking", "Savings"],
        "currency": ["KRW"] * 4,
        "counterparty": ["", "", "", ""],
        "datetime": [
            "2024-10-01T10:00:00",
            "2024-10-02T10:00:00",
            "2024-10-03T10:00:00",
            "2024-10-04T10:00:00",
        ],
        "category_rule": ["", "", "", ""],
        "category_final": ["구독", "구독", "이체", "이체"],
        "tags_rule": ["[]", "[]", "[]", "[]"],
        "tags_ai": ["[]", "[]", "[]", "[]"],
        "tags_manual": ["[]", "[]", "[]", "[]"],
        "tags_final": ["[]", "[]", "[]", "[]"],
        "confidence": [None, None, None, None],
        "needs_review": [1, 1, 1, 1],
        "is_transfer": [0, 0, 1, 1],
        "transfer_group_id": ["", "", "transfer-a", "transfer-a"],
        "file_id": ["241001_1"] * 4,
        "source_row": [1, 2, 3, 4],
    }
    pl.DataFrame(rows).write_csv(month_dir / "transactions.csv")


def _write_korean_spacing_cluster_data(data_dir: Path) -> str:
    """Write spacing-variant merchants for read-only cluster suggestion tests."""
    month_dir = data_dir / "transactions" / "2024" / "10"
    month_dir.mkdir(parents=True, exist_ok=True)
    rules_content = "version: 1\nrules: []\n"
    (data_dir / "rules.yaml").write_text(rules_content, encoding="utf-8")

    rows = {
        "row_hash": ["cluster-1", "cluster-2"],
        "date": ["2024-10-01", "2024-10-02"],
        "time": ["10:00", "10:00"],
        "type_raw": ["지출", "지출"],
        "type_norm": ["expense", "expense"],
        "major_raw": ["식비", "식비"],
        "minor_raw": ["카페", "카페"],
        "merchant_raw": ["스타벅스", "스타 벅스"],
        "memo_raw": ["", ""],
        "amount": [-5000.0, -5100.0],
        "account": ["Card", "Card"],
        "currency": ["KRW", "KRW"],
        "counterparty": ["", ""],
        "datetime": ["2024-10-01T10:00:00", "2024-10-02T10:00:00"],
        "category_rule": ["", ""],
        "category_final": ["카페", "카페"],
        "tags_rule": ["[]", "[]"],
        "tags_ai": ["[]", "[]"],
        "tags_manual": ["[]", "[]"],
        "tags_final": ["[]", "[]"],
        "confidence": [None, None],
        "needs_review": [1, 1],
        "is_transfer": [0, 0],
        "transfer_group_id": ["", ""],
        "file_id": ["241001_1", "241001_1"],
        "source_row": [1, 2],
    }
    pl.DataFrame(rows).write_csv(month_dir / "transactions.csv")
    return rules_content


class TestSuggestRulesCommand:
    """Tests for rules suggest CLI command."""

    def test_no_data_directory(self, tmp_path: Path) -> None:
        """Shows an error when no transaction data exists."""
        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "suggest"])

        assert result.exit_code == 1
        assert "No transaction data found" in result.output or "not found" in result.output.lower()

    def test_help_option(self) -> None:
        """Shows help text for the updated context-based command."""
        result = runner.invoke(app, ["rules", "suggest", "--help"])

        assert result.exit_code == 0
        clean_output = strip_ansi(result.output)
        assert "Suggest rule patterns with rich merchant context" in clean_output
        assert "--top" in clean_output
        assert "--min-count" in clean_output
        assert "--output" in clean_output
        assert "--apply" in clean_output
        assert "--yes" in clean_output
        assert "--tag-after" in clean_output
        assert "--privacy" in clean_output

    def test_json_redacted_error_includes_privacy_metadata_without_data_path(
        self, tmp_path: Path
    ) -> None:
        """rules suggest redacted JSON errors should not expose local data paths."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "rules",
                "suggest",
                "--json",
                "--privacy",
                "redacted",
            ],
        )

        assert result.exit_code == 4, result.output
        payload = json.loads(result.output)
        message = payload["error"]["message"]
        assert payload["_meta"]["privacy"]["profile"] == "redacted"
        assert "No transaction data found" in message
        assert "[REDACTED_PATH]" in message
        assert str(tmp_path) not in message
        assert "transactions" not in message

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_json_redacted_privacy_masks_merchant_context_pii(
        self,
        mock_generate,
        mock_stats,
        tmp_path: Path,
    ) -> None:
        """rules suggest redacted JSON should keep structure without merchant PII."""
        (tmp_path / "transactions").mkdir(parents=True)
        suggestion = _sample_suggestion()
        suggestion["suggested_rule"] = {
            "name": "suggested_netflix",
            "match": "Netflix",
            "category": "구독",
            "tags": ["구독", "정기지출"],
            "priority": 85,
        }
        mock_stats.return_value = {
            "untagged_count": 3,
            "suggestable_untagged_count": 3,
            "suggestable_total_count": 3,
            "transfer_excluded_count": 0,
            "transfer_excluded_untagged_count": 0,
            "total_count": 4,
            "coverage_before_pct": 25.0,
            "suggestable_coverage_before_pct": 0.0,
        }
        mock_generate.return_value = [suggestion]

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "rules",
                "suggest",
                "--json",
                "--privacy",
                "redacted",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        serialized = json.dumps(payload, ensure_ascii=False)
        redacted = payload["suggestions"][0]
        assert payload["_meta"]["privacy"]["profile"] == "redacted"
        assert redacted["merchant"] == "[REDACTED]"
        assert redacted["total_amount"] is None
        assert redacted["avg_amount"] is None
        assert redacted["payment_method"] == "[REDACTED]"
        assert redacted["sample_memos"] == []
        assert redacted["suggested_rule"]["name"] == "[REDACTED]"
        assert redacted["suggested_rule"]["match"] == "[REDACTED]"
        assert "Netflix" not in serialized
        assert "Monthly plan" not in serialized
        assert "신한카드" not in serialized
        assert "51000" not in serialized

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_json_compact_privacy_omits_raw_suggestion_samples(
        self,
        mock_generate,
        mock_stats,
        tmp_path: Path,
    ) -> None:
        """rules suggest compact JSON should keep counts and workflow cues only."""
        (tmp_path / "transactions").mkdir(parents=True)
        suggestion = _sample_suggestion()
        suggestion["suggested_rule"] = {
            "name": "suggested_netflix",
            "match": "Netflix",
            "category": "구독",
            "tags": ["구독", "정기지출"],
            "priority": 85,
        }
        mock_stats.return_value = {
            "untagged_count": 3,
            "suggestable_untagged_count": 3,
            "suggestable_total_count": 3,
            "transfer_excluded_count": 0,
            "transfer_excluded_untagged_count": 0,
            "total_count": 4,
            "coverage_before_pct": 25.0,
            "suggestable_coverage_before_pct": 0.0,
        }
        mock_generate.return_value = [suggestion]

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "rules",
                "suggest",
                "--json",
                "--privacy",
                "compact",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        serialized = json.dumps(payload, ensure_ascii=False)
        assert payload["_meta"]["privacy"]["profile"] == "compact"
        assert payload["suggestion_count"] == 1
        assert payload["suggestions"] == [
            {
                "transaction_count": 3,
                "active_month_count": 1,
                "is_recurring": True,
                "banksalad_category": {"major": "정기지출", "minor": "구독"},
                "time_patterns": {"weekday_pct": 0.67, "lunch_pct": 0.0},
                "similar_merchant_count": 1,
                "merchant_kind": None,
                "ambiguous_reason": None,
                "default_action": None,
                "auto_apply_eligible": True,
                "suggested_rule": {
                    "category": "구독",
                    "tags": ["구독", "정기지출"],
                    "priority": 85,
                },
            }
        ]
        assert '"merchant":' not in serialized
        assert "amount" not in serialized
        assert "sample_memos" not in serialized
        assert "Netflix" not in serialized
        assert "Monthly plan" not in serialized

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    def test_all_tagged(self, mock_stats, tmp_path: Path) -> None:
        """Shows success message when all transactions are tagged."""
        (tmp_path / "transactions").mkdir(parents=True)
        mock_stats.return_value = {
            "untagged_count": 0,
            "total_count": 5,
            "coverage_before_pct": 100.0,
        }

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "suggest"])

        assert result.exit_code == 0
        assert "모든 거래가 태그되었습니다" in result.output

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_shows_context_table(self, mock_generate, mock_stats, tmp_path: Path) -> None:
        """Renders merchant context when untagged merchants exist."""
        (tmp_path / "transactions").mkdir(parents=True)
        mock_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate.return_value = [_sample_suggestion()]

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "suggest"])

        assert result.exit_code == 0
        clean_output = strip_ansi(result.output)
        assert "미태그 거래 분석" in clean_output
        assert "Merchant Context" in clean_output
        assert "Netflix" in clean_output
        assert "Monthly plan" in clean_output
        mock_generate.assert_called_once()

    @patch("finjuice.pipeline.tagging.suggestions.format_suggestions_report")
    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_save_to_file(
        self,
        mock_generate,
        mock_stats,
        mock_format,
        tmp_path: Path,
    ) -> None:
        """Saves the merchant context report to a file."""
        (tmp_path / "transactions").mkdir(parents=True)
        mock_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate.return_value = [_sample_suggestion()]
        mock_format.return_value = "context report"
        output_file = tmp_path / "output.txt"

        result = runner.invoke(
            app,
            ["--data-dir", str(tmp_path), "rules", "suggest", "-o", str(output_file)],
        )

        assert result.exit_code == 0
        assert "저장되었습니다" in result.output
        assert output_file.exists()
        assert output_file.read_text() == "context report"

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_top_n_option(self, mock_generate, mock_stats, tmp_path: Path) -> None:
        """Passes `--top` through to the merchant context generator."""
        (tmp_path / "transactions").mkdir(parents=True)
        mock_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate.return_value = [_sample_suggestion()]

        result = runner.invoke(
            app,
            ["--data-dir", str(tmp_path), "rules", "suggest", "--top", "20"],
        )

        assert result.exit_code == 0
        assert mock_generate.call_args.kwargs["top_n"] == 20

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_min_count_option(self, mock_generate, mock_stats, tmp_path: Path) -> None:
        """Passes `--min-count` through to the merchant context generator."""
        (tmp_path / "transactions").mkdir(parents=True)
        mock_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate.return_value = [_sample_suggestion()]

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "suggest", "-m", "5"])

        assert result.exit_code == 0
        assert mock_generate.call_args.kwargs["min_count"] == 5

    @patch("finjuice.pipeline.cli.commands.rules.sys.stdin.isatty", return_value=False)
    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_apply_requires_interactive_tty(
        self,
        mock_generate,
        mock_stats,
        _mock_isatty,
        tmp_path: Path,
    ) -> None:
        """`--apply` without `--yes` should fail in non-interactive mode."""
        (tmp_path / "transactions").mkdir(parents=True)
        mock_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate.return_value = [_sample_suggestion()]

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "suggest", "--apply"])

        assert result.exit_code == 1
        assert "non-interactive" in result.output or "interactive" in result.output.lower()
        assert "--apply --yes" in result.output

    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_apply_without_suggestions(self, mock_generate, mock_stats, tmp_path: Path) -> None:
        """Shows the empty-state message when there are no suggestion candidates."""
        (tmp_path / "transactions").mkdir(parents=True)
        mock_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate.return_value = []

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "suggest", "--apply"])

        assert result.exit_code == 0
        assert "제안" in result.output and "없습니다" in result.output

    @patch("finjuice.pipeline.tagging.pipeline.run_tagging")
    @patch("finjuice.pipeline.tagging.suggestions.apply_suggestion_to_rules")
    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_yes_applies_all_suggestions(
        self,
        mock_generate,
        mock_stats,
        mock_apply,
        mock_run_tagging,
        tmp_path: Path,
    ) -> None:
        """`--apply --yes` applies all suggestions without prompting."""
        from finjuice.pipeline.tagging.models import TagRule

        (tmp_path / "transactions").mkdir(parents=True)
        (tmp_path / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
        mock_stats.return_value = {
            "untagged_count": 2,
            "total_count": 4,
            "coverage_before_pct": 50.0,
        }
        mock_generate.return_value = [
            _sample_suggestion("Merchant1"),
            _sample_suggestion("Merchant2"),
        ]
        mock_apply.return_value = TagRule(
            name="test",
            match="test",
            fields=["merchant_raw"],
            tags=["test"],
            priority=80,
        )
        mock_run_tagging.return_value = {"coverage_pct": 80.0}

        result = runner.invoke(
            app,
            ["--data-dir", str(tmp_path), "rules", "suggest", "--apply", "--yes"],
        )

        assert result.exit_code == 0
        assert mock_apply.call_count == 2
        assert "적용" in result.output

        events = _read_audit_events(tmp_path)
        assert len(events) == 2
        assert {event["command"] for event in events} == {"rules suggest"}
        assert {event["action"] for event in events} == {"applied"}
        assert {event["rule_name"] for event in events} == {"test"}
        assert {tuple(event["fields_changed"]) for event in events} == {("rule",)}
        assert {event["change_summary"] for event in events} == {"suggestion rule applied"}
        assert all(event["success"] is True for event in events)
        rendered_events = json.dumps(events, ensure_ascii=False)
        assert "Merchant1" not in rendered_events
        assert "Merchant2" not in rendered_events
        assert "51000" not in rendered_events

    @patch("finjuice.pipeline.tagging.suggestions.apply_suggestion_to_rules")
    @patch("finjuice.pipeline.tagging.suggestions.get_suggestion_coverage_stats")
    @patch("finjuice.pipeline.tagging.suggestions.generate_merchant_context")
    def test_no_tag_after_skips_retagging(
        self,
        mock_generate,
        mock_stats,
        mock_apply,
        tmp_path: Path,
    ) -> None:
        """`--no-tag-after` skips retagging after applying rules."""
        from finjuice.pipeline.tagging.models import TagRule

        (tmp_path / "transactions").mkdir(parents=True)
        (tmp_path / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
        mock_stats.return_value = {
            "untagged_count": 1,
            "total_count": 4,
            "coverage_before_pct": 75.0,
        }
        mock_generate.return_value = [_sample_suggestion("Merchant1")]
        mock_apply.return_value = TagRule(
            name="test",
            match="test",
            fields=["merchant_raw"],
            tags=["test"],
            priority=80,
        )

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "rules",
                "suggest",
                "--apply",
                "--yes",
                "--no-tag-after",
            ],
        )

        assert result.exit_code == 0
        assert mock_apply.call_count == 1
        assert "커버리지 변화" not in result.output

    def test_json_counts_suggestable_untagged_after_transfer_exclusions(
        self,
        tmp_path: Path,
    ) -> None:
        """rules suggest --json should explain transfer-excluded untagged rows."""
        data_dir = tmp_path / "data"
        _write_mixed_transfer_suggestion_data(data_dir)

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "suggest",
                "--json",
                "--top",
                "5",
                "--min-count",
                "2",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["untagged_count"] == 4
        assert payload["suggestable_untagged_count"] == 2
        assert payload["total_count"] == 4
        assert payload["suggestable_total_count"] == 2
        assert payload["transfer_exclusions"]["excluded_count"] == 2
        assert payload["transfer_exclusions"]["excluded_untagged_count"] == 2
        assert [suggestion["merchant"] for suggestion in payload["suggestions"]] == ["Netflix"]

    def test_json_includes_fuzzy_merchant_cluster_without_mutating_rules(
        self,
        tmp_path: Path,
    ) -> None:
        """rules suggest --json should surface clusters without writing rules.yaml."""
        data_dir = tmp_path / "data"
        original_rules = _write_korean_spacing_cluster_data(data_dir)

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "suggest",
                "--json",
                "--top",
                "2",
                "--min-count",
                "1",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert (data_dir / "rules.yaml").read_text(encoding="utf-8") == original_rules
        assert {suggestion["merchant"] for suggestion in payload["suggestions"]} == {
            "스타벅스",
            "스타 벅스",
        }
        for suggestion in payload["suggestions"]:
            cluster = suggestion["merchant_cluster"]
            assert cluster["reason"] == "normalized_merchant_match"
            assert cluster["confidence"] == 1.0
