"""Tests for the checkup CLI command."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.checkup import (
    BudgetPostureSummary,
    BudgetSummary,
    CheckupBundle,
    NetWorthPostureSummary,
    NextAction,
    PipelineFreshnessSummary,
    ReviewPressureSummary,
    ReviewSample,
)
from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


@pytest.fixture
def checkup_data_dir(tmp_path: Path) -> Path:
    """Create a minimally initialized data directory for checkup CLI tests."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "transactions").mkdir()
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    return data_dir


def _empty_bundle(data_dir: Path) -> CheckupBundle:
    """Build an explicit empty-state bundle."""
    return CheckupBundle(
        data_dir=str(data_dir),
        actionable=True,
        warnings=[
            "No transaction partitions found. Import data before running the pipeline loop.",
            "goals.yaml not found. Budget posture is unconfigured.",
        ],
        next_actions=[
            NextAction(
                domain="pipeline",
                priority="high",
                reason="거래 파티션이 없어 파이프라인 기반 점검을 시작할 수 없습니다.",
                command="finjuice import <banksalad.xlsx>",
            ),
            NextAction(
                domain="budget",
                priority="medium",
                reason="예산 기준이 없어 지출 posture를 판단할 수 없습니다.",
                command="finjuice budget edit --set total=<monthly_budget> --yes",
            ),
        ],
        pipeline=PipelineFreshnessSummary(
            status="empty",
            actionable=True,
            pending_import_status="clear",
            pending_import_files=0,
            failed_import_files=0,
            transaction_partitions=0,
            data_range=None,
            latest_transaction_date=None,
            days_since_latest=None,
            monthly_avg_income=None,
            monthly_avg_expense=None,
            savings_rate_3mo=None,
            active_filters=0,
            warning=(
                "No transaction partitions found. Import data before running the pipeline loop."
            ),
        ),
        review=ReviewPressureSummary(
            status="empty",
            actionable=False,
            month=None,
            total_candidates=0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
            samples=[],
        ),
        budget=BudgetPostureSummary(
            status="missing_config",
            actionable=True,
            month="2026-04",
            goals_file_exists=False,
            filters_applied=0,
            summary=None,
            over_budget_categories=[],
            unbudgeted_categories=[],
            warning="goals.yaml not found. Budget posture is unconfigured.",
        ),
        networth=NetWorthPostureSummary(
            status="missing_data",
            actionable=True,
            as_of=None,
            snapshot_months=0,
            assets_file_exists=False,
            asset_count=0,
            liability_count=0,
            total_assets=0.0,
            total_liabilities=0.0,
            net_worth=0.0,
            target=None,
            gap_to_target=None,
            warning="No asset snapshots or assets.yaml entries found for net worth posture.",
        ),
    )


def _healthy_bundle(data_dir: Path) -> CheckupBundle:
    """Build a quiet healthy-state bundle."""
    return CheckupBundle(
        data_dir=str(data_dir),
        actionable=False,
        warnings=[],
        next_actions=[],
        pipeline=PipelineFreshnessSummary(
            status="healthy",
            actionable=False,
            pending_import_status="clear",
            pending_import_files=0,
            failed_import_files=0,
            transaction_partitions=2,
            data_range="2026-04-01 ~ 2026-04-18",
            latest_transaction_date="2026-04-18",
            days_since_latest=0,
            monthly_avg_income=3000000,
            monthly_avg_expense=140000,
            savings_rate_3mo=0.61,
            active_filters=0,
            warning=None,
        ),
        review=ReviewPressureSummary(
            status="healthy",
            actionable=False,
            month="2026-04",
            total_candidates=0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
            samples=[],
        ),
        budget=BudgetPostureSummary(
            status="healthy",
            actionable=False,
            month="2026-04",
            goals_file_exists=True,
            filters_applied=0,
            summary=BudgetSummary(
                target=300000,
                actual=140000,
                remaining=160000,
                progress_pct=46.7,
                status="under",
            ),
            over_budget_categories=[],
            unbudgeted_categories=[],
            warning=None,
        ),
        networth=NetWorthPostureSummary(
            status="on_target",
            actionable=False,
            as_of="2026-04-18",
            snapshot_months=1,
            assets_file_exists=True,
            asset_count=2,
            liability_count=1,
            total_assets=220000000.0,
            total_liabilities=10000000.0,
            net_worth=210000000.0,
            target=100000000,
            gap_to_target=-110000000.0,
            warning=None,
        ),
    )


def _attention_bundle(data_dir: Path) -> CheckupBundle:
    """Build a multi-domain needs-attention bundle."""
    return CheckupBundle(
        data_dir=str(data_dir),
        actionable=True,
        warnings=[],
        next_actions=[
            NextAction(
                domain="budget",
                priority="high",
                reason="2026-01 예산이 초과 상태입니다.",
                command="finjuice budget status --json",
            ),
            NextAction(
                domain="review",
                priority="high",
                reason="최신 월에 수동 검토 후보 4건이 남아 있습니다.",
                command="finjuice review --json",
            ),
            NextAction(
                domain="networth",
                priority="medium",
                reason="순자산이 음수라 liabilities 구성이 우선 점검 대상입니다.",
                command="finjuice networth --json",
            ),
            NextAction(
                domain="pipeline",
                priority="medium",
                reason="최신 거래일이 85일 전이라 파이프라인 상태가 오래됐습니다.",
                command="finjuice refresh",
            ),
        ],
        pipeline=PipelineFreshnessSummary(
            status="stale",
            actionable=True,
            pending_import_status="clear",
            pending_import_files=0,
            failed_import_files=0,
            transaction_partitions=1,
            data_range="2026-01-10 ~ 2026-01-23",
            latest_transaction_date="2026-01-23",
            days_since_latest=85,
            monthly_avg_income=2000000,
            monthly_avg_expense=199000,
            savings_rate_3mo=0.42,
            active_filters=0,
            warning=None,
        ),
        review=ReviewPressureSummary(
            status="needs_attention",
            actionable=True,
            month="2026-01",
            total_candidates=4,
            needs_review_count=1,
            untagged_count=1,
            unclassified_count=1,
            low_confidence_count=4,
            samples=[
                ReviewSample(
                    date="2026-01-23",
                    merchant="추가 후보",
                    amount=-9000.0,
                    reasons=["low_confidence"],
                )
            ],
            rule_notes=[
                {
                    "rule_name": "suggested_secret_merchant",
                    "notes": "Auto-suggested for Secret Merchant (3 transactions)",
                    "tags": ["구독"],
                    "category": "구독",
                }
            ],
        ),
        budget=BudgetPostureSummary(
            status="needs_attention",
            actionable=True,
            month="2026-01",
            goals_file_exists=True,
            filters_applied=0,
            summary=BudgetSummary(
                target=100000,
                actual=199000,
                remaining=-99000,
                progress_pct=199.0,
                status="over",
            ),
            over_budget_categories=["식비"],
            unbudgeted_categories=["의료", "생활"],
            warning=None,
        ),
        networth=NetWorthPostureSummary(
            status="negative",
            actionable=True,
            as_of="2026-01-31",
            snapshot_months=1,
            assets_file_exists=True,
            asset_count=1,
            liability_count=1,
            total_assets=20000000.0,
            total_liabilities=40000000.0,
            net_worth=-20000000.0,
            target=None,
            gap_to_target=None,
            warning=None,
        ),
    )


def test_checkup_help(checkup_data_dir: Path) -> None:
    """finjuice checkup --help should expose the JSON option and purpose."""
    result = runner.invoke(app, ["--data-dir", str(checkup_data_dir), "checkup", "--help"])

    assert result.exit_code == 0
    output = cli_text(result)
    assert "--json" in output
    assert "--privacy" in output
    assert "inspect/decide" in output


def test_checkup_json_empty_state(checkup_data_dir: Path) -> None:
    """checkup --json should expose summary, domains, warnings, and next actions."""
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_empty_bundle(checkup_data_dir),
    ) as mock_collect:
        result = runner.invoke(app, ["--data-dir", str(checkup_data_dir), "checkup", "--json"])

    assert result.exit_code == 0
    mock_collect.assert_called_once()
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "checkup"
    assert payload["data_dir"] == str(checkup_data_dir)
    assert payload["summary"] == {
        "status": "needs_attention",
        "priority": "high",
        "headline": "거래 파티션이 없어 파이프라인 기반 점검을 시작할 수 없습니다.",
        "recommended_command": "finjuice import <banksalad.xlsx>",
        "domains_needing_attention": ["pipeline", "budget", "networth"],
        "warning_count": 2,
        "next_action_count": 2,
    }
    assert payload["actionable"] is True
    assert payload["warnings"][0] == (
        "No transaction partitions found. Import data before running the pipeline loop."
    )
    assert payload["domains"]["pipeline"]["status"] == "empty"
    assert payload["domains"]["budget"]["status"] == "missing_config"
    assert payload["domains"]["networth"]["status"] == "missing_data"
    assert payload["next_actions"][0]["command"] == "finjuice import <banksalad.xlsx>"


def test_checkup_json_redacted_privacy_masks_domain_samples(checkup_data_dir: Path) -> None:
    """checkup redacted JSON should hide path, review sample, and amount values."""
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_attention_bundle(checkup_data_dir),
    ):
        result = runner.invoke(
            app,
            ["--data-dir", str(checkup_data_dir), "checkup", "--json", "--privacy", "redacted"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["_meta"]["privacy"]["profile"] == "redacted"
    assert payload["data_dir"] == "[REDACTED]"
    assert payload["domains"]["review"]["samples"] == []
    assert payload["domains"]["review"]["rule_notes"] == [
        {
            "rule_name": "[REDACTED]",
            "notes": "[REDACTED]",
            "tags": ["구독"],
            "category": "구독",
        }
    ]
    assert payload["domains"]["budget"]["summary"]["target"] is None
    assert payload["domains"]["budget"]["summary"]["actual"] is None
    assert payload["domains"]["networth"]["net_worth"] is None
    assert "추가 후보" not in serialized
    assert "suggested_secret_merchant" not in serialized
    assert "Auto-suggested for Secret Merchant" not in serialized
    assert "Secret Merchant" not in serialized
    assert "-9000" not in serialized
    assert "199000" not in serialized
    assert "40000000" not in serialized
    assert str(checkup_data_dir) not in serialized


def test_checkup_json_compact_privacy_omits_samples_and_financial_amounts(
    checkup_data_dir: Path,
) -> None:
    """checkup compact JSON should keep orchestration cues without detailed samples."""
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_attention_bundle(checkup_data_dir),
    ):
        result = runner.invoke(
            app,
            ["--data-dir", str(checkup_data_dir), "checkup", "--json", "--privacy", "compact"],
        )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["_meta"]["privacy"]["profile"] == "compact"
    assert "data_dir" not in payload
    assert payload["summary"]["recommended_command"] == "finjuice budget status --json"
    assert payload["domains"]["review"] == {
        "status": "needs_attention",
        "actionable": True,
        "month": "2026-01",
        "total_candidates": 4,
        "needs_review_count": 1,
        "untagged_count": 1,
        "unclassified_count": 1,
        "low_confidence_count": 4,
        "sample_count": 1,
        "rule_notes": [{"tags": ["구독"], "category": "구독"}],
    }
    assert payload["domains"]["budget"]["summary"] == {
        "progress_pct": 199.0,
        "status": "over",
    }
    assert payload["domains"]["networth"] == {
        "status": "negative",
        "actionable": True,
        "as_of": "2026-01-31",
        "snapshot_months": 1,
        "assets_file_exists": True,
        "asset_count": 1,
        "liability_count": 1,
        "warning": None,
    }
    assert "추가 후보" not in serialized
    assert "suggested_secret_merchant" not in serialized
    assert "Auto-suggested for Secret Merchant" not in serialized
    assert "Secret Merchant" not in serialized
    assert "-9000" not in serialized
    assert "199000" not in serialized
    assert "40000000" not in serialized
    assert str(checkup_data_dir) not in serialized


def test_checkup_text_output_healthy_state(checkup_data_dir: Path) -> None:
    """Healthy checkups should stay concise and avoid warning/action sections."""
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_healthy_bundle(checkup_data_dir),
    ):
        result = runner.invoke(app, ["--data-dir", str(checkup_data_dir), "checkup"])

    assert result.exit_code == 0
    output = cli_text(result)
    assert "finjuice checkup" in output
    assert "- status: ok" in output
    assert "- headline: No immediate action required." in output
    assert "- recommended: none" in output
    assert "- pipeline: healthy; latest=2026-04-18" in output
    assert "- budget: healthy; month=2026-04, actual=₩140,000, target=₩300,000" in output
    assert "- networth: on_target; net_worth=₩210,000,000" in output
    assert "Warnings" not in output
    assert "Next Actions" not in output


def test_checkup_text_output_needs_attention(checkup_data_dir: Path) -> None:
    """Needs-attention checkups should surface domain pressure and ordered next actions."""
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_attention_bundle(checkup_data_dir),
    ):
        result = runner.invoke(app, ["--data-dir", str(checkup_data_dir), "checkup"])

    assert result.exit_code == 0
    output = cli_text(result)
    assert "- status: needs_attention" in output
    assert "- recommended: finjuice budget status --json" in output
    assert "- pipeline: stale; latest data 85d old" in output
    assert "- review: needs_attention; candidates=4, untagged=1, low_confidence=4" in output
    assert "- budget: needs_attention; month=2026-01, actual=₩199,000, target=₩100,000" in output
    assert "- networth: negative; net_worth=-₩20,000,000" in output
    assert "Next Actions" in output
    assert "[high] finjuice budget status --json: 2026-01 예산이 초과 상태입니다." in output
    assert "[high] finjuice review --json: 최신 월에 수동 검토 후보 4건이 남아 있습니다." in output


def test_checkup_text_redacted_privacy_hides_raw_won_amounts(checkup_data_dir: Path) -> None:
    """Text mode with --privacy redacted must not leak raw 원 amounts to the terminal.

    Previously, privacy profiles applied only to JSON output: text rendering
    still emitted budget/networth/obligation amounts unchanged. This guards
    that regression.
    """
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_attention_bundle(checkup_data_dir),
    ):
        result = runner.invoke(
            app,
            ["--data-dir", str(checkup_data_dir), "checkup", "--privacy", "redacted"],
        )

    assert result.exit_code == 0
    output = cli_text(result)
    # Raw 원 amounts from the attention bundle must not appear in the text body.
    assert "₩199,000" not in output
    assert "₩100,000" not in output
    assert "₩20,000,000" not in output
    # The status/structure should still be present — only amounts are nulled.
    assert "- status: needs_attention" in output
    assert "- budget: needs_attention" in output
    assert "- networth: negative" in output
    # Privacy-nulled amounts render as "-".
    assert "actual=-" in output
    assert "target=-" in output
    assert "net_worth=-" in output


def test_checkup_text_compact_privacy_handles_dropped_amount_keys(
    checkup_data_dir: Path,
) -> None:
    """Compact profile drops financial keys; text renderer should not raise.

    The compact transform on the checkup payload omits ``summary.actual``,
    ``summary.target``, ``net_worth``, and ``threshold_monthly_krw`` entirely.
    Text rendering must tolerate the missing keys and fall back to "-".
    """
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_attention_bundle(checkup_data_dir),
    ):
        result = runner.invoke(
            app,
            ["--data-dir", str(checkup_data_dir), "checkup", "--privacy", "compact"],
        )

    assert result.exit_code == 0
    output = cli_text(result)
    assert "₩" not in output  # No 원 sign anywhere
    assert "- status: needs_attention" in output
    assert "- budget: needs_attention" in output


def test_checkup_text_raw_privacy_unchanged(checkup_data_dir: Path) -> None:
    """Default RAW profile must preserve the prior text output verbatim."""
    with patch(
        "finjuice.pipeline.cli.commands.checkup.collect_checkup_bundle",
        return_value=_attention_bundle(checkup_data_dir),
    ):
        result = runner.invoke(
            app,
            ["--data-dir", str(checkup_data_dir), "checkup", "--privacy", "raw"],
        )

    assert result.exit_code == 0
    output = cli_text(result)
    # Raw amounts still present in raw profile.
    assert "actual=₩199,000" in output
    assert "target=₩100,000" in output
    assert "net_worth=-₩20,000,000" in output
