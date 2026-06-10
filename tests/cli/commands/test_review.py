"""Tests for the review CLI command."""

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import review as review_module
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ErrorCode, ExitCode
from tests.conftest import cli_text

runner = CliRunner()


def _write_partition(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write a month partition for review command tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "transactions" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "transactions.csv")


@pytest.fixture
def review_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with multi-month transaction fixtures."""
    data_dir = tmp_path / "review-data"
    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    _write_partition(
        data_dir,
        "2025-10",
        [
            {
                "row_hash": "oct-old-untagged",
                "date": "2025-10-01",
                "time": "09:00",
                "datetime": "2025-10-01T09:00:00",
                "merchant_raw": "Old Untagged",
                "amount": -12000.0,
                "category_final": "생활",
                "tags_final": "[]",
                "confidence": 0.8,
                "needs_review": 0,
            },
            {
                "row_hash": "oct-old-tagged",
                "date": "2025-10-02",
                "time": "10:00",
                "datetime": "2025-10-02T10:00:00",
                "merchant_raw": "Old Tagged",
                "amount": -32000.0,
                "category_final": "쇼핑",
                "tags_final": '["쇼핑"]',
                "confidence": 0.95,
                "needs_review": 0,
            },
        ],
    )

    _write_partition(
        data_dir,
        "2025-11",
        [
            {
                "row_hash": "nov-needs-review-flag",
                "date": "2025-11-10",
                "time": "09:00",
                "datetime": "2025-11-10T09:00:00",
                "merchant_raw": "Needs Review Flag",
                "amount": -11000.0,
                "category_final": "식비",
                "tags_final": '["식비"]',
                "confidence": 0.95,
                "needs_review": 1,
            },
            {
                "row_hash": "nov-untagged-cafe",
                "date": "2025-11-11",
                "time": "10:00",
                "datetime": "2025-11-11T10:00:00",
                "merchant_raw": "Untagged Cafe",
                "amount": -5500.0,
                "category_final": "카페",
                "tags_final": "[]",
                "confidence": 0.6,
                "needs_review": 0,
            },
            {
                "row_hash": "nov-low-confidence-tagged",
                "date": "2025-11-12",
                "time": "11:00",
                "datetime": "2025-11-12T11:00:00",
                "merchant_raw": "Low Confidence Tagged",
                "amount": -19000.0,
                "category_final": "구독",
                "tags_final": '["구독"]',
                "confidence": 0.65,
                "needs_review": 0,
            },
            {
                "row_hash": "nov-threshold-specific-low-confidence",
                "date": "2025-11-12",
                "time": "11:30",
                "datetime": "2025-11-12T11:30:00",
                "merchant_raw": "Threshold Specific Low Confidence",
                "amount": -21000.0,
                "category_final": "문화",
                "tags_final": '["문화"]',
                "confidence": 0.75,
                "needs_review": 0,
            },
            {
                "row_hash": "nov-unclassified-tagged",
                "date": "2025-11-13",
                "time": "12:00",
                "datetime": "2025-11-13T12:00:00",
                "merchant_raw": "Unclassified Tagged",
                "amount": -27000.0,
                "category_final": "미분류",
                "tags_final": '["기타"]',
                "confidence": 0.8,
                "needs_review": 0,
            },
            {
                "row_hash": "nov-normal-tagged",
                "date": "2025-11-14",
                "time": "13:00",
                "datetime": "2025-11-14T13:00:00",
                "merchant_raw": "Normal Tagged",
                "amount": -43000.0,
                "category_final": "교통",
                "tags_final": '["교통"]',
                "confidence": 0.9,
                "needs_review": 0,
            },
            {
                "row_hash": "nov-null-confidence",
                "date": "2025-11-15",
                "time": "14:00",
                "datetime": "2025-11-15T14:00:00",
                "merchant_raw": "Null Confidence",
                "amount": -8000.0,
                "category_final": "기타",
                "tags_final": '["기타"]',
                "confidence": None,
                "needs_review": 0,
            },
        ],
    )

    return data_dir


@pytest.fixture
def empty_review_data_dir(tmp_path: Path) -> Path:
    """Create an initialized data directory without transaction partitions."""
    data_dir = tmp_path / "empty-review-data"
    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def test_review_help(review_data_dir: Path) -> None:
    """finjuice review --help should show review options."""
    result = runner.invoke(app, ["--data-dir", str(review_data_dir), "review", "--help"])

    assert result.exit_code == 0
    assert "--untagged" in cli_text(result)
    assert "--low-confidence" in cli_text(result)
    assert "--month" in cli_text(result)
    assert "--all-history" in cli_text(result)
    assert "--json" in cli_text(result)
    assert "--cursor" in cli_text(result)
    assert "--privacy" in cli_text(result)


def test_review_basic_shows_default_review_transactions(review_data_dir: Path) -> None:
    """Default review mode should show review-worthy rows from the latest month."""
    result = runner.invoke(app, ["--data-dir", str(review_data_dir), "review"])

    assert result.exit_code == 0
    assert "Needs Review Flag" in cli_text(result)
    assert "Untagged Cafe" in cli_text(result)
    assert "Unclassified Tagged" in cli_text(result)
    assert "Low Confidence Tagged" not in cli_text(result)
    assert "Normal Tagged" not in cli_text(result)


def test_review_untagged_filter(review_data_dir: Path) -> None:
    """--untagged should restrict output to empty-tag transactions only."""
    result = runner.invoke(app, ["--data-dir", str(review_data_dir), "review", "--untagged"])

    assert result.exit_code == 0
    assert "Untagged Cafe" in cli_text(result)
    assert "Needs Review Flag" not in cli_text(result)
    assert "Unclassified Tagged" not in cli_text(result)


def test_review_low_confidence_filter(review_data_dir: Path) -> None:
    """--low-confidence should include rows below the threshold and null confidence."""
    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--low-confidence", "0.7"],
    )

    assert result.exit_code == 0
    assert "Low Confidence Tagged" in cli_text(result)
    assert "Untagged Cafe" in cli_text(result)
    assert "Null Confidence" in cli_text(result)
    assert "Needs Review Flag" not in cli_text(result)


def test_review_month_filter(review_data_dir: Path) -> None:
    """--month should scope the review query to that specific partition."""
    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--month", "2025-10"],
    )

    assert result.exit_code == 0
    assert "Old Untagged" in cli_text(result)
    assert "Needs Review Flag" not in cli_text(result)
    assert "Untagged Cafe" not in cli_text(result)


def test_review_all_history_includes_older_review_backlog(review_data_dir: Path) -> None:
    """--all-history should search older partitions while keeping default filters."""
    result = runner.invoke(app, ["--data-dir", str(review_data_dir), "review", "--all-history"])

    assert result.exit_code == 0
    assert "Old Untagged" in cli_text(result)
    assert "Old Tagged" not in cli_text(result)
    assert "Needs Review Flag" in cli_text(result)


def test_review_json_output(review_data_dir: Path) -> None:
    """--json should return valid structured review output with metadata."""
    result = runner.invoke(app, ["--data-dir", str(review_data_dir), "review", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "review"
    assert payload["total_count"] == 3
    assert payload["filters"]["month"] == "2025-11"
    assert payload["transactions"][0]["merchant_raw"] == "Unclassified Tagged"
    assert payload["transactions"][0]["row_hash"] == "nov-unclassified-tagged"
    assert payload["transactions"][0]["reasons"] == ["unclassified"]
    assert payload["transactions"][0]["severity"] == "medium"
    assert payload["pagination"] == {
        "limit": 50,
        "cursor": "0",
        "next_cursor": None,
        "has_more": False,
        "total_estimate": 3,
        "truncated_by_bytes": False,
    }
    assert payload["health"] == {
        "status": "warning",
        "reasons": ["review_queue"],
    }
    assert payload["actionable"] is True
    assert payload["signals"] == {
        "matched_count": 3,
        "returned_count": 3,
        "truncated": False,
        "needs_review_count": 1,
        "needs_review_flag_count": 1,
        "untagged_count": 1,
        "unclassified_count": 1,
        "uncategorized_count": 1,
        "rule_matched_count": 0,
        "low_confidence_count": 0,
        "low_confidence_threshold": None,
    }
    assert payload["transactions"][0]["rule_matched"] is False
    assert payload["next_steps"] == [
        {
            "signal": "untagged_transactions",
            "message": "Focus on empty-tag rows first.",
            "command": "finjuice review --json --untagged --month 2025-11",
        }
    ]


def test_review_json_default_matches_explicit_raw_privacy(review_data_dir: Path) -> None:
    """Default review JSON should stay raw-compatible with explicit --privacy raw."""
    default_result = runner.invoke(app, ["--data-dir", str(review_data_dir), "review", "--json"])
    raw_result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--json", "--privacy", "raw"],
    )

    assert default_result.exit_code == 0, default_result.output
    assert raw_result.exit_code == 0, raw_result.output
    default_payload = json.loads(default_result.output)
    raw_payload = json.loads(raw_result.output)
    default_payload["_meta"].pop("timestamp")
    raw_payload["_meta"].pop("timestamp")
    assert default_payload == raw_payload
    assert raw_payload["_meta"]["privacy"]["profile"] == "raw"


def test_review_json_redacted_privacy_masks_row_level_pii(review_data_dir: Path) -> None:
    """review --json --privacy redacted should preserve workflow without row PII."""
    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--json", "--privacy", "redacted"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["_meta"]["privacy"]["profile"] == "redacted"
    assert payload["signals"]["matched_count"] == 3
    assert payload["transactions"][0]["row_hash"] == "nov-unclassified-tagged"
    assert payload["transactions"][0]["merchant_raw"] == "[REDACTED]"
    assert payload["transactions"][0]["amount"] is None
    assert "Unclassified Tagged" not in serialized
    assert "Untagged Cafe" not in serialized
    assert "-27000" not in serialized


def test_review_json_compact_privacy_keeps_workflow_cues_only(review_data_dir: Path) -> None:
    """review --json --privacy compact should omit row-level PII but keep workflow cues."""
    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--json", "--privacy", "compact"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["_meta"]["privacy"]["profile"] == "compact"
    assert payload["signals"]["matched_count"] == 3
    assert payload["transactions"][0] == {
        "row_hash": "nov-unclassified-tagged",
        "needs_review": 0,
        "rule_matched": False,
        "reasons": ["unclassified"],
        "severity": "medium",
    }
    assert (
        payload["next_steps"][0]["command"] == "finjuice review --json --untagged --month 2025-11"
    )
    assert "merchant_raw" not in serialized
    assert "amount" not in serialized
    assert "Unclassified Tagged" not in serialized


def test_review_lower_pii_privacy_masks_merchant_derived_rule_notes(
    review_data_dir: Path,
) -> None:
    """Lower-PII review JSON should not expose merchant-derived rule note text."""
    (review_data_dir / "rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "rules:",
                "  - name: suggested_secret_merchant",
                '    match: "Secret Merchant"',
                "    fields: [merchant_raw]",
                '    tags: ["구독"]',
                "    category: 구독",
                "    priority: 90",
                "    notes: Auto-suggested for Secret Merchant (3 transactions)",
                "",
            ]
        ),
        encoding="utf-8",
    )

    redacted_result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--json", "--privacy", "redacted"],
    )
    compact_result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--json", "--privacy", "compact"],
    )

    assert redacted_result.exit_code == 0, redacted_result.output
    assert compact_result.exit_code == 0, compact_result.output
    redacted_payload = json.loads(redacted_result.output)
    compact_payload = json.loads(compact_result.output)
    serialized = json.dumps(
        {"redacted": redacted_payload, "compact": compact_payload},
        ensure_ascii=False,
    )
    assert redacted_payload["rule_notes"] == [
        {
            "rule_name": "[REDACTED]",
            "notes": "[REDACTED]",
            "tags": ["구독"],
            "category": "구독",
        }
    ]
    assert compact_payload["rule_notes"] == [{"tags": ["구독"], "category": "구독"}]
    assert "suggested_secret_merchant" not in serialized
    assert "Auto-suggested for Secret Merchant" not in serialized
    assert "Secret Merchant" not in serialized


def test_review_json_marks_rule_matched_rows(tmp_path: Path) -> None:
    """review --json should expose the rule_matched terminology flag additively."""
    data_dir = tmp_path / "review-rule-matched"
    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    _write_partition(
        data_dir,
        "2025-12",
        [
            {
                "row_hash": "rule-matched",
                "date": "2025-12-01",
                "time": "09:00",
                "datetime": "2025-12-01T09:00:00",
                "merchant_raw": "Rule Matched Cafe",
                "amount": -7000.0,
                "category_rule": "카페",
                "category_final": "카페",
                "tags_rule": '["카페"]',
                "tags_final": '["카페"]',
                "confidence": 0.4,
                "needs_review": 1,
            }
        ],
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "review", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["transactions"][0]["rule_matched"] is True
    assert payload["signals"]["rule_matched_count"] == 1


def test_review_json_all_history_paginates_deterministically(review_data_dir: Path) -> None:
    """All-history review should page through a stable newest-first backlog."""
    first_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--json",
            "--all-history",
            "--limit",
            "2",
        ],
    )
    assert first_result.exit_code == 0, first_result.output
    first_payload = json.loads(first_result.output)

    assert first_payload["filters"]["all_history"] is True
    assert first_payload["filters"]["month"] is None
    assert first_payload["month"] is None
    assert first_payload["signals"]["matched_count"] == 4
    assert first_payload["signals"]["returned_count"] == 2
    assert first_payload["signals"]["truncated"] is True
    assert [row["row_hash"] for row in first_payload["transactions"]] == [
        "nov-unclassified-tagged",
        "nov-untagged-cafe",
    ]
    assert first_payload["pagination"]["next_cursor"] == "2"
    assert first_payload["next_steps"][-1]["command"] == (
        "finjuice review --json --all-history --limit 2 --cursor 2"
    )

    second_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--json",
            "--all-history",
            "--limit",
            "2",
            "--cursor",
            "2",
        ],
    )
    assert second_result.exit_code == 0, second_result.output
    second_payload = json.loads(second_result.output)

    assert [row["row_hash"] for row in second_payload["transactions"]] == [
        "nov-needs-review-flag",
        "oct-old-untagged",
    ]
    assert second_payload["pagination"]["has_more"] is False
    assert second_payload["pagination"]["next_cursor"] is None


def test_review_json_rows_include_reason_severity_contract(review_data_dir: Path) -> None:
    """Rows should expose machine-readable reason labels and highest severity."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--json",
            "--low-confidence",
            "0.7",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    rows_by_hash = {row["row_hash"]: row for row in payload["transactions"]}
    assert rows_by_hash["nov-null-confidence"]["reasons"] == ["low_confidence"]
    assert rows_by_hash["nov-null-confidence"]["severity"] == "low"
    assert rows_by_hash["nov-untagged-cafe"]["reasons"] == [
        "untagged",
        "low_confidence",
    ]
    assert rows_by_hash["nov-untagged-cafe"]["severity"] == "medium"


def test_review_json_low_confidence_reasons_use_requested_threshold(
    review_data_dir: Path,
) -> None:
    """Low-confidence reasons should use the same threshold that selected the row."""
    raw_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--json",
            "--low-confidence",
            "0.8",
        ],
    )
    compact_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--json",
            "--low-confidence",
            "0.8",
            "--privacy",
            "compact",
        ],
    )

    assert raw_result.exit_code == 0, raw_result.output
    assert compact_result.exit_code == 0, compact_result.output
    raw_payload = json.loads(raw_result.output)
    compact_payload = json.loads(compact_result.output)
    raw_rows_by_hash = {row["row_hash"]: row for row in raw_payload["transactions"]}
    compact_rows_by_hash = {row["row_hash"]: row for row in compact_payload["transactions"]}
    row_hash = "nov-threshold-specific-low-confidence"
    assert raw_rows_by_hash[row_hash]["reasons"] == ["low_confidence"]
    assert raw_rows_by_hash[row_hash]["severity"] == "low"
    assert compact_rows_by_hash[row_hash] == {
        "row_hash": row_hash,
        "needs_review": 0,
        "rule_matched": False,
        "reasons": ["low_confidence"],
        "severity": "low",
    }


def test_review_json_truncated_queue_preserves_active_filters(review_data_dir: Path) -> None:
    """Truncated follow-up commands should keep the current review filter flags."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--json",
            "--low-confidence",
            "0.7",
            "--limit",
            "1",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["signals"]["matched_count"] == 3
    assert payload["signals"]["returned_count"] == 1
    assert payload["signals"]["truncated"] is True
    assert payload["next_steps"] == [
        {
            "signal": "untagged_transactions",
            "message": "Focus on empty-tag rows first.",
            "command": "finjuice review --json --untagged --month 2025-11 --low-confidence 0.7",
        },
        {
            "signal": "truncated_queue",
            "message": "Fetch the next page of the review queue.",
            "command": (
                "finjuice review --json --month 2025-11 --low-confidence 0.7 --limit 1 --cursor 1"
            ),
        },
    ]


def test_review_json_invalid_month_uses_review_command(review_data_dir: Path) -> None:
    """Invalid month input should preserve the review command in JSON errors."""
    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--month", "2025-13", "--json"],
    )

    assert result.exit_code == ExitCode.USAGE_ERROR
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "review"
    assert payload["error"]["code"] == ErrorCode.INVALID_ARGS


def test_review_json_invalid_low_confidence_uses_review_command(review_data_dir: Path) -> None:
    """Invalid low-confidence input should preserve the review command in JSON errors."""
    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--low-confidence", "1.1", "--json"],
    )

    assert result.exit_code == ExitCode.USAGE_ERROR
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "review"
    assert payload["error"]["code"] == ErrorCode.INVALID_ARGS


def test_review_json_month_and_all_history_are_mutually_exclusive(review_data_dir: Path) -> None:
    """--month and --all-history should not silently mix incompatible scopes."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--month",
            "2025-11",
            "--all-history",
            "--json",
        ],
    )

    assert result.exit_code == ExitCode.USAGE_ERROR
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "review"
    assert payload["error"]["code"] == ErrorCode.INVALID_ARGS


def test_review_json_missing_month_uses_review_command(review_data_dir: Path) -> None:
    """Missing month partitions should preserve the review command in JSON errors."""
    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "review", "--month", "2025-12", "--json"],
    )

    assert result.exit_code == ExitCode.NO_DATA
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "review"
    assert payload["error"]["code"] == ErrorCode.NO_DATA


def test_review_json_no_data_uses_review_command(empty_review_data_dir: Path) -> None:
    """No available partitions should preserve the review command in JSON errors."""
    result = runner.invoke(app, ["--data-dir", str(empty_review_data_dir), "review", "--json"])

    assert result.exit_code == ExitCode.NO_DATA
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "review"
    assert payload["error"]["code"] == ErrorCode.NO_DATA


def test_review_json_unexpected_error_uses_review_command(
    review_data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unexpected failures should preserve the review command in JSON errors."""

    def _raise_error(_: Path) -> tuple[pl.DataFrame | None, str | None]:
        raise RuntimeError("boom")

    monkeypatch.setattr(review_module, "_load_latest_month", _raise_error)

    result = runner.invoke(app, ["--data-dir", str(review_data_dir), "review", "--json"])

    assert result.exit_code == ExitCode.GENERAL_ERROR
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "review"
    assert payload["error"]["code"] == ErrorCode.GENERAL_ERROR


def test_review_empty_result(review_data_dir: Path) -> None:
    """No matching rows should still exit cleanly with an empty review result."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--month",
            "2025-10",
            "--low-confidence",
            "0.1",
        ],
    )

    assert result.exit_code == 0
    assert "No transactions match the review filters" in cli_text(result)


def test_review_json_empty_result_includes_clear_health(review_data_dir: Path) -> None:
    """Empty review queues should expose a non-actionable healthy contract."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "review",
            "--month",
            "2025-10",
            "--low-confidence",
            "0.1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["transactions"] == []
    assert payload["health"] == {
        "status": "ok",
        "reasons": [],
    }
    assert payload["actionable"] is False
    assert payload["signals"] == {
        "matched_count": 0,
        "returned_count": 0,
        "truncated": False,
        "needs_review_count": 0,
        "needs_review_flag_count": 0,
        "untagged_count": 0,
        "unclassified_count": 0,
        "uncategorized_count": 0,
        "rule_matched_count": 0,
        "low_confidence_count": 0,
        "low_confidence_threshold": 0.1,
    }
    assert payload["next_steps"] == []
