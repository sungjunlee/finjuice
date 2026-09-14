"""Recurring-rule intake remains distinct from one-time transaction corrections."""

from typing import Any

import pytest
import test_canonical_intake_submission as intake_fixtures

from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.intake_application import confirm_intake
from finjuice.pipeline.storage.sqlite.intake_queries import intake_decision_view
from finjuice.pipeline.storage.sqlite.intake_submission import submit_intake
from finjuice.pipeline.storage.sqlite.mutations import MutationOutcome, MutationRequest
from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes

NOW = intake_fixtures.NOW
_connect = intake_fixtures._connect
_submission = intake_fixtures._submission
repository = intake_fixtures.repository


def _apply(repository: Any, decision: dict[str, Any], revision: int, key: str) -> Any:
    paths, generation, service, _, _ = repository
    submit_intake(
        service,
        _submission(
            generation,
            idempotency_key=key,
            expected_revision=revision,
            proposal_scope="agent.intake.rule",
            proposal={"change_kind": "recurring_rule", "operation": "rule", "decision": decision},
        ),
    )
    with _connect(paths, generation) as connection:
        item = next(
            row
            for row in intake_decision_view(connection)["decisions"]
            if row["expected_revision"] == revision + 1
        )
    kwargs = {
        "expected_generation": generation,
        "expected_revision": revision + 1,
        "idempotency_key": item["application_key"],
        "confirmed_at": NOW,
    }
    receipt = confirm_intake(service, item, **kwargs)
    retry = confirm_intake(service, item, **kwargs)
    assert retry.replayed and retry.changeset_id == receipt.changeset_id
    return receipt


def _rules(repository: Any, revision: int) -> Any:
    _, generation, service, _, _ = repository
    result = service.preview(
        MutationRequest("test.rules.read", "read", {}, generation, revision, "test"),
        lambda context: MutationOutcome(
            {"content": (context.read_config_bytes("rules") or b"version: 1\nrules: []\n").decode()}
        ),
    )
    return load_rules_bytes(result["content"].encode())


def test_rule_intake_applies_corrects_and_removes_only_explicit_rule(repository: Any) -> None:
    first = _apply(
        repository,
        {
            "action": "upsert",
            "rule": {
                "name": "synthetic",
                "match": "coffee",
                "fields": ["merchant_raw"],
                "tags": ["a"],
            },
        },
        0,
        "first",
    )
    assert first.committed_revision == 2
    assert _rules(repository, 2)[0].tags == ["a"]
    _apply(
        repository,
        {
            "action": "upsert",
            "rule": {
                "name": "synthetic",
                "match": "coffee",
                "fields": ["merchant_raw"],
                "tags": ["b"],
            },
        },
        2,
        "correct",
    )
    assert _rules(repository, 4)[0].tags == ["b"]
    _apply(repository, {"action": "remove", "name": "synthetic"}, 4, "remove")
    assert _rules(repository, 6) == []
    paths, generation, _, _, _ = repository
    with _connect(paths, generation) as connection:
        assert connection.execute("SELECT count(*) FROM config_revisions").fetchone()[0] == 3
        assert (
            connection.execute("SELECT count(*) FROM agent_intake_applications").fetchone()[0] == 3
        )


def test_one_time_proposal_cannot_become_a_recurring_rule(repository: Any) -> None:
    paths, generation, service, _, _ = repository
    submit_intake(
        service,
        _submission(
            generation,
            proposal={
                "change_kind": "transaction_override",
                "operation": "rule",
                "decision": {"action": "upsert", "rule": {"name": "bad", "tags": ["bad"]}},
            },
        ),
    )
    with _connect(paths, generation) as connection:
        item = intake_decision_view(connection)["decisions"][0]
    with pytest.raises(MutationValidationError, match="Unsupported"):
        confirm_intake(
            service,
            item,
            expected_generation=generation,
            expected_revision=1,
            idempotency_key=item["application_key"],
            confirmed_at=NOW,
        )
    assert _rules(repository, 1) == []
    with _connect(paths, generation) as connection:
        assert (
            connection.execute("SELECT count(*) FROM agent_intake_confirmations").fetchone()[0] == 0
        )
