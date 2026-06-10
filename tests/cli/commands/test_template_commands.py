"""Tests for `finjuice template` command group."""

import json
from datetime import date, timedelta

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands.template_cmd import _log_template_run_event
from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


@pytest.fixture
def template_data_dir(tmp_path):
    """Create temporary dataset for template command tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    month_dir = data_dir / "transactions" / "2024" / "10"
    month_dir.mkdir(parents=True)

    df = pl.DataFrame(
        {
            "date": [
                "2024-09-29",
                "2024-09-30",
                "2024-10-01",
                "2024-10-02",
                "2024-10-03",
                "2024-10-04",
                "2024-10-05",
            ],
            "time": ["08:10", "19:45", "08:30", "13:00", "20:20", "9:05", "07:50"],
            "merchant_raw": [
                "Starbucks",
                "Netflix",
                "Starbucks",
                "Netflix",
                "Netflix",
                "Coupang",
                "Gym",
            ],
            "amount": [-5100, -15000, -5000, -15000, -15000, -320000, -45000],
            "memo_raw": ["coffee", "sub", "coffee", "sub", "sub", "shopping", "health"],
            "major_raw": ["Food", "Living", "Food", "Living", "Living", "Shopping", "Health"],
            "minor_raw": ["Cafe", "Sub", "Cafe", "Sub", "Sub", "Online", "Gym"],
            "type_norm": [
                "expense",
                "expense",
                "expense",
                "expense",
                "expense",
                "expense",
                "expense",
            ],
            "is_transfer": [0, 0, 0, 0, 0, 0, 0],
            "tags_final": [
                json.dumps(["cafe"]),
                json.dumps(["subscription"]),
                json.dumps(["cafe"]),
                json.dumps(["subscription"]),
                json.dumps(["subscription"]),
                json.dumps(["shopping"]),
                json.dumps(["health"]),
            ],
            "category_final": [
                "Cafe",
                "Subscription",
                "Cafe",
                "Subscription",
                "Subscription",
                "Shopping",
                "Health",
            ],
            "account": ["Card A", "Card A", "Card A", "Card A", "Card A", "Card B", "Card B"],
        }
    )
    df.write_csv(month_dir / "transactions.csv")

    (data_dir / "rules.yaml").write_text(
        """
version: 1
rules: []
""".strip()
    )

    return data_dir


@pytest.fixture
def review_template_data_dir(tmp_path):
    """Create data with consumption, event, transfer, payment, and savings rows."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    month_dir = data_dir / "transactions" / "2026" / "05"
    month_dir.mkdir(parents=True)
    next_month_dir = data_dir / "transactions" / "2026" / "06"
    next_month_dir.mkdir(parents=True)

    def row(
        row_hash: str,
        date_value: str,
        merchant: str,
        amount: int,
        category: str,
        tags: list[str],
        *,
        is_transfer: int = 0,
        type_norm: str = "expense",
    ) -> dict[str, object]:
        return {
            "row_hash": row_hash,
            "date": date_value,
            "time": "09:00",
            "datetime": f"{date_value}T09:00:00",
            "type_raw": "승인",
            "type_norm": type_norm,
            "major_raw": category,
            "minor_raw": category,
            "merchant_raw": merchant,
            "memo_raw": "",
            "amount": amount,
            "account": "테스트카드",
            "currency": "KRW",
            "category_final": category,
            "tags_final": json.dumps(tags, ensure_ascii=False),
            "is_transfer": is_transfer,
            "transfer_group_id": "transfer-1" if is_transfer else "",
        }

    may_rows = pl.DataFrame(
        [
            row("grocery", "2026-05-01", "동네마트", -100, "식비", ["생활"]),
            row("travel", "2026-05-02", "제주호텔", -300, "여행", ["제주여행", "여행"]),
            row("medical", "2026-05-03", "서울병원", -200, "의료", ["융모막검사", "의료"]),
            row("cafe", "2026-05-04", "동네카페", -50, "식비", ["카페"]),
            row("card", "2026-05-05", "카드대금", -1000, "카드대금", ["카드대금"]),
            row("transfer", "2026-05-06", "내계좌이체", -200, "이체", ["이체"], is_transfer=1),
            row("irp", "2026-05-07", "IRP", -400, "저축", ["IRP", "정기저축"]),
        ]
    )
    june_rows = pl.DataFrame([row("june-grocery", "2026-06-01", "동네마트", -10, "식비", ["생활"])])
    may_rows.write_csv(month_dir / "transactions.csv")
    june_rows.write_csv(next_month_dir / "transactions.csv")
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def test_template_list(template_data_dir):
    """List command should show built-in templates."""
    result = runner.invoke(app, ["--data-dir", str(template_data_dir), "template", "list"])

    assert result.exit_code == 0
    assert "monthly_spend" in cli_text(result)
    assert "tag_breakdown" in cli_text(result)
    assert "merchant_monthly_trend" in cli_text(result)
    assert "spend_by_weekday_hour" in cli_text(result)
    assert "monthly_consumption_summary" in cli_text(result)
    assert "event_adjusted_spend" in cli_text(result)


def test_template_list_json_output(template_data_dir):
    """List command should emit a structured JSON template registry."""
    result = runner.invoke(
        app,
        ["--data-dir", str(template_data_dir), "template", "list", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "template list"
    assert isinstance(payload["templates"], list)
    monthly_spend = next(item for item in payload["templates"] if item["name"] == "monthly_spend")
    assert monthly_spend["description"] == "Monthly total spending and count (excluding transfers)"
    assert set(monthly_spend["params"]) == {"since", "until"}
    template_names = {item["name"] for item in payload["templates"]}
    assert {
        "monthly_consumption_summary",
        "consumption_category_breakdown",
        "merchant_top_spend",
        "event_adjusted_spend",
    }.issubset(template_names)


def test_template_show(template_data_dir):
    """Show command should print SQL and metadata."""
    result = runner.invoke(
        app,
        ["--data-dir", str(template_data_dir), "template", "show", "monthly_spend"],
    )

    assert result.exit_code == 0
    assert "Monthly total spending" in cli_text(result)
    assert "SELECT" in cli_text(result)
    assert "{{since}}" in cli_text(result)


def test_template_show_json_output(template_data_dir):
    """Show command should emit structured JSON metadata and SQL."""
    # Arrange
    args = ["--data-dir", str(template_data_dir), "template", "show", "monthly_spend", "--json"]

    # Act
    result = runner.invoke(app, args)

    # Assert
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "template show"
    assert payload["name"] == "monthly_spend"
    assert payload["description"] == "Monthly total spending and count (excluding transfers)"
    assert set(payload["parameters"]) == {"since", "until"}
    assert "SELECT" in payload["sql"]
    assert "{{since}}" in payload["sql"]


def test_template_show_json_unknown_template(template_data_dir):
    """Show command should emit a structured JSON error for unknown templates."""
    # Arrange
    args = ["--data-dir", str(template_data_dir), "template", "show", "missing_template", "--json"]

    # Act
    result = runner.invoke(app, args)

    # Assert
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "template show"
    assert payload["error"]["code"] == "INVALID_ARGS"
    assert payload["error"]["message"] == "Unknown template: missing_template"
    assert payload["exit_code"] == 2


def test_template_run_table_output(template_data_dir):
    """Run command should execute SQL template and print table output."""
    result = runner.invoke(
        app,
        ["--data-dir", str(template_data_dir), "template", "run", "monthly_spend"],
    )

    assert result.exit_code == 0
    assert "Template Result: monthly_spend" in cli_text(result)
    assert "2024-10" in cli_text(result)


def test_template_run_json_output(template_data_dir):
    """Run command should emit an enveloped JSON result with rows."""
    result = runner.invoke(
        app,
        ["--data-dir", str(template_data_dir), "template", "run", "monthly_spend", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "monthly_spend"
    assert payload["row_count"] == 2
    assert payload["rows"][0]["month"] == "2024-10"
    assert payload["rows"][0]["transaction_count"] == 5
    assert payload["rows"][0]["total_spend"] == 400000
    assert payload["rows"][1]["month"] == "2024-09"
    assert payload["rows"][1]["transaction_count"] == 2
    assert payload["rows"][1]["total_spend"] == 20100


def test_template_run_monthly_consumption_summary_excludes_non_consumption(
    review_template_data_dir,
):
    """Canonical consumption spend should exclude transfers, payments, and savings."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_template_data_dir),
            "template",
            "run",
            "monthly_consumption_summary",
            "--param",
            "since=2026-05",
            "--param",
            "until=2026-05",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["template_name"] == "monthly_consumption_summary"
    assert payload["rows"] == [
        {
            "month": "2026-05",
            "transaction_count": 4,
            "consumption_spend": 650,
            "excluded_non_consumption_spend": 1400,
        }
    ]


def test_template_run_consumption_category_and_merchant_breakdowns(
    review_template_data_dir,
):
    """Review templates should expose category and merchant breakdowns for one month."""
    category_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_template_data_dir),
            "template",
            "run",
            "consumption_category_breakdown",
            "--param",
            "month=2026-05",
            "--param",
            "top_n=2",
            "--json",
        ],
    )
    merchant_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_template_data_dir),
            "template",
            "run",
            "merchant_top_spend",
            "--param",
            "month=2026-05",
            "--param",
            "top_n=2",
            "--json",
        ],
    )

    assert category_result.exit_code == 0, category_result.output
    assert merchant_result.exit_code == 0, merchant_result.output
    category_payload = json.loads(category_result.output)
    merchant_payload = json.loads(merchant_result.output)
    assert category_payload["rows"] == [
        {"category": "여행", "transaction_count": 1, "consumption_spend": 300},
        {"category": "의료", "transaction_count": 1, "consumption_spend": 200},
    ]
    assert merchant_payload["rows"] == [
        {"merchant": "제주호텔", "transaction_count": 1, "consumption_spend": 300},
        {"merchant": "서울병원", "transaction_count": 1, "consumption_spend": 200},
    ]


def test_template_run_event_adjusted_spend_excludes_selected_event_tags(
    review_template_data_dir,
):
    """Event tags should subtract only selected event spend from normal consumption."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_template_data_dir),
            "template",
            "run",
            "event_adjusted_spend",
            "--param",
            "month=2026-05",
            "--param",
            "event_tags=제주여행,융모막검사",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [
        {
            "month": "2026-05",
            "event_tags": "융모막검사, 제주여행",
            "transaction_count": 4,
            "event_transaction_count": 2,
            "total_consumption_spend": 650,
            "event_spend": 500,
            "adjusted_consumption_spend": 150,
        }
    ]


def test_template_run_event_adjusted_spend_handles_zero_events(review_template_data_dir):
    """Omitting event tags should keep adjusted total equal to total consumption spend."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_template_data_dir),
            "template",
            "run",
            "event_adjusted_spend",
            "--param",
            "month=2026-05",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["rows"] == [
        {
            "month": "2026-05",
            "event_tags": "",
            "transaction_count": 4,
            "event_transaction_count": 0,
            "total_consumption_spend": 650,
            "event_spend": 0,
            "adjusted_consumption_spend": 650,
        }
    ]


def test_template_run_recurring_candidates_classifies_intent(tmp_path):
    """Recurring candidates should expose deterministic intent classes."""
    data_dir = tmp_path / "data"
    month_dir = data_dir / "transactions" / "2024" / "10"
    month_dir.mkdir(parents=True)
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    def row(
        row_hash: str,
        date_value: str,
        merchant: str,
        amount: int,
        major: str,
        minor: str,
        memo: str,
    ) -> dict[str, object]:
        return {
            "row_hash": row_hash,
            "date": date_value,
            "time": "09:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": major,
            "minor_raw": minor,
            "merchant_raw": merchant,
            "memo_raw": memo,
            "amount": amount,
            "account": "Card",
            "currency": "KRW",
            "counterparty": "",
            "datetime": f"{date_value}T09:00:00",
            "category_rule": "",
            "category_final": minor,
            "tags_rule": "[]",
            "tags_ai": "[]",
            "tags_manual": "[]",
            "tags_final": "[]",
            "confidence": None,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": "",
            "file_id": "241001_1",
            "source_row": int(row_hash.rsplit("-", 1)[1]),
        }

    rows = []
    candidates = [
        ("savings", "청년적금", -100000, "저축", "적금", "monthly savings"),
        ("loan", "대출이자", -25000, "금융", "대출이자", "loan interest"),
        ("spending", "Netflix", -15000, "정기지출", "구독", "subscription"),
        ("unknown", "Mystery Club", -7777, "기타", "기타", ""),
    ]
    for idx, (prefix, merchant, amount, major, minor, memo) in enumerate(candidates, 1):
        rows.append(row(f"{prefix}-1", "2024-10-01", merchant, amount, major, minor, memo))
        rows.append(row(f"{prefix}-2", "2024-10-15", merchant, amount, major, minor, memo))

    pl.DataFrame(rows).write_csv(month_dir / "transactions.csv")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "template",
            "run",
            "recurring_candidates",
            "--param",
            "min_occurrences=2",
            "--param",
            "min_amount=1000",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0, cli_text(result)
    payload = json.loads(cli_text(result))
    rows_by_merchant = {item["merchant_raw"]: item for item in payload["rows"]}
    assert rows_by_merchant["청년적금"]["intent"] == "savings"
    assert rows_by_merchant["청년적금"]["intent_confidence"] == 0.9
    assert rows_by_merchant["대출이자"]["intent"] == "loan_or_interest"
    assert rows_by_merchant["대출이자"]["intent_confidence"] == 0.9
    assert rows_by_merchant["Netflix"]["intent"] == "spending"
    assert rows_by_merchant["Netflix"]["intent_confidence"] == 0.75
    assert rows_by_merchant["Mystery Club"]["intent"] == "unknown"
    assert rows_by_merchant["Mystery Club"]["intent_confidence"] == 0.0


def test_template_run_output_json_envelopes_rows(template_data_dir):
    """--output json should match the enveloped --json payload shape."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "monthly_spend"
    assert payload["row_count"] == 2
    assert payload["rows"][0]["month"] == "2024-10"


def test_template_run_json_flag_takes_priority_over_output_json(template_data_dir):
    """--json should wrap output even when --output json is also provided."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "json",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "template run"
    assert payload["rows"][0]["month"] == "2024-10"


def test_template_run_json_flag_rejects_conflicting_output(template_data_dir):
    """--json should reject non-JSON output selections."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "csv",
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "INVALID_ARGS"
    assert "Cannot use --json" in payload["error"]["message"]


def test_template_run_json_file_output(template_data_dir, tmp_path):
    """Run command should save JSON output to file when requested."""
    output_file = tmp_path / "out" / "monthly.json"

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "json",
            "--file",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert output_file.exists()
    payload = json.loads(output_file.read_text())
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "monthly_spend"
    assert payload["row_count"] == 2
    assert payload["rows"][0]["month"] == "2024-10"


def test_template_run_xlsx_output(template_data_dir, tmp_path):
    """Run command should generate XLSX file for POC output mode."""
    output_file = tmp_path / "out" / "monthly.xlsx"

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "xlsx",
            "--file",
            str(output_file),
        ],
    )

    assert result.exit_code == 0
    assert output_file.exists()


def test_template_run_markdown_output_without_pandas(template_data_dir, monkeypatch):
    """Markdown output should not rely on DataFrame.to_pandas()."""

    def _raise_no_pandas(*_args, **_kwargs):  # pragma: no cover - should not be called
        raise AssertionError("to_pandas should not be called for markdown output")

    monkeypatch.setattr(pl.DataFrame, "to_pandas", _raise_no_pandas)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "markdown",
        ],
    )

    assert result.exit_code == 0
    rendered = cli_text(result)
    assert "| month | transaction_count | total_spend |" in rendered
    assert "| 2024-10 | 5 | 400000 |" in rendered


def test_template_run_rejects_param_injection(template_data_dir):
    """Injection-like parameter input should fail validation."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--param",
            "since=2024-10';DROP TABLE transactions",
        ],
    )

    assert result.exit_code == 1
    assert "Invalid month value" in cli_text(result)
    audit_log_path = template_data_dir / ".execution_audit.jsonl"
    assert audit_log_path.exists()
    events = [json.loads(line) for line in audit_log_path.read_text().splitlines() if line.strip()]
    latest = events[-1]
    assert latest["event"] == "template_run"
    assert latest["template_name"] == "monthly_spend"
    assert latest["template_domain"] == "transaction"
    assert latest["success"] is False
    assert latest["error_type"] == "ValueError"


def test_template_run_event_resolves_asset_domain(template_data_dir):
    """Template audit event should classify asset-prefixed names as asset domain."""
    _log_template_run_event(
        data_dir=template_data_dir,
        template_name="asset_overview",
        success=True,
        output_format="json",
        user_params={},
        duration=0.12,
        row_count=1,
    )

    audit_log_path = template_data_dir / ".execution_audit.jsonl"
    assert audit_log_path.exists()
    events = [json.loads(line) for line in audit_log_path.read_text().splitlines() if line.strip()]
    latest = events[-1]
    assert latest["event"] == "template_run"
    assert latest["template_name"] == "asset_overview"
    assert latest["template_domain"] == "asset"
    assert latest["success"] is True


def test_template_run_rejects_unknown_param(template_data_dir):
    """Unknown template parameters should be rejected."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--param",
            "foo=bar",
        ],
    )

    assert result.exit_code == 1
    assert "Unknown parameters" in cli_text(result)


def test_template_run_requires_file_for_xlsx(template_data_dir):
    """xlsx output requires --file path."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "xlsx",
        ],
    )

    assert result.exit_code == 1
    assert "--file is required" in cli_text(result)


def test_template_run_merchant_monthly_trend_default_window(template_data_dir):
    """Merchant monthly trend should use data-based default month window."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "merchant_monthly_trend",
            "--param",
            "merchant=Netflix",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "merchant_monthly_trend"
    assert payload["row_count"] == 2
    assert payload["rows"][0]["month"] == "2024-10"
    assert payload["rows"][1]["month"] == "2024-09"
    assert payload["rows"][0]["transaction_count"] == 2
    assert payload["rows"][1]["transaction_count"] == 1


def test_template_run_merchant_monthly_trend_with_since_filter(template_data_dir):
    """Merchant monthly trend should apply explicit period filter."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "merchant_monthly_trend",
            "--param",
            "merchant=Starbucks",
            "--param",
            "since=2024-10",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "merchant_monthly_trend"
    assert payload["row_count"] == 1
    assert len(payload["rows"]) == 1
    assert payload["rows"][0]["month"] == "2024-10"
    assert payload["rows"][0]["transaction_count"] == 1


def test_template_run_spend_by_weekday_hour(template_data_dir):
    """Weekday/hour template should return long-table shape."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "spend_by_weekday_hour",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "spend_by_weekday_hour"
    assert payload["row_count"] >= 1
    assert set(payload["rows"][0]).issuperset(
        {"weekday_idx", "weekday_name", "hour", "transaction_count", "total_spend", "avg_spend"}
    )
    assert any(row["hour"] == 9 for row in payload["rows"])


def test_template_run_rejects_read_csv_injection(template_data_dir):
    """read_csv-like string should be blocked by restricted keyword validator."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "merchant_monthly_trend",
            "--param",
            "merchant=read_csv(",
        ],
    )

    assert result.exit_code == 1
    assert "Security violation" in cli_text(result)


def test_template_run_allows_dropbox_substring(template_data_dir):
    """DROP substring inside merchant literal (Dropbox) should be allowed."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "merchant_monthly_trend",
            "--param",
            "merchant=Dropbox",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0


def test_template_run_writes_template_audit_event(template_data_dir):
    """Successful template execution should append template_run audit event."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(template_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0

    audit_log_path = template_data_dir / ".execution_audit.jsonl"
    assert audit_log_path.exists()
    events = [json.loads(line) for line in audit_log_path.read_text().splitlines() if line.strip()]
    latest = events[-1]
    assert latest["event"] == "template_run"
    assert latest["template_name"] == "monthly_spend"
    assert latest["template_domain"] == "transaction"
    assert latest["success"] is True
    assert latest["output_format"] == "json"
    assert isinstance(latest["duration"], float)
    assert isinstance(latest["row_count"], int)


# ---------------------------------------------------------------------------
# Review-workflow templates (weekly_anomalies, new_merchants, spending_comparison)
# ---------------------------------------------------------------------------


@pytest.fixture
def review_data_dir(tmp_path):
    """Historical dataset with two review periods anchored on its latest transaction date."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    latest_date = date(2024, 10, 31)

    # Current period: latest 7 days in the dataset, with higher cafe spending and "NewShop".
    recent_dates = [latest_date - timedelta(days=i) for i in range(0, 5)]
    # Prior period: the preceding 7 days, with lower cafe spending and no "NewShop".
    prior_dates = [latest_date - timedelta(days=i) for i in range(8, 13)]

    rows = []
    # Prior period transactions
    for d in prior_dates:
        rows.append(
            {
                "date": d.isoformat(),
                "time": "10:00",
                "merchant_raw": "Starbucks",
                "amount": -5000,
                "memo_raw": "",
                "major_raw": "Food",
                "minor_raw": "Cafe",
                "type_norm": "expense",
                "is_transfer": 0,
                "tags_final": json.dumps(["cafe"]),
                "category_final": "Cafe",
                "account": "Card A",
            }
        )
    # Current period transactions — more cafe + new merchant
    for d in recent_dates:
        rows.append(
            {
                "date": d.isoformat(),
                "time": "10:00",
                "merchant_raw": "Starbucks",
                "amount": -10000,
                "memo_raw": "",
                "major_raw": "Food",
                "minor_raw": "Cafe",
                "type_norm": "expense",
                "is_transfer": 0,
                "tags_final": json.dumps(["cafe"]),
                "category_final": "Cafe",
                "account": "Card A",
            }
        )
    # New merchant only in current period
    rows.append(
        {
            "date": (latest_date - timedelta(days=2)).isoformat(),
            "time": "14:00",
            "merchant_raw": "NewShop",
            "amount": -30000,
            "memo_raw": "",
            "major_raw": "Shopping",
            "minor_raw": "Online",
            "type_norm": "expense",
            "is_transfer": 0,
            "tags_final": json.dumps(["shopping"]),
            "category_final": "Shopping",
            "account": "Card B",
        }
    )

    df = pl.DataFrame(rows)

    # Partition rows by YYYY/MM to avoid duplicates across partitions
    df = df.with_columns(pl.col("date").str.slice(0, 7).alias("_ym"))
    for ym_val in df["_ym"].unique().to_list():
        year, month = ym_val.split("-")
        part_dir = data_dir / "transactions" / year / month
        part_dir.mkdir(parents=True, exist_ok=True)
        month_rows = df.filter(pl.col("_ym") == ym_val).drop("_ym")
        month_rows.write_csv(part_dir / "transactions.csv")

    (data_dir / "rules.yaml").write_text("version: 1\nrules: []")

    return data_dir


def test_template_run_weekly_anomalies(review_data_dir):
    """weekly_anomalies should detect category spending changes."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "template",
            "run",
            "weekly_anomalies",
            "--param",
            "period_days=7",
            "--param",
            "threshold_pct=10",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "weekly_anomalies"
    assert payload["row_count"] >= 1
    row_keys = set(payload["rows"][0])
    assert row_keys.issuperset({"category", "current_spend", "prior_spend", "change_pct"})
    # Cafe spending doubled (5000 -> 10000 per txn), so change_pct should be positive
    cafe_rows = [r for r in payload["rows"] if r["category"] == "Cafe"]
    assert len(cafe_rows) == 1
    assert cafe_rows[0]["change_pct"] > 0
    assert cafe_rows[0]["current_spend"] > cafe_rows[0]["prior_spend"]


def test_template_run_weekly_anomalies_monthly_mode(review_data_dir):
    """weekly_anomalies should accept period_days=30 for monthly review."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "template",
            "run",
            "weekly_anomalies",
            "--param",
            "period_days=30",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["template_name"] == "weekly_anomalies"


def test_template_run_new_merchants(review_data_dir):
    """new_merchants should find merchants only in the recent period."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "template",
            "run",
            "new_merchants",
            "--param",
            "days=7",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "new_merchants"
    assert payload["row_count"] >= 1
    merchants = [r["merchant_raw"] for r in payload["rows"]]
    assert "NewShop" in merchants
    assert "Starbucks" not in merchants
    row_keys = set(payload["rows"][0])
    assert row_keys.issuperset({"merchant_raw", "transaction_count", "total_spend"})


def test_template_run_spending_comparison(review_data_dir):
    """spending_comparison should return current vs prior period totals."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "template",
            "run",
            "spending_comparison",
            "--param",
            "period_days=7",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "spending_comparison"
    assert payload["row_count"] == 1
    row = payload["rows"][0]
    assert set(row).issuperset(
        {"current_txn_count", "current_spend", "prior_txn_count", "prior_spend", "change_pct"}
    )
    assert row["current_spend"] > row["prior_spend"]


def test_template_run_spending_comparison_defaults(review_data_dir):
    """spending_comparison should use default period_days=7."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "template",
            "run",
            "spending_comparison",
            "--output",
            "json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["template_name"] == "spending_comparison"
    assert payload["row_count"] == 1
