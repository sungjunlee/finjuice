"""Focused tests for workflow automation signal collection."""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.automation import collect_automation_signals
from finjuice.pipeline.config import Config


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


def test_collect_automation_signal_no_signal(tmp_path: Path) -> None:
    """Empty data dirs should return a stable, clear summary."""
    config = Config(data_dir=tmp_path)

    summary = collect_automation_signals(config, large_transaction_threshold=300000)

    assert summary.actionable is False
    assert summary.pending_imports.status == "clear"
    assert summary.pending_imports.files_found == 0
    assert summary.tagging_pressure.status == "clear"
    assert summary.tagging_pressure.untagged_transactions == 0
    assert summary.tagging_pressure.suggestable_untagged_transactions == 0
    assert summary.large_transactions.status == "clear"
    assert summary.large_transactions.count == 0
    assert summary.next_steps == []
    assert summary.warnings == []
    assert summary.to_dict()["data_dir"] == str(tmp_path)


def test_collect_automation_signal_actionable_summary(tmp_path: Path) -> None:
    """Pending imports, untagged merchants, and large expenses should all surface."""
    _write_sample_transactions(tmp_path)

    imports_dir = tmp_path / "imports"
    imports_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(Path("tests/fixtures/sample_banksalad.xlsx"), imports_dir / "staged.xlsx")

    config = Config(data_dir=tmp_path)
    summary = collect_automation_signals(
        config,
        large_transaction_threshold=300000,
        merchant_sample_limit=3,
        large_transaction_sample_limit=3,
    )

    assert summary.actionable is True

    assert summary.pending_imports.status == "present"
    assert summary.pending_imports.files_found == 1
    assert summary.pending_imports.pending_files == 1
    assert summary.pending_imports.estimated_new_rows > 0
    assert [sample.source_file for sample in summary.pending_imports.sample_files] == [
        "staged.xlsx"
    ]

    assert summary.tagging_pressure.status == "present"
    assert summary.tagging_pressure.total_transactions == 5
    assert summary.tagging_pressure.untagged_transactions == 4
    assert summary.tagging_pressure.coverage_pct == pytest.approx(20.0)
    assert summary.tagging_pressure.suggestable_untagged_transactions == 4
    assert summary.tagging_pressure.suggestable_coverage_pct == pytest.approx(20.0)
    assert summary.tagging_pressure.transfer_excluded_untagged_transactions == 0
    assert [sample.merchant for sample in summary.tagging_pressure.merchant_pressure] == [
        "스타벅스"
    ]

    assert summary.large_transactions.status == "present"
    assert summary.large_transactions.threshold == 300000
    assert summary.large_transactions.count == 1
    assert summary.large_transactions.samples[0].merchant == "항공사"
    assert summary.large_transactions.samples[0].amount_krw == pytest.approx(800000.0)

    commands = [hint.command for hint in summary.next_steps]
    assert "finjuice refresh" in commands
    assert "finjuice rules suggest" in commands
    assert "finjuice template run anomaly_large_txn --param threshold=300000" in commands
    assert summary.warnings == []


def test_collect_automation_signal_zero_large_threshold_disables_signal(tmp_path: Path) -> None:
    """A zero large-transaction threshold should disable that signal cleanly."""
    config = Config(data_dir=tmp_path)

    summary = collect_automation_signals(config, large_transaction_threshold=0)

    assert summary.actionable is False
    assert summary.large_transactions.status == "clear"
    assert summary.large_transactions.threshold == 0
    assert summary.large_transactions.count == 0
    assert summary.large_transactions.samples == []
    assert all(hint.signal != "large_transactions" for hint in summary.next_steps)
