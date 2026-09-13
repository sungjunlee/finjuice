"""Repository checkup composition uses one pinned canonical input bundle."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from finjuice.pipeline.checkup import repository
from finjuice.pipeline.checkup.compose import collect_checkup_bundle
from finjuice.pipeline.checkup.import_preview import StagedImportSummary
from finjuice.pipeline.checkup.repository import RepositoryCheckupOptions
from finjuice.pipeline.checkup.repository_inputs import scoped_transactions
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand, capture_exact_xlsx
from finjuice.pipeline.storage.sqlite.transaction_scopes import TransactionScope
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions
from tests.pipeline.test_sqlite_exact_import import _tx_book
from tests.pipeline.test_sqlite_exact_import import _tx_row as _workbook_row

TODAY = date(2026, 9, 13)


@pytest.fixture
def active(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> QueryRoot:
    source = init_data_dir(tmp_path, "source")
    write_transactions(
        source,
        "2026-09",
        [
            _tx_row("2026-09-01", -100, "synthetic", category_final="food", tags_final="[]"),
            _tx_row("2026-09-02", -200, "auxiliary", category_final="food", tags_final="[]"),
        ],
    )
    root = _activate(source, tmp_path)
    monkeypatch.setattr(
        "finjuice.pipeline.checkup.import_preview._now", lambda: "fixed-observation"
    )
    return root


def _collect(active: QueryRoot):
    return collect_checkup_bundle(
        Config(data_dir=active.root), today=TODAY, evidence_provider=active.provider
    )


def test_detach_once_then_writer_change_keeps_previous_bundle(
    active: QueryRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = _collect(active)
    calls = 0
    original = repository.read_checkup_snapshot

    def detach_then_mutate(*args, **kwargs):
        nonlocal calls
        calls += 1
        snapshot = original(*args, **kwargs)
        StorageMutationFacade(active.root, active.provider).replace_config(
            ConfigDocument("goals", b"PRIVATE_SENTINEL: [", "invalid", None, "test.v1")
        )
        return snapshot

    monkeypatch.setattr(repository, "read_checkup_snapshot", detach_then_mutate)
    pinned = _collect(active)
    assert calls == 1
    assert pinned == before
    monkeypatch.setattr(repository, "read_checkup_snapshot", original)
    fresh = _collect(active)
    assert fresh.repository is not None and before.repository is not None
    assert fresh.repository["dataset_revision"] == before.repository["dataset_revision"] + 1
    assert fresh.networth.status == "target_unknown"
    assert "PRIVATE_SENTINEL" not in str(fresh.to_dict())


def test_staged_pending_noop_and_capture_failure_are_readonly(active: QueryRoot) -> None:
    imports = active.root / "imports"
    imports.mkdir()
    data = _tx_book(_workbook_row(2))
    (imports / "new.xlsx").write_bytes(data)
    (imports / "broken.xlsx").write_bytes(b"not-a-workbook")
    before = read_checkup_snapshot(active.root, active.provider)
    pending = _collect(active)
    assert pending.pipeline.pending_import_files == 1
    assert pending.pipeline.failed_import_files == 1
    assert read_checkup_snapshot(active.root, active.provider) == before
    StorageMutationFacade(active.root, active.provider).import_exact_xlsx(
        ExactImportCommand(capture_exact_xlsx(data, filename="new.xlsx"))
    )
    after_import = read_checkup_snapshot(active.root, active.provider)
    completed = _collect(active)
    assert completed.pipeline.pending_import_files == 0
    assert completed.pipeline.failed_import_files == 1
    assert read_checkup_snapshot(active.root, active.provider) == after_import
    assert "broken.xlsx" not in str(completed.to_dict())


def test_unknown_month_included_aux_excluded_and_empty_latest_month(active: QueryRoot) -> None:
    snapshot = read_checkup_snapshot(active.root, active.provider)
    assert snapshot is not None
    transactions = snapshot.status.transactions
    first, second = transactions.rows
    scopes = (
        TransactionScope(first["transaction_id"], None, True),
        TransactionScope(second["transaction_id"], "2026-09", False, 2),
    )
    modified = replace(transactions, scopes=scopes, partition_months=("2026-09", "2026-10"))
    pinned = replace(snapshot, status=replace(snapshot.status, transactions=modified))
    frame = scoped_transactions(modified)
    assert frame.height == 1
    assert frame["transaction_id"].to_list() == [first["transaction_id"]]
    bundle = repository._collect(
        pinned,
        RepositoryCheckupOptions(Config(data_dir=active.root), TODAY, 35, 3, False),
        StagedImportSummary(0, 0, {"test": "captured"}, None),
    )
    assert bundle.repository is not None and bundle.repository["unknown_month_rows"] == 1
    assert bundle.pipeline.transaction_partitions == 2
    assert bundle.review.month == "2026-10"
    assert bundle.budget.month == "2026-10"

    native_only = replace(modified, partition_months=())
    native_bundle = repository._collect(
        replace(pinned, status=replace(pinned.status, transactions=native_only)),
        RepositoryCheckupOptions(Config(data_dir=active.root), TODAY, 35, 3, False),
        StagedImportSummary(0, 0, {"test": "captured"}, None),
    )
    assert native_bundle.pipeline.transaction_partitions == 0
    assert native_bundle.pipeline.status != "empty"
    assert native_bundle.pipeline.latest_transaction_date == first["date"]
