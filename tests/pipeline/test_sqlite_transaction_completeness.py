"""Completeness metadata is collected once and enforced only on requested scopes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from finjuice.pipeline.storage.read_facade import (
    read_analysis_snapshot,
    read_checkup_snapshot,
    transaction_frame,
)
from finjuice.pipeline.storage.sqlite import analysis_reads, transaction_completeness
from tests.cli.commands.test_repository_query import QueryRoot
from tests.cli.commands.test_repository_query import query_root as _query_root_fixture

query_root = _query_root_fixture


def test_analysis_and_checkup_reuse_transaction_completeness(
    query_root: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    from finjuice.pipeline.storage.sqlite import transaction_reads

    calls = 0
    original = transaction_reads.unmaterialized_transaction_months

    def counted(connection):
        nonlocal calls
        calls += 1
        return original(connection)

    monkeypatch.setattr(transaction_reads, "unmaterialized_transaction_months", counted)
    analysis = read_analysis_snapshot(query_root.root, query_root.provider)
    assert analysis is not None and calls == 1
    checkup = read_checkup_snapshot(query_root.root, query_root.provider)
    assert checkup is not None and calls == 2
    assert analysis.unmaterialized_months == analysis.transactions.unmaterialized_months == ()
    assert checkup.unmaterialized_months == checkup.status.transactions.unmaterialized_months == ()
    assert (
        analysis_reads.unmaterialized_transaction_months
        is transaction_completeness.unmaterialized_transaction_months
    )


def test_frame_projection_does_not_globally_reject_other_month(query_root: QueryRoot) -> None:
    analysis = read_analysis_snapshot(query_root.root, query_root.provider)
    assert analysis is not None
    snapshot = replace(analysis.transactions, unmaterialized_months=("1900-01",))
    assert transaction_frame(snapshot).height == len(snapshot.rows)
    transaction_completeness.require_transaction_completeness(snapshot, month="2026-09")
