"""Observed staged input summaries never reread canonical or live source state."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finjuice.pipeline.checkup import import_preview
from finjuice.pipeline.checkup.import_preview import (
    StagedImportObservationError,
    capture_staged_imports,
    summarize_staged_imports,
)
from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.exact_import.preview import ImportPreviewSnapshot
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row


def _snapshot(digests: tuple[str, ...]) -> ImportPreviewSnapshot:
    return ImportPreviewSnapshot(
        RepositoryInfo(1, 5, "synthetic-generation", 7), (), {digest: () for digest in digests}
    )


def test_capture_order_duplicates_and_live_changes(tmp_path: Path) -> None:
    content = _tx_book(_tx_row(2))
    (tmp_path / "z.xlsx").write_bytes(content)
    (tmp_path / "a.xlsx").write_bytes(content)
    observation = capture_staged_imports(tmp_path)
    assert [capture.filename for capture in observation.captures] == ["a.xlsx", "z.xlsx"]
    assert len(observation.digests) == 1
    for path in tmp_path.iterdir():
        path.write_text("PRIVATE_SENTINEL corrupt")
    summary = summarize_staged_imports(observation, _snapshot(observation.digests))
    assert summary.pending_files == 2
    assert summary.failed_files == 0
    assert summary.metadata["preview_policy"] == "independent_baseline.v1"
    assert summary.metadata["dataset_revision"] == 7
    assert summary.metadata["unique_digest_count"] == 1
    text = json.dumps(summary.metadata)
    assert str(tmp_path) not in text
    assert "a.xlsx" not in text and "PRIVATE_SENTINEL" not in text
    assert observation.digests[0] not in text


def test_fast_does_not_open_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / "private.xlsx").write_text("invalid")

    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("must not capture")

    monkeypatch.setattr(import_preview, "capture_exact_xlsx", forbidden)
    observation = capture_staged_imports(tmp_path, fast=True)
    summary = summarize_staged_imports(observation, _snapshot(()))
    assert summary.pending_files == 1
    assert summary.failed_files == 0
    assert summary.metadata["files_not_examined"] == 1
    assert summary.metadata["files_examined"] == 0
    assert summary.warning is not None


def test_capture_failure_continues_and_is_private(tmp_path: Path) -> None:
    (tmp_path / "a-PRIVATE_SENTINEL.xlsx").write_bytes(b"private invalid xlsx")
    (tmp_path / "b.xlsx").write_bytes(_tx_book(_tx_row(2)))
    observation = capture_staged_imports(tmp_path)
    summary = summarize_staged_imports(observation, _snapshot(observation.digests))
    assert summary.pending_files == summary.failed_files == 1
    assert summary.metadata["files_examined"] == 2
    assert summary.metadata["failure_codes"] == {"capture_failed": 1}
    assert "PRIVATE_SENTINEL" not in json.dumps(summary.metadata)


@pytest.mark.parametrize("noop", [True, False])
def test_only_verified_noop_is_not_pending(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, noop: bool
) -> None:
    (tmp_path / "one.xlsx").write_bytes(_tx_book(_tx_row(2)))
    observation = capture_staged_imports(tmp_path)
    monkeypatch.setattr(
        import_preview,
        "preview_captured_import",
        lambda *_: MutationOutcome(
            result={"noop": noop, "counts": {"transactions": {"quarantined": 1}}}
        ),
    )
    summary = summarize_staged_imports(observation, _snapshot(observation.digests))
    assert summary.pending_files == (0 if noop else 1)
    assert summary.metadata["already_imported_files"] == (1 if noop else 0)


def test_mapping_failure_continues(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = _tx_book(_tx_row(2))
    (tmp_path / "a.xlsx").write_bytes(content)
    (tmp_path / "b.xlsx").write_bytes(content)
    observation = capture_staged_imports(tmp_path)
    calls = 0

    def preview(*args: object) -> MutationOutcome:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("PRIVATE_SENTINEL")
        return MutationOutcome(result={"noop": False})

    monkeypatch.setattr(import_preview, "preview_captured_import", preview)
    summary = summarize_staged_imports(observation, _snapshot(observation.digests))
    assert calls == 2 and summary.failed_files == summary.pending_files == 1
    assert summary.metadata["failure_codes"] == {"mapping_failed": 1}


def test_unrequested_lookup_fails_entire_summary(tmp_path: Path) -> None:
    (tmp_path / "one.xlsx").write_bytes(_tx_book(_tx_row(2)))
    observation = capture_staged_imports(tmp_path)
    with pytest.raises(MutationValidationError):
        summarize_staged_imports(observation, _snapshot(()))


def test_inventory_failure_never_means_clear(tmp_path: Path) -> None:
    invalid = tmp_path / "private-file"
    invalid.write_text("not a directory")
    with pytest.raises(StagedImportObservationError, match="could not be observed"):
        capture_staged_imports(invalid)


def test_absent_directory_is_explicit_empty_observation(tmp_path: Path) -> None:
    observation = capture_staged_imports(tmp_path / "missing")
    summary = summarize_staged_imports(observation, _snapshot(()))
    assert summary.pending_files == summary.failed_files == 0
    assert summary.metadata["directory_state"] == "absent"
    assert summary.metadata["files_seen"] == 0
    assert summary.warning is None
    assert capture_staged_imports(tmp_path).metadata["directory_state"] == "present"
