"""Pagination tests for read-oriented CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.csv_transactions import write_month

runner = CliRunner()


def _transaction(index: int, *, month: int = 10) -> dict[str, object]:
    day = (index % 28) + 1
    amount = -1000.0 - index
    return {
        "row_hash": f"row-{month}-{index:03d}",
        "date": f"2024-{month:02d}-{day:02d}",
        "time": "09:00",
        "datetime": f"2024-{month:02d}-{day:02d}T09:00:00",
        "type_raw": "지출",
        "type_norm": "expense",
        "major_raw": "생활",
        "minor_raw": "테스트",
        "merchant_raw": f"Merchant {index:03d}",
        "memo_raw": "",
        "amount": amount,
        "account": "테스트카드",
        "currency": "KRW",
        "counterparty": "",
        "category_rule": "생활",
        "category_final": "생활",
        "tags_rule": [],
        "tags_ai": [],
        "tags_manual": [],
        "tags_final": ["테스트"],
        "confidence": 1.0,
        "needs_review": 0,
        "is_transfer": 0,
        "transfer_group_id": "",
        "file_id": f"241{month:02d}_1",
        "source_row": index,
    }


@pytest.fixture
def paginated_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "metadata").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    write_month(
        data_dir / "transactions",
        pl.DataFrame([_transaction(i, month=10) for i in range(25)]),
        2024,
        10,
    )
    write_month(
        data_dir / "transactions",
        pl.DataFrame([_transaction(i, month=11) for i in range(3)]),
        2024,
        11,
    )
    return data_dir


def _invoke_json(data_dir: Path, args: list[str]) -> dict[str, object]:
    result = runner.invoke(app, ["--data-dir", str(data_dir), *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_query_limit_returns_pagination_envelope(paginated_data_dir: Path) -> None:
    payload = _invoke_json(
        paginated_data_dir,
        [
            "query",
            "SELECT range AS n FROM range(12) ORDER BY n",
            "--json",
            "--limit",
            "10",
        ],
    )

    assert payload["_meta"]["command"] == "query"
    assert payload["row_count"] == 10
    assert len(payload["rows"]) == 10
    assert payload["pagination"]["limit"] == 10
    assert payload["pagination"]["cursor"] == "0"
    assert payload["pagination"]["next_cursor"] == "10"
    assert payload["pagination"]["has_more"] is True


def test_query_paginates_constant_sql_after_init(tmp_path: Path) -> None:
    data_dir = tmp_path / "empty-data"
    init_result = runner.invoke(app, ["--data-dir", str(data_dir), "init"])
    assert init_result.exit_code == 0, init_result.output

    payload = _invoke_json(
        data_dir,
        [
            "query",
            "SELECT 1 AS n UNION ALL SELECT 2 UNION ALL SELECT 3",
            "--json",
            "--limit",
            "2",
        ],
    )

    assert payload["row_count"] == 2
    assert payload["pagination"]["next_cursor"] == "2"


def test_query_cursor_advance(paginated_data_dir: Path) -> None:
    payload = _invoke_json(
        paginated_data_dir,
        [
            "query",
            "SELECT range AS n FROM range(12) ORDER BY n",
            "--json",
            "--limit",
            "5",
            "--cursor",
            "5",
        ],
    )

    assert [row["n"] for row in payload["rows"]] == [5, 6, 7, 8, 9]
    assert payload["pagination"]["cursor"] == "5"
    assert payload["pagination"]["next_cursor"] == "10"


def test_query_has_more_false_on_last_page(paginated_data_dir: Path) -> None:
    payload = _invoke_json(
        paginated_data_dir,
        [
            "query",
            "SELECT range AS n FROM range(12) ORDER BY n",
            "--json",
            "--limit",
            "5",
            "--cursor",
            "10",
        ],
    )

    assert [row["n"] for row in payload["rows"]] == [10, 11]
    assert payload["pagination"]["has_more"] is False
    assert payload["pagination"]["next_cursor"] is None


def test_query_limit_zero_is_valid(paginated_data_dir: Path) -> None:
    payload = _invoke_json(
        paginated_data_dir,
        ["query", "SELECT range AS n FROM range(3)", "--json", "--limit", "0"],
    )

    assert payload["row_count"] == 0
    assert payload["rows"] == []
    assert payload["pagination"]["limit"] == 0


def test_query_invalid_cursor_returns_validation_failed(paginated_data_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(paginated_data_dir),
            "query",
            "SELECT 1",
            "--json",
            "--cursor",
            "not-a-cursor",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "query"
    assert payload["error"]["code"] == "VALIDATION_FAILED"


def test_query_hard_cap_returns_validation_failed(paginated_data_dir: Path) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(paginated_data_dir),
            "query",
            "SELECT 1",
            "--json",
            "--limit",
            "99999",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "query"
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert payload["exit_code"] == 3


def test_query_max_bytes_truncates(paginated_data_dir: Path) -> None:
    payload = _invoke_json(
        paginated_data_dir,
        [
            "query",
            "SELECT repeat('x', 200) AS payload FROM range(50)",
            "--json",
            "--limit",
            "10000",
            "--max-bytes",
            "1024",
        ],
    )

    assert payload["pagination"]["truncated_by_bytes"] is True
    assert payload["row_count"] < 50


def test_show_limit_default_preserved(paginated_data_dir: Path) -> None:
    payload = _invoke_json(paginated_data_dir, ["show", "--month", "2024-10", "--json"])

    assert payload["_meta"]["command"] == "show"
    assert payload["row_count"] == 20
    assert payload["pagination"]["limit"] == 20
    assert payload["pagination"]["has_more"] is True


def test_show_cursor_advance(paginated_data_dir: Path) -> None:
    payload = _invoke_json(
        paginated_data_dir,
        ["show", "--month", "2024-10", "--json", "--limit", "5", "--cursor", "5"],
    )

    assert payload["row_count"] == 5
    assert payload["pagination"]["cursor"] == "5"
    assert payload["pagination"]["next_cursor"] == "10"


def test_template_run_pagination(paginated_data_dir: Path) -> None:
    payload = _invoke_json(
        paginated_data_dir,
        ["template", "run", "monthly_spend", "--json", "--limit", "1"],
    )

    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "monthly_spend"
    assert payload["row_count"] == 1
    assert len(payload["rows"]) == 1
    assert payload["pagination"]["limit"] == 1
    assert payload["pagination"]["next_cursor"] == "1"
    assert payload["pagination"]["has_more"] is True
