"""One-shot automation keeps canonical data separate from staged observations."""

from __future__ import annotations

import json
import shutil
from io import BytesIO

import polars as pl
import pytest
from openpyxl import Workbook
from typer.testing import CliRunner

from finjuice.pipeline import automation_repository
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config_file import save_config
from finjuice.pipeline.config_schema import (
    AutomationConfig,
    AutomationThresholdsConfig,
    DataConfig,
    UserConfig,
)
from finjuice.pipeline.storage.mutation_facade import StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand, capture_exact_xlsx
from tests.cli.commands.test_automation_run import _set_home
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_rules_suggest import _source_for_suggestions
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row
from tests.test_json_schemas import _load_schema, _validator_for


def _config(*, enabled=True, tagging=2, large=500):
    save_config(
        UserConfig(
            data=DataConfig(directory="/configured-synthetic-data"),
            automation=AutomationConfig(
                enabled=enabled,
                thresholds=AutomationThresholdsConfig(
                    untagged_count=tagging, large_transaction=large
                ),
            ),
            _automation_explicit=True,
        )
    )


@pytest.fixture
def active(tmp_path, monkeypatch):
    _set_home(monkeypatch, tmp_path)
    _config()
    root = _activate(_source_for_suggestions(tmp_path), tmp_path)
    (root.root / "imports").mkdir()
    return root


def _run(root, *, legacy=False, privacy="raw", human=False, evidence=True):
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(root.legacy if legacy else root.root),
            "automation",
            "run",
            "--privacy",
            privacy,
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": root.provider} if evidence and not legacy else {},
    )


def _payload(result):
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator_for(_load_schema("automation_run.schema.json")).validate(payload)
    return payload


def test_signals_match_legacy_and_ignore_live_domain_files(active):
    expected = _payload(_run(active, legacy=True))
    result = _payload(_run(active))
    for key in ("tagging_pressure", "large_transactions", "thresholds", "next_steps"):
        assert result[key] == expected[key]
    assert result["tagging_pressure"]["suggestable_untagged_transactions"] == 3
    assert result["large_transactions"]["count"] == 4  # Existing normalized transfer view.
    assert result["_meta"]["threshold_source"] == "runtime_config"
    assert result["_meta"]["calculation_policy"] == "legacy_automation_signals.v1"
    for name in ("rules.yaml", "goals.yaml", "metadata/import_history.csv"):
        path = active.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PRIVATE_POISON: [")
    shutil.rmtree(active.root / "transactions", ignore_errors=True)
    repeated = _payload(_run(active))
    assert repeated["tagging_pressure"] == result["tagging_pressure"]
    assert repeated["large_transactions"] == result["large_transactions"]


@pytest.mark.parametrize("privacy", ["raw", "redacted", "compact"])
def test_staged_independent_counts_privacy_and_no_mutation(active, privacy):
    data = _tx_book(_tx_row(2))
    imports = active.root / "imports"
    for name in ("PRIVATE_FIRST.xlsx", "PRIVATE_DUPLICATE.xlsx"):
        (imports / name).write_bytes(data)
    (imports / "PRIVATE_BROKEN.xlsx").write_bytes(b"bad workbook")
    before = read_checkup_snapshot(active.root, active.provider)
    payload = _payload(_run(active, privacy=privacy))
    pending = payload["pending_imports"]
    assert pending["pending_files"] == 2
    assert pending["estimated_new_rows"] == 2
    assert payload["_meta"]["staged_import_dispositions"]["transactions"]["inserted"] == 2
    assert payload["_meta"]["staged_observation"]["preview_policy"] == "independent_baseline.v1"
    assert payload["_meta"]["staged_observation"]["failed_files"] == 1
    if privacy == "raw":
        assert all(sample["validation_skips"] is None for sample in pending["sample_files"])
        assert pending["failed_files"][0]["error"] == "capture_failed"
    else:
        assert "PRIVATE_" not in json.dumps(payload)
    assert read_checkup_snapshot(active.root, active.provider) == before


def test_completed_noop_and_empty_workbook_remain_distinct(active):
    data = _tx_book(_tx_row(2))
    imports = active.root / "imports"
    (imports / "completed.xlsx").write_bytes(data)
    StorageMutationFacade(active.root, active.provider).import_exact_xlsx(
        ExactImportCommand(capture_exact_xlsx(data, filename="completed.xlsx"))
    )
    stream = BytesIO()
    Workbook().save(stream)
    (imports / "empty.xlsx").write_bytes(stream.getvalue())
    payload = _payload(_run(active))
    assert payload["pending_imports"]["pending_files"] == 1
    assert payload["pending_imports"]["estimated_new_rows"] == 0
    assert payload["pending_imports"]["sample_files"][0]["source_file"] == "empty.xlsx"
    assert payload["_meta"]["staged_observation"]["already_imported_files"] == 1


def test_capture_bytes_are_pinned_before_live_file_changes(active, monkeypatch):
    path = active.root / "imports/new.xlsx"
    path.write_bytes(_tx_book(_tx_row(2)))
    capture = automation_repository.capture_staged_imports
    calls = []

    def capture_then_change(*args, **kwargs):
        result = capture(*args, **kwargs)
        calls.append(result)
        path.write_bytes(b"PRIVATE_POISON")
        return result

    monkeypatch.setattr(automation_repository, "capture_staged_imports", capture_then_change)
    result = _payload(_run(active))
    assert len(calls) == 1
    assert result["pending_imports"]["estimated_new_rows"] == 1
    assert result["pending_imports"]["failed_files"] == []


def test_runtime_thresholds_change_without_repository_mutation(active):
    before = read_checkup_snapshot(active.root, active.provider)
    _config(enabled=False, tagging=0, large=0)
    payload = _payload(_run(active))
    assert payload["enabled"] is False and payload["actionable"] is False
    assert payload["large_transactions"]["count"] == 0
    assert payload["tagging_pressure"]["suggestable_untagged_transactions"] == 3
    assert payload["tagging_pressure"]["threshold_exceeded"] is False
    assert payload["next_steps"] == []
    human = _run(active, human=True)
    assert human.exit_code == 0, human.output
    assert "Repository revision 0" in human.output
    assert "thresholds: runtime config" in human.output
    assert "independent previews" in human.output
    assert read_checkup_snapshot(active.root, active.provider) == before


@pytest.mark.parametrize("privacy", ["raw", "redacted", "compact"])
def test_missing_evidence_is_static_failure_not_csv_fallback(active, privacy, caplog):
    (active.root / "rules.yaml").write_text("PRIVATE_POISON: [")
    result = _run(active, privacy=privacy, evidence=False)
    assert result.exit_code == 3, result.output
    assert "PRIVATE_POISON" not in result.output + caplog.text
    assert json.loads(result.output)["error"]["code"] == "VALIDATION_FAILED"


def test_legacy_redacted_merchant_amounts_satisfy_schema(active):
    payload = _payload(_run(active, legacy=True, privacy="redacted"))
    sample = payload["tagging_pressure"]["merchant_pressure"][0]
    assert sample["avg_amount"] is None and sample["total_amount"] is None


@pytest.mark.parametrize("amount", [float("nan"), float("inf")])
def test_nonfinite_pinned_amounts_fail_with_large_checks_disabled(active, monkeypatch, amount):
    project = automation_repository.analysis_frame

    def nonfinite_frame(*args, **kwargs):
        return project(*args, **kwargs).with_columns(pl.lit(amount).alias("amount"))

    monkeypatch.setattr(automation_repository, "analysis_frame", nonfinite_frame)
    _config(large=0)
    result = _run(active)
    assert result.exit_code == 3
    assert "complete validated evidence" in result.output
