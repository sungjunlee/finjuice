"""Synthetic canonical N:M settlement, identity fences and restore continuity."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite import (
    GenerationPaths,
    RepositoryBuilder,
    RepositoryReader,
    new_entity_id,
    upgrade_repository,
)
from finjuice.pipeline.storage.sqlite.backup import create_backup, restore_backup
from finjuice.pipeline.storage.sqlite.backup_coverage import _load_facts
from finjuice.pipeline.storage.sqlite.schema import SQLITE_SCHEMA_VERSION
from tests.pipeline.test_account_decisions import Environment, _environment
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row

NOW = "2026-09-14T00:00:00Z"


def _invoke(env: Environment, args: list[str], *, human: bool = False) -> Any:
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(env.source.data_dir),
            "ssot",
            "reconcile",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": env.source.evidence_provider},
    )


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    body: dict[str, Any] = json.loads(result.output[result.output.index("{") :])
    return body


def _seed(tmp_path: Path, amounts: list[str]) -> tuple[Environment, list[str]]:
    env = _environment(tmp_path)
    with RepositoryReader(env.database) as reader:
        before = {row["entity_id"] for row in reader.rows("transactions")}
    env.import_bytes(
        _tx_book(
            *[
                _tx_row(index + 2, amount=value, income=Decimal(value) > 0)
                for index, value in enumerate(amounts)
            ]
        ),
        "payments",
    )
    with RepositoryReader(env.database) as reader:
        rows = reader.transaction_snapshot().rows
        payments = [row["transaction_id"] for row in rows if row["transaction_id"] not in before]
    assert len(payments) == len(amounts)
    return env, payments


def _item(key: str, amount: str, **extra: Any) -> dict[str, Any]:
    return {
        "external_key": key,
        "evidence_kind": "order",
        "occurred_on": "2024-03-15",
        "amount": amount,
        "currency": "KRW",
        "settlement_unit": True,
        "detail": {"reference": key},
        **extra,
    }


def _submit(
    env: Environment, items: list[dict[str, Any]], *, key: str = "evidence", human: bool = False
) -> tuple[dict[str, Any], list[str]]:
    original = env.root / "original-order.txt"
    original.write_bytes(b"synthetic original order\r\n")
    metadata = env.file(
        key + ".json",
        {"source_namespace": "synthetic.orders.v1", "received_at": NOW, "items": items},
    )
    args = ["submit", str(original), metadata, *env.options(key)]
    return _payload(_invoke(env, args, human=human)), args


def _candidates(env: Environment) -> dict[str, Any]:
    return _payload(_invoke(env, ["candidates", "--window-days", "90"]))


def _confirm(
    env: Environment, candidate: dict[str, Any], *, key: str = "confirm", human: bool = False
) -> tuple[dict[str, Any], list[str]]:
    request = env.file(
        key + ".json",
        {
            "evidence_ids": candidate["evidence_ids"],
            "payment_ids": candidate["payment_ids"],
            "expected_residual": candidate["residual"],
            "currency": candidate["currency"],
            "reason": "operator checked originals",
            "confirmed_at": NOW,
        },
    )
    args = ["confirm", request, *env.options(key)]
    return _payload(_invoke(env, args, human=human)), args


def reconcile_catalog_outputs(tmp_path: Path) -> dict[str, dict[str, Any]]:
    env, payments = _seed(tmp_path, ["-600", "-750"])
    submitted, _ = _submit(env, [_item("installment", "1350")])
    view = _candidates(env)
    candidate = next(row for row in view["candidates"] if set(row["payment_ids"]) == set(payments))
    confirmed, _ = _confirm(env, candidate)
    path = env.file(
        "withdraw.json",
        {
            "allocation_id": confirmed["allocation_id"],
            "reason": "review again",
            "withdrawn_at": NOW,
        },
    )
    withdrawn = _payload(_invoke(env, ["withdraw", path, *env.options("withdraw")]))
    return {"submit": submitted, "candidates": view, "confirm": confirmed, "withdraw": withdrawn}


@pytest.mark.parametrize("human", [False, True])
def test_actual_installment_confirm_withdraw_retry_and_capture_restore(
    tmp_path: Path, human: bool
) -> None:
    env, payments = _seed(tmp_path, ["-600", "-750"])
    with RepositoryReader(env.database) as reader:
        before = reader.rows("transactions")
    submitted, args = _submit(
        env,
        [
            _item("purchase", "1350", evidence_kind="purchase", settlement_unit=False),
            _item("installment", "1350", parent_external_key="purchase"),
            _item(
                "line",
                "1350",
                evidence_kind="line_item",
                parent_external_key="installment",
                settlement_unit=False,
            ),
            _item(
                "payment-proof",
                "600",
                evidence_kind="payment_evidence",
                settlement_unit=False,
                transaction_id=next(
                    identifier
                    for identifier in payments
                    if _payment_amount(env, identifier) == "-600"
                ),
            ),
        ],
        human=human,
    )
    retry = _payload(_invoke(env, args))
    assert retry["replayed"] and retry["changeset_id"] == submitted["changeset_id"]
    view = _candidates(env)
    assert len(view["evidence"]) == 4
    candidate = next(row for row in view["candidates"] if set(row["payment_ids"]) == set(payments))
    assert candidate["status"] == "matched" and Decimal(candidate["residual"]) == 0
    confirmed, confirmation_args = _confirm(env, candidate, human=human)
    assert _payload(_invoke(env, confirmation_args))["changeset_id"] == confirmed["changeset_id"]
    revision = env.revision()
    duplicate = _invoke(env, [*confirmation_args[:2], *env.options("duplicate")])
    assert duplicate.exit_code != 0 and env.revision() == revision
    after = _candidates(env)
    assert after["ledger_cash_totals"] == view["ledger_cash_totals"]
    assert not any(set(row["payment_ids"]) & set(payments) for row in after["candidates"])
    path = env.file(
        "withdraw.json",
        {
            "allocation_id": confirmed["allocation_id"],
            "reason": "new installment review",
            "withdrawn_at": NOW,
        },
    )
    withdrawal_args = ["withdraw", path, *env.options("withdraw")]
    withdrawn = _payload(_invoke(env, withdrawal_args, human=human))
    assert _payload(_invoke(env, withdrawal_args))["changeset_id"] == withdrawn["changeset_id"]
    final = _candidates(env)
    assert final["allocations"][0]["decision"] == "withdrawn"
    assert any(set(row["payment_ids"]) == set(payments) for row in final["candidates"])
    _confirm(env, candidate, key="reconfirm")
    with RepositoryReader(env.database) as reader:
        assert reader.rows("transactions") == before
        assert len(reader.rows("reconcile_allocations")) == 2
    backup = tmp_path / "captured"
    create_backup(env.database, backup)
    restored = GenerationPaths(tmp_path / "restored")
    restore_backup(backup, restored.root)
    with RepositoryReader(restored.database) as reader:
        actual = reader.reconcile_evidence(window_days=90)
        assert reader.rows("transactions") == before
    assert actual == _candidates_without_meta(env)
    assert {item.identity_digest for item in _facts(env.database) if item.kind == "reconcile"} == {
        item.identity_digest for item in _facts(restored.database) if item.kind == "reconcile"
    }
    assert any(item.kind == "reconcile" for item in _facts(restored.database))


def _candidates_without_meta(env: Environment) -> dict[str, Any]:
    result = _candidates(env)
    result.pop("_meta", None)
    return result


def _payment_amount(env: Environment, identifier: str) -> str:
    with RepositoryReader(env.database) as reader:
        return next(
            str(Decimal(row["amount"]))
            for row in reader.transaction_snapshot().rows
            if row["transaction_id"] == identifier
        )


@pytest.mark.parametrize(
    "evidence,payments,status,residual",
    [
        (["901", "902"], ["-1803"], "matched", "0"),
        (["-77"], ["77"], "matched", "0"),
        (["999"], ["-700"], "partial", "299"),
        (["77"], ["77"], "unmatched", "77"),
        (
            ["123456789012345678901234567890123456789012345678901234567890.0001"],
            ["-123456789012345678901234567890123456789012345678901234567890.0001"],
            "matched",
            "0",
        ),
    ],
)
def test_many_orders_refund_partial_and_long_exact_amounts(
    tmp_path: Path, evidence: list[str], payments: list[str], status: str, residual: str
) -> None:
    env, _ = _seed(tmp_path, payments)
    submitted, _ = _submit(
        env, [_item(f"order-{index}", value) for index, value in enumerate(evidence)]
    )
    with localcontext() as context:
        context.prec = 3
        result = _candidates(env)
    matching = [
        row
        for row in result["candidates"]
        if set(row["evidence_ids"]) & set(submitted["evidence_ids"])
    ]
    assert len(matching) == 1
    assert matching[0]["status"] == status
    assert Decimal(matching[0]["residual"]) == Decimal(residual)
    if status != "unmatched":
        applied, _ = _confirm(env, matching[0])
        assert applied["status"] == status


def test_identity_conflict_hierarchy_and_reviewed_residual_fences(tmp_path: Path) -> None:
    env, _ = _seed(tmp_path, ["-100"])
    _, args = _submit(env, [_item("same", "100")])
    metadata = Path(args[2])
    body = json.loads(metadata.read_text())
    body["items"][0]["amount"] = "101"
    metadata.write_text(json.dumps(body))
    revision = env.revision()
    assert _invoke(env, args).exit_code != 0
    assert _invoke(env, [*args[:3], *env.options("changed")]).exit_code != 0
    assert env.revision() == revision
    body["items"] = [
        _item("parent", "100", evidence_kind="purchase"),
        _item("child", "100", parent_external_key="parent"),
    ]
    metadata.write_text(json.dumps(body))
    assert _invoke(env, [*args[:3], *env.options("double-count")]).exit_code != 0
    assert env.revision() == revision
    candidate = _candidates(env)["candidates"][0]
    candidate["residual"] = "1"
    path = env.file(
        "bad-residual.json",
        {
            "evidence_ids": candidate["evidence_ids"],
            "payment_ids": candidate["payment_ids"],
            "expected_residual": "1",
            "currency": "KRW",
            "reason": "bad review",
            "confirmed_at": NOW,
        },
    )
    assert _invoke(env, ["confirm", path, *env.options("bad")]).exit_code != 0
    assert env.revision() == revision


@pytest.mark.parametrize("version", [4, 5, 6, 7, 8])
def test_old_raw_restore_and_explicit_clone_upgrade(tmp_path: Path, version: int) -> None:
    source = GenerationPaths(tmp_path / "source")
    with RepositoryBuilder(source, new_entity_id(), expected_schema_version=version) as builder:
        builder.finalize()
    raw_before = source.database.read_bytes()
    create_backup(source.database, tmp_path / "backup")
    raw = GenerationPaths(tmp_path / "raw")
    restore_backup(tmp_path / "backup", raw.root)
    with RepositoryReader(raw.database, expected_schema_version=version) as reader:
        assert reader.info.schema_version == version
    upgrade = GenerationPaths(tmp_path / "upgraded")
    upgrade_repository(raw.database, upgrade)
    with RepositoryReader(upgrade.database) as reader:
        assert reader.info.schema_version == SQLITE_SCHEMA_VERSION == 9
        assert reader.rows("reconcile_evidence") == []
    assert source.database.read_bytes() == raw_before


def _facts(database: Path) -> Any:
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        return _load_facts(connection)


def test_explicit_many_to_many_and_same_evidence_new_retry_key(tmp_path: Path) -> None:
    env, payments = _seed(tmp_path, ["-150", "-170"])
    submitted, args = _submit(env, [_item("first", "110"), _item("second", "210")])
    revision = env.revision()
    repeated = _payload(_invoke(env, [*args[:3], *env.options("second-submit-key")]))
    assert repeated["inserted_count"] == 0 and repeated["state_changed"] is False
    assert repeated["evidence_ids"] == submitted["evidence_ids"]
    assert repeated["occurrence_id"] == submitted["occurrence_id"]
    assert env.revision() == revision
    confirmed, _ = _confirm(
        env,
        {
            "evidence_ids": submitted["evidence_ids"],
            "payment_ids": payments,
            "residual": "0",
            "currency": "KRW",
        },
    )
    assert confirmed["status"] == "matched"
    with RepositoryReader(env.database) as reader:
        assert len(reader.rows("reconcile_allocation_evidence")) == 2
        assert len(reader.rows("reconcile_allocation_payments")) == 2
