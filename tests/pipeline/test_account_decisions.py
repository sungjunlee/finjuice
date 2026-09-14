"""Real authority CLI decisions, exact source scope and restore continuity."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import MutationIdentity, StorageMutationFacade
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    PartyRecord,
    RepositoryReader,
    new_entity_id,
)
from finjuice.pipeline.storage.sqlite.backup import create_backup
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreSession,
    restore_workspace,
)
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationService
from finjuice.pipeline.storage.sqlite.schema import inspect_repository
from tests.pipeline.test_account_bindings import _changed_assets
from tests.pipeline.test_recovery_bundle import _live
from tests.pipeline.test_sqlite_exact_import import _asset_book, _capture, _tx_book, _tx_row
from tests.pipeline.test_sqlite_mutations import _request


@dataclass
class Environment:
    source: Any
    generation: str
    database: Path
    account: str
    other: str
    parties: tuple[str, str]
    facade: StorageMutationFacade
    root: Path

    def revision(self):
        return inspect_repository(self.database).dataset_revision

    def invoke(self, arguments: list[str], *, json_output: bool = True):
        return CliRunner().invoke(
            app,
            [
                "--data-dir",
                str(self.source.data_dir),
                "ssot",
                "account",
                *arguments,
                *(["--json"] if json_output else []),
            ],
            obj={"activation_evidence_provider": self.source.evidence_provider},
        )

    def options(self, key: str, revision: int | None = None):
        return [
            "--idempotency-key",
            key,
            "--expected-generation",
            self.generation,
            "--expected-revision",
            str(self.revision() if revision is None else revision),
        ]

    def file(self, name: str, body: dict):
        path = self.root / name
        path.write_text(json.dumps(body))
        return str(path)

    def import_bytes(self, content: bytes, key: str):
        return self.facade.import_exact_xlsx(
            ExactImportCommand(_capture(content)),
            identity=MutationIdentity(key, self.generation, self.revision()),
        )


def _environment(tmp_path: Path) -> Environment:
    source, _, paths, generation, _, _ = _live(tmp_path)
    account, other, party, second = [new_entity_id() for _ in range(4)]
    database = paths.generation(generation).database

    def seed(context):
        for identifier in (account, other):
            context.add_account(AccountRecord(identifier, account_kind="bank.v1"))
        for identifier in (party, second):
            context.add_party(PartyRecord(identifier))
        return MutationOutcome(result={"seed": True})

    facade = StorageMutationFacade(source.data_dir, source.evidence_provider)
    dispatch = facade.dispatch()
    MutationService(paths, dispatch.evidence).execute(
        _request(generation, "decision-seed", inspect_repository(database).dataset_revision), seed
    )
    return Environment(
        source, generation, database, account, other, (party, second), facade, tmp_path
    )


def _binding(env: Environment, *, transaction: bool = False):
    return {
        "source_namespace": "banksalad.transactions.account_text.v1"
        if transaction
        else "banksalad.assets.account_id.v1",
        "external_key": "카드A" if transaction else "acct-1",
        "account_id": env.account,
        "evidence": {"reason": "synthetic explicit decision"},
    }


def _ownership(env: Environment):
    return {
        "account_id": env.account,
        "completeness": "partial",
        "effective_from": "2026-01-01",
        "effective_to": "2026-12-31",
        "evidence": {"reason": "synthetic jointly held account"},
        "shares": [
            {"party_id": env.parties[0], "coefficient": "333333333333333333", "scale": 18},
            {"party_id": env.parties[1], "coefficient": "333333333333333333", "scale": 18},
        ],
    }


def _payload(result, schema_name: str | None = None):
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output[result.output.index("{") :])
    if schema_name:
        schema = json.loads((Path(__file__).parents[2] / "schemas" / schema_name).read_text())
        from tests.test_json_schemas import _validator_for

        _validator_for(schema).validate(payload)
    return payload


@pytest.mark.parametrize("json_output", [False, True])
def test_binding_preview_actual_scope_stale_and_correction(tmp_path, json_output):
    env = _environment(tmp_path)
    env.import_bytes(_asset_book(), "initial-source")
    body = _binding(env)
    request = env.file("binding.json", body)
    revision = env.revision()
    result = env.invoke(["preview", request], json_output=json_output)
    if not json_output:
        assert result.exit_code == 0 and "계좌 연결 미리보기" in result.output
        assert "기존 거래·자산은 변경하지 않습니다" in result.output
        result = env.invoke(["preview", request])
    preview = _payload(result, "ssot_account_preview.schema.json")
    assert env.revision() == revision == preview["expected_revision"]
    assert preview["expected_generation"] == env.generation
    assert preview["before"]["status"] == "unbound"
    assert preview["after"]["account_id"] == env.account
    assert preview["historical_rows_rewritten"] == 0
    scope = preview["observed_scope"]
    assert scope and scope[0]["account_id"] != env.account
    assert scope[0]["observation_id"] and scope[0]["source_occurrence_id"]
    first = _payload(env.invoke(["confirm", request, *env.options("confirm", revision)]))
    stale = env.invoke(["confirm", request, *env.options("stale", revision)])
    assert stale.exit_code != 0
    env.import_bytes(_changed_assets(), "subsequent-source")
    body["account_id"] = env.other
    request = env.file("correction.json", body)
    preview = _payload(env.invoke(["preview", request, "--corrects", first["binding_id"]]))
    assert preview["before"]["account_id"] == env.account
    assert preview["after"]["account_id"] == env.other
    _payload(
        env.invoke(
            [
                "correct",
                first["binding_id"],
                request,
                *env.options("correct", preview["expected_revision"]),
            ]
        )
    )
    with RepositoryReader(env.database) as reader:
        assert {row["account_id"] for row in reader.rows("asset_snapshots")} >= {
            scope[0]["account_id"],
            env.account,
        }
    wrong_generation = env.invoke(
        [
            "confirm",
            request,
            "--idempotency-key",
            "wrong-generation",
            "--expected-generation",
            new_entity_id(),
            "--expected-revision",
            str(env.revision()),
        ]
    )
    assert wrong_generation.exit_code != 0


@pytest.mark.parametrize("json_output", [False, True])
def test_ownership_cli_exact_correction_replay_import_and_restore(tmp_path, json_output):
    env = _environment(tmp_path)
    body = _ownership(env)
    request = env.file("ownership.json", body)
    options = env.options("owner")
    result = env.invoke(["ownership-confirm", request, *options], json_output=json_output)
    if not json_output:
        assert result.exit_code == 0 and "소유권 확정" in result.output
        result = env.invoke(["ownership-confirm", request, *options])
    first = _payload(result, "ssot_account_ownership_confirm.schema.json")
    replay = _payload(env.invoke(["ownership-confirm", request, *options]))
    assert replay["replayed"] and replay["assertion_id"] == first["assertion_id"]
    stale = env.invoke(
        ["ownership-confirm", request, *env.options("stale", first["base_revision"])]
    )
    assert stale.exit_code != 0
    projection = _payload(env.invoke(["ownership", env.account, "--as-of", "2026-07-15"]))
    assert projection["remainder"] == {"coefficient": "333333333333333334", "scale": 18}
    assert projection["unknown_remainder"] and len(projection["shares"]) == 2
    assert projection["assertions"][0]["evidence"] == body["evidence"]
    body["shares"] = [{"party_id": env.parties[1], "coefficient": "1", "scale": 0}]
    body["completeness"] = "complete"
    request = env.file("ownership-correct.json", body)
    conflict = env.invoke(["ownership-confirm", request, *options])
    assert conflict.exit_code != 0
    correction_args = [
        "ownership-correct",
        first["assertion_id"],
        request,
        *env.options("correct-owner"),
    ]
    result = env.invoke(correction_args, json_output=json_output)
    if not json_output:
        assert result.exit_code == 0 and "소유권 확정" in result.output
        assert first["assertion_id"] in result.output
        result = env.invoke(correction_args)
    correction = _payload(result, "ssot_account_ownership_correct.schema.json")
    assert correction["supersedes_assertion_id"] == first["assertion_id"]
    invalid_recorrection = env.invoke(
        ["ownership-correct", first["assertion_id"], request, *env.options("old-head")]
    )
    assert invalid_recorrection.exit_code != 0
    binding = env.file("binding.json", _binding(env))
    _payload(env.invoke(["confirm", binding, *env.options("bind")]))
    with RepositoryReader(env.database) as reader:
        baseline = {row["entity_id"] for row in reader.rows("asset_snapshots")}
    env.import_bytes(_asset_book(), "source-one")
    env.import_bytes(_changed_assets(), "source-two")
    backup = tmp_path / "backup"
    create_backup(env.database, backup)
    receipt = restore_workspace(backup, tmp_path / "restored")
    with InactiveRestoreSession(receipt) as session:
        projection = session.read_snapshot(
            lambda reader: reader.account_ownership(env.account, as_of="2026-07-15")
        )
        assert projection["assertion_id"] == correction["assertion_id"]
        assert projection["shares"][0]["party_id"] == env.parties[1]
        assert len(projection["assertions"]) == 2
        assert projection["remainder"] == {"coefficient": "0", "scale": 0}
        rows = session.read_snapshot(lambda reader: reader.rows("asset_snapshots"))
        assert baseline <= {row["entity_id"] for row in rows}
        imported = [row for row in rows if row["entity_id"] not in baseline]
        assert len(imported) == 2
        assert {row["account_id"] for row in imported} == {env.account}


def test_ownership_invalid_total_rolls_back_and_transaction_preview(tmp_path):
    env = _environment(tmp_path)
    env.import_bytes(_tx_book(_tx_row(2)), "transaction")
    request = env.file("binding.json", _binding(env, transaction=True))
    preview = _payload(env.invoke(["preview", request]))
    assert preview["observed_scope"] and preview["observed_scope"][0]["transaction_id"]
    revision = env.revision()
    with RepositoryReader(env.database) as reader:
        values_before = len(reader.rows("exact_values"))
    body = _ownership(env)
    body["completeness"] = "complete"
    result = env.invoke(
        ["ownership-confirm", env.file("invalid.json", body), *env.options("invalid")]
    )
    assert result.exit_code != 0
    assert env.revision() == revision
    with RepositoryReader(env.database) as reader:
        assert len(reader.rows("exact_values")) == values_before
        assert not [
            row
            for row in reader.rows("ownership_assertion_sets")
            if row["account_id"] == env.account
        ]


def _catalog_command_result(tmp_path: Path, command: str):
    env = _environment(tmp_path)
    if command == "preview":
        return env.invoke([command, env.file("binding.json", _binding(env))])
    request = env.file("ownership.json", _ownership(env))
    args = [command]
    if command == "ownership-correct":
        first = _payload(env.invoke(["ownership-confirm", request, *env.options("first")]))
        args.append(first["assertion_id"])
    return env.invoke([*args, request, *env.options("catalog")])
