"""Actual account binding, differing XLSX imports, correction and restore regressions."""

from __future__ import annotations

import io
import json
import zipfile
from dataclasses import replace
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    GenerationPaths,
    PartyRecord,
    RepositoryBuilder,
    RepositoryReader,
    new_entity_id,
    upgrade_repository,
)
from finjuice.pipeline.storage.sqlite.account_bindings import (
    ASSET_ACCOUNT_NAMESPACE,
    TRANSACTION_ACCOUNT_NAMESPACE,
    AccountBindingConfirmation,
)
from finjuice.pipeline.storage.sqlite.backup import create_backup, restore_backup
from finjuice.pipeline.storage.sqlite.errors import MutationConflictError, MutationValidationError
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreSession,
    restore_workspace,
)
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationService
from tests.pipeline.test_sqlite_exact_import import _asset_book, _import, _query, _tx_book, _tx_row
from tests.pipeline.test_sqlite_exact_import import repo as repo_fixture
from tests.pipeline.test_sqlite_mutations import _ownership_handler, _request

repo = repo_fixture


def _accounts(repo) -> tuple[str, str]:
    ids = (new_entity_id(), new_entity_id())

    def seed(context):
        for identifier in ids:
            context.add_account(AccountRecord(identifier, account_kind="bank.v1"))
        return MutationOutcome(result={"accounts": list(ids)})

    MutationService(repo.paths, repo.evidence).execute(
        _request(repo.generation, "accounts", repo.revision()), seed
    )
    return ids


def _ownership(repo, account: str) -> str:
    party = new_entity_id()
    apply = _ownership_handler(
        account_id=account, party_id=party, assertion_id=new_entity_id(), value_id=new_entity_id()
    )

    def seed(context):
        context.add_party(PartyRecord(party))
        return apply(context)

    MutationService(repo.paths, repo.evidence).execute(
        _request(repo.generation, "ownership", repo.revision()), seed
    )
    return party


def _decision(account: str, *, namespace: str = ASSET_ACCOUNT_NAMESPACE, key: str = "acct-1"):
    return AccountBindingConfirmation(
        namespace,
        key,
        account,
        {"kind": "operator_confirmation", "reason": "synthetic account verified"},
    )


def _changed_assets() -> bytes:
    original = _asset_book()
    buffer = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(original)) as source, zipfile.ZipFile(buffer, "w") as target:
        for name in source.namelist():
            data = source.read(name)
            if name.endswith("sheet1.xml"):
                data = data.replace(b"2026-06-15", b"2026-07-15").replace(b"150.25", b"151.25")
                data = data.replace("계좌A".encode(), "새 표시명".encode())
            target.writestr(name, data)
    assert buffer.getvalue() != original
    return buffer.getvalue()


def test_confirmed_binding_preserves_stable_account_across_different_xlsx_and_restore(
    repo, tmp_path: Path
) -> None:
    account, other = _accounts(repo)
    party = _ownership(repo, account)
    decision = _decision(account)
    receipt = repo.facade.confirm_account_binding(
        decision, identity=repo.identity("confirm", repo.revision())
    )
    _import(repo, _asset_book(), key="first", revision=repo.revision())
    _import(repo, _changed_assets(), key="second", revision=repo.revision())
    assert _query(repo.database, "SELECT DISTINCT account_id FROM asset_snapshots") == [(account,)]
    assert (
        repo.facade.read_account_ownership(account, as_of="2026-07-15")["shares"][0]["party_id"]
        == party
    )
    snapshot = repo.facade.read_account_bindings()
    assert snapshot["candidates"][0]["status"] == "confirmed"
    backup = tmp_path / "backup"
    create_backup(repo.database, backup)
    restored = restore_workspace(backup, tmp_path / "workspace")
    with InactiveRestoreSession(restored) as session:
        assert (
            session.read_snapshot(lambda reader: reader.rows("account_source_bindings"))[0][
                "account_id"
            ]
            == account
        )
        assert (
            session.read_snapshot(
                lambda reader: reader.account_ownership(account, as_of="2026-07-15")
            )["shares"][0]["party_id"]
            == party
        )
        correction = replace(
            decision, account_id=other, supersedes_binding_id=receipt.result["binding_id"]
        )
        request = _request(
            repo.generation, "correct-restored", repo.revision(), scope="account.binding.correct"
        )
        session.execute(
            request,
            lambda context: MutationOutcome(result=context.confirm_account_binding(correction)),
        )
        session.backup(tmp_path / "second-backup")
    second = restore_workspace(tmp_path / "second-backup", tmp_path / "second-workspace")
    with InactiveRestoreSession(second) as session:
        history = session.read_snapshot(lambda reader: reader.rows("account_source_bindings"))
        assert len(history) == 2 and {row["account_id"] for row in history} == {account, other}
    assert _query(repo.database, "SELECT account_id FROM account_source_bindings") == [(account,)]


def test_binding_replay_conflict_ambiguity_and_correction(repo) -> None:
    account, other = _accounts(repo)
    decision = _decision(account)
    identity = repo.identity("confirm", repo.revision())
    first = repo.facade.confirm_account_binding(decision, identity=identity)
    replay = repo.facade.confirm_account_binding(decision, identity=identity)
    assert replay.replayed and replay.changeset_id == first.changeset_id
    with pytest.raises(MutationConflictError):
        repo.facade.confirm_account_binding(replace(decision, account_id=other), identity=identity)
    with pytest.raises(MutationConflictError):
        repo.facade.confirm_account_binding(
            decision, identity=repo.identity("stale", identity.expected_revision)
        )
    conflicting = repo.facade.confirm_account_binding(
        replace(decision, account_id=other),
        identity=repo.identity("explicit-second", repo.revision()),
    )
    assert repo.facade.read_account_bindings()["candidates"][0]["status"] == "ambiguous"
    _import(repo, _asset_book(), key="ambiguous-import", revision=repo.revision())
    unresolved = _query(repo.database, "SELECT account_id FROM asset_snapshots")[0][0]
    assert unresolved not in {account, other}
    correction = replace(decision, supersedes_binding_id=conflicting.result["binding_id"])
    repo.facade.confirm_account_binding(
        correction, identity=repo.identity("correct", repo.revision())
    )
    assert repo.facade.read_account_bindings()["candidates"][0]["account_id"] == account
    _import(repo, _changed_assets(), key="after-correct", revision=repo.revision())
    assert set(
        row[0] for row in _query(repo.database, "SELECT account_id FROM asset_snapshots")
    ) == {unresolved, account}
    with pytest.raises(MutationConflictError):
        repo.facade.confirm_account_binding(
            correction, identity=repo.identity("already-corrected", repo.revision())
        )
    with pytest.raises(MutationValidationError):
        repo.facade.confirm_account_binding(
            replace(correction, external_key="different"),
            identity=repo.identity("wrong-key", repo.revision()),
        )


def test_transaction_text_requires_explicit_binding_and_does_not_merge_names(repo) -> None:
    account, _ = _accounts(repo)
    repo.facade.confirm_account_binding(
        _decision(account, namespace=TRANSACTION_ACCOUNT_NAMESPACE, key="카드A"),
        identity=repo.identity("tx-bind", repo.revision()),
    )
    _import(repo, _tx_book(_tx_row(2, amount="10")), key="tx1", revision=repo.revision())
    _import(repo, _tx_book(_tx_row(2, amount="20")), key="tx2", revision=repo.revision())
    assert _query(repo.database, "SELECT DISTINCT account_id FROM transactions") == [(account,)]


def test_v5_backup_restore_and_explicit_clone_upgrade_preserve_policy_schema(
    tmp_path: Path,
) -> None:
    source = GenerationPaths(tmp_path / "v5")
    generation, account = new_entity_id(), new_entity_id()
    with RepositoryBuilder(source, generation, expected_schema_version=5) as builder:
        builder.add_account(AccountRecord(account, account_kind="bank.v1"))
        builder.finalize()
    create_backup(source.database, tmp_path / "v5-backup")
    raw = restore_backup(tmp_path / "v5-backup", tmp_path / "v5-restored")
    with RepositoryReader(raw.database, expected_schema_version=5) as reader:
        assert "account_source_bindings" not in reader.table_names
    current = GenerationPaths(tmp_path / "v6")
    upgrade_repository(raw.database, current)
    with RepositoryReader(current.database) as reader:
        assert reader.info.schema_version == 6
        assert reader.rows("account_source_bindings") == []
        assert reader.rows("accounts")[0]["entity_id"] == account
    with RepositoryReader(source.database, expected_schema_version=5) as reader:
        assert reader.info.schema_version == 5


@pytest.mark.parametrize("json_output", [False, True])
def test_account_cli_confirmation_correction_and_candidates(
    repo, tmp_path: Path, monkeypatch, json_output: bool
) -> None:
    account, other = _accounts(repo)
    monkeypatch.setattr(
        "finjuice.pipeline.cli.commands.ssot_accounts._facade", lambda ctx: repo.facade
    )
    request = tmp_path / "binding.json"
    request.write_text(
        json.dumps(
            {
                "source_namespace": ASSET_ACCOUNT_NAMESPACE,
                "external_key": "acct-1",
                "account_id": account,
                "evidence": {"reason": "explicit synthetic confirmation"},
            }
        )
    )
    runner = CliRunner()
    options = [
        "--idempotency-key",
        "cli-bind",
        "--expected-generation",
        repo.generation,
        "--expected-revision",
        str(repo.revision()),
    ]
    args = ["--data-dir", str(repo.data_dir), "ssot", "account", "confirm", str(request), *options]
    if json_output:
        args.append("--json")
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    binding = _query(repo.database, "SELECT binding_id FROM account_source_bindings")[0][0]
    if json_output:
        assert json.loads(result.output)["binding_id"] == binding
    result = runner.invoke(
        app, ["--data-dir", str(repo.data_dir), "ssot", "account", "list", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["candidates"][0]["account_id"] == account
    body = json.loads(request.read_text())
    body["account_id"] = other
    request.write_text(json.dumps(body))
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(repo.data_dir),
            "ssot",
            "account",
            "correct",
            binding,
            str(request),
            "--idempotency-key",
            "cli-correct",
            "--expected-generation",
            repo.generation,
            "--expected-revision",
            str(repo.revision()),
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["account_id"] == other
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(repo.data_dir),
            "ssot",
            "account",
            "ownership",
            account,
            "--as-of",
            "2026-07-15",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "unknown"
