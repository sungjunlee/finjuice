"""Actual canonical JSON statement adapter: coverage, decisions, mapping and restore."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.statements.canonical import (
    STATEMENT_ACCOUNT_NAMESPACE,
    STATEMENT_SCHEMA_VERSION,
)
from finjuice.pipeline.storage.mutation_facade import MutationIdentity
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryReader
from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
from finjuice.pipeline.storage.sqlite.backup import create_backup, restore_backup
from finjuice.pipeline.storage.sqlite.backup_coverage import _load_facts
from tests.pipeline.test_account_decisions import Environment, _environment

NOW = "2026-09-14T00:00:00Z"
ORIGINAL = b"upstream statement original bytes\r\n"
ORIGINAL_HASH = "sha256:" + hashlib.sha256(ORIGINAL).hexdigest()
IDENTITY = "bank.synthetic.statement.v1"
ACCOUNT_KEY = "synthetic-checking-01"


def _invoke(env: Environment, args: list[str], *, human: bool = False) -> Any:
    return CliRunner().invoke(
        app,
        ["--data-dir", str(env.source.data_dir), "ssot", *args, *([] if human else ["--json"])],
        obj={"activation_evidence_provider": env.source.evidence_provider},
    )


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    body: dict[str, Any] = json.loads(result.output[result.output.index("{") :])
    return body


def _record(external_id: str, amount: str = "-1200.50", **overrides: Any) -> dict[str, Any]:
    record = {
        "external_transaction_id": external_id,
        "source_account_key": ACCOUNT_KEY,
        "amount": amount,
        "occurred_on": "2026-09-01",
        "occurred_at": "2026-09-01T12:30:00+09:00",
        "type": "expense",
        "description": "합성 가맹점",
    }
    record.update(overrides)
    return record


def _envelope(records: list[dict[str, Any]], **overrides: Any) -> dict[str, Any]:
    envelope = {
        "source_identity": IDENTITY,
        "schema_version": STATEMENT_SCHEMA_VERSION,
        "parser_version": "synthetic-adapter.v1",
        "original_hash": ORIGINAL_HASH,
        "as_of": "2026-09-02T00:00:00Z",
        "collected_at": "2026-09-02T00:05:00Z",
        "coverage": "full",
        "currency": "KRW",
        "idempotency_key": "producer-batch-1",
        "records": records,
    }
    envelope.update(overrides)
    return envelope


def _document(env: Environment, name: str, envelope: dict[str, Any]) -> str:
    path = env.root / name
    path.write_text(json.dumps(envelope, ensure_ascii=False))
    return str(path)


def _import_args(
    env: Environment, document: str, key: str, *, original: str | None = None
) -> list[str]:
    extra = ["--original", original] if original else []
    return [
        "import-json",
        document,
        "--imported-at",
        NOW,
        *extra,
        *env.options(key),
    ]


def _original(env: Environment) -> str:
    path = env.root / "original-statement.bin"
    path.write_bytes(ORIGINAL)
    return str(path)


def _bind(env: Environment, key: str = "bind-account") -> None:
    env.facade.confirm_account_binding(
        AccountBindingConfirmation(
            source_namespace=STATEMENT_ACCOUNT_NAMESPACE,
            external_key=ACCOUNT_KEY,
            account_id=env.account,
            evidence={"reason": "operator confirmed synthetic statement account"},
        ),
        identity=MutationIdentity(key, env.generation, env.revision()),
    )


def statement_catalog_outputs(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Return actual successful command payloads for the shared schema catalog test."""
    env = _environment(tmp_path)
    _bind(env)
    document = _document(env, "statement.json", _envelope([_record("txn-1", decision=None)]))
    imported = _payload(_invoke(env, _import_args(env, document, "import-1")))
    evidence = _payload(_invoke(env, ["statement-evidence"]))
    return {"ssot_import_json": imported, "ssot_statement_evidence": evidence}


@pytest.mark.parametrize("human", [False, True])
def test_pending_then_confirmed_binding_creates_one_economic_record(
    tmp_path: Path, human: bool
) -> None:
    # Arrange: a full collection arrives before any account binding exists.
    env = _environment(tmp_path)
    pending_doc = _document(
        env, "pending.json", _envelope([_record("txn-1", decision={"action": "create"})])
    )
    original = _original(env)

    # Act.
    arguments = _import_args(env, pending_doc, "import-1", original=original)
    first = _invoke(env, arguments, human=human)
    assert first.exit_code == 0, first.output
    pending = _payload(_invoke(env, arguments))

    # Assert: no guessed transaction, but durable evidence is preserved.
    assert pending["replayed"] and pending["counts"] == {
        "created": 0,
        "linked": 0,
        "reused": 0,
        "pending": 1,
    }
    assert pending["pending_external_ids"] == ["txn-1"]
    assert pending["original_artifact_id"] == ORIGINAL_HASH
    evidence = _payload(_invoke(env, ["statement-evidence"]))
    assert evidence["record_count"] == 1 and evidence["pending_external_ids"] == ["txn-1"]
    if human:
        assert "보류 1" in first.output

    # Act: the operator confirms the binding and re-sends the same collection.
    _bind(env)
    applied = _payload(_invoke(env, _import_args(env, pending_doc, "import-2")))

    # Assert: exactly one economic transaction, evidence from both occurrences kept.
    assert applied["counts"] == {"created": 1, "linked": 0, "reused": 0, "pending": 0}
    assert _payload(_invoke(env, ["statement-evidence"]))["pending_external_ids"] == []
    transaction_id = applied["created_transaction_ids"][0]
    with RepositoryReader(env.database) as reader:
        assert len(reader.rows("transactions")) == 1
        assert len(_statement_occurrences(reader)) == 2

    # Act: a third send under a brand new request key.
    repeated = _payload(_invoke(env, _import_args(env, pending_doc, "import-3")))

    # Assert: no second economic transaction, but the new occurrence is retained.
    assert repeated["counts"] == {"created": 0, "linked": 0, "reused": 1, "pending": 0}
    assert repeated["reused_external_ids"] == ["txn-1"]
    with RepositoryReader(env.database) as reader:
        assert [row["entity_id"] for row in reader.rows("transactions")] == [transaction_id]
        links = reader.rows("transaction_source_links")
    assert sorted(row["link_kind"] for row in links) == ["duplicate_evidence", "origin"]


def test_second_source_links_the_same_transaction_without_duplicating_it(tmp_path: Path) -> None:
    # Arrange: one economic transaction from the first source.
    env = _environment(tmp_path)
    _bind(env)
    first_doc = _document(
        env, "first.json", _envelope([_record("txn-1", decision={"action": "create"})])
    )
    created = _payload(_invoke(env, _import_args(env, first_doc, "import-1")))
    transaction_id = created["created_transaction_ids"][0]

    # Act: a second source explicitly links the same canonical transaction UUID.
    second_doc = _document(
        env,
        "second.json",
        _envelope(
            [_record("card-9", decision={"action": "link", "transaction_id": transaction_id})],
            source_identity="card.synthetic.statement.v1",
            idempotency_key="producer-batch-2",
        ),
    )
    linked = _payload(_invoke(env, _import_args(env, second_doc, "import-2")))

    # Assert: new evidence, no second economic transaction.
    assert linked["counts"] == {"created": 0, "linked": 1, "reused": 0, "pending": 0}
    with RepositoryReader(env.database) as reader:
        assert len(reader.rows("transactions")) == 1
        evidence = reader.statement_evidence(source_identity="card.synthetic.statement.v1")
    assert evidence["records"][0]["transaction_id"] == transaction_id


def test_wrong_link_target_and_changed_content_are_refused(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    _bind(env)
    document = _document(
        env, "first.json", _envelope([_record("txn-1", decision={"action": "create"})])
    )
    created = _payload(_invoke(env, _import_args(env, document, "import-1")))
    transaction_id = created["created_transaction_ids"][0]
    revision = env.revision()
    wrong = _document(
        env,
        "wrong.json",
        _envelope(
            [
                _record(
                    "card-9",
                    amount="-999.00",
                    decision={"action": "link", "transaction_id": transaction_id},
                )
            ],
            source_identity="card.synthetic.statement.v1",
        ),
    )
    assert _invoke(env, _import_args(env, wrong, "import-wrong")).exit_code != 0
    changed = _document(
        env, "changed.json", _envelope([_record("txn-1", amount="-1.00", decision=None)])
    )
    assert _invoke(env, _import_args(env, changed, "import-changed")).exit_code != 0
    assert env.revision() == revision


def test_malformed_row_leaves_confirmed_state_untouched_and_retry_is_safe(tmp_path: Path) -> None:
    # Arrange: a batch whose last row is malformed.
    env = _environment(tmp_path)
    _bind(env)
    broken = _document(
        env,
        "broken.json",
        _envelope(
            [
                _record("txn-1", decision={"action": "create"}),
                _record("txn-2", amount=-500.25, decision={"action": "create"}),
            ]
        ),
    )
    revision = env.revision()

    # Act.
    failure = _invoke(env, _import_args(env, broken, "import-broken"))

    # Assert: nothing was written and the same key can be reused after a fix.
    assert failure.exit_code != 0 and env.revision() == revision
    with RepositoryReader(env.database) as reader:
        assert reader.rows("transactions") == []
        assert reader.statement_evidence()["record_count"] == 0
    fixed = _document(
        env,
        "fixed.json",
        _envelope(
            [
                _record("txn-1", decision={"action": "create"}),
                _record("txn-2", amount="-500.25", decision={"action": "create"}),
            ]
        ),
    )
    repaired = _payload(_invoke(env, _import_args(env, fixed, "import-broken")))
    assert repaired["counts"]["created"] == 2


def test_credential_field_and_unsupported_schema_are_rejected(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    secret = _document(
        env, "secret.json", _envelope([_record("txn-1", api_key="must-never-be-stored")])
    )
    result = _invoke(env, _import_args(env, secret, "import-secret"))
    assert result.exit_code != 0
    assert "must-never-be-stored" not in result.output
    stale = _document(
        env, "stale.json", _envelope([_record("txn-1")], schema_version="finjuice.statement.v0")
    )
    assert _invoke(env, _import_args(env, stale, "import-stale")).exit_code != 0


@pytest.mark.parametrize("coverage", ["full", "partial", "historical"])
def test_every_coverage_shares_one_contract_and_never_deletes(
    tmp_path: Path, coverage: str
) -> None:
    env = _environment(tmp_path)
    _bind(env)
    first = _document(
        env, "first.json", _envelope([_record("txn-1", decision={"action": "create"})])
    )
    _payload(_invoke(env, _import_args(env, first, "import-1")))
    narrowed = _document(
        env,
        "narrow.json",
        _envelope(
            [_record("txn-2", decision={"action": "create"})],
            coverage=coverage,
            idempotency_key="producer-batch-2",
        ),
    )
    applied = _payload(_invoke(env, _import_args(env, narrowed, "import-2")))
    assert applied["coverage"] == coverage and applied["counts"]["created"] == 1
    with RepositoryReader(env.database) as reader:
        assert len(reader.rows("transactions")) == 2
        assert len(reader.statement_evidence()["records"]) == 2


def test_exact_large_decimal_survives_manual_correction_capture_and_restore(
    tmp_path: Path,
) -> None:
    # Arrange: an exact amount far beyond float precision.
    env = _environment(tmp_path)
    _bind(env)
    amount = "123456789012345678901234567890.0001"
    document = _document(
        env,
        "exact.json",
        _envelope([_record("txn-1", amount=amount, decision={"action": "create"})]),
    )
    created = _payload(
        _invoke(env, _import_args(env, document, "import-1", original=_original(env)))
    )
    transaction_id = created["created_transaction_ids"][0]

    # Act: the user applies a manual override, then the same collection is re-sent.
    env.facade.edit_manual_transaction(
        _manual_edit(transaction_id),
        identity=MutationIdentity("manual-1", env.generation, env.revision()),
    )
    _payload(_invoke(env, _import_args(env, document, "import-2")))

    # Assert: manual state and exact decimal are preserved; restore keeps the mapping.
    with RepositoryReader(env.database) as reader:
        row = next(
            item for item in reader.rows("transactions") if item["entity_id"] == transaction_id
        )
        assert json.loads(row["tags_manual_json"]) == ["검토완료"]
        value = next(
            item
            for item in reader.rows("exact_values")
            if item["value_id"] == row["amount_value_id"]
        )
        before = reader.statement_evidence()
    assert value["lexical"] == amount
    backup = tmp_path / "captured"
    create_backup(env.database, backup)
    restored = GenerationPaths(tmp_path / "restored")
    restore_backup(backup, restored.root)
    with RepositoryReader(restored.database) as reader:
        assert reader.statement_evidence() == before
    assert _statement_artifacts(restored.database) == _statement_artifacts(env.database)


def _statement_occurrences(reader: Any) -> list[dict[str, Any]]:
    from finjuice.pipeline.statements.canonical import STATEMENT_OCCURRENCE_KIND

    return [
        row
        for row in reader.rows("source_occurrences")
        if row["occurrence_kind"] == STATEMENT_OCCURRENCE_KIND
    ]


def _manual_edit(transaction_id: str) -> Any:
    from finjuice.pipeline.storage.sqlite.mutations import ManualTransactionEdit

    return ManualTransactionEdit(identifier=transaction_id, add_tags=("검토완료",))


def _statement_artifacts(database: Path) -> set[str]:
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        return {
            item.identity_digest
            for item in _load_facts(connection)
            if item.kind in {"entry", "changeset"}
        }


def test_existing_mapping_rejects_a_different_explicit_target(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    _bind(env)
    document = _document(
        env,
        "create.json",
        _envelope(
            [
                _record("txn-1", decision={"action": "create"}),
                _record("txn-2", decision={"action": "create"}),
            ]
        ),
    )
    created = _payload(_invoke(env, _import_args(env, document, "create")))
    revision = env.revision()
    changed = _document(
        env,
        "remap.json",
        _envelope(
            [
                _record(
                    "txn-1",
                    decision={
                        "action": "link",
                        "transaction_id": created["created_transaction_ids"][1],
                    },
                )
            ]
        ),
    )
    result = _invoke(env, _import_args(env, changed, "remap"))
    assert result.exit_code != 0
    assert env.revision() == revision


@pytest.mark.parametrize(
    "occurred_at",
    [
        None,
        "2026-09-01T13:04:05+09:00",
        "2026-09-01T13:04+09:00",
        "2026-09-01T13:04:05.123456+09:00",
        "2026-09-01T04:04:05Z",
    ],
)
def test_overlap_identity_preserves_statement_event_time_without_rewriting_dates(
    tmp_path: Path,
    occurred_at: str | None,
) -> None:
    from finjuice.pipeline.statements.canonical import _preview_identity, parse_document, plan_rows
    from finjuice.pipeline.storage.sqlite.exact_import.lookup import (
        load_transaction_identity_snapshot,
    )

    env = _environment(tmp_path)
    _bind(env)
    payload = _envelope([_record("timed", occurred_at=occurred_at, decision={"action": "create"})])
    path = _document(env, "timed.json", payload)
    imported = _payload(_invoke(env, _import_args(env, path, "time-import")))
    transaction_id = imported["created_transaction_ids"][0]
    row = plan_rows(parse_document(json.dumps(payload).encode()))[0]
    with sqlite3.connect(env.database) as connection:
        observed = connection.execute(
            "SELECT o.effective_at, o.observed_at FROM observations o "
            "JOIN transactions t ON t.observation_id = o.entity_id WHERE t.entity_id = ?",
            (transaction_id,),
        ).fetchone()
        identity = next(
            item
            for item in load_transaction_identity_snapshot(connection)
            if item["transaction_id"] == transaction_id
        )
    assert observed == ("2026-09-01", occurred_at)
    assert identity == _preview_identity(row, transaction_id)
    assert identity["effective_at"] == (occurred_at or "2026-09-01")
    assert identity["time_raw"] == ("" if occurred_at is None else occurred_at[11:])
