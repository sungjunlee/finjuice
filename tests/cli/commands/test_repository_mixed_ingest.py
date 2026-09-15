"""Batch previews follow committed overlap and replay decisions across input formats."""

from __future__ import annotations

import pytest

from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.cli.commands.test_repository_statement_ingest import (
    _bind,
    _payload,
    _stage,
    _transactions,
)
from tests.pipeline.test_canonical_statement_json import _envelope, _record
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row

active_root = _active_root_fixture


@pytest.mark.parametrize("first_format", ["json", "xlsx", "same_xlsx"])
def test_batch_preview_matches_committed_overlap_and_replay(
    active_root: _ActiveRoot, first_format: str
) -> None:
    _bind(active_root)
    workbook = _tx_book(_tx_row(2, time_text=None))
    if first_format == "json":
        _stage(
            active_root,
            "a.json",
            _envelope(
                [
                    _record(
                        "same-transaction",
                        amount="-1000.00",
                        occurred_on="2024-03-15",
                        occurred_at=None,
                        decision={"action": "create"},
                    )
                ]
            ),
        )
    else:
        first = workbook if first_format == "same_xlsx" else _tx_book(_tx_row(3, time_text=None))
        (active_root.root / "imports" / "a.xlsx").write_bytes(first)
    (active_root.root / "imports" / "b.xlsx").write_bytes(workbook)
    before = _authority_state(active_root)

    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))

    assert _authority_state(active_root) == before
    applied = _payload(_invoke(active_root, "ingest", "--json"))
    assert preview["summary"] == applied["summary"]
    assert preview["summary"]["new_transactions"] == 1
    assert [r["result"]["counts"] for r in preview["receipts"]] == [
        r["result"]["counts"] for r in applied["receipts"]
    ]
    assert len(_transactions(active_root)) == 1
    retry = _payload(_invoke(active_root, "ingest", "--json"))
    assert retry["summary"]["new_transactions"] == 0
    assert len(_transactions(active_root)) == 1
