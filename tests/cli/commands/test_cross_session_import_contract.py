"""Independent source-identity checks after integrating targeted/history ingest."""

from __future__ import annotations

import json

import pytest

from finjuice.pipeline.cli.output import ExitCode
from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_import_commands import _transaction_count
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row

active_root = _active_root_fixture


def test_renamed_source_and_reused_filename_follow_bytes(
    active_root: _ActiveRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = active_root.root / "imports" / "monthly.xlsx"
    first_bytes = _tx_book(_tx_row(2, amount="-1000"))
    source.write_bytes(first_bytes)
    first = _invoke(active_root, "ingest", "--json")
    assert first.exit_code == ExitCode.SUCCESS, first.output

    def reject_legacy_history(*args, **kwargs):
        pytest.fail("Active ingest consulted filename-based legacy history")

    monkeypatch.setattr(
        "finjuice.pipeline.metadata.import_history_helpers.list_unprocessed_xlsx",
        reject_legacy_history,
    )
    source.rename(source.with_name("renamed.xlsx"))
    source.write_bytes(_tx_book(_tx_row(2, amount="-2000")))
    before_preview = _authority_state(active_root)

    preview = _invoke(active_root, "ingest", "--only-unprocessed", "--dry-run", "--json")
    assert preview.exit_code == ExitCode.SUCCESS, preview.output
    assert _authority_state(active_root) == before_preview
    assert _transaction_count(active_root) == 1

    applied = _invoke(active_root, "ingest", "--only-unprocessed", "--json")
    assert applied.exit_code == ExitCode.SUCCESS, applied.output
    assert _transaction_count(active_root) == 2
    assert json.loads(applied.output)["summary"]["new_transactions"] == 1

    replay = _invoke(active_root, "ingest", "--only-unprocessed", "--json")
    assert replay.exit_code == ExitCode.SUCCESS, replay.output
    assert json.loads(replay.output)["summary"]["new_transactions"] == 0
    assert _transaction_count(active_root) == 2
