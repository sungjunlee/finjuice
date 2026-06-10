"""Tests for CLI `rules test` dry-run command."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _write_rules(data_dir: Path) -> None:
    """Write a small rules.yaml file for rule-test scenarios."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "rules.yaml").write_text(
        """version: 1
rules:
  - name: llm_service
    match: "OPENAI|Anthropic"
    fields: [merchant_raw]
    tags: ["AI"]
    priority: 90

  - name: streaming_bundle
    match: "Netflix|Disney"
    fields: [merchant_raw]
    tags: ["streaming"]
    priority: 80
""",
        encoding="utf-8",
    )


def _write_transactions(data_dir: Path, *, month: str, rows: list[dict[str, object]]) -> None:
    """Write one Polars CSV partition for the requested month."""
    year, month_number = month.split("-")
    month_dir = data_dir / "transactions" / year / month_number
    month_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(month_dir / "transactions.csv")


@pytest.fixture
def rules_test_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with rules and two monthly partitions."""
    data_dir = tmp_path / "data"
    _write_rules(data_dir)
    _write_transactions(
        data_dir,
        month="2024-09",
        rows=[
            {
                "date": "2024-09-29",
                "time": "09:10",
                "merchant_raw": "OPENAI API",
                "amount": -18000.0,
                "account": "신한카드",
                "category_final": "디지털서비스",
                "tags_rule": json.dumps(["AI", "streaming"]),
                "tags_final": json.dumps(["AI", "streaming"]),
            },
        ],
    )
    _write_transactions(
        data_dir,
        month="2024-10",
        rows=[
            {
                "date": "2024-10-03",
                "time": "14:22",
                "merchant_raw": "OPENAI",
                "amount": -28000.0,
                "account": "신한카드",
                "category_final": "디지털서비스",
                "tags_rule": json.dumps(["AI", "streaming"]),
                "tags_final": json.dumps(["AI", "streaming"]),
            },
            {
                "date": "2024-10-04",
                "time": "09:15",
                "merchant_raw": "Anthropic",
                "amount": -19000.0,
                "account": "하나카드",
                "category_final": "디지털서비스",
                "tags_rule": json.dumps(["AI", "streaming"]),
                "tags_final": json.dumps(["AI", "streaming"]),
            },
            {
                "date": "2024-10-05",
                "time": "18:30",
                "merchant_raw": "Coupang",
                "amount": -33000.0,
                "account": "하나카드",
                "category_final": "쇼핑",
                "tags_rule": json.dumps(["shopping"]),
                "tags_final": json.dumps(["shopping"]),
            },
        ],
    )
    return data_dir


class TestRulesTestCommand:
    """Tests for `finjuice rules test`."""

    def test_rules_test_happy_path_default(self, rules_test_data_dir: Path) -> None:
        """Happy path shows the matched-row summary for a single rule."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(rules_test_data_dir),
                "rules",
                "test",
                "llm_service",
                "--month",
                "2024-10",
            ],
        )

        assert result.exit_code == 0
        assert "matched 2 of 3" in result.output

    def test_rules_test_json_schema(self, rules_test_data_dir: Path) -> None:
        """JSON output includes the expected top-level keys."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(rules_test_data_dir),
                "rules",
                "test",
                "llm_service",
                "--month",
                "2024-10",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["rule_name"] == "llm_service"
        assert payload["match_count"] == 2
        assert len(payload["sample"]) == 2
        assert "monthly_distribution" in payload
        assert "cross_tags_top" in payload

    def test_rules_test_limit(self, rules_test_data_dir: Path) -> None:
        """Sample rows respect --limit without changing the match count."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(rules_test_data_dir),
                "rules",
                "test",
                "llm_service",
                "--limit",
                "2",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["match_count"] == 3
        assert len(payload["sample"]) == 2

    def test_rules_test_month_filter(self, rules_test_data_dir: Path) -> None:
        """--month restricts the scan to one partition."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(rules_test_data_dir),
                "rules",
                "test",
                "llm_service",
                "--month",
                "2024-10",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["scope"]["month"] == "2024-10"
        assert payload["scope"]["total_rows_scanned"] == 3
        assert payload["match_count"] == 2
        assert payload["monthly_distribution"] == {"2024-10": 2}

    def test_rules_test_unknown_rule(self, rules_test_data_dir: Path) -> None:
        """Unknown rule names return a did-you-mean hint."""
        result = runner.invoke(
            app,
            ["--data-dir", str(rules_test_data_dir), "rules", "test", "llm_servicx"],
        )

        assert result.exit_code == 2
        assert "Rule not found" in result.output
        assert "Did you mean" in result.output
        assert "llm_service" in result.output

    def test_rules_test_cross_tags(self, rules_test_data_dir: Path) -> None:
        """Cross tags exclude the tested rule's own tags."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(rules_test_data_dir),
                "rules",
                "test",
                "llm_service",
                "--month",
                "2024-10",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["cross_tags_top"][0]["tag"] == "streaming"
        assert payload["cross_tags_top"][0]["count"] == 2
        assert all(item["tag"] != "AI" for item in payload["cross_tags_top"])

    def test_rules_test_mirrors_tagging_pipeline_projection(self, tmp_path: Path) -> None:
        """Rules referencing fields outside the pipeline projection match 0 rows.

        The real `finjuice tag` path projects only `merchant_raw`, `memo_raw`,
        `major_raw`, `minor_raw`, `type_norm`, `amount`, and `account` before
        rule evaluation. `rules test` must agree so users never see a phantom
        match that wouldn't fire during real tagging.
        """
        data_dir = tmp_path / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "rules.yaml").write_text(
            """version: 1
rules:
  - name: bad_field_rule
    match: "디지털서비스"
    fields: [category_final]
    tags: ["bogus"]
    priority: 90
""",
            encoding="utf-8",
        )
        _write_transactions(
            data_dir,
            month="2024-10",
            rows=[
                {
                    "date": "2024-10-03",
                    "time": "10:00",
                    "merchant_raw": "OPENAI",
                    "amount": -10000.0,
                    "account": "신한카드",
                    # category_final would match the rule pattern if the
                    # dry-run accepted it, but the real pipeline ignores the
                    # field, so match_count must be 0.
                    "category_final": "디지털서비스",
                    "tags_rule": json.dumps([]),
                    "tags_final": json.dumps([]),
                },
            ],
        )

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "test", "bad_field_rule", "--json"],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert payload["match_count"] == 0, payload

    def test_rules_test_cross_tags_excludes_ai_and_manual(self, tmp_path: Path) -> None:
        """`cross_tags_top` must read `tags_rule` only — AI/manual tags never leak in."""
        data_dir = tmp_path / "data"
        _write_rules(data_dir)
        _write_transactions(
            data_dir,
            month="2024-10",
            rows=[
                {
                    "date": "2024-10-03",
                    "time": "10:00",
                    "merchant_raw": "OPENAI",
                    "amount": -10000.0,
                    "account": "신한카드",
                    "category_final": "디지털서비스",
                    # Target rule tag ("AI") + one legacy rule tag ("streaming").
                    "tags_rule": json.dumps(["AI", "streaming"]),
                    # tags_final additionally carries AI-only and manual-only
                    # values that must NOT appear in cross_tags_top.
                    "tags_final": json.dumps(["AI", "streaming", "ai-suggested", "manual-review"]),
                    "tags_ai": json.dumps(["ai-suggested"]),
                    "tags_manual": json.dumps(["manual-review"]),
                },
            ],
        )

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(data_dir),
                "rules",
                "test",
                "llm_service",
                "--json",
            ],
        )

        assert result.exit_code == 0
        payload = json.loads(result.output)
        cross_tags = {item["tag"] for item in payload["cross_tags_top"]}
        assert "streaming" in cross_tags
        # AI tag and ai-only/manual-only tags must never be reported as legacy
        # rule overlap.
        assert "AI" not in cross_tags
        assert "ai-suggested" not in cross_tags
        assert "manual-review" not in cross_tags

    def test_rules_test_missing_rules_file(self, tmp_path: Path) -> None:
        """Missing rules.yaml returns RULES_FILE_NOT_FOUND, not RULE_NOT_FOUND."""
        data_dir = tmp_path / "data"
        _write_transactions(
            data_dir,
            month="2024-10",
            rows=[
                {
                    "date": "2024-10-01",
                    "time": "09:00",
                    "merchant_raw": "OPENAI",
                    "amount": -10000.0,
                    "account": "신한카드",
                    "category_final": "디지털서비스",
                    "tags_final": json.dumps([]),
                },
            ],
        )

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "test", "llm_service", "--json"],
        )

        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "RULES_FILE_NOT_FOUND"
        assert "Rules file not found" in payload["error"]["message"]

    def test_rules_test_invalid_month(self, rules_test_data_dir: Path) -> None:
        """Malformed --month emits INVALID_ARGS with exit code 2."""
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(rules_test_data_dir),
                "rules",
                "test",
                "llm_service",
                "--month",
                "2024/10",
                "--json",
            ],
        )

        assert result.exit_code == 2
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "INVALID_ARGS"

    def test_rules_test_no_data(self, tmp_path: Path) -> None:
        """Empty partitions surface NO_DATA (exit 4) without traceback."""
        data_dir = tmp_path / "data"
        _write_rules(data_dir)
        (data_dir / "transactions").mkdir(parents=True, exist_ok=True)

        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir), "rules", "test", "llm_service", "--json"],
        )

        assert result.exit_code == 4
        payload = json.loads(result.output)
        assert payload["error"]["code"] == "NO_DATA"
