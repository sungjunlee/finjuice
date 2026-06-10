"""CLI integration tests for declarative report_filters."""

from __future__ import annotations

import json
from pathlib import Path

from finjuice.pipeline.cli.main import app
from tests.cli.report_filter_support import (
    build_cli_data_dir as _build_cli_data_dir,
)
from tests.cli.report_filter_support import (
    runner,
)


def test_status_and_template_json_meta_report_zero_when_block_absent(
    no_report_filters_data_dir: Path,
) -> None:
    """Absent report_filters should emit `_meta.filters_applied = 0`."""
    status_result = runner.invoke(
        app,
        ["--data-dir", str(no_report_filters_data_dir), "status", "--json"],
    )
    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["_meta"]["filters_applied"] == 0
    assert status_payload["transactions"]["count"] == 1

    template_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(no_report_filters_data_dir),
            "template",
            "run",
            "monthly_spend",
            "--json",
        ],
    )
    assert template_result.exit_code == 0
    template_payload = json.loads(template_result.output)
    assert template_payload["_meta"]["filters_applied"] == 0
    assert template_payload["row_count"] == 1


def test_status_and_template_json_meta_count_matched_rules_not_rows(
    report_filters_data_dir: Path,
) -> None:
    """`filters_applied` should count matched rules even when rules overlap on one row."""
    status_result = runner.invoke(
        app,
        ["--data-dir", str(report_filters_data_dir), "status", "--json", "--detailed"],
    )
    assert status_result.exit_code == 0
    status_payload = json.loads(status_result.output)
    assert status_payload["_meta"]["filters_applied"] == 3
    assert status_payload["transactions"]["count"] == 1
    # #444 rebase: detailed_stats is now sourced from insights.StatusSnapshot.
    # For a single-month fixture, monthly_avg_expense == total_expense.
    assert status_payload["detailed_stats"]["monthly_avg_expense"] == 50000

    template_result = runner.invoke(
        app,
        ["--data-dir", str(report_filters_data_dir), "template", "run", "monthly_spend", "--json"],
    )
    assert template_result.exit_code == 0
    template_payload = json.loads(template_result.output)
    assert template_payload["_meta"]["filters_applied"] == 3
    assert template_payload["row_count"] == 1
    assert template_payload["rows"][0]["transaction_count"] == 1
    assert template_payload["rows"][0]["total_spend"] == 50000.0


def test_report_filters_never_mutate_partition_csvs(report_filters_data_dir: Path) -> None:
    """Running filtered read commands must not modify transaction CSVs on disk."""
    partition_path = report_filters_data_dir / "transactions" / "2024" / "10" / "transactions.csv"
    before = partition_path.read_text(encoding="utf-8")

    status_result = runner.invoke(
        app,
        ["--data-dir", str(report_filters_data_dir), "status", "--json"],
    )
    template_result = runner.invoke(
        app,
        ["--data-dir", str(report_filters_data_dir), "template", "run", "monthly_spend", "--json"],
    )

    assert status_result.exit_code == 0
    assert template_result.exit_code == 0
    assert partition_path.read_text(encoding="utf-8") == before


def test_rules_validate_fails_on_invalid_report_filters(tmp_path: Path) -> None:
    """`rules validate` should surface report_filters schema errors."""
    data_dir = _build_cli_data_dir(
        tmp_path,
        """
        version: 1
        report_filters:
          excluded_merchants:
            - pattern: "foo"
              match_type: "wildcard"
              reason: "bad"
        rules: []
        """,
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "rules", "validate", "--json"],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "rules validate"
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "report_filters.excluded_merchants[0].match_type" in payload["error"]["message"]
