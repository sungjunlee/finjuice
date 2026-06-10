"""Tests for the `finjuice journal` command group."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import polars as pl
import pytest
import yaml
from typer.testing import CliRunner

import finjuice.pipeline.cli.commands.journal as journal_cmd
import finjuice.pipeline.insights as insights_module
from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()
KST = timezone(timedelta(hours=9))


class _MissingDuckDBAnalytics:
    """DuckDBAnalytics stand-in that always raises the doctor hint."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise ImportError(insights_module.DUCKDB_INSTALL_HINT)


def fail_on_interactive_prompt(*args: object, **kwargs: object) -> None:
    """Fail tests when an interactive prompt is unexpectedly invoked."""
    raise AssertionError("interactive prompt should not be called")


@pytest.fixture
def journal_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with predictable snapshot metrics."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    rows = [
        _transaction_row(
            row_hash="jan-income",
            date="2026-01-05",
            amount=3_000_000.0,
            category_final="급여",
            merchant_raw="회사",
            type_norm="income",
            type_raw="입금",
        ),
        _transaction_row(
            row_hash="jan-expense",
            date="2026-01-06",
            amount=-1_000_000.0,
            category_final="금융",
            merchant_raw="보험사",
        ),
        _transaction_row(
            row_hash="jan-transfer",
            date="2026-01-07",
            amount=-100_000.0,
            category_final="이체",
            merchant_raw="내계좌이체",
            is_transfer=1,
            type_norm="transfer",
            type_raw="이체",
        ),
        _transaction_row(
            row_hash="feb-income",
            date="2026-02-05",
            amount=3_000_000.0,
            category_final="급여",
            merchant_raw="회사",
            type_norm="income",
            type_raw="입금",
        ),
        _transaction_row(
            row_hash="feb-expense",
            date="2026-02-07",
            amount=-1_500_000.0,
            category_final="의료/건강",
            merchant_raw="병원",
        ),
        _transaction_row(
            row_hash="mar-income",
            date="2026-03-05",
            amount=3_000_000.0,
            category_final="급여",
            merchant_raw="회사",
            type_norm="income",
            type_raw="입금",
        ),
        _transaction_row(
            row_hash="mar-expense",
            date="2026-03-08",
            amount=-2_000_000.0,
            category_final="금융",
            merchant_raw="세금",
        ),
        _transaction_row(
            row_hash="apr-income",
            date="2026-04-05",
            amount=3_000_000.0,
            category_final="급여",
            merchant_raw="회사",
            type_norm="income",
            type_raw="입금",
        ),
        _transaction_row(
            row_hash="apr-expense",
            date="2026-04-07",
            amount=-1_800_000.0,
            category_final="주거",
            merchant_raw="월세",
        ),
    ]

    for month in ("01", "02", "03", "04"):
        month_rows = [row for row in rows if row["date"][5:7] == month]
        month_dir = data_dir / "transactions" / "2026" / month
        month_dir.mkdir(parents=True)
        pl.DataFrame(month_rows).write_csv(month_dir / "transactions.csv")

    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "report_filters.yaml").write_text(
        """
filters:
  - name: exclude_meta
    enabled: true
  - name: disabled_example
    enabled: false
""".strip()
        + "\n",
        encoding="utf-8",
    )

    return data_dir


def test_journal_new_creates_snapshot_front_matter_and_matches_status(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`journal new` should create the expected file and snapshot fields."""
    fixed_now = datetime(2026, 4, 15, 12, 34, 56, tzinfo=KST)
    monkeypatch.setattr(journal_cmd, "_now", lambda: fixed_now)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "retirement-planning",
            "--no-gitignore-check",
        ],
    )

    assert result.exit_code == 0
    created_path = _path_from_output(result)
    expected_path = journal_data_dir.parent / "_journal" / "2026-04-15_retirement-planning.md"
    assert created_path == expected_path
    payload = _front_matter(created_path)

    assert payload["created"] == "2026-04-15T12:34:56+09:00"
    assert payload["topic"] == "retirement-planning"
    assert payload["data_range"] == "2026-01-05 ~ 2026-04-07"
    assert set(payload["snapshot"]) == {
        "monthly_avg_income",
        "monthly_avg_expense",
        "savings_rate_3mo",
        "residual_savings_rate_3mo",
        "monthly_avg_consumption_expense",
        "consumption_savings_rate_3mo",
        "structural_savings_monthly_avg",
        "structural_savings_transaction_monthly_avg",
        "recurring_savings_monthly_amount",
        "structural_savings_sources",
        "top_categories",
        "active_filters",
        "active_goals",
    }
    assert payload["snapshot"]["monthly_avg_income"] == 3_000_000
    assert payload["snapshot"]["monthly_avg_expense"] == 1_600_000
    assert payload["snapshot"]["savings_rate_3mo"] == 0.41
    assert payload["snapshot"]["residual_savings_rate_3mo"] == 0.41
    assert payload["snapshot"]["monthly_avg_consumption_expense"] == 1_600_000
    assert payload["snapshot"]["consumption_savings_rate_3mo"] == 0.41
    assert payload["snapshot"]["structural_savings_monthly_avg"] == 0
    assert payload["snapshot"]["structural_savings_transaction_monthly_avg"] == 0
    assert payload["snapshot"]["recurring_savings_monthly_amount"] == 0
    assert payload["snapshot"]["structural_savings_sources"] == []
    assert payload["snapshot"]["active_filters"] == 1
    assert payload["snapshot"]["active_goals"] == []
    assert payload["snapshot"]["top_categories"] == [
        {"name": "금융", "amount": 3_000_000},
        {"name": "주거", "amount": 1_800_000},
        {"name": "의료/건강", "amount": 1_500_000},
        {"name": "이체", "amount": 100_000},
    ]

    status_result = runner.invoke(
        app,
        ["--data-dir", str(journal_data_dir), "status", "--json", "--detailed"],
    )
    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["detailed_stats"]["data_range"] == payload["data_range"]
    assert (
        status_payload["detailed_stats"]["monthly_avg_income"]
        == payload["snapshot"]["monthly_avg_income"]
    )
    assert (
        status_payload["detailed_stats"]["monthly_avg_expense"]
        == payload["snapshot"]["monthly_avg_expense"]
    )
    assert (
        status_payload["detailed_stats"]["savings_rate_3mo"]
        == payload["snapshot"]["savings_rate_3mo"]
    )
    assert (
        status_payload["detailed_stats"]["residual_savings_rate_3mo"]
        == payload["snapshot"]["residual_savings_rate_3mo"]
    )
    assert (
        status_payload["detailed_stats"]["structural_savings_monthly_avg"]
        == payload["snapshot"]["structural_savings_monthly_avg"]
    )
    assert (
        status_payload["detailed_stats"]["top_categories"] == payload["snapshot"]["top_categories"]
    )
    assert (
        status_payload["detailed_stats"]["active_filters"] == payload["snapshot"]["active_filters"]
    )


def test_journal_new_supports_all_templates(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each built-in template should render a distinct body stub."""
    bodies: dict[str, str] = {}
    for offset, template_name in enumerate(("diagnosis", "planning", "retrospective"), start=1):
        monkeypatch.setattr(
            journal_cmd,
            "_now",
            lambda offset=offset: datetime(2026, 4, 15, 9 + offset, 0, 0, tzinfo=KST),
        )
        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(journal_data_dir),
                "journal",
                "new",
                "--topic",
                template_name,
                "--template",
                template_name,
                "--no-gitignore-check",
            ],
        )

        assert result.exit_code == 0
        created_path = _path_from_output(result)
        bodies[template_name] = _body(created_path)

    assert len(set(bodies.values())) == 3
    assert "Current Signal" in bodies["diagnosis"]
    assert "Objective" in bodies["planning"]
    assert "What Worked" in bodies["retrospective"]


def test_journal_new_same_day_same_topic_appends_counter_without_overwriting(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated same-day topic runs should create suffixed filenames."""
    fixed_now = datetime(2026, 4, 15, 10, 0, 0, tzinfo=KST)
    monkeypatch.setattr(journal_cmd, "_now", lambda: fixed_now)

    first = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "smoke",
            "--no-gitignore-check",
        ],
    )
    assert first.exit_code == 0
    first_path = _path_from_output(first)
    first_path.write_text(first_path.read_text(encoding="utf-8") + "\nORIGINAL\n", encoding="utf-8")

    second = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "smoke",
            "--no-gitignore-check",
        ],
    )
    assert second.exit_code == 0
    second_path = _path_from_output(second)

    assert first_path.name == "2026-04-15_smoke.md"
    assert second_path.name == "2026-04-15_smoke_2.md"
    assert "ORIGINAL" in first_path.read_text(encoding="utf-8")


def test_journal_new_without_topic_uses_auto_generated_session_topic(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No `--topic` should create a session-based slug in non-interactive mode."""
    fixed_now = datetime(2026, 4, 15, 12, 34, 56, tzinfo=KST)
    monkeypatch.setattr(journal_cmd, "_now", lambda: fixed_now)

    result = runner.invoke(
        app,
        ["--data-dir", str(journal_data_dir), "journal", "new", "--no-gitignore-check"],
    )

    assert result.exit_code == 0
    created_path = _path_from_output(result)
    assert created_path.name == "2026-04-15_session-20260415-123456.md"
    assert _front_matter(created_path)["topic"] == "session-20260415-123456"


def test_journal_new_normalizes_topic_slug_with_path_separators(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Dangerous topic strings must stay inside the journal directory."""
    fixed_now = datetime(2026, 4, 15, 13, 0, 0, tzinfo=KST)
    monkeypatch.setattr(journal_cmd, "_now", lambda: fixed_now)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "a/b..c",
            "--no-gitignore-check",
        ],
    )

    assert result.exit_code == 0
    created_path = _path_from_output(result)
    assert created_path.parent == (journal_data_dir.parent / "_journal").resolve()
    assert created_path.name == "2026-04-15_a-b-c.md"


def test_journal_list_and_json_are_consistent(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default list output and JSON output should describe the same entries in the same order."""
    monkeypatch.setattr(journal_cmd, "_now", lambda: datetime(2026, 4, 15, 8, 0, 0, tzinfo=KST))
    first = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "alpha",
            "--no-gitignore-check",
        ],
    )
    assert first.exit_code == 0

    monkeypatch.setattr(journal_cmd, "_now", lambda: datetime(2026, 4, 15, 9, 30, 0, tzinfo=KST))
    second = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "beta",
            "--no-gitignore-check",
        ],
    )
    assert second.exit_code == 0
    first_path = _path_from_output(first)
    second_path = _path_from_output(second)

    table_result = runner.invoke(
        app,
        ["--data-dir", str(journal_data_dir), "journal", "list"],
    )
    assert table_result.exit_code == 0

    json_result = runner.invoke(
        app,
        ["--data-dir", str(journal_data_dir), "journal", "list", "--json"],
    )
    assert json_result.exit_code == 0
    payload = json.loads(json_result.output)

    assert payload["_meta"]["command"] == "journal list"
    assert payload["count"] == 2
    assert [entry["topic"] for entry in payload["entries"]] == ["beta", "alpha"]
    assert [entry["path"] for entry in payload["entries"]] == [str(second_path), str(first_path)]
    table_output = cli_text(table_result)
    assert table_output.index(second_path.name) < table_output.index(first_path.name)


def test_journal_resume_uses_newest_entry_and_open_respects_editor(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`resume` should resolve newest first and pass the file to $EDITOR when requested."""
    monkeypatch.setattr(journal_cmd, "_now", lambda: datetime(2026, 4, 15, 8, 0, 0, tzinfo=KST))
    first = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "alpha",
            "--no-gitignore-check",
        ],
    )
    assert first.exit_code == 0

    monkeypatch.setattr(journal_cmd, "_now", lambda: datetime(2026, 4, 16, 8, 0, 0, tzinfo=KST))
    second = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "beta",
            "--no-gitignore-check",
        ],
    )
    assert second.exit_code == 0
    newest_path = _path_from_output(second)

    resume_result = runner.invoke(
        app,
        ["--data-dir", str(journal_data_dir), "journal", "resume"],
    )
    assert resume_result.exit_code == 0
    assert _path_from_output(resume_result) == newest_path

    recorded: list[list[str]] = []

    def fake_run(command: list[str], check: bool = False) -> None:
        recorded.append(command)

    monkeypatch.setattr(journal_cmd.subprocess, "run", fake_run)
    open_result = runner.invoke(
        app,
        ["--data-dir", str(journal_data_dir), "journal", "resume", "beta", "--open"],
        env={"EDITOR": "mock-editor --wait"},
    )
    assert open_result.exit_code == 0
    assert recorded == [["mock-editor", "--wait", str(newest_path)]]
    assert _path_from_output(open_result) == newest_path


def test_journal_resume_with_empty_editor_prints_hint_and_path(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty $EDITOR should not crash resume --open."""
    monkeypatch.setattr(journal_cmd, "_now", lambda: datetime(2026, 4, 15, 8, 0, 0, tzinfo=KST))
    created = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "alpha",
            "--no-gitignore-check",
        ],
    )
    assert created.exit_code == 0
    expected_path = _path_from_output(created)

    result = runner.invoke(
        app,
        ["--data-dir", str(journal_data_dir), "journal", "resume", "--open"],
        env={"EDITOR": ""},
    )

    assert result.exit_code == 0
    assert "$EDITOR is not set" in cli_text(result)
    assert _path_from_output(result) == expected_path


def test_journal_new_skips_gitignore_prompt_in_non_interactive_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Non-interactive invocations must not prompt for gitignore changes."""
    data_dir = tmp_path / "data"
    transactions_dir = data_dir / "transactions" / "2026" / "04"
    transactions_dir.mkdir(parents=True)
    pl.DataFrame([_transaction_row("txn", "2026-04-01", -10_000.0, "식비", "가맹점")]).write_csv(
        transactions_dir / "transactions.csv"
    )
    (tmp_path / ".git").mkdir()
    monkeypatch.setattr(journal_cmd.typer, "confirm", fail_on_interactive_prompt)
    monkeypatch.setattr(journal_cmd, "_now", lambda: datetime(2026, 4, 15, 8, 0, 0, tzinfo=KST))

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "journal", "new", "--topic", "skip-check"],
    )

    assert result.exit_code == 0
    assert not (tmp_path / ".gitignore").exists()


def test_journal_new_without_duckdb_still_writes_valid_yaml_with_null_analytics(
    journal_data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing DuckDB should null-fill analytics fields without breaking front matter."""
    monkeypatch.setattr(journal_cmd, "_now", lambda: datetime(2026, 4, 15, 7, 0, 0, tzinfo=KST))
    monkeypatch.setattr(insights_module, "DuckDBAnalytics", _MissingDuckDBAnalytics)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(journal_data_dir),
            "journal",
            "new",
            "--topic",
            "duckdb-missing",
            "--no-gitignore-check",
        ],
    )

    assert result.exit_code == 0
    created_path = _path_from_output(result)
    payload = _front_matter(created_path)

    assert payload["data_range"] == "2026-01-05 ~ 2026-04-07"
    assert payload["snapshot"]["monthly_avg_income"] is None
    assert payload["snapshot"]["monthly_avg_expense"] is None
    assert payload["snapshot"]["savings_rate_3mo"] is None
    assert payload["snapshot"]["residual_savings_rate_3mo"] is None
    assert payload["snapshot"]["monthly_avg_consumption_expense"] is None
    assert payload["snapshot"]["consumption_savings_rate_3mo"] is None
    assert payload["snapshot"]["structural_savings_monthly_avg"] == 0
    assert payload["snapshot"]["structural_savings_transaction_monthly_avg"] == 0
    assert payload["snapshot"]["recurring_savings_monthly_amount"] == 0
    assert payload["snapshot"]["structural_savings_sources"] == []
    assert payload["snapshot"]["top_categories"] is None
    assert payload["snapshot"]["active_filters"] == 1
    assert payload["snapshot"]["active_goals"] == []
    assert "Detailed analytics unavailable" in cli_text(result)


def _transaction_row(
    row_hash: str,
    date: str,
    amount: float,
    category_final: str,
    merchant_raw: str,
    *,
    is_transfer: int = 0,
    type_norm: str = "expense",
    type_raw: str = "지출",
) -> dict[str, object]:
    """Build a schema-compatible transaction row for journal tests."""
    return {
        "row_hash": row_hash,
        "date": date,
        "time": "09:00",
        "type_raw": type_raw,
        "type_norm": type_norm,
        "major_raw": category_final,
        "minor_raw": category_final,
        "merchant_raw": merchant_raw,
        "memo_raw": None,
        "amount": amount,
        "account": "테스트계좌",
        "currency": "KRW",
        "counterparty": None,
        "datetime": f"{date}T09:00:00",
        "tags_rule": "[]",
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": "[]",
        "category_rule": category_final,
        "category_final": category_final,
        "confidence": 0.9,
        "needs_review": 0,
        "is_transfer": is_transfer,
        "transfer_group_id": None,
        "file_id": f"{date.replace('-', '')}_1",
        "source_row": 1,
    }


def _front_matter(path: Path) -> dict[str, object]:
    """Parse the leading YAML block from a journal file."""
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, front_matter, _ = text.split("---\n", 2)
    payload = yaml.safe_load(front_matter)
    assert isinstance(payload, dict)
    return payload


def _body(path: Path) -> str:
    """Return the markdown body after the front matter block."""
    text = path.read_text(encoding="utf-8")
    parts = text.split("---\n", 2)
    assert len(parts) == 3
    return parts[2].strip()


def _path_from_output(result: object) -> Path:
    """Resolve the final printed path from CLI output."""
    lines = [line.strip() for line in cli_text(result).splitlines() if line.strip()]
    return Path(lines[-1]).resolve()
