"""Tests for rules suggest preview and dry-run flows."""

import json
import re
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from terminal output."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _build_transaction(
    row_hash: str,
    date: str,
    merchant_raw: str,
    amount: float,
    *,
    memo_raw: str = "",
    tags_final: str = "[]",
    file_id: str = "241001_1",
    source_row: int = 1,
) -> dict[str, object]:
    """Create a CSV row with the fields required by rules suggest."""
    time = f"0{source_row}:00" if source_row < 10 else f"{source_row}:00"
    return {
        "row_hash": row_hash,
        "date": date,
        "time": time,
        "type_raw": "지출",
        "type_norm": "expense",
        "major_raw": "정기지출",
        "minor_raw": "구독",
        "merchant_raw": merchant_raw,
        "memo_raw": memo_raw,
        "amount": amount,
        "account": "신한카드",
        "currency": "KRW",
        "counterparty": "",
        "datetime": f"{date}T{time}:00",
        "category_rule": "",
        "category_final": "미분류",
        "tags_rule": "[]",
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": tags_final,
        "confidence": None,
        "needs_review": 0,
        "is_transfer": 0,
        "transfer_group_id": "",
        "file_id": file_id,
        "source_row": source_row,
    }


def _write_transactions(data_dir: Path, rows: list[dict[str, object]]) -> None:
    """Write rows into a single month transaction partition."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "transactions.csv")


def _create_preview_data_dir(tmp_path: Path) -> Path:
    """Create transactions that yield one Netflix suggestion."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _build_transaction(
                "row1",
                "2024-10-01",
                "Netflix",
                -17000.0,
                memo_raw="Monthly plan",
                tags_final="[]",
                source_row=1,
            ),
            _build_transaction(
                "row2",
                "2024-10-02",
                "Netflix",
                -17000.0,
                memo_raw="Monthly plan",
                tags_final="[]",
                source_row=2,
            ),
            _build_transaction(
                "row3",
                "2024-10-03",
                "Netflix",
                -17000.0,
                memo_raw="Already tagged",
                tags_final='["구독"]',
                source_row=3,
            ),
            _build_transaction(
                "row4",
                "2024-10-04",
                "Starbucks",
                -5000.0,
                memo_raw="Latte",
                tags_final='["카페"]',
                source_row=4,
            ),
        ],
    )
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def _create_empty_suggestions_data_dir(tmp_path: Path) -> Path:
    """Create data with no untagged transactions so suggestions are empty."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _build_transaction(
                "row1",
                "2024-10-01",
                "Tagged Merchant",
                -12000.0,
                memo_raw="Already tagged",
                tags_final='["생활"]',
                source_row=1,
            ),
        ],
    )
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def test_rules_suggest_preview_shows_context_table(tmp_path: Path) -> None:
    """--preview should show the DuckDB-backed merchant context table."""
    data_dir = _create_preview_data_dir(tmp_path)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "rules", "suggest", "--preview"])

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "Merchant Context Preview" in output
    assert "Netflix" in output
    assert "17,000" in output
    assert "Monthly plan" in output
    assert "정기지출 / 구독" in output


def test_rules_suggest_apply_dry_run_shows_changes_without_modifying_files(tmp_path: Path) -> None:
    """--apply --dry-run should not write rules.yaml."""
    data_dir = _create_preview_data_dir(tmp_path)
    rules_file = data_dir / "rules.yaml"
    before = rules_file.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "rules", "suggest", "--apply", "--dry-run"],
    )

    assert result.exit_code == 0
    output = _strip_ansi(result.output)
    assert "Dry-Run Merchant Context" in output
    assert "suggested_netflix" in output
    assert "category: 구독" in output
    assert "Dry run: no changes made" in output
    assert rules_file.read_text(encoding="utf-8") == before


def test_rules_suggest_preview_json_includes_rich_context(tmp_path: Path) -> None:
    """--preview --json should include the rich merchant context payload."""
    data_dir = _create_preview_data_dir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "rules", "suggest", "--preview", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "rules suggest"
    suggestion = payload["suggestions"][0]
    assert suggestion["merchant"] == "Netflix"
    assert suggestion["avg_amount"] == 17000.0
    assert suggestion["amount_stddev"] == 0.0
    assert suggestion["active_months"] == ["2024-10"]
    assert suggestion["banksalad_category"] == {"major": "정기지출", "minor": "구독"}
    assert suggestion["payment_method"] == "신한카드"
    assert suggestion["time_patterns"]["weekday_pct"] == 1.0
    assert suggestion["time_patterns"]["lunch_pct"] == 0.0
    assert suggestion["similar_merchants"] == []
    assert suggestion["pattern"] == "Netflix"
    assert suggestion["sample_memos"] == ["Monthly plan"]
    # Issue #374: suggested_rule field
    assert "suggested_rule" in suggestion
    rule = suggestion["suggested_rule"]
    assert rule["name"] == "suggested_netflix"
    assert rule["match"] == "Netflix"
    assert rule["category"] == "구독"
    assert rule["tags"] == ["구독", "정기지출"]
    assert rule["priority"] == 80  # single month, not recurring


def test_rules_suggest_json_marks_payment_gateway_as_skip_rule(tmp_path: Path) -> None:
    """Known PG suggestions should be visible but not auto-apply eligible."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _build_transaction("pg1", "2024-10-01", "케이지이니시스", -10000.0, source_row=1),
            _build_transaction("pg2", "2024-10-02", "케이지이니시스", -11000.0, source_row=2),
        ],
    )
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    result = runner.invoke(app, ["--data-dir", str(data_dir), "rules", "suggest", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    suggestion = payload["suggestions"][0]
    assert suggestion["merchant"] == "케이지이니시스"
    assert suggestion["merchant_kind"] == "payment_gateway"
    assert suggestion["ambiguous_reason"] == "payment_gateway"
    assert suggestion["default_action"] == "skip_rule"
    assert suggestion["auto_apply_eligible"] is False


def test_rules_suggest_apply_dry_run_json_excludes_payment_gateway(tmp_path: Path) -> None:
    """PG candidates should not appear in would_apply for preview-first automation."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _build_transaction("pg1", "2024-10-01", "케이지이니시스", -10000.0, source_row=1),
            _build_transaction("pg2", "2024-10-02", "케이지이니시스", -11000.0, source_row=2),
            _build_transaction("n1", "2024-10-03", "Local Cafe", -5000.0, source_row=3),
            _build_transaction("n2", "2024-10-04", "Local Cafe", -5500.0, source_row=4),
        ],
    )
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "suggest",
            "--apply",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [item["merchant"] for item in payload["would_apply"]] == ["Local Cafe"]
    assert payload["auto_apply_skipped"] == [
        {
            "merchant": "케이지이니시스",
            "reason": "payment_gateway",
            "default_action": "skip_rule",
        }
    ]


def test_rules_suggest_apply_dry_run_human_excludes_payment_gateway_rules(
    tmp_path: Path,
) -> None:
    """Human dry-run should not advertise skipped PG candidates as rules to add."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _build_transaction("pg1", "2024-10-01", "케이지이니시스", -10000.0, source_row=1),
            _build_transaction("pg2", "2024-10-02", "케이지이니시스", -11000.0, source_row=2),
            _build_transaction("n1", "2024-10-03", "Local Cafe", -5000.0, source_row=3),
            _build_transaction("n2", "2024-10-04", "Local Cafe", -5500.0, source_row=4),
        ],
    )
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "suggest",
            "--apply",
            "--dry-run",
        ],
    )

    assert result.exit_code == 0, result.output
    output = _strip_ansi(result.output)
    would_add = output.split("Would add these rules:", 1)[1].split("Auto-apply skipped:", 1)[0]
    skipped = output.split("Auto-apply skipped:", 1)[1]
    assert "Local Cafe" in would_add
    assert "케이지이니시스" not in would_add
    assert "케이지이니시스 (payment_gateway)" in skipped


def test_rules_suggest_apply_yes_json_skips_payment_gateway(tmp_path: Path) -> None:
    """Headless auto-apply should not persist broad PG merchant rules."""
    data_dir = tmp_path / "data"
    rules_file = data_dir / "rules.yaml"
    _write_transactions(
        data_dir,
        [
            _build_transaction("pg1", "2024-10-01", "케이지이니시스", -10000.0, source_row=1),
            _build_transaction("pg2", "2024-10-02", "케이지이니시스", -11000.0, source_row=2),
            _build_transaction("n1", "2024-10-03", "Local Cafe", -5000.0, source_row=3),
            _build_transaction("n2", "2024-10-04", "Local Cafe", -5500.0, source_row=4),
        ],
    )
    rules_file.write_text("version: 1\nrules: []\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "suggest",
            "--apply",
            "--yes",
            "--no-tag-after",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["applied"] == 1
    assert payload["skipped"] == 1
    assert payload["auto_apply_skipped"] == 1
    rules_content = rules_file.read_text(encoding="utf-8")
    assert "Local Cafe" in rules_content
    assert "케이지이니시스" not in rules_content


def test_rules_suggest_file_id_json_limits_import_scope(tmp_path: Path) -> None:
    """--file-id should prioritize newly imported rows for curation."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _build_transaction(
                "new1",
                "2024-10-01",
                "New Import Merchant",
                -1000.0,
                file_id="250607_1",
                source_row=1,
            ),
            _build_transaction(
                "new2",
                "2024-10-02",
                "New Import Merchant",
                -1000.0,
                file_id="250607_1",
                source_row=2,
            ),
            _build_transaction(
                "old1",
                "2024-10-03",
                "Old Merchant",
                -1000.0,
                file_id="250606_1",
                source_row=3,
            ),
            _build_transaction(
                "old2",
                "2024-10-04",
                "Old Merchant",
                -1000.0,
                file_id="250606_1",
                source_row=4,
            ),
        ],
    )
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "suggest",
            "--file-id",
            "250607_1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total_count"] == 2
    assert [suggestion["merchant"] for suggestion in payload["suggestions"]] == [
        "New Import Merchant"
    ]


def test_rules_suggest_file_id_json_empty_result_is_not_unknown(
    tmp_path: Path,
) -> None:
    """A known file_id with no open suggestions should return an empty success payload."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _build_transaction(
                "tagged1",
                "2024-10-01",
                "Tagged Merchant",
                -1000.0,
                tags_final='["생활"]',
                file_id="250607_1",
                source_row=1,
            ),
            _build_transaction(
                "tagged2",
                "2024-10-02",
                "Tagged Merchant",
                -1000.0,
                tags_final='["생활"]',
                file_id="250607_1",
                source_row=2,
            ),
        ],
    )
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "suggest",
            "--file-id",
            "250607_1",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["total_count"] == 2
    assert payload["suggestions"] == []
    assert payload["message"] == "All transactions are tagged."


def test_rules_suggest_file_id_json_unknown_fails_loudly(tmp_path: Path) -> None:
    """Unknown file_id should be a structured no-data error."""
    data_dir = _create_preview_data_dir(tmp_path)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "suggest",
            "--file-id",
            "missing_1",
            "--json",
        ],
    )

    assert result.exit_code == 4, result.output
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "NO_DATA"
    assert "missing_1" in payload["error"]["message"]


def test_rules_suggest_apply_dry_run_json_reports_no_write(tmp_path: Path) -> None:
    """--apply --dry-run --json should return the would-apply payload."""
    data_dir = _create_preview_data_dir(tmp_path)
    rules_file = data_dir / "rules.yaml"
    before = rules_file.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "rules",
            "suggest",
            "--apply",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["rules_file_modified"] is False
    assert payload["message"] == "Dry run: no changes made"
    assert payload["suggestions"][0]["banksalad_category"] == {"major": "정기지출", "minor": "구독"}
    assert payload["would_apply"][0]["rule"]["name"] == "suggested_netflix"
    assert payload["would_apply"][0]["rule"]["category"] == "구독"
    assert payload["would_apply"][0]["rule"]["tags"] == ["구독", "정기지출"]
    assert rules_file.read_text(encoding="utf-8") == before


def test_rules_suggest_preview_handles_empty_suggestions(tmp_path: Path) -> None:
    """Preview mode should handle the no-suggestions case cleanly."""
    data_dir = _create_empty_suggestions_data_dir(tmp_path)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "rules", "suggest", "--preview"])

    assert result.exit_code == 0
    assert "모든 거래가 태그되었습니다" in _strip_ansi(result.output)
