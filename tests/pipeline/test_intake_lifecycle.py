"""Actual immutable intake revision, withdrawal, typed correction and recovery workflows."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
from finjuice.pipeline.storage.sqlite.inactive_restore import (
    InactiveRestoreSession,
    restore_workspace,
)
from finjuice.pipeline.storage.sqlite.mutations import MutationContext
from finjuice.pipeline.storage.sqlite.recovery_bundle import (
    capture_recovery_bundle,
    verify_recovery_bundle,
)
from tests.pipeline.test_account_bindings import _changed_assets
from tests.pipeline.test_account_decisions import _environment
from tests.pipeline.test_canonical_intake_cli import (
    NOW,
    _confirm_arguments,
    _documents,
    _invoke,
    _payload,
)
from tests.pipeline.test_sqlite_exact_import import _asset_book


def _view(env, proposal_id):
    return next(
        row
        for row in _payload(_invoke(env, ["list"]))["decisions"]
        if row["proposal_id"] == proposal_id
    )


def _revise_body(parent, **changes):
    return {
        "parent_payload_digest": parent["payload_digest"],
        "proposal": copy.deepcopy(parent["proposal"]),
        "evidence": {"reason": "explicit synthetic correction"},
        "revised_at": NOW,
        "uncertainties": [],
        "resolutions": {
            value: "synthetic evidence explicitly resolved" for value in parent["uncertainties"]
        },
        **changes,
    }


def _revise(env, parent, body, key, human=False):
    args = ["revise", parent["proposal_id"], env.file(key + ".json", body), *env.options(key)]
    result = _invoke(env, args, human=human)
    assert result.exit_code == 0, result.output
    if human:
        assert "증빙 제안 수정" in result.output and parent["proposal_id"] in result.output
    payload = _payload(_invoke(env, args))
    assert payload["replayed"]
    from tests.test_json_schemas import _load_schema, _validator_for

    _validator_for(_load_schema("ssot_intake_revise.schema.json")).validate(payload)
    return payload, args


def _setup_graph(tmp_path, monkeypatch):
    import tests.pipeline.test_account_decisions as helper

    original = helper._live
    captured = []

    def live(path):
        result = original(path)
        captured.append(result[1])
        return result

    monkeypatch.setattr(helper, "_live", live)
    return _environment(tmp_path), captured


@pytest.mark.parametrize("human", [False, True])
def test_revision_resolves_stale_uncertainty_corrects_applied_fact_and_restores(
    tmp_path, monkeypatch, human
):
    env, expected = _setup_graph(tmp_path, monkeypatch)
    source, metadata = _documents(env, uncertain=True)
    original_bytes = Path(source).read_bytes()
    submitted = _payload(_invoke(env, ["submit", source, metadata, *env.options("submit")]))
    # An independent receipt makes the original uncertain proposal stale as well.
    _payload(_invoke(env, ["submit", source, metadata, *env.options("other")]))
    parent = _view(env, submitted["proposal_id"])
    assert parent["stale"] and parent["uncertainties"]
    Path(source).unlink()
    body = _revise_body(parent, extraction={"operator_corrected": "explicit ownership shares"})
    body["proposal"]["decision"]["completeness"] = "complete"
    body["proposal"]["decision"]["shares"] = [
        {"party_id": env.parties[0], "coefficient": "1", "scale": 0}
    ]
    before = env.revision()
    revised, args = _revise(env, parent, body, "revise", human)
    assert env.revision() == before + 1 == revised["expected_revision"]
    old = _view(env, parent["proposal_id"])
    child = _view(env, revised["proposal_id"])
    assert old["status"] == "revised" and old["proposal"] == parent["proposal"]
    assert (
        old["extraction"] == parent["extraction"]
        and old["uncertainties"] == parent["uncertainties"]
    )
    assert old["successor_proposal_ids"] == [child["proposal_id"]]
    assert child["source_artifact_id"] == old["source_artifact_id"]
    assert (
        child["extractor"] == "operator.revision.v1"
        and child["lineage"]["parent_extraction_id"] == old["extraction_id"]
    )
    assert _invoke(env, _confirm_arguments(submitted)).exit_code != 0
    denied_revision = _invoke(
        env,
        [
            "revise",
            parent["proposal_id"],
            env.file("revive.json", _revise_body(parent)),
            *env.options("revive"),
        ],
    )
    assert denied_revision.exit_code != 0
    assert _view(env, parent["proposal_id"])["status"] == "rejected"
    applied = _payload(_invoke(env, _confirm_arguments(revised)))
    applied_parent = _view(env, revised["proposal_id"])
    corrected_body = _revise_body(applied_parent)
    corrected_body["proposal"]["decision"]["shares"] = [
        {"party_id": env.parties[1], "coefficient": "1", "scale": 0}
    ]
    # Same operation and account, but an applied correction must explicitly name the real head.
    missing_head = _invoke(
        env,
        [
            "revise",
            revised["proposal_id"],
            env.file("missing-head.json", corrected_body),
            *env.options("missing-head"),
        ],
    )
    assert missing_head.exit_code != 0
    corrected_body["proposal"]["decision"]["supersedes_assertion_id"] = applied["applied"][
        "assertion_id"
    ]
    correction, _ = _revise(env, applied_parent, corrected_body, "correction", human)
    assert _view(env, revised["proposal_id"])["status"] == "applied"
    corrected = _payload(_invoke(env, _confirm_arguments(correction)))
    assert corrected["applied"]["supersedes_assertion_id"] == applied["applied"]["assertion_id"]
    assert _payload(_invoke(env, args))["changeset_id"] == revised["changeset_id"]
    env.facade.confirm_account_binding(
        AccountBindingConfirmation(
            "banksalad.assets.account_id.v1",
            "acct-1",
            env.account,
            {"reason": "synthetic stable source"},
        )
    )
    env.import_bytes(_asset_book(), "xlsx-one")
    env.import_bytes(_changed_assets(), "xlsx-two")
    receipt = capture_recovery_bundle(env.source, expected[0])
    assert verify_recovery_bundle(env.source.destination, expected[0]) == receipt
    restored = restore_workspace(env.source.destination / "snapshot", tmp_path / "restored")
    with InactiveRestoreSession(restored) as session:
        ownership = session.read_snapshot(
            lambda reader: reader.account_ownership(env.account, as_of="2026-07-15")
        )
        assert ownership["shares"][0]["party_id"] == env.parties[1]
        decisions = session.read_snapshot(lambda reader: reader.intake_decisions())["decisions"]
        assert (
            next(row for row in decisions if row["proposal_id"] == revised["proposal_id"])["status"]
            == "applied"
        )
        assert (
            next(row for row in decisions if row["proposal_id"] == correction["proposal_id"])[
                "lineage"
            ]["parent_application_changeset_id"]
            == applied["changeset_id"]
        )
        artifact = old["source_artifact_id"].split(":", 1)[1]
        assert (
            (restored.workspace / "generation") / "objects" / "sha256" / artifact[:2] / artifact
        ).read_bytes() == original_bytes


@pytest.mark.parametrize("human", [False, True])
def test_pending_withdrawal_is_idempotent_and_never_undoes_applied_domain(tmp_path, human):
    env = _environment(tmp_path)
    source, metadata = _documents(env)
    submitted = _payload(_invoke(env, ["submit", source, metadata, *env.options("submit")]))
    parent = _view(env, submitted["proposal_id"])
    body = {
        "payload_digest": parent["payload_digest"],
        "evidence": {"reason": "operator withdrew request"},
        "rejected_at": NOW,
    }
    args = [
        "withdraw",
        parent["proposal_id"],
        env.file("withdraw.json", body),
        *env.options("withdraw"),
    ]
    first = _invoke(env, args, human=human)
    assert first.exit_code == 0, first.output
    if human:
        assert "증빙 제안 철회" in first.output
    result = _payload(_invoke(env, args))
    assert result["replayed"] and result["status"] == "rejected"
    from tests.test_json_schemas import _load_schema, _validator_for

    _validator_for(_load_schema("ssot_intake_withdraw.schema.json")).validate(result)
    assert _view(env, parent["proposal_id"])["status"] == "rejected"
    assert _invoke(env, _confirm_arguments(submitted)).exit_code != 0
    denied_revision = _invoke(
        env,
        [
            "revise",
            parent["proposal_id"],
            env.file("revive.json", _revise_body(parent)),
            *env.options("revive"),
        ],
    )
    assert denied_revision.exit_code != 0
    assert _view(env, parent["proposal_id"])["status"] == "rejected"
    another = _payload(_invoke(env, ["submit", source, metadata, *env.options("another")]))
    applied = _payload(_invoke(env, _confirm_arguments(another)))
    body["payload_digest"] = _view(env, another["proposal_id"])["payload_digest"]
    denied = _invoke(
        env,
        ["withdraw", another["proposal_id"], env.file("applied.json", body), *env.options("undo")],
    )
    assert denied.exit_code != 0
    assert (
        _view(env, another["proposal_id"])["application"]["changeset_id"] == applied["changeset_id"]
    )


def test_revision_atomic_failure_identity_conflict_and_source_revalidation(tmp_path, monkeypatch):
    env = _environment(tmp_path)
    source, metadata = _documents(env, uncertain=True)
    submitted = _payload(_invoke(env, ["submit", source, metadata, *env.options("submit")]))
    parent = _view(env, submitted["proposal_id"])
    body = _revise_body(parent)
    revision = env.revision()
    args = [
        "revise",
        parent["proposal_id"],
        env.file("revise.json", body),
        *env.options("revise", revision),
    ]
    original = MutationContext.add_intake_confirmation

    def fail_confirmation(context, record):
        if record.detail.get("action") == "superseded":
            raise RuntimeError("synthetic ordinary failure after successor staging")
        return original(context, record)

    with monkeypatch.context() as patch:
        patch.setattr(MutationContext, "add_intake_confirmation", fail_confirmation)
        assert _invoke(env, args).exit_code != 0
    assert env.revision() == revision
    with RepositoryReader(env.database) as reader:
        assert len(reader.rows("agent_intake_proposals")) == 1
        assert len(reader.rows("agent_intake_extractions")) == 1
        assert reader.rows("agent_intake_confirmations") == []
    from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore

    def invalid_source(*_args):
        raise ValueError("synthetic retained object verification failure")

    with monkeypatch.context() as patch:
        patch.setattr(SourceObjectStore, "verify", invalid_source)
        assert _invoke(env, args).exit_code != 0
    assert env.revision() == revision
    missing_resolution = copy.deepcopy(body)
    missing_resolution["resolutions"] = {}
    assert (
        _invoke(
            env,
            [
                "revise",
                parent["proposal_id"],
                env.file("unresolved.json", missing_resolution),
                *env.options("unresolved"),
            ],
        ).exit_code
        != 0
    )
    wrong = copy.deepcopy(body)
    wrong["parent_payload_digest"] = "0" * 64
    assert (
        _invoke(
            env,
            ["revise", parent["proposal_id"], env.file("wrong.json", wrong), *env.options("wrong")],
        ).exit_code
        != 0
    )
    changed_kind = copy.deepcopy(body)
    changed_kind["proposal"]["change_kind"] = "transaction_override"
    assert (
        _invoke(
            env,
            [
                "revise",
                parent["proposal_id"],
                env.file("kind.json", changed_kind),
                *env.options("kind"),
            ],
        ).exit_code
        != 0
    )
    changed_account = copy.deepcopy(body)
    changed_account["proposal"]["decision"]["account_id"] = env.other
    assert (
        _invoke(
            env,
            [
                "revise",
                parent["proposal_id"],
                env.file("account.json", changed_account),
                *env.options("account"),
            ],
        ).exit_code
        != 0
    )
    result = _payload(_invoke(env, args))
    assert result["committed_revision"] == revision + 1
    conflict = copy.deepcopy(body)
    conflict["evidence"] = {"reason": "different request under same key"}
    Path(args[2]).write_text(json.dumps(conflict))
    assert _invoke(env, args).exit_code != 0
    assert env.revision() == revision + 1


@pytest.mark.parametrize("kind", ["transaction_override", "recurring_rule"])
def test_applied_transaction_or_rule_revision_preserves_operation_and_target(tmp_path, kind):
    env = _environment(tmp_path)
    source, metadata = _documents(env)
    document = json.loads(Path(metadata).read_text())
    from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row

    env.import_bytes(_tx_book(_tx_row(2)), "transaction")
    with RepositoryReader(env.database) as reader:
        transaction_id = reader.rows("transactions")[0]["entity_id"]
    if kind == "transaction_override":
        proposal = {
            "change_kind": kind,
            "operation": "manual_transaction",
            "decision": {"identifier": transaction_id, "note_supplied": True, "note": "first"},
        }
    else:
        proposal = {
            "change_kind": kind,
            "operation": "rule",
            "decision": {
                "action": "upsert",
                "rule": {
                    "name": "lifecycle-synthetic",
                    "match": "coffee",
                    "fields": ["merchant_raw"],
                    "tags": ["first"],
                },
            },
        }
    document["proposal"] = proposal
    Path(metadata).write_text(json.dumps(document))
    submitted = _payload(_invoke(env, ["submit", source, metadata, *env.options("submit")]))
    _payload(_invoke(env, _confirm_arguments(submitted)))
    parent = _view(env, submitted["proposal_id"])
    body = _revise_body(parent)
    if kind == "transaction_override":
        body["proposal"]["decision"]["note"] = "corrected"
    else:
        body["proposal"]["decision"]["rule"]["tags"] = ["corrected"]
    successor, _ = _revise(env, parent, body, "revise")
    applied = _payload(_invoke(env, _confirm_arguments(successor)))
    assert _view(env, submitted["proposal_id"])["status"] == "applied"
    with RepositoryReader(env.database) as reader:
        if kind == "transaction_override":
            row = next(
                row for row in reader.rows("transactions") if row["entity_id"] == transaction_id
            )
            assert row["notes_manual"] == "corrected"
        else:
            assert applied["applied"]["rule_name"] == "lifecycle-synthetic"
            head = next(row for row in reader.rows("config_heads") if row["config_kind"] == "rules")
            revision = next(
                row
                for row in reader.rows("config_revisions")
                if row["entity_id"] == head["revision_id"]
            )
            assert "corrected" in revision["canonical_payload_json"]


def intake_lifecycle_catalog_outputs(tmp_path):
    env = _environment(tmp_path)
    source, metadata = _documents(env, uncertain=True)
    submitted = _payload(_invoke(env, ["submit", source, metadata, *env.options("submit")]))
    parent = _view(env, submitted["proposal_id"])
    revised, _ = _revise(env, parent, _revise_body(parent), "revise")
    child = _view(env, revised["proposal_id"])
    body = {
        "payload_digest": child["payload_digest"],
        "evidence": {"reason": "synthetic withdrawal"},
        "rejected_at": NOW,
    }
    withdrawn = _payload(
        _invoke(
            env,
            [
                "withdraw",
                child["proposal_id"],
                env.file("withdraw.json", body),
                *env.options("withdraw"),
            ],
        )
    )
    return {"ssot_intake_revise": revised, "ssot_intake_withdraw": withdrawn}
