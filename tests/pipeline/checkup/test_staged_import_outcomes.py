"""Private per-file staged outcomes share one preview pass with public totals."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline.checkup import import_preview as preview
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome
from tests.pipeline.checkup.test_repository_import_preview import _snapshot
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row


def test_outcomes_counts_failures_order_and_one_pass(tmp_path: Path, monkeypatch) -> None:
    for name in ("b.xlsx", "a.xlsx", "d.xlsx"):
        (tmp_path / name).write_bytes(_tx_book(_tx_row(2)))
    (tmp_path / "c-PRIVATE.xlsx").write_bytes(b"invalid")
    observation = preview.capture_staged_imports(tmp_path)
    calls = []
    counts = {"transactions": {"inserted": 2, "quarantined": 1}}

    def evaluate(command, snapshot):
        calls.append(command.capture.filename)
        if command.capture.filename == "d.xlsx":
            raise MutationConflictError("PRIVATE_EXCEPTION")
        return MutationOutcome(
            result={"noop": command.capture.filename == "b.xlsx", "counts": counts}
        )

    monkeypatch.setattr(preview, "preview_captured_import", evaluate)
    result = preview.evaluate_staged_imports(observation, _snapshot(observation.digests))
    assert calls == ["a.xlsx", "b.xlsx", "d.xlsx"]
    assert [(item.filename, item.status) for item in result.outcomes] == [
        ("a.xlsx", "pending"),
        ("b.xlsx", "noop"),
        ("c-PRIVATE.xlsx", "failed"),
        ("d.xlsx", "failed"),
    ]
    assert result.summary.pending_files == 1 and result.summary.failed_files == 2
    assert result.summary.metadata["already_imported_files"] == 1
    assert result.outcomes[1].counts == counts
    counts["transactions"]["inserted"] = 99
    assert result.outcomes[0].counts["transactions"]["inserted"] == 2
    assert "PRIVATE" not in json.dumps(result.summary.metadata)


def test_old_positional_failures_and_fast_have_no_invented_filenames() -> None:
    observation = preview.StagedImportObservation((), (), {"fast": False}, 2, 2)
    result = preview.evaluate_staged_imports(observation, _snapshot(()))
    assert result.outcomes == () and result.summary.failed_files == 2
    assert result.summary.metadata["failure_codes"] == {"capture_failed": 2}
    fast = replace(observation, metadata={"fast": True}, capture_failed_files=0)
    result = preview.evaluate_staged_imports(fast, _snapshot(()))
    assert result.outcomes == () and result.summary.pending_files == 2
    assert result.summary.warning is not None


def test_lookup_failure_propagates_and_summary_delegates(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / "a.xlsx").write_bytes(_tx_book(_tx_row(2)))
    observation = preview.capture_staged_imports(tmp_path)
    with pytest.raises(MutationValidationError):
        preview.evaluate_staged_imports(observation, _snapshot(()))
    expected = preview.StagedImportSummary(0, 0, {}, None)
    monkeypatch.setattr(
        preview, "evaluate_staged_imports", lambda *_: preview.StagedImportEvaluation((), expected)
    )
    assert preview.summarize_staged_imports(observation, _snapshot(())) is expected
