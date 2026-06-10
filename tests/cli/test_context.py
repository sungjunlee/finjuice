"""Tests for the `finjuice context` command."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.context import DEFAULT_CONTEXT_BUDGET
from tests.conftest import cli_text

runner = CliRunner()


@pytest.fixture
def context_data_dir(tmp_path: Path) -> Path:
    """Create deterministic data + journal fixtures for context emission tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "metadata").mkdir()

    rows = [
        _transaction_row("2026-02-20", -20_000, "카페", "Cafe Legacy"),
        _transaction_row(
            "2026-03-05",
            3_000_000,
            "급여",
            "회사",
            type_norm="income",
            type_raw="입금",
        ),
        _transaction_row("2026-03-10", -30_000, "교통", "Bus Legacy"),
        _transaction_row("2026-03-25", -80_000, "카페", "Cafe Spring"),
        _transaction_row("2026-03-27", -100_000, "식비", "Grocer March"),
        _transaction_row(
            "2026-04-05",
            3_000_000,
            "급여",
            "회사",
            type_norm="income",
            type_raw="입금",
        ),
        _transaction_row("2026-04-10", -150_000, "카페", "Cafe April"),
        _transaction_row("2026-04-12", -30_000, "식비", "Grocer April"),
        _transaction_row(
            "2026-04-14",
            -100_000,
            "이체",
            "Internal Transfer",
            is_transfer=1,
            type_norm="transfer",
            type_raw="이체",
        ),
    ]

    for month in ("02", "03", "04"):
        month_dir = data_dir / "transactions" / "2026" / month
        month_dir.mkdir(parents=True)
        month_rows = [row for row in rows if row["date"][5:7] == month]
        pl.DataFrame(month_rows).write_csv(month_dir / "transactions.csv")

    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    journal_dir = tmp_path / "_journal"
    journal_dir.mkdir()
    _write_journal(
        journal_dir / "2026-04-15_lifecycle-plan.md",
        created="2026-04-15T09:00:00+09:00",
        topic="lifecycle-plan",
        body="Plan retirement buckets and debt paydown order. " * 8,
    )
    _write_journal(
        journal_dir / "2026-04-14_spending-triage.md",
        created="2026-04-14T18:30:00+09:00",
        topic="spending-triage",
        body="Review recurring spend shifts and shopping volatility. " * 8,
    )
    _write_journal(
        journal_dir / "2026-04-13_rule-cleanup.md",
        created="2026-04-13T08:15:00+09:00",
        topic="rule-cleanup",
        body="Capture merchants that should graduate into report filters. " * 8,
    )
    _write_journal(
        journal_dir / "2026-04-12_midmonth-check.md",
        created="2026-04-12T07:00:00+09:00",
        topic="midmonth-check",
        body="Assess whether the mid-month burn rate is still recoverable. " * 8,
    )
    _write_journal(
        journal_dir / "2026-04-11_april-kickoff.md",
        created="2026-04-11T06:45:00+09:00",
        topic="april-kickoff",
        body="Set the starting constraints for April and freeze unnecessary spend. " * 8,
    )

    return data_dir


def test_context_command_is_registered_in_help() -> None:
    """The root help output should advertise the new top-level command."""
    result = runner.invoke(app, ["--help"])

    assert result.exit_code == 0
    assert "context" in cli_text(result)


def test_context_json_envelope_includes_required_keys(context_data_dir: Path) -> None:
    """`--json` should emit the expected top-level context envelope."""
    result = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))

    assert set(payload) == {
        "journals",
        "status_snapshot",
        "active_goals",
        "financial_metadata",
        "rule_notes",
        "top_patterns",
        "_meta",
    }
    assert payload["active_goals"] == []
    assert payload["financial_metadata"] == {}
    assert payload["rule_notes"] == []
    assert set(payload["journals"][0]) == {
        "path",
        "filename",
        "topic",
        "created",
        "data_range",
        "snapshot",
        "summary_200",
    }
    assert set(payload["top_patterns"][0]) == {"label", "delta_krw", "direction"}
    assert payload["_meta"]["budget"] == DEFAULT_CONTEXT_BUDGET


def test_context_journal_flag_clamps_newest_first(context_data_dir: Path) -> None:
    """`--journal N` should limit output while preserving journal-list ordering."""
    result = runner.invoke(
        app,
        ["--data-dir", str(context_data_dir), "context", "--json", "--journal", "2"],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))

    assert [entry["filename"] for entry in payload["journals"]] == [
        "2026-04-15_lifecycle-plan.md",
        "2026-04-14_spending-triage.md",
    ]


def test_context_budget_truncation_populates_dropped_sections(context_data_dir: Path) -> None:
    """Small budgets should truncate in the documented drop order."""
    result = runner.invoke(
        app,
        ["--data-dir", str(context_data_dir), "context", "--json", "--budget", "120"],
    )

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))

    assert payload["_meta"]["truncated"] is True
    assert payload["_meta"]["dropped_sections"]
    assert payload["_meta"]["dropped_sections"][0] == "top_patterns"
    assert payload["active_goals"] == []


def test_context_budget_flag_overrides_env_and_env_overrides_default(
    context_data_dir: Path,
) -> None:
    """Budget resolution should follow CLI flag > env var > default."""
    env_only = runner.invoke(
        app,
        ["--data-dir", str(context_data_dir), "context", "--json"],
        env={"FINJUICE_CONTEXT_BUDGET": "1234"},
    )
    env_and_flag = runner.invoke(
        app,
        ["--data-dir", str(context_data_dir), "context", "--json", "--budget", "4321"],
        env={"FINJUICE_CONTEXT_BUDGET": "1234"},
    )

    assert env_only.exit_code == 0
    assert env_and_flag.exit_code == 0
    assert json.loads(cli_text(env_only))["_meta"]["budget"] == 1234
    assert json.loads(cli_text(env_and_flag))["_meta"]["budget"] == 4321


def test_context_text_output_is_readable_and_ansi_clean_when_piped(context_data_dir: Path) -> None:
    """Text mode should stay plain and greppable without ANSI escape codes."""
    result = runner.invoke(app, ["--data-dir", str(context_data_dir), "context"])
    output = cli_text(result)

    assert result.exit_code == 0
    assert "\x1b[" not in output
    assert "finjuice context" in output
    assert "Journals" in output
    assert "Status Snapshot" in output
    assert "Financial Metadata" in output
    assert "Rule Notes" in output
    assert "Top Patterns" in output
    assert "Tokens:" in output


def test_context_missing_goals_yaml_returns_empty_list(context_data_dir: Path) -> None:
    """Missing goals.yaml should not fail the command and should emit an empty list."""
    result = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])

    assert result.exit_code == 0
    assert json.loads(cli_text(result))["active_goals"] == []


def test_context_monthly_budget_shape_populates_active_goals(context_data_dir: Path) -> None:
    """The new monthly_budget goals.yaml shape should produce a prompt-friendly label."""
    (context_data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 1800000",
                "  categories:",
                "    식비: 600000",
                "    교통: 150000",
                "    카페: 120000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["active_goals"]
    assert payload["active_goals"][0].startswith("Monthly budget: total ₩1,800,000")


def test_context_net_worth_target_populates_active_goals(context_data_dir: Path) -> None:
    """A valid net_worth_target should appear alongside the monthly budget label."""
    (context_data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "net_worth_target: 3000000000",
                "monthly_budget:",
                "  total: 1800000",
                "  categories:",
                "    식비: 600000",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["active_goals"][1] == "Net worth target: ₩3,000,000,000"


def test_context_recurring_savings_populates_active_goals(context_data_dir: Path) -> None:
    """A valid recurring_savings block should appear in context active goals."""
    (context_data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 1800000",
                "  categories:",
                "    식비: 600000",
                "recurring_savings:",
                "  - label: IRP",
                "    amount: 300000",
                "    frequency: monthly",
                "    tags: [IRP, 정기저축]",
                "  - label: 연금저축",
                "    amount: 2400000",
                "    frequency: yearly",
                "    start_month: 2026-01",
                "    source: goals.yaml",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    assert payload["active_goals"][1] == (
        "Recurring savings: total ₩500,000/mo (IRP ₩300,000/mo, 연금저축 ₩200,000/mo)"
    )
    assert payload["status_snapshot"]["active_goals"] == payload["active_goals"]


def test_context_goals_metadata_and_rule_notes_are_summarized(context_data_dir: Path) -> None:
    """goals.yaml metadata and rule notes should appear without raw transaction rows."""
    (context_data_dir / "goals.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "monthly_budget:",
                "  total: 1800000",
                "  categories:",
                "    식비: 600000",
                "financial_context:",
                "  income:",
                "    monthly_estimate: 5000000",
                '    as_of: "2026-04-20"',
                "  family:",
                "    household_size: 3",
                "    dependents_count: 1",
                "  housing:",
                '    status: "rent"',
                "    monthly_payment: 900000",
                "known_obligations:",
                "  - label: 전세대출 이자",
                "    kind: loan",
                "    amount: 450000",
                "    frequency: monthly",
                '    as_of: "2026-04-20"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (context_data_dir / "rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "rules:",
                "  - name: rent_rule",
                '    match: "임대인"',
                "    fields: [merchant_raw]",
                '    tags: ["주거"]',
                "    category: 주거",
                "    priority: 90",
                "    notes: 월세 후보는 goals.yaml known_obligations에서 확정한다.",
                "",
            ]
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])

    assert result.exit_code == 0
    payload = json.loads(cli_text(result))
    metadata = payload["financial_metadata"]
    assert metadata["financial_context"]["income"]["monthly_estimate"] == 5_000_000
    assert metadata["financial_context"]["family"]["dependents_count"] == 1
    assert metadata["financial_context"]["housing"]["monthly_payment"] == 900_000
    assert metadata["known_obligations"][0]["monthly_amount"] == 450_000
    assert payload["status_snapshot"]["financial_metadata"] == metadata
    assert payload["rule_notes"] == [
        {
            "rule_name": "rent_rule",
            "notes": "월세 후보는 goals.yaml known_obligations에서 확정한다.",
            "tags": ["주거"],
            "category": "주거",
        }
    ]


def test_context_output_is_deterministic_for_fixed_input(context_data_dir: Path) -> None:
    """Repeated runs should emit identical JSON apart from envelope timestamp."""
    first = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])
    second = runner.invoke(app, ["--data-dir", str(context_data_dir), "context", "--json"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    first_payload = json.loads(cli_text(first))
    second_payload = json.loads(cli_text(second))
    assert first_payload["_meta"].pop("timestamp")
    assert second_payload["_meta"].pop("timestamp")
    assert first_payload == second_payload


def _transaction_row(
    date: str,
    amount: int,
    category_final: str,
    merchant_raw: str,
    *,
    is_transfer: int = 0,
    type_norm: str = "expense",
    type_raw: str = "승인",
) -> dict[str, object]:
    """Create a minimal transaction row compatible with the analytics view."""
    row_hash = f"{date}-{merchant_raw}-{amount}"
    return {
        "row_hash": row_hash,
        "date": date,
        "time": "12:00:00",
        "amount": amount,
        "merchant_raw": merchant_raw,
        "category_final": category_final,
        "is_transfer": is_transfer,
        "tags_final": "[]",
        "account": "체크카드",
        "currency": "KRW",
        "type_norm": type_norm,
        "type_raw": type_raw,
    }


def _write_journal(path: Path, *, created: str, topic: str, body: str) -> None:
    """Write a deterministic journal markdown file with snapshot front matter."""
    path.write_text(
        "\n".join(
            [
                "---",
                f'created: "{created}"',
                f"topic: {topic}",
                "data_range: 2026-02-20 ~ 2026-04-14",
                "snapshot:",
                "  monthly_avg_income: 3000000",
                "  monthly_avg_expense: 205000",
                "  savings_rate_3mo: 0.93",
                "  active_filters: 0",
                "  active_goals: []",
                "---",
                "",
                body.strip(),
                "",
            ]
        ),
        encoding="utf-8",
    )
