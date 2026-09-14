"""Active ingest must use canonical byte identity, never legacy filename history.

Covers the ``--force`` / ``--only-unprocessed`` flags that arrived with the
legacy history-skip work (#474) once repository authority is active.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finjuice.pipeline.cli.output import ExitCode
from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_import_commands import _transaction_count, _write_xlsx
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.pipeline.test_sqlite_exact_import import _inline, _row, _tx_book, _tx_row

active_root = _active_root_fixture

_HISTORY_HEADER = (
    "file_id,original_filename,imported_from,archived,archived_path,imported_at,source_rows"
)


def _write_legacy_history(root: Path, filenames: list[str]) -> Path:
    """Plant a legacy import_history.csv that active ingest must ignore."""
    metadata_dir = root / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    lines = [_HISTORY_HEADER]
    for index, name in enumerate(filenames, start=1):
        lines.append(f"250101_{index},{name},/tmp/{name},no,,2025-01-01T00:00:00,1")
    history = metadata_dir / "import_history.csv"
    history.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return history


def _other_bytes(path: Path) -> None:
    """Write a valid workbook whose bytes differ from :func:`_write_xlsx`."""
    path.write_bytes(_tx_book(_tx_row(2), extra_sheets={"notes": _row(1, _inline("A1", "other"))}))


def test_force_and_only_unprocessed_conflict_before_any_active_write(
    active_root: _ActiveRoot,
) -> None:
    """Mutually exclusive flags must fail before the exact domain is touched."""
    _write_xlsx(active_root.root / "imports" / "staged.xlsx")
    before = _authority_state(active_root)

    result = _invoke(active_root, "ingest", "--force", "--only-unprocessed", "--json")

    assert result.exit_code == ExitCode.USAGE_ERROR, result.output
    payload = json.loads(result.output)
    assert "--force" in payload["error"]["message"]
    assert "--only-unprocessed" in payload["error"]["message"]
    assert _authority_state(active_root) == before


def test_only_unprocessed_imports_changed_bytes_under_reused_filename(
    active_root: _ActiveRoot,
) -> None:
    """A reused filename with different bytes is new canonical work, not a skip."""
    staged = active_root.root / "imports" / "reused.xlsx"
    _write_xlsx(staged)
    first = _invoke(active_root, "ingest", "--json")
    assert first.exit_code == ExitCode.SUCCESS, first.output
    first_receipt = json.loads(first.output)["receipts"][0]

    _other_bytes(staged)
    second = _invoke(active_root, "ingest", "--only-unprocessed", "--json")

    assert second.exit_code == ExitCode.SUCCESS, second.output
    payload = json.loads(second.output)
    receipt = payload["receipts"][0]
    assert receipt["filename"] == "reused.xlsx"
    # The new bytes were interpreted as their own artifact, not skipped by name.
    assert receipt["result"]["noop"] is False
    assert receipt["result"]["artifact_id"] != first_receipt["result"]["artifact_id"]
    assert receipt["result"]["occurrence_id"] != first_receipt["result"]["occurrence_id"]
    assert payload["history_skipped"] == 0
    assert payload["would_parse"] == 1


def test_only_unprocessed_same_bytes_is_canonical_noop(active_root: _ActiveRoot) -> None:
    """Identical bytes reuse the completed occurrence and report a truthful skip."""
    staged = active_root.root / "imports" / "same.xlsx"
    _write_xlsx(staged)
    first = _invoke(active_root, "ingest", "--json")
    assert first.exit_code == ExitCode.SUCCESS, first.output
    first_receipt = json.loads(first.output)["receipts"][0]
    rows_before = _transaction_count(active_root)

    second = _invoke(active_root, "ingest", "--only-unprocessed", "--json")

    assert second.exit_code == ExitCode.SUCCESS, second.output
    payload = json.loads(second.output)
    receipt = payload["receipts"][0]
    assert receipt["result"]["noop"] is True
    assert receipt["result"]["occurrence_id"] == first_receipt["result"]["occurrence_id"]
    assert receipt["result"]["counts"]["transactions"]["inserted"] == 0
    assert payload["history_skipped"] == 1
    assert payload["would_parse"] == 0
    assert _transaction_count(active_root) == rows_before


def test_only_unprocessed_ignores_legacy_import_history(active_root: _ActiveRoot) -> None:
    """A legacy history row for this filename must not fake a canonical skip."""
    staged = active_root.root / "imports" / "claimed.xlsx"
    _write_xlsx(staged)
    history = _write_legacy_history(active_root.root, ["claimed.xlsx"])
    history_before = history.read_bytes()

    result = _invoke(active_root, "ingest", "--only-unprocessed", "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 1
    assert payload["history_skipped"] == 0
    assert payload["would_parse"] == 1
    assert history.read_bytes() == history_before


def test_dry_run_ignores_legacy_import_history_and_previews_bytes(
    active_root: _ActiveRoot,
) -> None:
    """Default active preview previews staged bytes regardless of legacy history."""
    staged = active_root.root / "imports" / "preview.xlsx"
    _write_xlsx(staged)
    _write_legacy_history(active_root.root, ["preview.xlsx"])
    before = _authority_state(active_root)

    result = _invoke(active_root, "ingest", "--dry-run", "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 1
    assert payload["history_skipped"] == 0
    assert payload["would_parse"] == 1
    assert _authority_state(active_root) == before


def test_active_ingest_never_reads_legacy_history_helpers(
    active_root: _ActiveRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Active authority must not call the filename-based history helpers at all."""
    _write_xlsx(active_root.root / "imports" / "fresh.xlsx")
    _write_legacy_history(active_root.root, ["fresh.xlsx"])

    def _reject(*args: object, **kwargs: object) -> object:
        pytest.fail("Active ingest read legacy filename-based import history")

    monkeypatch.setattr(
        "finjuice.pipeline.metadata.import_history_helpers.list_unprocessed_xlsx", _reject
    )
    monkeypatch.setattr(
        "finjuice.pipeline.metadata.import_history_helpers.processed_original_filenames", _reject
    )

    result = _invoke(active_root, "ingest", "--only-unprocessed", "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output


def test_active_orchestrator_empty_file_paths_imports_nothing(active_root: _ActiveRoot) -> None:
    """An explicit empty list must not fall back to globbing imports/."""
    from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import (
        compute_full_pipeline_ingest,
    )
    from finjuice.pipeline.config import Config

    _write_xlsx(active_root.root / "imports" / "leftover.xlsx")
    before = _authority_state(active_root)

    result = compute_full_pipeline_ingest(
        Config(data_dir=active_root.root), [], facade=active_root.facade
    )

    assert result["authority"] == "repository"
    assert result["receipts"] == []
    assert result["summary"]["files_processed"] == 0
    assert _authority_state(active_root) == before


def test_active_orchestrator_explicit_file_paths_ignores_siblings(
    active_root: _ActiveRoot, tmp_path: Path
) -> None:
    """Explicit workbooks are imported; staged siblings are left alone."""
    from finjuice.pipeline.cli.commands.full_pipeline_orchestrator import (
        compute_full_pipeline_ingest,
    )
    from finjuice.pipeline.config import Config

    target = tmp_path / "target.xlsx"
    _write_xlsx(target)
    _other_bytes(active_root.root / "imports" / "leftover.xlsx")

    result = compute_full_pipeline_ingest(
        Config(data_dir=active_root.root), [target], facade=active_root.facade
    )

    assert result["source"] == "files"
    assert [receipt["filename"] for receipt in result["receipts"]] == ["target.xlsx"]
    assert result["summary"]["failed"] == 0
