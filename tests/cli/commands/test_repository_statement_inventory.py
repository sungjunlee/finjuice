"""Canonical statement inventory agrees across active diagnostics and ingestion."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.cli.commands.test_automation_run import _set_home
from tests.cli.commands.test_repository_automation import _config
from tests.cli.commands.test_repository_bulk_commands import _invoke
from tests.cli.commands.test_repository_doctor import (
    observed_environment as _observed_environment_fixture,
)
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.cli.commands.test_repository_statement_ingest import _bind, _payload, _stage
from tests.pipeline.test_canonical_statement_json import _envelope, _record

active_root = _active_root_fixture
observed_environment = _observed_environment_fixture


@pytest.fixture(autouse=True)
def isolated_automation_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_home(monkeypatch, tmp_path)
    _config()


def _diagnose(active: _ActiveRoot, command: str) -> dict[str, Any]:
    args = ("run", "--json") if command == "automation" else ("--json",)
    result = _invoke(active, command, *args)
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _assert_inventory(active: _ActiveRoot, command: str, pending: int) -> None:
    before = _authority_state(active)
    payload = _diagnose(active, command)
    observation = payload["_meta"]["staged_observation"]
    assert observation["files_seen"] == 1
    assert observation["pending_files"] == pending
    assert observation["failed_files"] == 0
    assert observation["preview_policy"] == "independent_baseline.v1"
    if command == "automation":
        assert payload["pending_imports"]["pending_files"] == pending
    if pending and command in {"automation", "checkup"}:
        actions = payload["next_steps" if command == "automation" else "next_actions"]
        assert any(action["command"] == "finjuice refresh" for action in actions)
    assert _authority_state(active) == before


@pytest.mark.parametrize("command", ["doctor", "checkup", "automation"])
def test_json_only_inventory_becomes_noop_after_ingest(
    active_root: _ActiveRoot, command: str
) -> None:
    _bind(active_root)
    _stage(
        active_root,
        "statement.json",
        _envelope([_record("inventory-1", decision={"action": "create"})]),
    )
    (active_root.root / "imports" / "other.json").write_text('{"unrelated": true}')
    (active_root.root / "imports" / "broken.json").write_text("{")

    _assert_inventory(active_root, command, 1)
    applied = _payload(_invoke(active_root, "ingest", "--json"))
    assert applied["summary"]["new_transactions"] == 1
    _assert_inventory(active_root, command, 0)


@pytest.mark.parametrize("command", ["doctor", "checkup", "automation"])
def test_recorded_pending_statement_becomes_actionable_after_account_confirmation(
    active_root: _ActiveRoot, command: str
) -> None:
    _stage(
        active_root,
        "statement.json",
        _envelope([_record("inventory-1", decision={"action": "create"})]),
    )
    first = _payload(_invoke(active_root, "ingest", "--json"))
    assert first["summary"]["new_transactions"] == 0
    _assert_inventory(active_root, command, 0)

    _bind(active_root)

    _assert_inventory(active_root, command, 1)
    applied = _payload(_invoke(active_root, "ingest", "--json"))
    assert applied["summary"]["new_transactions"] == 1
    _assert_inventory(active_root, command, 0)


@pytest.mark.parametrize("command", ["doctor", "checkup", "automation"])
@pytest.mark.parametrize(
    "record",
    [
        pytest.param(_record("invalid-1", amount="not-money"), id="amount"),
        pytest.param(
            _record("invalid-1", decision={"action": "link", "transaction_id": "not-a-uuid"}),
            id="link-id",
        ),
    ],
)
def test_claimed_but_invalid_statement_is_a_failed_staged_file(
    active_root: _ActiveRoot, command: str, record: dict[str, Any]
) -> None:
    _stage(
        active_root,
        "invalid-statement.json",
        _envelope([record]),
    )
    before = _authority_state(active_root)

    payload = _diagnose(active_root, command)

    observation = payload["_meta"]["staged_observation"]
    assert observation["files_seen"] == 1
    assert observation["pending_files"] == 0
    assert observation["failed_files"] == 1
    assert _authority_state(active_root) == before


def test_fast_checkup_counts_canonical_json_without_previewing_it(
    active_root: _ActiveRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_preview(*args: object, **kwargs: object) -> None:
        raise AssertionError("Fast mode must not evaluate statement rows")

    monkeypatch.setattr(
        "finjuice.pipeline.storage.sqlite.checkup_reads._statement_preview", unexpected_preview
    )
    _stage(active_root, "statement.json", _envelope([_record("fast-1")]))
    before = _authority_state(active_root)

    result = _invoke(active_root, "checkup", "--fast", "--json")

    assert result.exit_code == 0, result.output
    observation = json.loads(result.output)["_meta"]["staged_observation"]
    assert observation["files_seen"] == 1
    assert observation["files_examined"] == 1
    assert observation["files_not_examined"] == 0
    assert observation["pending_files"] == 1
    assert observation["fast"] is True
    assert _authority_state(active_root) == before


@pytest.mark.parametrize("damage", ["missing", "corrupt", "future-version"])
def test_brief_status_reports_unavailable_repository_without_mutating_it(
    active_root: _ActiveRoot, damage: str
) -> None:
    import sqlite3

    from typer.testing import CliRunner

    from finjuice.pipeline.cli.main import app

    if damage == "missing":
        active_root.database.unlink()
    elif damage == "corrupt":
        active_root.database.write_bytes(b"synthetic invalid SQLite database")
    else:
        with sqlite3.connect(active_root.database) as connection:
            connection.execute("PRAGMA user_version = 999")

    def file_fingerprints() -> dict[str, bytes]:
        return {
            path.relative_to(active_root.root).as_posix(): path.read_bytes()
            for path in active_root.root.rglob("*")
            if path.is_file() and path != active_root.paths.coordination_lock
        }

    before = file_fingerprints()

    result = CliRunner().invoke(
        app,
        ["--data-dir", str(active_root.root)],
        obj={"activation_evidence_provider": active_root.provider},
    )

    assert result.exit_code == 0, result.output
    assert "Repository authority could not be verified; run finjuice doctor" in result.output
    assert "미처리 파일" not in result.output
    assert "CSV" not in result.output
    assert "Traceback" not in result.output
    assert file_fingerprints() == before


@pytest.mark.parametrize("command", ["doctor", "checkup", "automation", "brief"])
def test_diagnostics_ignore_statement_above_capture_limit(
    active_root: _ActiveRoot, command: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from typer.testing import CliRunner

    from finjuice.pipeline.cli.main import app
    from finjuice.pipeline.statements import staged

    # Exercise the production bound using a tiny limit and a small synthetic file.
    monkeypatch.setattr(staged, "MAX_STATEMENT_BYTES", 8)
    _stage(active_root, "over-limit.json", _envelope([_record("bounded-1")]))
    before = _authority_state(active_root)

    if command == "brief":
        result = CliRunner().invoke(
            app,
            ["--data-dir", str(active_root.root)],
            obj={"activation_evidence_provider": active_root.provider},
        )
        assert result.exit_code == 0, result.output
        assert "미처리 파일" not in result.output
    else:
        payload = _diagnose(active_root, command)
        observation = payload["_meta"]["staged_observation"]
        assert observation["files_seen"] == 0
        assert observation["pending_files"] == 0
    assert _authority_state(active_root) == before
