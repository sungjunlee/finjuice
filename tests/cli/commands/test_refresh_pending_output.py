"""Full-pipeline progress preserves pending statement visibility."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from finjuice.pipeline.cli.commands import refresh_cmd
from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import FullPipelineOptions


@pytest.mark.parametrize("pending", [None, 0, 2])
@pytest.mark.parametrize("failed", [0, 1])
@pytest.mark.parametrize("json_output", [False, True])
def test_refresh_pending_statement_notice(
    monkeypatch: pytest.MonkeyPatch,
    pending: int | None,
    failed: int,
    json_output: bool,
) -> None:
    # Arrange: exercise the real progress callback with a synthetic ingest result.
    summary = {"new_transactions": 0, "updated": 0, "failed": failed}
    if pending is not None:
        summary["pending"] = pending
    result = {"steps": {"ingest": {"summary": summary}}}
    warnings: list[str] = []
    monkeypatch.setattr(refresh_cmd.output, "warning", warnings.append)

    def run_pipeline(_ctx: Any, _config: Any, options: FullPipelineOptions) -> dict[str, Any]:
        if options.on_step_complete is not None:
            options.on_step_complete("ingest", result["steps"]["ingest"], 1, 4)
        return result

    monkeypatch.setattr(refresh_cmd, "run_full_pipeline_orchestrator", run_pipeline)

    # Act.
    actual = refresh_cmd._compute_full_pipeline_result(
        MagicMock(), MagicMock(), json_output, command_name="refresh"
    )

    # Assert: pending rows remain visible alongside success or failure, without JSON changes.
    notices = [message for message in warnings if "Pending statement records:" in message]
    assert notices == (
        ["  Pending statement records: 2 (awaiting confirmation)"]
        if pending and not json_output
        else []
    )
    assert actual is result
    assert ("pending" in summary) == (pending is not None)
