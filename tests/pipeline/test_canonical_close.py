"""Actual canonical close CLI: freeze, late input, reopen, reclose diff and restore."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
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
from tests.pipeline.test_sqlite_exact_import import _inline, _n, _row, _s, _tx_book, _tx_row

PERIOD = "2024-03"
NOW = "2026-09-14T00:00:00Z"
LATER = "2026-09-15T00:00:00Z"


def _invoke(env: Environment, args: list[str], *, human: bool = False) -> Any:
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(env.source.data_dir),
            "ssot",
            "close",
            *args,
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": env.source.evidence_provider},
    )


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    body: dict[str, Any] = json.loads(result.output[result.output.index("{") :])
    return body


def _seed(env: Environment, amounts: list[str], key: str) -> None:
    env.import_bytes(
        _tx_book(
            *[
                _tx_row(index + 2, amount=value, income=Decimal(value) > 0)
                for index, value in enumerate(amounts)
            ]
        ),
        key,
    )


def _close_args(env: Environment, key: str, **overrides: str) -> list[str]:
    options = {
        "--period": PERIOD,
        "--source-as-of": NOW,
        "--calculation-policy": "cash.v1",
        "--closed-at": NOW,
        "--reason": "monthly operating close",
        **overrides,
    }
    flat = [item for pair in options.items() for item in pair]
    return ["run", *flat, *env.options(key)]


def _reopen_args(env: Environment, key: str) -> list[str]:
    return [
        "reopen",
        "--period",
        PERIOD,
        "--reason",
        "late card statement arrived",
        "--reopened-at",
        LATER,
        *env.options(key),
    ]


def close_catalog_outputs(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Return actual successful command payloads for the shared schema catalog test."""
    env = _environment(tmp_path)
    _seed(env, ["-1000.00", "2500.00"], "close-seed")
    closed = _payload(_invoke(env, _close_args(env, "close-1")))
    reopened = _payload(_invoke(env, _reopen_args(env, "reopen-1")))
    history = _payload(_invoke(env, ["history", "--period", PERIOD]))
    return {
        "ssot_close_run": closed,
        "ssot_close_reopen": reopened,
        "ssot_close_history": history,
    }


@pytest.mark.parametrize("human", [False, True])
def test_close_late_data_reopen_reclose_diff_and_restore(tmp_path: Path, human: bool) -> None:
    # Arrange: a month with exact multi-currency-free ledger facts.
    env = _environment(tmp_path)
    _seed(env, ["-1000.00", "2500.00"], "close-seed")

    # Act: freeze the first close and retry it with the same request identity.
    arguments = _close_args(env, "close-1")
    first = _invoke(env, arguments, human=human)
    assert first.exit_code == 0, first.output
    closed = _payload(_invoke(env, arguments))
    assert closed["replayed"] and closed["close"]["close_revision"] == 1
    totals = closed["close"]["totals"]["transactions"]["KRW"]
    assert (totals["income"], totals["expense"], totals["net"]) == (
        "2500.00",
        "-1000.00",
        "1500.00",
    )
    assert closed["close"]["completeness"] == "complete"
    if human:
        assert "마감 리비전 1" in first.output

    # Assert: late input never overwrites a still-closed month.
    _seed(env, ["-250.00"], "late-input")
    blocked = _invoke(env, _close_args(env, "close-blocked"))
    assert blocked.exit_code != 0
    stored = _payload(_invoke(env, ["history", "--period", PERIOD]))
    assert stored["periods"][PERIOD] == {
        "state": "closed",
        "close_revision": 1,
        "completeness": "complete",
        "report_digest": stored["revisions"][0]["report_digest"],
    }
    assert stored["revisions"][0]["report"]["totals"]["transactions"]["KRW"]["net"] == "1500.00"

    # Act: explicit reopen, then reclose creates a successor with an explicit diff.
    reopen = _reopen_args(env, "reopen-1")
    assert _invoke(env, reopen, human=human).exit_code == 0
    reopened = _payload(_invoke(env, reopen))
    assert reopened["replayed"] and reopened["close_revision"] == 1
    reclosed = _payload(
        _invoke(env, _close_args(env, "close-2", **{"--source-as-of": LATER, "--closed-at": LATER}))
    )
    assert reclosed["reclosed"] and reclosed["close"]["close_revision"] == 2
    assert reclosed["close"]["totals"]["transactions"]["KRW"]["net"] == "1250.00"
    changed = {change["field"] for change in reclosed["diff"]}
    assert {"dataset_revision", "totals", "source_as_of", "transaction_count"} <= changed

    # Assert: history keeps the predecessor report unchanged and reproducible.
    rendered = _invoke(env, ["history"], human=human)
    assert rendered.exit_code == 0, rendered.output
    if human:
        assert f"{PERIOD}: closed" in rendered.output
    history = _payload(_invoke(env, ["history"]))
    assert [row["close_revision"] for row in history["revisions"]] == [1, 2]
    assert history["revisions"][0]["report"] == stored["revisions"][0]["report"]
    assert history["revisions"][1]["predecessor_close_id"] == history["revisions"][0]["close_id"]
    assert history["periods"][PERIOD]["state"] == "closed"

    # Assert: capture and restore preserve the full immutable close history.
    backup = tmp_path / "captured"
    create_backup(env.database, backup)
    restored = GenerationPaths(tmp_path / "restored")
    restore_backup(backup, restored.root)
    with RepositoryReader(restored.database) as reader:
        assert reader.close_history() == _history_without_meta(history)
    assert {item.identity_digest for item in _facts(env.database) if item.kind == "close"} == {
        item.identity_digest for item in _facts(restored.database) if item.kind == "close"
    }
    assert any(item.kind == "close" for item in _facts(restored.database))


def _history_without_meta(history: dict[str, Any]) -> dict[str, Any]:
    result = dict(history)
    result.pop("_meta", None)
    return result


def _facts(database: Path) -> Any:
    with sqlite3.connect(database.as_uri() + "?mode=ro", uri=True) as connection:
        return _load_facts(connection)


def test_unknown_currency_is_reported_unresolved_not_summed(tmp_path: Path) -> None:
    # Arrange: one in-period row whose source never stated a currency.
    env = _environment(tmp_path)
    env.import_bytes(_tx_book(_tx_row(2, amount="-1000.00"), _unknown_currency_row(3)), "seed")

    # Act.
    closed = _payload(_invoke(env, _close_args(env, "close-incomplete")))

    # Assert: the unknown currency is a named unresolved fact, never a guessed total.
    assert closed["close"]["completeness"] == "incomplete"
    assert closed["close"]["unresolved"]["currency_unknown"] == 1
    assert list(closed["close"]["totals"]["transactions"]) == ["KRW"]
    assert closed["close"]["totals"]["transactions"]["KRW"]["expense"] == "-1000.00"
    assert closed["close"]["transaction_count"] == 2


def _unknown_currency_row(number: int) -> str:
    return _row(
        number,
        _inline(f"A{number}", "2024-03-15"),
        _inline(f"B{number}", "13:04:05"),
        _s(f"C{number}", 8),
        _inline(f"D{number}", "카페"),
        _n(f"E{number}", "-500.00"),
        _s(f"F{number}", 11),
    )


def test_reopen_requires_an_existing_close_and_is_single_use(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    _seed(env, ["-10.00"], "close-seed")
    assert _invoke(env, _reopen_args(env, "no-close")).exit_code != 0
    _payload(_invoke(env, _close_args(env, "close-1")))
    _payload(_invoke(env, _reopen_args(env, "reopen-1")))
    revision = env.revision()
    assert _invoke(env, _reopen_args(env, "reopen-again")).exit_code != 0
    assert env.revision() == revision


@pytest.mark.parametrize("version", [4, 5, 6, 7, 8])
def test_old_raw_restore_and_explicit_clone_upgrade_adds_empty_close(
    tmp_path: Path, version: int
) -> None:
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
        assert reader.rows("close_revisions") == []
        assert reader.close_history() == {"revisions": [], "periods": {}}
    assert source.database.read_bytes() == raw_before
