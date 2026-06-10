"""Tests for the networth CLI command group."""

import json
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands.networth import _select_projection_rows
from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _init_data_dir(tmp_path: Path, name: str = "data") -> Path:
    """Create a minimal initialized finjuice data directory."""
    data_dir = tmp_path / name
    data_dir.mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "transactions").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def _write_snapshot(data_dir: Path, month: str, rows: list[dict[str, object]]) -> None:
    """Write an asset snapshot partition for tests."""
    year, mon = month.split("-")
    partition_dir = data_dir / "assets" / "snapshots" / year / mon
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "snapshots.csv")


def _write_assets_yaml(data_dir: Path, raw_text: str) -> None:
    """Write assets.yaml into a test data directory."""
    (data_dir / "assets.yaml").write_text(raw_text, encoding="utf-8")


def _write_scenarios_yaml(data_dir: Path) -> None:
    """Write scenarios.yaml into a test data directory."""
    (data_dir / "scenarios.yaml").write_text(
        """version: 1
assumptions:
  default_savings_per_month: 2000000
  asset_returns:
    real_estate:
      conservative: 0.01
      neutral: 0.03
      optimistic: 0.05
    financial:
      conservative: 0.02
      neutral: 0.06
      optimistic: 0.1
    deposit:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    cash:
      conservative: 0.0
      neutral: 0.02
      optimistic: 0.04
  liability_rate_delta: -0.005
lifecycle_events:
  - name: 이사 준비
    date: "2026-05-10"
    one_time_expense: 10000000
  - name: 생활비 증가
    start: "2026-06-10"
    end: "2026-07-10"
    monthly_net_expense: 500000
""",
        encoding="utf-8",
    )


def _build_populated_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with snapshots and assets.yaml."""
    data_dir = _init_data_dir(tmp_path, "populated")

    _write_snapshot(
        data_dir,
        "2026-01",
        [
            {
                "snapshot_date": "2026-01-31",
                "account_id": "증권계좌",
                "instrument_id": "인덱스펀드",
                "quantity": 100.0,
                "market_value": 110000000.0,
                "currency": "KRW",
                "file_id": "260131_1",
                "source_row": 1,
            },
            {
                "snapshot_date": "2026-01-31",
                "account_id": "증권계좌",
                "instrument_id": "정기예금",
                "quantity": 1.0,
                "market_value": 170000000.0,
                "currency": "KRW",
                "file_id": "260131_1",
                "source_row": 2,
            },
        ],
    )
    _write_snapshot(
        data_dir,
        "2026-03",
        [
            {
                "snapshot_date": "2026-03-15",
                "account_id": "증권계좌",
                "instrument_id": "인덱스펀드",
                "quantity": 120.0,
                "market_value": 140000000.0,
                "currency": "KRW",
                "file_id": "260315_1",
                "source_row": 1,
            },
            {
                "snapshot_date": "2026-03-15",
                "account_id": "증권계좌",
                "instrument_id": "정기예금",
                "quantity": 1.0,
                "market_value": 180000000.0,
                "currency": "KRW",
                "file_id": "260315_1",
                "source_row": 2,
            },
            {
                "snapshot_date": "2026-03-15",
                "account_id": "미래에셋",
                "instrument_id": "USD Cash",
                "quantity": 1.0,
                "market_value": 40000000.0,
                "currency": "KRW",
                "file_id": "260315_1",
                "source_row": 3,
            },
        ],
    )
    _write_snapshot(
        data_dir,
        "2026-04",
        [
            {
                "snapshot_date": "2026-04-05",
                "account_id": "증권계좌",
                "instrument_id": "인덱스펀드",
                "quantity": 125.0,
                "market_value": 145000000.0,
                "currency": "KRW",
                "file_id": "260405_1",
                "source_row": 1,
            },
            {
                "snapshot_date": "2026-04-10",
                "account_id": "증권계좌",
                "instrument_id": "인덱스펀드",
                "quantity": 130.0,
                "market_value": 150000000.0,
                "currency": "KRW",
                "file_id": "260410_1",
                "source_row": 1,
            },
            {
                "snapshot_date": "2026-04-10",
                "account_id": "증권계좌",
                "instrument_id": "정기예금",
                "quantity": 1.0,
                "market_value": 200000000.0,
                "currency": "KRW",
                "file_id": "260410_1",
                "source_row": 2,
            },
            {
                "snapshot_date": "2026-04-10",
                "account_id": "미래에셋",
                "instrument_id": "USD Cash",
                "quantity": 1.0,
                "market_value": 50000000.0,
                "currency": "KRW",
                "file_id": "260410_1",
                "source_row": 3,
            },
        ],
    )
    _write_assets_yaml(
        data_dir,
        """version: 1
manual_assets:
  - name: 거주 부동산
    category: real_estate
    value: 1850000000
  - name: 정기예금
    category: deposit
    value: 250000000
  - name: 현금 비상금
    category: cash
    value: 15000000
liabilities:
  - name: 담보대출
    principal: 150000000
    rate: 3.6
    type: mortgage
""",
    )

    return data_dir


def test_networth_json_happy_path(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(app, ["--data-dir", str(data_dir), "networth", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["as_of"] == "2026-04-10"
    assert payload["total_assets"] == 2315000000.0
    assert payload["total_liabilities"] == 150000000.0
    assert payload["net_worth"] == 2165000000.0
    assert payload["_meta"]["filters_applied"] == 0
    assert payload["_meta"]["as_of"] == "2026-04-10"
    assert payload["health"] == {
        "status": "ok",
        "reasons": [],
    }
    assert payload["actionable"] is False
    assert payload["signals"] == {
        "snapshot_status": "snapshot_and_manual",
        "has_snapshot_data": True,
        "has_manual_assets": True,
        "has_liabilities": True,
        "asset_count": 5,
        "liability_count": 1,
        "net_worth_negative": False,
    }
    assert payload["next_steps"] == []


def test_networth_snapshot_only_without_assets_yaml(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "snapshot-only")
    _write_snapshot(
        data_dir,
        "2026-04",
        [
            {
                "snapshot_date": "2026-04-10",
                "account_id": "증권계좌",
                "instrument_id": "인덱스펀드",
                "quantity": 1.0,
                "market_value": 150000000.0,
                "currency": "KRW",
                "file_id": "260410_1",
                "source_row": 1,
            }
        ],
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "networth", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["as_of"] == "2026-04-10"
    assert payload["total_assets"] == 150000000.0
    assert payload["total_liabilities"] == 0.0
    assert payload["net_worth"] == 150000000.0
    assert payload["health"] == {
        "status": "warning",
        "reasons": ["snapshot_only"],
    }
    assert payload["actionable"] is True
    assert payload["next_steps"] == [
        {
            "signal": "snapshot_only",
            "message": (
                "Add manual assets or liabilities if snapshots do not cover the full balance sheet."
            ),
            "command": "finjuice assets status --json",
        }
    ]


def test_networth_manual_only_when_no_snapshot_exists_for_date(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "manual-only")
    _write_assets_yaml(
        data_dir,
        """version: 1
manual_assets:
  - name: 거주 부동산
    category: real_estate
    value: 1850000000
liabilities:
  - name: 담보대출
    principal: 150000000
""",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "--date", "2026-01-01", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["as_of"] == "2026-01-01"
    assert payload["total_assets"] == 1850000000.0
    assert payload["total_liabilities"] == 150000000.0
    assert payload["net_worth"] == 1700000000.0
    assert payload["health"] == {
        "status": "warning",
        "reasons": ["snapshot_missing"],
    }
    assert payload["actionable"] is True
    assert payload["signals"]["snapshot_status"] == "manual_only"


def test_networth_dedup_prefers_manual_asset_over_snapshot(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "breakdown", "--by", "asset", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    by_name = {row["asset_name"]: row for row in payload["breakdown"]}
    assert by_name["정기예금"]["value"] == 250000000.0
    assert "거주 부동산" in by_name
    assert by_name["인덱스펀드"]["value"] == 150000000.0


def test_networth_breakdown_accepts_local_date_option(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "networth",
            "breakdown",
            "--by",
            "category",
            "--date",
            "2026-03-20",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["as_of"] == "2026-03-20"
    assert payload["_meta"]["as_of"] == "2026-03-20"
    categories = {row["category"]: row["value"] for row in payload["breakdown"]}
    assert categories["deposit"] == 250000000.0
    assert categories["financial"] == 180000000.0
    assert categories["cash"] == 15000000.0
    assert categories["real_estate"] == 1850000000.0


def test_networth_breakdown_inherits_parent_date_option(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "networth",
            "--date",
            "2026-03-20",
            "breakdown",
            "--by",
            "asset",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["as_of"] == "2026-03-20"
    assert payload["_meta"]["as_of"] == "2026-03-20"
    by_name = {row["asset_name"]: row["value"] for row in payload["breakdown"]}
    assert by_name["인덱스펀드"] == 140000000.0
    assert by_name["정기예금"] == 250000000.0
    assert by_name["USD Cash"] == 40000000.0


def test_networth_liabilities_only_can_be_negative(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "liabilities-only")
    _write_assets_yaml(
        data_dir,
        """version: 1
liabilities:
  - name: 신용대출
    principal: 50000000
""",
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "networth", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["total_assets"] == 0.0
    assert payload["total_liabilities"] == 50000000.0
    assert payload["net_worth"] == -50000000.0
    assert payload["health"] == {
        "status": "warning",
        "reasons": ["snapshot_missing", "negative_net_worth"],
    }
    assert payload["actionable"] is True
    assert payload["next_steps"] == [
        {
            "signal": "snapshot_missing",
            "message": "Capture an asset snapshot or confirm assets.yaml coverage.",
            "command": "finjuice assets status --json",
        },
        {
            "signal": "negative_net_worth",
            "message": "Inspect the balance-sheet mix behind the negative position.",
            "command": "finjuice networth breakdown --by category --json",
        },
    ]


def test_networth_validate_rejects_unknown_category_with_line_number(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "invalid-category")
    _write_assets_yaml(
        data_dir,
        """version: 1
manual_assets:
  - name: 비트코인
    category: crypto
    value: 1000000
""",
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "networth", "validate"])

    assert result.exit_code == 1
    assert "Line 4" in result.output
    assert "manual_assets[0].category" in result.output


def test_networth_validate_json_uses_standard_validation_envelope(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "invalid-category-json")
    _write_assets_yaml(
        data_dir,
        """version: 1
manual_assets:
  - name: 비트코인
    category: crypto
    value: 1000000
""",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "validate", "--json"],
    )

    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["valid"] is False
    assert payload["status"] == "issues"
    assert payload["errors"] == 1
    assert payload["warnings"] == 0
    assert len(payload["problems"]) == 1
    assert payload["problems"][0]["severity"] == "error"
    assert payload["problems"][0]["type"] == "invalid_assets_config"
    assert payload["problems"][0]["path"] == "manual_assets[0].category"
    assert payload["problems"][0]["line"] == 4
    assert "Line 4" in payload["problems"][0]["formatted"]


def test_networth_runtime_rejects_invalid_assets_yaml(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "runtime-invalid")
    _write_assets_yaml(
        data_dir,
        """version: 1
manual_assets:
  - name: 비트코인
    category: crypto
    value: 1000000
""",
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "networth", "--json"])

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "Line 4" in payload["error"]["message"]


def test_networth_commands_ignore_invalid_rules_yaml(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)
    (data_dir / "rules.yaml").write_text("version: 1\nrules: [\n", encoding="utf-8")

    command_matrix = [
        (["networth", "--json"], "net_worth"),
        (["networth", "breakdown", "--by", "asset", "--json"], "breakdown"),
        (["networth", "history", "--months", "6", "--json"], "history"),
    ]

    for args, expected_key in command_matrix:
        result = runner.invoke(app, ["--data-dir", str(data_dir), *args])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert expected_key in payload


def test_networth_date_boundary_picks_latest_snapshot_on_or_before_date(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "--date", "2026-03-20", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["as_of"] == "2026-03-20"
    assert payload["_meta"]["as_of"] == "2026-03-20"
    assert payload["total_assets"] == 2295000000.0


def test_networth_breakdown_category_shares_sum_to_approximately_100(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "breakdown", "--by", "category", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    share_sum = sum(row["share_pct"] for row in payload["breakdown"])
    assert abs(share_sum - 100.0) <= 1.0
    assert payload["_meta"]["filters_applied"] == 0
    assert payload["_meta"]["as_of"] == "2026-04-10"


def test_networth_history_truncates_when_fewer_months_exist(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "history", "--months", "6", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert len(payload["history"]) == 3
    assert [row["as_of"] for row in payload["history"]] == [
        "2026-01-31",
        "2026-03-15",
        "2026-04-10",
    ]
    assert payload["_meta"]["as_of"] == "2026-04-10"


def test_networth_text_output_preserves_negative_sign(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "negative-text")
    _write_snapshot(
        data_dir,
        "2026-04",
        [
            {
                "snapshot_date": "2026-04-10",
                "account_id": "증권계좌",
                "instrument_id": "인덱스펀드",
                "quantity": 1.0,
                "market_value": 10000000.0,
                "currency": "KRW",
                "file_id": "260410_1",
                "source_row": 1,
            }
        ],
    )
    _write_assets_yaml(
        data_dir,
        """version: 1
liabilities:
  - name: 신용대출
    principal: 50000000
""",
    )

    networth_result = runner.invoke(app, ["--data-dir", str(data_dir), "networth"])
    history_result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "history", "--months", "1"],
    )

    assert networth_result.exit_code == 0
    assert history_result.exit_code == 0
    assert "-₩40,000,000" in networth_result.output
    assert "-₩40,000,000" in history_result.output


def test_networth_empty_envelope_when_no_assets_exist(tmp_path: Path) -> None:
    data_dir = _init_data_dir(tmp_path, "empty")

    result = runner.invoke(app, ["--data-dir", str(data_dir), "networth", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["as_of"] is None
    assert payload["total_assets"] == 0.0
    assert payload["total_liabilities"] == 0.0
    assert payload["net_worth"] == 0.0
    assert payload["_meta"]["filters_applied"] == 0
    assert payload["health"] == {
        "status": "critical",
        "reasons": ["no_asset_data"],
    }
    assert payload["actionable"] is True
    assert payload["signals"] == {
        "snapshot_status": "empty",
        "has_snapshot_data": False,
        "has_manual_assets": False,
        "has_liabilities": False,
        "asset_count": 0,
        "liability_count": 0,
        "net_worth_negative": False,
    }
    assert payload["next_steps"] == [
        {
            "signal": "no_asset_data",
            "message": "Capture an asset snapshot or confirm assets.yaml coverage.",
            "command": "finjuice assets status --json",
        }
    ]


def test_networth_validate_succeeds_for_valid_assets_yaml(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "validate", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["valid"] is True
    assert payload["status"] == "valid"
    assert payload["manual_assets"] == 3
    assert payload["liabilities"] == 1
    assert payload["errors"] == 0
    assert payload["warnings"] == 0
    assert payload["problems"] == []


def test_networth_init_creates_assets_yaml(tmp_path: Path) -> None:
    """networth init should create a starter assets.yaml from template."""
    data_dir = _init_data_dir(tmp_path, "init-test")

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "init", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["created"] is True
    assert str(data_dir) in payload["path"]

    assets_yaml = data_dir / "assets.yaml"
    assert assets_yaml.exists()
    content = assets_yaml.read_text()
    assert "version:" in content
    assert "manual_assets:" in content
    assert "liabilities:" in content


def test_networth_init_idempotent(tmp_path: Path) -> None:
    """networth init should not overwrite an existing assets.yaml."""
    data_dir = _init_data_dir(tmp_path, "init-idem")
    (data_dir / "assets.yaml").write_text("custom data", encoding="utf-8")

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "init", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["created"] is False

    content = (data_dir / "assets.yaml").read_text()
    assert content == "custom data"


def test_networth_forecast_json_happy_path(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)
    _write_scenarios_yaml(data_dir)
    (data_dir / "goals.yaml").write_text(
        """version: 1
net_worth_target: 2300000000
monthly_budget:
  total: 2000000
  categories:
    식비: 700000
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "forecast", "--years", "2", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "networth forecast"
    assert payload["_meta"]["scenario"] == "neutral"
    assert payload["_meta"]["years"] == 2
    assert payload["_meta"]["start_date"] == "2026-04-10"
    assert payload["scenario"] == "neutral"
    assert len(payload["projections"]) == 25
    assert payload["projections"][0]["date"] == "2026-04-10"
    assert payload["projections"][1]["events_fired"] == [
        {
            "name": "이사 준비",
            "type": "one_time_expense",
            "effective_date": "2026-05-10",
        }
    ]
    assert payload["summary"]["start_net_worth"] == 2165000000.0
    assert payload["summary"]["end_net_worth"] > payload["summary"]["start_net_worth"]
    assert payload["summary"]["target_net_worth"] == 2300000000
    assert payload["summary"]["target_reached"] is True
    assert payload["summary"]["target_reached_at"] is not None


def test_networth_forecast_all_scenarios_orders_end_values(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)
    _write_scenarios_yaml(data_dir)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "networth",
            "forecast",
            "--scenario",
            "all",
            "--years",
            "1",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["_meta"]["scenario"] == "all"
    assert set(payload["scenarios"]) == {"conservative", "neutral", "optimistic"}
    assert all(
        scenario_payload["summary"]["target_reached"] is None
        for scenario_payload in payload["scenarios"].values()
    )
    end_values = {
        scenario_name: scenario_payload["summary"]["end_net_worth"]
        for scenario_name, scenario_payload in payload["scenarios"].items()
    }
    assert end_values["conservative"] < end_values["neutral"] < end_values["optimistic"]


def test_networth_forecast_all_scenarios_text_hides_goal_status_without_target(
    tmp_path: Path,
) -> None:
    data_dir = _build_populated_data_dir(tmp_path)
    _write_scenarios_yaml(data_dir)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "networth",
            "forecast",
            "--scenario",
            "all",
            "--years",
            "1",
        ],
    )

    assert result.exit_code == 0
    assert "Scenario Comparison" in result.output
    assert "Reached" not in result.output


def test_networth_forecast_requires_scenarios_yaml(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "forecast", "--json"],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "scenarios.yaml" in payload["error"]["message"]


def test_networth_forecast_rejects_invalid_goals_yaml(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)
    _write_scenarios_yaml(data_dir)
    (data_dir / "goals.yaml").write_text(
        """version: 1
monthly_budget:
  total: invalid
  categories:
    식비: 700000
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "forecast", "--json"],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "goals.yaml is invalid" in payload["error"]["message"]
    assert "monthly_budget.total" in payload["error"]["message"]


def test_networth_forecast_accepts_signed_lifecycle_cashflows(tmp_path: Path) -> None:
    data_dir = _build_populated_data_dir(tmp_path)
    (data_dir / "scenarios.yaml").write_text(
        """version: 1
assumptions:
  default_savings_per_month: 0
  asset_returns:
    real_estate:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    financial:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    deposit:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
    cash:
      conservative: 0.0
      neutral: 0.0
      optimistic: 0.0
  liability_rate_delta: 0.0
lifecycle_events:
  - name: Bonus
    date: "2026-05-10"
    one_time_expense: -2000000
""",
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "networth", "forecast", "--years", "1", "--json"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["projections"][1]["events_fired"] == [
        {
            "name": "Bonus",
            "type": "one_time_expense",
            "effective_date": "2026-05-10",
        }
    ]
    assert payload["projections"][1]["net_worth"] > payload["summary"]["start_net_worth"]


def test_select_projection_rows_for_long_horizons_keeps_yearly_checkpoints_and_events() -> None:
    projections = [
        {
            "date": f"2026-{((index % 12) + 1):02d}-01",
            "events_fired": [],
        }
        for index in range(37)
    ]
    projections[5]["events_fired"] = [{"name": "Bonus"}]
    projections[18]["events_fired"] = [{"name": "Move"}]

    selected = _select_projection_rows(projections)

    assert selected[0]["date"] == projections[0]["date"]
    assert projections[5] in selected
    assert projections[12] in selected
    assert projections[18] in selected
    assert projections[24] in selected
    assert selected[-1]["date"] == projections[-1]["date"]
    assert projections[11] not in selected
