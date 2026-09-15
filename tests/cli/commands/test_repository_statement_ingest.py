"""JSON statement files use the common ingest path on an active repository."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.cli.output import ExitCode
from finjuice.pipeline.statements.canonical import STATEMENT_ACCOUNT_NAMESPACE
from finjuice.pipeline.storage.mutation_facade import MutationIdentity
from finjuice.pipeline.storage.sqlite import AccountRecord, RepositoryReader, new_entity_id
from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationService
from finjuice.pipeline.storage.sqlite.schema import inspect_repository
from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.pipeline.test_canonical_statement_json import ACCOUNT_KEY, _envelope, _record
from tests.pipeline.test_sqlite_mutations import _request

active_root = _active_root_fixture


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == ExitCode.SUCCESS, result.output
    body: dict[str, Any] = json.loads(result.output[result.output.index("{") :])
    return body


def _stage(active: _ActiveRoot, name: str, envelope: dict[str, Any]) -> Path:
    path = active.root / "imports" / name
    path.write_text(json.dumps(envelope, ensure_ascii=False), encoding="utf-8")
    return path


def _revision(active: _ActiveRoot) -> int:
    revision = inspect_repository(active.database).dataset_revision
    assert revision is not None
    return revision


def _bind(active: _ActiveRoot) -> str:
    account_id = new_entity_id()

    def seed(context: Any) -> MutationOutcome:
        context.add_account(AccountRecord(account_id, account_kind="bank.v1"))
        return MutationOutcome(result={"account": account_id})

    MutationService(active.paths, active.evidence).execute(
        _request(active.generation, "statement-account", 0), seed
    )
    active.facade.confirm_account_binding(
        AccountBindingConfirmation(
            source_namespace=STATEMENT_ACCOUNT_NAMESPACE,
            external_key=ACCOUNT_KEY,
            account_id=account_id,
            evidence={"reason": "operator confirmed synthetic statement account"},
        ),
        identity=MutationIdentity("bind-account", active.generation, _revision(active)),
    )
    return account_id


def _transactions(active: _ActiveRoot) -> list[dict[str, Any]]:
    with RepositoryReader(active.database) as reader:
        return list(reader.rows("transactions"))


@pytest.mark.parametrize("coverage", ["full", "partial", "historical"])
def test_ingest_json_statement_full_partial_historical_and_retry(
    active_root: _ActiveRoot, coverage: str
) -> None:
    _bind(active_root)
    staged = _stage(
        active_root,
        f"{coverage}.json",
        _envelope([_record("txn-1", decision={"action": "create"})], coverage=coverage),
    )
    original = staged.read_bytes()

    first = _payload(_invoke(active_root, "ingest", "--json"))
    receipt = first["receipts"][0]
    assert receipt["filename"] == staged.name
    assert receipt["result"]["counts"]["created"] == 1
    assert receipt["result"]["counts"]["transactions"]["inserted"] == 1
    assert first["summary"]["new_transactions"] == 1
    assert receipt["result"]["noop"] is False
    created = _transactions(active_root)
    assert len(created) == 1

    retry = _payload(_invoke(active_root, "ingest", "--json"))
    assert retry["receipts"][0]["result"]["counts"]["created"] == 0
    assert retry["receipts"][0]["result"]["counts"]["reused"] == 1
    assert retry["summary"]["new_transactions"] == 0
    assert retry["summary"]["updated"] == 1
    assert staged.read_bytes() == original
    assert len(_transactions(active_root)) == 1
    dumped = json.dumps(retry)
    assert "-1200.50" not in dumped
    assert ACCOUNT_KEY not in dumped
    assert str(staged) not in dumped


def test_second_source_preserves_evidence_without_duplicating(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "first.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    created = _payload(_invoke(active_root, "ingest", "--json"))
    assert created["summary"]["new_transactions"] == 1
    transaction_id = _transactions(active_root)[0]["entity_id"]

    (active_root.root / "imports" / "first.json").unlink()
    _stage(
        active_root,
        "card.json",
        _envelope(
            [_record("card-9", decision={"action": "link", "transaction_id": transaction_id})],
            source_identity="card.synthetic.statement.v1",
            idempotency_key="producer-batch-2",
        ),
    )
    linked = _payload(_invoke(active_root, "ingest", "--json"))
    assert linked["receipts"][0]["result"]["counts"]["linked"] == 1
    assert linked["receipts"][0]["result"]["counts"]["created"] == 0
    assert linked["summary"]["new_transactions"] == 0
    assert len(_transactions(active_root)) == 1
    with RepositoryReader(active_root.database) as reader:
        evidence = reader.statement_evidence(source_identity="card.synthetic.statement.v1")
    assert evidence["records"][0]["transaction_id"] == transaction_id


def test_collection_failure_is_retryable_and_preserves_manual_correction(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "ok.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    first = _payload(_invoke(active_root, "ingest", "--json"))
    assert first["summary"]["new_transactions"] == 1
    transaction_id = _transactions(active_root)[0]["entity_id"]
    active_root.facade.edit_manual_transaction(
        _manual_edit(transaction_id),
        identity=MutationIdentity("manual-1", active_root.generation, _revision(active_root)),
    )
    (active_root.root / "imports" / "ok.json").unlink()
    broken = _stage(
        active_root,
        "broken.json",
        _envelope(
            [
                _record("txn-1", decision={"action": "create"}),
                _record("txn-2", amount=-500.25, decision={"action": "create"}),
            ]
        ),
    )
    revision = _revision(active_root)
    tags = _manual_tags(active_root, transaction_id)

    failed = _invoke(active_root, "ingest", "--json")
    assert failed.exit_code != ExitCode.SUCCESS
    assert "must-never-be-stored" not in failed.output
    assert _revision(active_root) == revision
    assert _manual_tags(active_root, transaction_id) == tags

    broken.write_text(
        json.dumps(
            _envelope(
                [
                    _record("txn-1", decision={"action": "create"}),
                    _record("txn-2", decision={"action": "create"}),
                ]
            ),
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    repaired = _payload(_invoke(active_root, "ingest", "--json"))
    assert repaired["summary"]["new_transactions"] == 1
    assert repaired["receipts"][0]["result"]["counts"]["reused"] == 1
    assert _manual_tags(active_root, transaction_id) == ["검토완료"]
    assert len(_transactions(active_root)) == 2


def test_credentials_and_unrelated_json_stay_out_of_the_ingest_path(
    active_root: _ActiveRoot,
) -> None:
    _bind(active_root)
    secret = _stage(
        active_root,
        "secret.json",
        _envelope([_record("txn-1", api_key="must-never-be-stored")]),
    )
    noise = active_root.root / "imports" / "notes.json"
    noise.write_text('{"hello": "world"}', encoding="utf-8")
    revision = _revision(active_root)

    failed = _invoke(active_root, "ingest", "--json")
    assert failed.exit_code != ExitCode.SUCCESS
    assert "must-never-be-stored" not in failed.output
    assert "api_key" not in failed.output
    assert _revision(active_root) == revision
    assert _transactions(active_root) == []
    assert secret.exists()

    secret.unlink()
    skipped = _payload(_invoke(active_root, "ingest", "--json"))
    assert skipped["receipts"] == []
    assert skipped["summary"]["files_processed"] == 0
    assert _transactions(active_root) == []
    assert noise.exists()


def test_ingest_processes_xlsx_and_json_together(active_root: _ActiveRoot) -> None:
    from tests.cli.commands.test_repository_import_commands import _write_xlsx

    _bind(active_root)
    _write_xlsx(active_root.root / "imports" / "book.xlsx")
    _stage(
        active_root,
        "statement.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )

    result = _payload(_invoke(active_root, "ingest", "--json"))
    names = [item["filename"] for item in result["receipts"]]
    assert names == ["book.xlsx", "statement.json"]
    assert result["summary"]["files_processed"] == 2
    assert result["summary"]["new_transactions"] >= 2
    assert len(_transactions(active_root)) >= 2


def test_dry_run_validates_without_writing(active_root: _ActiveRoot) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "preview.json",
        _envelope([_record("txn-1", decision={"action": "create"})]),
    )
    revision = _revision(active_root)

    preview = _payload(_invoke(active_root, "ingest", "--dry-run", "--json"))
    assert preview["dry_run"] is True
    assert preview["receipts"][0]["state_changed"] is False
    assert preview["receipts"][0]["result"]["counts"]["pending"] == 1
    assert preview["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 0
    assert preview["summary"]["new_transactions"] == 0
    assert _revision(active_root) == revision
    assert _transactions(active_root) == []


def _manual_edit(transaction_id: str) -> Any:
    from finjuice.pipeline.storage.sqlite.mutations import ManualTransactionEdit

    return ManualTransactionEdit(identifier=transaction_id, add_tags=("검토완료",))


def _manual_tags(active: _ActiveRoot, transaction_id: str) -> list[str]:
    with RepositoryReader(active.database) as reader:
        row = next(
            item for item in reader.rows("transactions") if item["entity_id"] == transaction_id
        )
    return json.loads(row["tags_manual_json"])
