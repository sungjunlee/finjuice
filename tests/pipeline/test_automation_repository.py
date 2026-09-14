"""Automation composition remains pinned and independent of live legacy files."""

from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline import automation_repository as adapter
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, write_transactions
from tests.pipeline.test_suggestion_repository import root

__all__ = ["root"]
OPTIONS = adapter.RepositoryAutomationOptions(10)


def _collect(root: QueryRoot, options=OPTIONS):
    return adapter.collect_repository_automation(Config(data_dir=root.root), root.provider, options)


def test_live_poison_and_unrelated_invalid_goals(root: QueryRoot, monkeypatch) -> None:
    monkeypatch.setattr("finjuice.pipeline.checkup.import_preview._now", lambda: "fixed")
    before = _collect(root)
    assert before is not None
    (root.root / "rules.yaml").write_bytes(b"PRIVATE_POISON: [")
    (root.root / "goals.yaml").write_bytes(b"PRIVATE_POISON: [")
    write_transactions(
        root.root,
        "2026-08",
        [_tx_row("2026-08-01", -99999, "PRIVATE_POISON", category_final="food", tags_final="[]")],
    )
    assert _collect(root) == before
    StorageMutationFacade(root.root, root.provider).replace_config(
        ConfigDocument("goals", b"PRIVATE_GOAL: [", "invalid", None, "test.v1")
    )
    after = _collect(root)
    assert after is not None and after.summary == before.summary
    assert after.metadata["dataset_revision"] == 1
    assert "PRIVATE_GOAL" not in str(after)


def test_one_read_pin_between_calculations(root: QueryRoot, monkeypatch) -> None:
    original_read = adapter.read_checkup_snapshot
    original_suggest = adapter.suggestions_from_frame
    reads = []

    def read(*args, **kwargs):
        reads.append(1)
        return original_read(*args, **kwargs)

    def suggest(*args):
        result = original_suggest(*args)
        StorageMutationFacade(root.root, root.provider).replace_config(
            ConfigDocument("rules", b"PRIVATE_POISON: [", "invalid", None, "test.v1")
        )
        return result

    monkeypatch.setattr(adapter, "read_checkup_snapshot", read)
    monkeypatch.setattr(adapter, "suggestions_from_frame", suggest)
    pinned = _collect(root)
    assert pinned is not None and pinned.metadata["dataset_revision"] == 0
    assert len(reads) == 1
    assert pinned.summary.large_transactions.count == 2
    with pytest.raises(adapter.RepositoryAutomationError):
        _collect(root)


def test_zero_large_threshold_does_not_change_tagging(root: QueryRoot) -> None:
    before = _collect(root)
    disabled = _collect(root, replace(OPTIONS, large_transaction_threshold=0))
    assert before is not None and disabled is not None
    assert disabled.summary.large_transactions.status == "clear"
    assert disabled.summary.large_transactions.count == 0
    assert disabled.summary.tagging_pressure == before.summary.tagging_pressure
    assert disabled.metadata["threshold_source"] == "runtime_config"


@pytest.mark.parametrize("opaque", [False, True])
def test_incomplete_or_invalid_empty_never_clear_success(tmp_path: Path, opaque: bool) -> None:
    source = tmp_path / "source"
    source.mkdir()
    write_transactions(
        source,
        "2026-08",
        [
            _tx_row(
                "2026-08-01",
                -20,
                "PRIVATE_POISON",
                category_final="food",
                tags_final="bad[" if opaque else "[]",
            )
        ],
    )
    if not opaque:
        path = source / "transactions/2026/08/transactions.csv"
        path.write_text(path.read_text().splitlines()[0] + "\n")
        (source / "rules.yaml").write_bytes(b"PRIVATE_POISON: [")
    active = _activate(source, tmp_path)
    with pytest.raises(adapter.RepositoryAutomationError, match="complete validated evidence"):
        _collect(active)


def test_detached_scope_excludes_auxiliary(root: QueryRoot) -> None:
    config = Config(data_dir=root.root)
    staged = adapter.capture_staged_imports(config.import_dir)
    snapshot = adapter.read_checkup_snapshot(root.root, root.provider, digests=staged.digests)
    assert snapshot is not None
    transactions = snapshot.status.transactions
    scopes = tuple(replace(scope, included=False) for scope in transactions.scopes)
    changed = replace(
        snapshot, status=replace(snapshot.status, transactions=replace(transactions, scopes=scopes))
    )
    result = adapter.automation_from_snapshot(config, changed, staged, OPTIONS)
    assert result.summary.large_transactions.count == 0
    assert result.summary.tagging_pressure.status == "clear"
