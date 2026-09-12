"""A partially committed pipeline must fail without hiding completed receipts."""

from __future__ import annotations

import json

import pytest

from finjuice.pipeline.cli.commands import full_pipeline_orchestrator as pipeline
from finjuice.pipeline.cli.output import ExitCode
from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture

active_root = _active_root_fixture


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_partial_ingest_stops_later_steps_and_returns_committed_receipts(
    active_root: _ActiveRoot, monkeypatch: pytest.MonkeyPatch, json_output: bool
) -> None:
    partial = {
        "summary": {
            "files_processed": 2,
            "new_transactions": 1,
            "updated": 0,
            "failed": 1,
            "failed_files": [["synthetic-bad.xlsx", "invalid workbook"]],
        },
        "receipts": [{"changeset_id": "synthetic-committed-receipt"}],
    }

    def reject_later_step(*args, **kwargs):
        pytest.fail("A later pipeline step ran after partial ingest failure")

    monkeypatch.setattr(pipeline, "compute_full_pipeline_ingest", lambda *a, **kw: partial)
    for name in ("tag", "transfer", "export"):
        monkeypatch.setattr(pipeline, f"compute_full_pipeline_{name}", reject_later_step)
    before = _authority_state(active_root)

    result = _invoke(active_root, "refresh", *(["--json"] if json_output else []))

    assert result.exit_code == ExitCode.GENERAL_ERROR, result.output
    if json_output:
        recorded = json.loads(result.output)["_meta"]["pipeline"]
        assert recorded["failed_step"] == "ingest"
        assert recorded["completed_steps"] == []
        assert recorded["steps"]["ingest"] == partial
    else:
        assert "파이프라인 완료" not in result.output
        assert "ingest" in result.output
    assert _authority_state(active_root) == before


def test_export_exception_retains_prior_step_results_without_raw_error_text(
    active_root: _ActiveRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    completed = {
        "ingest": {"summary": {"failed": 0}, "receipt": {"changeset_id": "import-receipt"}},
        "tag": {"changeset_id": "tag-receipt"},
        "transfer": {"changeset_id": "transfer-receipt"},
    }
    for step, payload in completed.items():
        monkeypatch.setattr(
            pipeline,
            f"compute_full_pipeline_{step}",
            lambda *args, _payload=payload, **kwargs: _payload,
        )

    def fail_export(*args, **kwargs):
        raise OSError("synthetic-sensitive-error-detail")

    monkeypatch.setattr(pipeline, "compute_full_pipeline_export", fail_export)
    before = _authority_state(active_root)

    result = _invoke(active_root, "refresh", "--json")

    assert result.exit_code == ExitCode.GENERAL_ERROR, result.output
    recorded = json.loads(result.output)["_meta"]["pipeline"]
    assert recorded["failed_step"] == "export"
    assert recorded["completed_steps"] == ["ingest", "tag", "transfer"]
    assert recorded["steps"] == completed
    assert recorded["error_type"] == "OSError"
    assert "synthetic-sensitive-error-detail" not in result.output
    assert _authority_state(active_root) == before
