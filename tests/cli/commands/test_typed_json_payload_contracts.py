"""Tests for schema-backed internal CLI JSON payload contracts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from referencing import Registry, Resource

from finjuice import __version__
from finjuice.pipeline.automation import (
    AutomationHint,
    AutomationSummary,
    LargeTransactionSample,
    LargeTransactionSignal,
    MerchantPressureSample,
    PendingImportFailure,
    PendingImportFile,
    PendingImportsSignal,
    TaggingPressureSignal,
)
from finjuice.pipeline.checkup import (
    BudgetPostureSummary,
    BudgetSummary,
    CheckupBundle,
    NetWorthPostureSummary,
    NextAction,
    PipelineFreshnessSummary,
    ReviewPressureSummary,
)
from finjuice.pipeline.cli.commands.automation import (
    _compact_automation_run_payload,
    _serialize_automation_run_payload,
)
from finjuice.pipeline.cli.commands.checkup.rendering import (
    _compact_checkup,
    _serialize_checkup_payload,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMAS_DIR = REPO_ROOT / "schemas"


def _load_schema(filename: str) -> dict[str, Any]:
    return json.loads((SCHEMAS_DIR / filename).read_text(encoding="utf-8"))


def _build_schema_registry() -> Registry[Any]:
    """Pre-register every schema by bare filename for cross-schema `$ref` resolution.

    Replaces the deprecated `jsonschema.RefResolver(base_uri=…)` pattern. The
    on-disk schemas reference each other by bare filename (e.g.
    ``"$ref": "_meta.schema.json"``), so registering each schema under its
    filename URI lets `referencing.Registry` resolve them directly.
    """
    resources = [
        (
            schema_file.name,
            Resource.from_contents(json.loads(schema_file.read_text(encoding="utf-8"))),
        )
        for schema_file in SCHEMAS_DIR.glob("*.schema.json")
    ]
    return Registry().with_resources(resources)


_SCHEMA_REGISTRY: Registry[Any] = _build_schema_registry()


def _validate_command_schema(
    payload: dict[str, Any],
    *,
    command: str,
    schema_file: str,
    privacy: str = "raw",
) -> None:
    """Validate an internal payload after adding the public CLI envelope."""
    schema = _load_schema(schema_file)
    envelope = {
        "_meta": {
            "schema_version": "1.0",
            "finjuice_version": __version__,
            "command": command,
            "timestamp": "2026-05-12T00:00:00+00:00",
            "privacy": {"profile": privacy},
        },
        **payload,
    }

    jsonschema.Draft202012Validator(schema, registry=_SCHEMA_REGISTRY).validate(envelope)


def _automation_summary() -> AutomationSummary:
    return AutomationSummary(
        data_dir="/tmp/finjuice-data",
        actionable=True,
        pending_imports=PendingImportsSignal(
            status="present",
            files_found=2,
            pending_files=1,
            estimated_new_rows=7,
            estimated_new_asset_rows=1,
            failed_files=[
                PendingImportFailure(source_file="bad.xlsx", error="invalid workbook"),
            ],
            sample_files=[
                PendingImportFile(
                    source_file="sample.xlsx",
                    estimated_new_rows=7,
                    estimated_new_asset_rows=1,
                    validation_skips=0,
                ),
            ],
        ),
        tagging_pressure=TaggingPressureSignal(
            status="present",
            total_transactions=10,
            untagged_transactions=4,
            coverage_pct=60.0,
            suggestable_untagged_transactions=3,
            suggestable_coverage_pct=70.0,
            transfer_excluded_untagged_transactions=1,
            merchant_pressure=[
                MerchantPressureSample(
                    merchant="Coffee",
                    transaction_count=3,
                    total_amount=-15000.0,
                    avg_amount=-5000.0,
                    sample_memos=["latte"],
                )
            ],
        ),
        large_transactions=LargeTransactionSignal(
            status="present",
            threshold=300000,
            count=1,
            samples=[
                LargeTransactionSample(
                    date="2026-05-01",
                    merchant="Airline",
                    account="card",
                    category="travel",
                    amount_krw=800000.0,
                )
            ],
        ),
        next_steps=[
            AutomationHint(
                signal="pending_imports",
                message="New import files look ready for a one-shot pipeline pass.",
                command="finjuice refresh",
            ),
            AutomationHint(
                signal="tagging_pressure",
                message="Rule-suggestable untagged transactions are accumulating.",
                command="finjuice rules suggest",
            ),
            AutomationHint(
                signal="large_transactions",
                message="Review large-expense anomalies.",
                command="finjuice template run anomaly_large_txn --param threshold=300000",
            ),
        ],
        warnings=["Existing warning."],
    )


def _checkup_bundle() -> CheckupBundle:
    return CheckupBundle(
        data_dir="/tmp/finjuice-data",
        actionable=True,
        warnings=["goals.yaml not found. Budget posture is unconfigured."],
        next_actions=[
            NextAction(
                domain="budget",
                priority="medium",
                reason="예산 기준이 없어 지출 posture를 판단할 수 없습니다.",
                command="finjuice budget edit --set total=<monthly_budget> --yes",
            )
        ],
        pipeline=PipelineFreshnessSummary(
            status="healthy",
            actionable=False,
            pending_import_status="clear",
            pending_import_files=0,
            failed_import_files=0,
            transaction_partitions=1,
            data_range="2026-05-01 ~ 2026-05-12",
            latest_transaction_date="2026-05-12",
            days_since_latest=0,
            monthly_avg_income=3000000,
            monthly_avg_expense=1200000,
            savings_rate_3mo=0.6,
            active_filters=0,
            warning=None,
        ),
        review=ReviewPressureSummary(
            status="healthy",
            actionable=False,
            month="2026-05",
            total_candidates=0,
            needs_review_count=0,
            untagged_count=0,
            unclassified_count=0,
            low_confidence_count=0,
            samples=[],
        ),
        budget=BudgetPostureSummary(
            status="needs_attention",
            actionable=True,
            month="2026-05",
            goals_file_exists=False,
            filters_applied=0,
            summary=BudgetSummary(
                target=1000000,
                actual=1200000,
                remaining=-200000,
                progress_pct=120.0,
                status="over",
            ),
            over_budget_categories=["식비"],
            unbudgeted_categories=[],
            warning="goals.yaml not found. Budget posture is unconfigured.",
        ),
        networth=NetWorthPostureSummary(
            status="on_target",
            actionable=False,
            as_of="2026-05-12",
            snapshot_months=1,
            assets_file_exists=True,
            asset_count=2,
            liability_count=1,
            total_assets=50000000.0,
            total_liabilities=10000000.0,
            net_worth=40000000.0,
            target=30000000,
            gap_to_target=-10000000.0,
            warning=None,
        ),
    )


def test_automation_run_typed_payload_validates_existing_schema() -> None:
    """The internal automation-run payload contract should match public JSON schema."""
    payload = _serialize_automation_run_payload(
        _automation_summary(),
        enabled=True,
        untagged_threshold=5,
        large_transaction_threshold=300000,
    )

    assert payload["tagging_pressure"]["threshold_basis"] == ("suggestable_untagged_transactions")
    assert payload["tagging_pressure"]["threshold_exceeded"] is False
    assert [step["signal"] for step in payload["next_steps"]] == [
        "pending_imports",
        "large_transactions",
    ]
    _validate_command_schema(
        payload,
        command="automation run",
        schema_file="automation_run.schema.json",
    )


def test_automation_run_compact_typed_payload_validates_existing_schema() -> None:
    """The compact automation-run payload contract should keep counts without samples."""
    raw_payload = _serialize_automation_run_payload(
        _automation_summary(),
        enabled=True,
        untagged_threshold=2,
        large_transaction_threshold=300000,
    )
    compact_payload = _compact_automation_run_payload(raw_payload)

    assert "data_dir" not in compact_payload
    assert compact_payload["pending_imports"]["sample_file_count"] == 1
    assert compact_payload["tagging_pressure"]["merchant_pressure_count"] == 1
    assert compact_payload["large_transactions"]["sample_count"] == 1
    _validate_command_schema(
        compact_payload,
        command="automation run",
        schema_file="automation_run.schema.json",
        privacy="compact",
    )


def test_checkup_typed_payload_validates_existing_schema() -> None:
    """The internal checkup payload contract should match public JSON schema."""
    payload = _serialize_checkup_payload(_checkup_bundle())

    assert payload["summary"] == {
        "status": "needs_attention",
        "priority": "medium",
        "headline": "예산 기준이 없어 지출 posture를 판단할 수 없습니다.",
        "recommended_command": "finjuice budget edit --set total=<monthly_budget> --yes",
        "domains_needing_attention": ["budget"],
        "warning_count": 1,
        "next_action_count": 1,
    }
    assert set(payload["domains"]) == {
        "pipeline",
        "review",
        "budget",
        "networth",
        "obligations",
    }
    _validate_command_schema(payload, command="checkup", schema_file="checkup.schema.json")


def test_checkup_compact_typed_payload_validates_existing_schema() -> None:
    """The compact checkup payload contract should preserve orchestration fields."""
    raw_payload = _serialize_checkup_payload(_checkup_bundle())
    compact_payload = _compact_checkup(raw_payload)

    assert "data_dir" not in compact_payload
    assert compact_payload["domains"]["budget"]["summary"] == {
        "progress_pct": 120.0,
        "status": "over",
    }
    _validate_command_schema(
        compact_payload,
        command="checkup",
        schema_file="checkup.schema.json",
        privacy="compact",
    )
