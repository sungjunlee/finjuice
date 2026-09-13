"""Doctor canonical domains remain pinned, independent and private-content safe."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor import repository
from finjuice.pipeline.storage.mutation_facade import ConfigDocument, StorageMutationFacade
from finjuice.pipeline.storage.read_facade import read_checkup_snapshot
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand, capture_exact_xlsx
from tests.cli.commands.test_repository_assets import _activate
from tests.cli.commands.test_repository_query import QueryRoot
from tests.pipeline.checkup.helpers import _tx_row, init_data_dir, write_transactions
from tests.pipeline.test_sqlite_exact_import import _tx_book
from tests.pipeline.test_sqlite_exact_import import _tx_row as _workbook_row


@pytest.fixture
def active(tmp_path: Path) -> QueryRoot:
    source = init_data_dir(tmp_path, "source")
    write_transactions(
        source,
        "2026-09",
        [_tx_row("2026-09-01", -100, "private", category_final="food", tags_final="[]")],
    )
    return _activate(source, tmp_path)


def _collect(active: QueryRoot):
    result = repository.collect_repository_doctor(Config(data_dir=active.root), active.provider)
    assert result is not None
    return result


def test_live_poison_ignored_and_dates_counted(active: QueryRoot) -> None:
    before = _collect(active)
    (active.root / "rules.yaml").write_text("PRIVATE: [")
    (active.legacy / "rules.yaml").write_text("PRIVATE: [")
    after = _collect(active)
    assert before.metadata["transaction_total"] == after.metadata["transaction_total"] == 1
    assert after.metadata["date_min"] == after.metadata["date_max"] == "2026-09-01"
    assert after.config_checks == before.config_checks
    assert after.metadata["staged_observation"]["directory_state"] == "absent"
    assert "PRIVATE" not in str(after)


def test_verified_legacy_only_and_missing_authority(active: QueryRoot, tmp_path: Path) -> None:
    assert repository.collect_repository_doctor(Config(data_dir=tmp_path / "legacy"), None) is None
    result = repository.collect_repository_doctor(Config(data_dir=active.root), None)
    assert result is not None
    assert result.metadata["authority"] == "unavailable"
    assert result.data_checks[0].status == "error"
    assert result.next_step == "finjuice status --json"


@pytest.mark.parametrize("opaque", [False, True])
def test_empty_or_opaque_transactions_do_not_hide_valid_rules(tmp_path: Path, opaque: bool) -> None:
    source = init_data_dir(tmp_path, "source")
    path = source / "transactions/2026/09/transactions.csv"
    path.parent.mkdir(parents=True)
    path.write_text("amount,amount\n1,2\n" if opaque else "row_hash,date,amount\n")
    (source / "goals.yaml").write_text("PRIVATE: [")
    active = _activate(source, tmp_path)
    result = _collect(active)
    assert result.config_checks[0].status == "ok"
    assert result.metadata["transaction_total"] == (None if opaque else 0)
    assert result.metadata["transaction_state"] == ("incomplete" if opaque else "available")
    assert result.metadata["date_min"] is None


@pytest.mark.parametrize("state", ["absent", "unselected", "invalid", "regex"])
def test_rules_selection_and_validation_are_static(
    active: QueryRoot, state: str, caplog, monkeypatch
) -> None:
    snapshot = read_checkup_snapshot(active.root, active.provider)
    assert snapshot is not None and snapshot.rules.head is not None
    selection = snapshot.rules
    if state == "absent":
        selection = replace(selection, head=None, selection_state="absent", revisions=())
    elif state == "unselected":
        selection = replace(selection, head=None, selection_state="unselected")
    else:
        content = (
            b"rules: []\n"
            if state == "invalid"
            else (
                b"rules:\n- name: PRIVATE\n  conditions:\n  - field: merchant_raw\n"
                b"    op: regex\n    value: '['\n  tags: [PRIVATE]\n"
            )
        )
        selection = replace(
            selection,
            head=replace(
                selection.head,
                content=content,
                parsed_status="invalid" if state == "invalid" else "parsed",
            ),
        )
    monkeypatch.setattr(
        repository, "read_checkup_snapshot", lambda *a, **k: replace(snapshot, rules=selection)
    )
    result = _collect(active)
    assert result.config_checks[0].status == ("warning" if state == "absent" else "error")
    assert "PRIVATE" not in str(result) + caplog.text
    assert result.metadata["transaction_total"] == 1


def test_single_detach_mutation_and_staged_pass(active: QueryRoot, monkeypatch) -> None:
    before = _collect(active)
    original_read = repository.read_checkup_snapshot
    original_capture = repository.capture_staged_imports
    original_evaluate = repository.evaluate_staged_imports
    calls = []

    def read(*args, **kwargs):
        calls.append("read")
        snapshot = original_read(*args, **kwargs)
        StorageMutationFacade(active.root, active.provider).replace_config(
            ConfigDocument("rules", b"rules: []\n", "invalid", None, "test.v1")
        )
        return snapshot

    def capture(*args, **kwargs):
        calls.append("capture")
        return original_capture(*args, **kwargs)

    def evaluate(*args, **kwargs):
        calls.append("evaluate")
        return original_evaluate(*args, **kwargs)

    monkeypatch.setattr(repository, "read_checkup_snapshot", read)
    monkeypatch.setattr(repository, "capture_staged_imports", capture)
    monkeypatch.setattr(repository, "evaluate_staged_imports", evaluate)
    pinned = _collect(active)
    assert calls == ["capture", "read", "evaluate"]
    assert pinned.config_checks == before.config_checks
    assert pinned.metadata["dataset_revision"] == before.metadata["dataset_revision"]
    monkeypatch.setattr(repository, "read_checkup_snapshot", original_read)
    fresh = _collect(active)
    assert fresh.metadata["dataset_revision"] == before.metadata["dataset_revision"] + 1
    assert fresh.config_checks[0].status == "error"


def test_staged_native_noop_and_failures_are_readonly(active: QueryRoot) -> None:
    imports = active.root / "imports"
    imports.mkdir()
    data = _tx_book(_workbook_row(2))
    (imports / "PRIVATE.xlsx").write_bytes(data)
    (imports / "PRIVATE-broken.xlsx").write_bytes(b"broken")
    before = read_checkup_snapshot(active.root, active.provider)
    pending = _collect(active)
    assert pending.metadata["staged_observation"]["pending_files"] == 1
    assert pending.metadata["staged_observation"]["failed_files"] == 1
    assert "PRIVATE" not in str(pending)
    assert read_checkup_snapshot(active.root, active.provider) == before
    StorageMutationFacade(active.root, active.provider).import_exact_xlsx(
        ExactImportCommand(capture_exact_xlsx(data, filename="PRIVATE.xlsx"))
    )
    result = _collect(active)
    assert result.metadata["staged_observation"]["already_imported_files"] == 1
    assert result.metadata["staged_observation"]["pending_files"] == 0
    assert result.metadata["transaction_total"] == 2


def test_staged_inventory_failure_preserves_other_domains(active: QueryRoot) -> None:
    (active.root / "imports").write_text("PRIVATE")
    result = _collect(active)
    assert result.config_checks[0].status == "ok"
    assert result.metadata["transaction_total"] == 1
    assert result.metadata["staged_observation"]["state"] == "unavailable"
    assert "pending_files" not in result.metadata["staged_observation"]


def test_tag_diagnostics_do_not_validate_report_filters(active: QueryRoot) -> None:
    StorageMutationFacade(active.root, active.provider).replace_config(
        ConfigDocument("rules", b"rules: []\nreport_filters: PRIVATE\n", "parsed", None, "test.v1")
    )
    result = _collect(active)
    assert result.config_checks[0].status == "ok"
    assert result.metadata["transaction_total"] == 1


def test_detached_scope_excludes_aux_and_separates_unknown_dates(
    active: QueryRoot, monkeypatch
) -> None:
    from finjuice.pipeline.storage.sqlite.transaction_scopes import TransactionScope

    snapshot = read_checkup_snapshot(active.root, active.provider)
    assert snapshot is not None
    transactions = snapshot.status.transactions
    row = transactions.rows[0]
    native = {**row, "transaction_id": "native", "date": None}
    aux = {**row, "transaction_id": "aux", "date": "1999-01-01"}
    transactions = replace(
        transactions,
        rows=(*transactions.rows, native, aux),
        scopes=(
            *transactions.scopes,
            TransactionScope("native", None, True),
            TransactionScope("aux", "1999-01", False),
        ),
        partition_months=("2026-09", "2026-10"),
    )
    detached = replace(snapshot, status=replace(snapshot.status, transactions=transactions))
    monkeypatch.setattr(repository, "read_checkup_snapshot", lambda *a, **k: detached)
    result = _collect(active)
    assert result.metadata["transaction_total"] == 2
    assert result.metadata["unknown_date_rows"] == result.metadata["unknown_month_rows"] == 1
    assert result.metadata["excluded_typed_rows"] == 1
    detail = next(c.detail for c in result.data_checks if c.name == "repository_transactions")
    assert detail is not None and "Partition months: 2" in detail
    assert "2026-09-01 ~ 2026-09-01" in detail and "unknown date rows: 1" in detail
    assert result.metadata["date_min"] == "2026-09-01"
    assert result.metadata["partition_months"] == ["2026-09", "2026-10"]


def test_structural_read_failure_stays_static(active: QueryRoot, monkeypatch) -> None:
    def broken(*args, **kwargs):
        raise ValueError("PRIVATE source contents")

    monkeypatch.setattr(repository, "read_checkup_snapshot", broken)
    result = _collect(active)
    assert result.metadata["canonical_domains"] == "unavailable"
    assert result.data_checks[0].name == "repository_read"
    assert "PRIVATE" not in str(result)
