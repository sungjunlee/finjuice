import importlib
import json
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import patch

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.analytics.install_hints import DUCKDB_DOCTOR_HINT
from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


def _reload_module(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def _assert_query_output(output: str) -> None:
    payload = json.loads(output)
    assert payload["rows"][0]["total"] == 3


def _assert_template_output(output: str) -> None:
    payload = json.loads(output)
    assert payload["_meta"]["command"] == "template run"
    assert payload["template_name"] == "monthly_spend"
    assert payload["row_count"] == 1
    assert payload["rows"][0]["month"] == "2024-10"
    assert payload["rows"][0]["transaction_count"] == 3


def _assert_explain_output(output: str) -> None:
    payload = json.loads(output)
    assert payload["transaction"]["merchant_raw"] == "Starbucks"
    assert payload["classification"]["matched_rules"] == ["coffee"]


class _MissingDuckDBAnalytics:
    """DuckDBAnalytics stand-in that always raises the doctor hint."""

    def __init__(self, *_args, **_kwargs) -> None:
        raise ImportError(DUCKDB_DOCTOR_HINT)


@pytest.fixture
def analytics_data_dir(tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    month_dir = data_dir / "transactions" / "2024" / "10"
    month_dir.mkdir(parents=True)

    df = pl.DataFrame(
        {
            "date": ["2024-10-01", "2024-10-02", "2024-10-03"],
            "time": ["08:30", "12:00", "18:15"],
            "merchant_raw": ["Starbucks", "Netflix", "Coupang"],
            "amount": [-5000, -15000, -30000],
            "memo_raw": ["Coffee", "Subscription", "Shopping"],
            "major_raw": ["Food", "Living", "Shopping"],
            "minor_raw": ["Cafe", "Sub", "Online"],
            "type_norm": ["expense", "expense", "expense"],
            "is_transfer": [0, 0, 0],
            "tags_final": [json.dumps(["cafe"]), json.dumps([]), json.dumps(["shopping"])],
            "category_final": ["Cafe", "Entertainment", "Shopping"],
            "account": ["Card A", "Card A", "Card B"],
        }
    )
    df.write_csv(month_dir / "transactions.csv")

    (data_dir / "rules.yaml").write_text(
        """
version: 1
rules:
  - name: coffee
    match: "Starbucks"
    fields: ["merchant_raw"]
    tags: ["cafe"]
    priority: 50
""".strip(),
        encoding="utf-8",
    )

    return data_dir


def test_duckdb_analytics_raises_helpful_import_error_when_extra_missing() -> None:
    with patch.dict(sys.modules, {"duckdb": None}):
        layer = _reload_module("finjuice.pipeline.analytics.duckdb_layer")

        assert layer.DUCKDB_AVAILABLE is False

        with pytest.raises(ImportError, match="finjuice doctor"):
            layer.DuckDBAnalytics(Path("unused"))

    _reload_module("finjuice.pipeline.analytics.duckdb_layer")


@pytest.mark.parametrize(
    "argv",
    [
        ["query", "SELECT COUNT(*) AS total FROM transactions"],
        ["template", "run", "monthly_spend"],
        ["explain", "Starbucks"],
        [
            "rules",
            "add",
            "--name",
            "coffee_preview",
            "--match",
            "Starbucks",
            "--tags",
            "cafe",
            "--dry-run",
        ],
    ],
    ids=["query", "template-run", "explain", "rules-add-dry-run"],
)
def test_analytics_commands_point_to_doctor_when_duckdb_missing(
    analytics_data_dir: Path,
    argv: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import finjuice.pipeline.analytics.duckdb_layer as duckdb_layer
    import finjuice.pipeline.cli.commands.explain as explain_cmd
    import finjuice.pipeline.cli.commands.query as query_cmd
    import finjuice.pipeline.cli.commands.template_cmd as template_cmd

    monkeypatch.setattr(query_cmd, "DuckDBAnalytics", _MissingDuckDBAnalytics)
    monkeypatch.setattr(explain_cmd, "DuckDBAnalytics", _MissingDuckDBAnalytics)
    monkeypatch.setattr(template_cmd, "DuckDBAnalytics", _MissingDuckDBAnalytics)
    monkeypatch.setattr(duckdb_layer, "DuckDBAnalytics", _MissingDuckDBAnalytics)

    result = runner.invoke(app, ["--data-dir", str(analytics_data_dir), *argv])

    assert result.exit_code == 1
    assert DUCKDB_DOCTOR_HINT in cli_text(result)
    assert "finjuice doctor" in cli_text(result)
    assert "Query execution failed:" not in cli_text(result)
    assert "Template execution failed:" not in cli_text(result)
    assert "Search failed:" not in cli_text(result)


@pytest.mark.parametrize(
    ("argv", "validator"),
    [
        (
            [
                "query",
                "SELECT COUNT(*) AS total FROM transactions",
                "--json",
            ],
            _assert_query_output,
        ),
        (
            [
                "template",
                "run",
                "monthly_spend",
                "--output",
                "json",
            ],
            _assert_template_output,
        ),
        (
            [
                "explain",
                "Starbucks",
                "--json",
            ],
            _assert_explain_output,
        ),
    ],
    ids=["query", "template", "explain"],
)
def test_analytics_commands_work_when_duckdb_installed(
    analytics_data_dir: Path,
    argv: list[str],
    validator: Callable[[str], None],
) -> None:
    pytest.importorskip("duckdb")

    result = runner.invoke(app, ["--data-dir", str(analytics_data_dir), *argv])

    assert result.exit_code == 0
    validator(result.output)
