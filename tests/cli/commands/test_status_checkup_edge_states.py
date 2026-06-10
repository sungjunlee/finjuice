"""Focused edge-state coverage for status/checkup diagnostic boundaries."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from finjuice.pipeline.checkup import collect_checkup_bundle
from finjuice.pipeline.cli.commands.checkup.compute import CheckupFacts
from finjuice.pipeline.cli.commands.checkup.detector import detect_checkup_diagnoses
from finjuice.pipeline.cli.commands.checkup.rendering import serialize_checkup_payload
from finjuice.pipeline.cli.commands.status.compute import (
    StatusCommandError,
    StatusOptions,
    collect_status_facts,
)
from finjuice.pipeline.cli.commands.status.detector import diagnose_status
from finjuice.pipeline.cli.commands.status.rendering import build_status_result
from finjuice.pipeline.cli.output import ErrorCode
from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.rules import ReportFilters


def test_status_compute_reports_no_data_before_missing_schema(tmp_path: Path) -> None:
    """No transaction data should win over absent rules/schema files."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    options = _status_options(data_dir)

    with pytest.raises(StatusCommandError) as exc_info:
        collect_status_facts(options)

    assert exc_info.value.error_code == ErrorCode.NO_DATA
    assert exc_info.value.message == "No transactions directory. Run 'finjuice ingest' first."


def test_status_detector_marks_missing_rules_config_critical(tmp_path: Path) -> None:
    """Missing rules.yaml should stay a critical status signal without raw row output."""
    data_dir = tmp_path / "data"
    _write_transactions(data_dir, [_status_row("2026-04-10", "untagged", tags="[]")])

    facts = collect_status_facts(_status_options(data_dir, report_filters=ReportFilters()))
    diagnoses = diagnose_status(facts)
    result = build_status_result(facts, diagnoses)

    assert result.payload["rules_file"]["exists"] is False
    assert result.payload["health"] == {
        "status": "critical",
        "reasons": ["missing_rules_file"],
    }
    assert result.payload["next_steps"] == [
        {
            "signal": "missing_rules_file",
            "message": "Initialize finjuice before relying on tagging coverage.",
            "command": "finjuice init",
        }
    ]
    assert "merchant_raw" not in json.dumps(result.payload, ensure_ascii=False)


def test_status_compute_honors_disabled_report_filters(tmp_path: Path) -> None:
    """The --no-filter path should disable report_filters at compute time."""
    data_dir = tmp_path / "data"
    _write_transactions(
        data_dir,
        [
            _status_row("2026-04-10", "excluded", merchant="Filtered Merchant"),
            _status_row("2026-04-11", "kept", merchant="Kept Merchant"),
        ],
    )
    (data_dir / "rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "report_filters:",
                "  excluded_merchants:",
                '    - pattern: "Filtered Merchant"',
                '      reason: "fixture"',
                "rules: []",
                "",
            ]
        ),
        encoding="utf-8",
    )

    filtered_facts = collect_status_facts(_status_options(data_dir))
    disabled_facts = collect_status_facts(_status_options(data_dir, no_filter=True))

    assert filtered_facts.total_rows == 1
    assert filtered_facts.filters_applied == 1
    assert disabled_facts.total_rows == 2
    assert disabled_facts.filters_applied == 0


def test_checkup_detector_preserves_stale_pipeline_signal(tmp_path: Path) -> None:
    """Stale transaction data should remain a pipeline diagnosis after CLI split."""
    data_dir = _init_checkup_data_dir(tmp_path)
    _write_transactions(
        data_dir,
        [
            _status_row("2026-01-10", "income", amount=3_000_000, tags='["income"]'),
            _status_row("2026-01-15", "expense", amount=-100_000, tags='["expense"]'),
        ],
    )

    bundle = collect_checkup_bundle(
        Config(data_dir=data_dir),
        today=date(2026, 4, 18),
        stale_after_days=35,
    )
    facts = CheckupFacts(bundle=bundle)
    diagnoses = detect_checkup_diagnoses(facts)
    payload = serialize_checkup_payload(facts, diagnoses)

    assert payload["domains"]["pipeline"]["status"] == "stale"
    assert payload["domains"]["pipeline"]["days_since_latest"] == 93
    assert "pipeline" in payload["summary"]["domains_needing_attention"]
    assert any(action["command"] == "finjuice refresh" for action in payload["next_actions"])


def _status_options(
    data_dir: Path,
    *,
    no_filter: bool = False,
    report_filters: ReportFilters | None = None,
) -> StatusOptions:
    """Build normalized status options for edge-state tests."""
    return StatusOptions(
        config=Config(data_dir=data_dir),
        data_dir_source="test fixture",
        detailed=False,
        top_n=5,
        no_filter=no_filter,
        report_filters=report_filters,
    )


def _init_checkup_data_dir(tmp_path: Path) -> Path:
    """Create enough files for checkup to isolate pipeline freshness."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "metadata").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "version: 1\nmonthly_budget:\n  total: 500000\n  categories: {}\n",
        encoding="utf-8",
    )
    (data_dir / "assets.yaml").write_text(
        "version: 1\nmanual_assets:\n  - name: cash\n    category: cash\n    value: 1000\n",
        encoding="utf-8",
    )
    return data_dir


def _write_transactions(data_dir: Path, rows: list[dict[str, Any]]) -> None:
    """Write one partition with complete status/checkup test rows."""
    partition_dir = data_dir / "transactions" / "2026" / "01"
    partition_dir.mkdir(parents=True, exist_ok=True)
    pl.DataFrame(rows).write_csv(partition_dir / "transactions.csv")


def _status_row(
    tx_date: str,
    row_hash: str,
    *,
    amount: int = -10_000,
    merchant: str | None = None,
    tags: str = '["tagged"]',
) -> dict[str, Any]:
    """Build a complete transaction row without sensitive fixture data."""
    resolved_merchant = merchant or row_hash
    return {
        "row_hash": row_hash,
        "date": tx_date,
        "time": "09:00",
        "type_raw": "입금" if amount > 0 else "지출",
        "type_norm": "income" if amount > 0 else "expense",
        "major_raw": "fixture",
        "minor_raw": "fixture",
        "merchant_raw": resolved_merchant,
        "memo_raw": None,
        "notes_manual": "",
        "amount": float(amount),
        "account": "fixture-account",
        "currency": "KRW",
        "counterparty": None,
        "datetime": f"{tx_date}T09:00:00",
        "category_rule": "fixture",
        "category_final": "fixture",
        "tags_rule": tags,
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": tags,
        "confidence": 0.9,
        "needs_review": 0,
        "is_transfer_candidate": 0,
        "is_transfer": 0,
        "transfer_group_id": None,
        "file_id": "fixture",
        "source_row": 1,
    }
