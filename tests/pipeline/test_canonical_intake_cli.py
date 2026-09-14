"""Real authority-bound intake CLI submission, decisions and application retries."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.sqlite import RepositoryReader
from tests.pipeline.test_account_decisions import Environment, _environment, _ownership

NOW = "2026-09-14T00:00:00Z"


def _invoke(env: Environment, arguments: list[str], *, human: bool = False) -> Any:
    return CliRunner().invoke(
        app,
        [
            "--data-dir",
            str(env.source.data_dir),
            "ssot",
            "intake",
            *arguments,
            *([] if human else ["--json"]),
        ],
        obj={"activation_evidence_provider": env.source.evidence_provider},
    )


def _payload(result: Any) -> dict[str, Any]:
    assert result.exit_code == 0, result.output
    payload: dict[str, Any] = json.loads(result.output[result.output.index("{") :])
    return payload


def _documents(env: Environment, *, uncertain: bool = False) -> tuple[str, str]:
    source = env.root / "original.txt"
    source.write_bytes("실제 보존할 합성 설명\r\n".encode())
    metadata = env.file(
        "intake.json",
        {
            "source_kind": "description",
            "media_type": "text/plain",
            "channel": "synthetic-cli",
            "received_at": NOW,
            "extractor": "synthetic.v1",
            "extraction": {"original": "separate"},
            "proposal_scope": "agent.intake.account",
            "policy_version": "synthetic.v1",
            "proposal": {
                "change_kind": "account_fact",
                "operation": "ownership",
                "decision": _ownership(env),
            },
            "uncertainties": ["account_mapping_unknown"] if uncertain else [],
        },
    )
    return str(source), metadata


def _confirm_arguments(proposal: dict[str, Any]) -> list[str]:
    return [
        "confirm",
        proposal["proposal_id"],
        "--confirmed-at",
        NOW,
        "--expected-generation",
        proposal["expected_generation"],
        "--expected-revision",
        str(proposal["expected_revision"]),
        "--idempotency-key",
        proposal["application_key"],
    ]


def intake_catalog_outputs(tmp_path: Path) -> dict[str, dict[str, Any]]:
    """Return actual successful command payloads for the shared schema catalog test."""
    env = _environment(tmp_path)
    source, metadata = _documents(env)
    submitted = _payload(_invoke(env, ["submit", source, metadata, *env.options("submit")]))
    listing = _payload(_invoke(env, ["list"]))
    confirmed = _payload(_invoke(env, _confirm_arguments(submitted)))
    return {
        "ssot_intake_submit": submitted,
        "ssot_intake_list": listing,
        "ssot_intake_confirm": confirmed,
    }


@pytest.mark.parametrize("human", [False, True])
def test_submit_list_confirm_and_original_receipt_retry(tmp_path: Path, human: bool) -> None:
    env = _environment(tmp_path)
    source, metadata = _documents(env)
    before = env.revision()
    arguments = ["submit", source, metadata, *env.options("submit", before)]
    first = _invoke(env, arguments, human=human)
    assert first.exit_code == 0, first.output
    submitted = _payload(_invoke(env, arguments))
    assert submitted["replayed"] and submitted["committed_revision"] == before + 1
    if human:
        assert "증빙 제출" in first.output and "확정 idempotency key" in first.output
    listing = _invoke(env, ["list"], human=human)
    assert listing.exit_code == 0, listing.output
    if human:
        assert "pending" in listing.output and "agent.intake.account" in listing.output
        assert "ownership" in listing.output and "불확실성" in listing.output
    else:
        assert _payload(listing)["decisions"][0]["status"] == "pending"
    confirmation = _confirm_arguments(submitted)
    wrong_key = [*confirmation[:-1], "unrelated-application-key"]
    assert _invoke(env, wrong_key).exit_code != 0
    assert env.revision() == before + 1
    applied = _invoke(env, confirmation, human=human)
    assert applied.exit_code == 0, applied.output
    replay = _payload(_invoke(env, confirmation))
    assert replay["replayed"] and replay["committed_revision"] == before + 2
    if human:
        assert "증빙 제안 적용" in applied.output
    else:
        assert _payload(applied)["changeset_id"] == replay["changeset_id"]
    assert _payload(_invoke(env, arguments))["changeset_id"] == submitted["changeset_id"]
    with RepositoryReader(env.database) as reader:
        assert (
            len(
                [
                    row
                    for row in reader.rows("ownership_assertion_sets")
                    if row["account_id"] == env.account
                ]
            )
            == 1
        )
        assert len(reader.rows("agent_intake_applications")) == 1
    assert _payload(_invoke(env, ["list"]))["decisions"][0]["status"] == "applied"
    assert env.revision() == before + 2


@pytest.mark.parametrize("uncertain", [False, True])
def test_stale_or_uncertain_confirmation_is_rejected(tmp_path: Path, uncertain: bool) -> None:
    env = _environment(tmp_path)
    source, metadata = _documents(env, uncertain=uncertain)
    submitted = _payload(_invoke(env, ["submit", source, metadata, *env.options("first")]))
    if not uncertain:
        _payload(_invoke(env, ["submit", source, metadata, *env.options("second")]))
    revision = env.revision()
    denied = _invoke(env, _confirm_arguments(submitted))
    assert denied.exit_code != 0
    if not uncertain:
        overridden = _confirm_arguments({**submitted, "expected_revision": revision})
        assert _invoke(env, overridden).exit_code != 0
    assert env.revision() == revision
    listing = _payload(_invoke(env, ["list"]))
    decision = next(
        item for item in listing["decisions"] if item["proposal_id"] == submitted["proposal_id"]
    )
    assert decision["status"] == ("uncertain" if uncertain else "stale")
    with RepositoryReader(env.database) as reader:
        assert not [
            row
            for row in reader.rows("ownership_assertion_sets")
            if row["account_id"] == env.account
        ]
        assert not reader.rows("agent_intake_applications")


def test_explicit_identity_and_regular_source_are_required(tmp_path: Path) -> None:
    env = _environment(tmp_path)
    source, metadata = _documents(env)
    revision = env.revision()
    missing = _invoke(env, ["submit", source, metadata])
    assert missing.exit_code != 0 and "Explicit" in missing.output
    link = env.root / "source-link"
    link.symlink_to(source)
    denied = _invoke(env, ["submit", str(link), metadata, *env.options("link")])
    assert denied.exit_code != 0
    assert env.revision() == revision
