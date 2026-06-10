"""Focused CLI tests for `finjuice automation run`."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config_file import save_config
from finjuice.pipeline.config_schema import (
    AutomationConfig,
    AutomationThresholdsConfig,
    DataConfig,
    UserConfig,
)

runner = CliRunner()


def _set_home(monkeypatch, tmp_path: Path) -> Path:
    """Point Path.home() to an isolated temporary directory."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: home)
    return home


def _write_sample_transactions(data_dir: Path) -> None:
    """Create a minimal partition with untagged pressure and one large expense."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "row_hash": ["r1", "r2", "r3", "r4", "r5"],
            "date": ["2024-10-01", "2024-10-03", "2024-10-05", "2024-10-07", "2024-10-08"],
            "time": ["09:00", "09:15", "12:00", "20:10", "08:00"],
            "merchant_raw": ["스타벅스", "스타벅스", "넷플릭스", "항공사", "내계좌이체"],
            "memo_raw": ["아이스 아메리카노", "", "정기결제", "출장", ""],
            "amount": [-4500.0, -5200.0, -17000.0, -800000.0, -120000.0],
            "account": ["신한카드", "신한카드", "현대카드", "기업카드", "신한은행"],
            "major_raw": ["식비", "식비", "구독", "여행", "이체"],
            "minor_raw": ["카페", "카페", "동영상", "항공", "이체"],
            "category_final": ["", "", "구독", "", "이체"],
            "category_rule": ["", "", "구독", "", ""],
            "tags_final": ["[]", "[]", '["구독"]', "[]", "[]"],
            "is_transfer": [0, 0, 0, 0, 1],
        }
    ).write_csv(partition_dir / "transactions.csv")


def _write_tagged_transactions(data_dir: Path) -> None:
    """Create a minimal partition with fully tagged transactions."""
    partition_dir = data_dir / "transactions" / "2024" / "11"
    partition_dir.mkdir(parents=True, exist_ok=True)

    pl.DataFrame(
        {
            "row_hash": ["r10", "r11"],
            "date": ["2024-11-01", "2024-11-02"],
            "time": ["09:00", "18:30"],
            "merchant_raw": ["편의점", "급여"],
            "memo_raw": ["간식", "월급"],
            "amount": [-3200.0, 2_500_000.0],
            "account": ["체크카드", "급여통장"],
            "major_raw": ["식비", "수입"],
            "minor_raw": ["편의점", "급여"],
            "category_final": ["식비", "급여"],
            "category_rule": ["식비", "급여"],
            "tags_final": ['["식비"]', '["급여"]'],
            "is_transfer": [0, 0],
        }
    ).write_csv(partition_dir / "transactions.csv")


def _build_data_dir(tmp_path: Path) -> Path:
    """Create a minimal data directory for automation-run tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "exports" / "reports").mkdir(parents=True)
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    _write_sample_transactions(data_dir)
    shutil.copy(Path("tests/fixtures/sample_banksalad.xlsx"), data_dir / "imports" / "staged.xlsx")
    return data_dir


def _build_clean_data_dir(tmp_path: Path) -> Path:
    """Create a minimal data directory with tagged transactions and no pending imports."""
    data_dir = tmp_path / "clean-data"
    data_dir.mkdir()
    (data_dir / "imports").mkdir()
    (data_dir / "exports" / "reports").mkdir(parents=True)
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

    _write_tagged_transactions(data_dir)
    return data_dir


def test_automation_run_json_uses_config_thresholds(monkeypatch, tmp_path: Path) -> None:
    """JSON output should use config-backed thresholds and filtered next steps."""
    _set_home(monkeypatch, tmp_path)
    data_dir = _build_data_dir(tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=5,
                    large_transaction=900_000,
                ),
            ),
            _automation_explicit=True,
        )
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "automation", "run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)

    assert payload["_meta"]["command"] == "automation run"
    assert payload["enabled"] is True
    assert payload["actionable"] is True
    assert payload["thresholds"] == {
        "untagged_count": 5,
        "large_transaction": 900_000,
    }

    assert payload["pending_imports"]["status"] == "present"
    assert payload["tagging_pressure"]["untagged_transactions"] == 4
    assert payload["tagging_pressure"]["suggestable_untagged_transactions"] == 4
    assert payload["tagging_pressure"]["transfer_excluded_untagged_transactions"] == 0
    assert payload["tagging_pressure"]["threshold"] == 5
    assert payload["tagging_pressure"]["threshold_basis"] == "suggestable_untagged_transactions"
    assert payload["tagging_pressure"]["threshold_exceeded"] is False
    assert payload["large_transactions"]["threshold"] == 900_000
    assert payload["large_transactions"]["status"] == "clear"

    commands = [hint["command"] for hint in payload["next_steps"]]
    assert commands == ["finjuice refresh"]


def test_automation_run_help_exposes_privacy_option(tmp_path: Path) -> None:
    """automation run should expose JSON privacy profiles for agents."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    result = runner.invoke(app, ["--data-dir", str(data_dir), "automation", "run", "--help"])

    assert result.exit_code == 0
    assert "--privacy" in result.output


def test_automation_run_json_redacted_privacy_masks_samples(monkeypatch, tmp_path: Path) -> None:
    """automation run redacted JSON should hide sample merchants, accounts, memos, and files."""
    _set_home(monkeypatch, tmp_path)
    data_dir = _build_data_dir(tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=2,
                    large_transaction=300_000,
                ),
            ),
            _automation_explicit=True,
        )
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "automation", "run", "--json", "--privacy", "redacted"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    serialized = json.dumps(payload, ensure_ascii=False)
    merchant_pressure = payload["tagging_pressure"]["merchant_pressure"][0]
    assert payload["_meta"]["privacy"]["profile"] == "redacted"
    assert payload["data_dir"] == "[REDACTED]"
    assert payload["pending_imports"]["sample_files"] == []
    assert merchant_pressure["merchant"] == "[REDACTED]"
    assert merchant_pressure["total_amount"] is None
    assert merchant_pressure["avg_amount"] is None
    assert merchant_pressure["sample_memos"] == []
    assert payload["large_transactions"]["samples"] == []
    sensitive_values = (
        "스타벅스",
        "아이스 아메리카노",
        "신한카드",
        "항공사",
        "기업카드",
        "staged.xlsx",
    )
    for sensitive in sensitive_values:
        assert sensitive not in serialized


def test_automation_run_json_compact_privacy_keeps_counts_without_samples(
    monkeypatch, tmp_path: Path
) -> None:
    """automation run compact JSON should keep signals and omit bulky high-risk samples."""
    _set_home(monkeypatch, tmp_path)
    data_dir = _build_data_dir(tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=2,
                    large_transaction=300_000,
                ),
            ),
            _automation_explicit=True,
        )
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "automation", "run", "--json", "--privacy", "compact"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["_meta"]["privacy"]["profile"] == "compact"
    assert "data_dir" not in payload
    assert payload["pending_imports"]["pending_files"] == 1
    assert "sample_files" not in payload["pending_imports"]
    assert payload["tagging_pressure"]["merchant_pressure_count"] == 1
    assert "merchant_pressure" not in payload["tagging_pressure"]
    assert payload["large_transactions"]["count"] == 1
    assert "samples" not in payload["large_transactions"]
    assert [step["signal"] for step in payload["next_steps"]] == [
        "pending_imports",
        "tagging_pressure",
        "large_transactions",
    ]
    sensitive_values = (
        "스타벅스",
        "아이스 아메리카노",
        "신한카드",
        "항공사",
        "기업카드",
        "staged.xlsx",
    )
    for sensitive in sensitive_values:
        assert sensitive not in serialized


def test_automation_run_json_zero_thresholds_disable_thresholded_signals(
    monkeypatch, tmp_path: Path
) -> None:
    """Zero thresholds should disable thresholded automation without failing the run."""
    _set_home(monkeypatch, tmp_path)
    data_dir = _build_clean_data_dir(tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=0,
                    large_transaction=0,
                ),
            ),
            _automation_explicit=True,
        )
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "automation", "run", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)

    assert payload["actionable"] is False
    assert payload["tagging_pressure"]["untagged_transactions"] == 0
    assert payload["tagging_pressure"]["suggestable_untagged_transactions"] == 0
    assert payload["tagging_pressure"]["threshold"] == 0
    assert payload["tagging_pressure"]["threshold_exceeded"] is False
    assert payload["large_transactions"]["status"] == "clear"
    assert payload["large_transactions"]["threshold"] == 0
    assert payload["next_steps"] == []
    assert (
        "Tagging-pressure automation is disabled because automation.thresholds.untagged_count is 0."
    ) in payload["warnings"]
    assert (
        "Large-transaction automation is disabled because "
        "automation.thresholds.large_transaction is 0."
    ) in payload["warnings"]


def test_automation_run_text_warns_when_config_disabled(monkeypatch, tmp_path: Path) -> None:
    """Text output should stay useful when automation is disabled in config."""
    _set_home(monkeypatch, tmp_path)
    data_dir = _build_data_dir(tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=False,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=2,
                    large_transaction=300_000,
                ),
            ),
            _automation_explicit=True,
        )
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "automation", "run"])

    assert result.exit_code == 0
    assert "Automation Run" in result.output
    assert "Automation is disabled in config; showing a preview-only summary." in result.output
    assert "Top suggestable untagged merchant: 스타벅스 (2 txn)" in result.output
    assert "finjuice refresh" in result.output
    assert "finjuice rules suggest" in result.output


def test_automation_run_text_shows_disabled_zero_thresholds(monkeypatch, tmp_path: Path) -> None:
    """Text output should make zero-threshold disablement explicit."""
    _set_home(monkeypatch, tmp_path)
    data_dir = _build_clean_data_dir(tmp_path)
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-data"),
            automation=AutomationConfig(
                enabled=True,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=0,
                    large_transaction=0,
                ),
            ),
            _automation_explicit=True,
        )
    )

    result = runner.invoke(app, ["--data-dir", str(data_dir), "automation", "run"])

    assert result.exit_code == 0
    assert "0 total untagged; 0 rule-suggestable (disabled; threshold 0)" in result.output
    assert "disabled (threshold 0)" in result.output
    assert "One-shot automation pass found no actionable signals." in result.output
