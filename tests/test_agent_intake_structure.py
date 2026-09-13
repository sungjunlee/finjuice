"""Structure and acceptance tests for agent intake (#444).

Public names live in ``finjuice.pipeline.agent`` as re-exports of the
definition modules. Behavioral tests cover the M1 confirmation slice:
idempotent resubmit, pension facts surviving XLSX import, one-time vs
recurring change kinds, original/source preservation, and operator JSON.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from finjuice.pipeline.agent import (
    CHANGE_KINDS,
    AccountMapping,
    AmendRequest,
    ChangeKindLockedError,
    ConfirmRequest,
    IdempotencyConflictError,
    ImpactScope,
    IntakeError,
    IntakeInput,
    IntakeSession,
    InterpretationDraft,
    MappingRequest,
    StaleRevisionError,
    UncertainMappingError,
    UnknownRecordError,
    WithdrawRequest,
    operator_payload,
    render_operator_view,
    source_digest,
)
from finjuice.pipeline.agent.models import (
    stored_changeset_status,
    stored_int,
    stored_text,
)

AGENT_DIR = Path("src/finjuice/pipeline/agent")
PACKAGE = "finjuice.pipeline.agent"
INTAKE_MODULE = "finjuice.pipeline.agent.intake"
APPLY_MODULE = "finjuice.pipeline.agent.apply"
KEYS_MODULE = "finjuice.pipeline.agent.keys"
MODELS_MODULE = "finjuice.pipeline.agent.models"
RENDER_MODULE = "finjuice.pipeline.agent.render"

INTAKE_NAMES = ("IntakeSession", "submit_intake", "import_xlsx_source")
APPLY_NAMES = (
    "confirm_proposal",
    "confirm_account_mapping",
    "withdraw_changeset",
    "amend_changeset",
    "confirmed_account_facts",
    "recurring_rules",
)
KEYS_NAMES = ("source_digest", "derived_submit_key")
RENDER_NAMES = ("operator_payload", "pending_decisions", "render_operator_view")
MODEL_NAMES = (
    "IntakeInput",
    "InterpretationDraft",
    "AccountMapping",
    "ImpactScope",
    "ConfirmRequest",
    "IntakeError",
)


def test_agent_package_reexports_definition_identity() -> None:
    """Public package names stay identity-equal to their definition modules."""
    package = importlib.import_module(PACKAGE)
    intake = importlib.import_module(INTAKE_MODULE)
    apply_mod = importlib.import_module(APPLY_MODULE)
    keys = importlib.import_module(KEYS_MODULE)
    render = importlib.import_module(RENDER_MODULE)
    models = importlib.import_module(MODELS_MODULE)

    for name in INTAKE_NAMES:
        assert getattr(package, name) is getattr(intake, name)
    for name in APPLY_NAMES:
        assert getattr(package, name) is getattr(apply_mod, name)
    for name in KEYS_NAMES:
        assert getattr(package, name) is getattr(keys, name)
    for name in RENDER_NAMES:
        assert getattr(package, name) is getattr(render, name)
    for name in MODEL_NAMES:
        assert getattr(package, name) is getattr(models, name)


def test_definition_modules_are_the_unique_home_for_public_names() -> None:
    """Moved names are defined once, at the definition site."""
    package = importlib.import_module(PACKAGE)
    for name in INTAKE_NAMES:
        assert getattr(package, name).__module__ == INTAKE_MODULE
    for name in APPLY_NAMES:
        assert getattr(package, name).__module__ == APPLY_MODULE
    for name in KEYS_NAMES:
        assert getattr(package, name).__module__ == KEYS_MODULE
    for name in RENDER_NAMES:
        assert getattr(package, name).__module__ == RENDER_MODULE
    for name in MODEL_NAMES:
        assert getattr(package, name).__module__ == MODELS_MODULE


def test_cluster_lives_in_definition_modules() -> None:
    """Parent package re-exports helpers and does not define them."""
    init_text = (AGENT_DIR / "__init__.py").read_text(encoding="utf-8")
    intake_text = (AGENT_DIR / "intake.py").read_text(encoding="utf-8")
    apply_text = (AGENT_DIR / "apply.py").read_text(encoding="utf-8")
    render_text = (AGENT_DIR / "render.py").read_text(encoding="utf-8")
    keys_text = (AGENT_DIR / "keys.py").read_text(encoding="utf-8")

    assert "def submit_intake" in intake_text
    assert "def submit_intake" not in init_text
    assert "submit_intake" in init_text
    assert "def confirm_proposal" in apply_text
    assert "def confirm_proposal" not in init_text
    assert "def operator_payload" in render_text
    assert "def source_digest" in keys_text
    assert "from finjuice.pipeline.agent import" not in intake_text
    assert "from finjuice.pipeline.agent import" not in apply_text
    assert "from finjuice.pipeline.agent import" not in render_text
    assert "from finjuice.pipeline.agent import" not in keys_text


def test_same_screenshot_and_description_do_not_duplicate_records() -> None:
    """Resending the same image/description reuses one evidence/proposal lineage."""
    session = IntakeSession()
    payload = _screenshot_input()
    first = session.submit(payload)
    second = session.submit(payload)
    retry = session.submit(payload, idempotency_key=first.idempotency_key)

    assert first.evidence_id == second.evidence_id == retry.evidence_id
    assert first.proposal_id == second.proposal_id
    assert second.replayed is True
    assert retry.replayed is True
    assert len(session.store.evidence) == 1
    assert len(session.store.proposals) == 1
    assert len(session.store.extractions) == 1


def test_tool_retry_with_different_payload_conflicts() -> None:
    """The same idempotency key cannot bind two different submit payloads."""
    session = IntakeSession()
    first = session.submit(_screenshot_input(), idempotency_key="retry-1")
    other = _screenshot_input(extracted={"account_kind": "pension", "label": "other"})
    with pytest.raises(IdempotencyConflictError):
        session.submit(other, idempotency_key=first.idempotency_key)
    assert len(session.store.evidence) == 1


def test_confirmed_pension_fact_survives_xlsx_import() -> None:
    """Screenshot-confirmed pension account facts remain after a later XLSX import."""
    session = IntakeSession()
    shot = session.submit(_screenshot_input())
    session.confirm_mapping(
        MappingRequest(proposal_id=shot.proposal_id, account_id="acct-irp", account_kind="pension")
    )
    confirmed = session.confirm(
        ConfirmRequest(proposal_id=shot.proposal_id, expected_revision=session.revision)
    )
    assert confirmed.status == "confirmed"
    facts = session.confirmed_account_facts()
    assert len(facts) == 1
    assert facts[0].mapping.account_kind == "pension"
    assert facts[0].mapping.candidate_account_id == "acct-irp"

    imported = session.import_xlsx(_xlsx_input())
    assert imported.evidence_id != shot.evidence_id
    facts_after = session.confirmed_account_facts()
    assert [item.changeset_id for item in facts_after] == [facts[0].changeset_id]
    assert facts_after[0].mapping.account_kind == "pension"
    assert session.store.evidence[shot.evidence_id].original_description == (
        "synthetic pension screenshot"
    )


def test_one_time_override_is_not_a_recurring_rule_and_can_be_amended() -> None:
    """One-time overrides stay distinct, tracked, amendable, and withdrawable."""
    session = IntakeSession()
    with pytest.raises(ChangeKindLockedError):
        session.submit(_override_input(applies_recurring=True))

    receipt = session.submit(_override_input())
    applied = session.confirm(
        ConfirmRequest(proposal_id=receipt.proposal_id, expected_revision=session.revision)
    )
    assert session.recurring_rules() == ()
    assert session.store.changesets[applied.changeset_id].change_kind == "transaction_override"
    assert "recurring_rule" in CHANGE_KINDS

    amended = session.amend(
        AmendRequest(
            changeset_id=applied.changeset_id,
            expected_revision=session.revision,
            target_id="tx-synthetic-1",
        )
    )
    assert amended.status == "amended"
    assert session.store.changesets[applied.changeset_id].status == "amended"
    successor = session.store.changesets[amended.changeset_id]
    assert successor.change_kind == "transaction_override"
    assert successor.supersedes_changeset_id == applied.changeset_id

    withdrawn = session.withdraw(
        WithdrawRequest(changeset_id=amended.changeset_id, expected_revision=session.revision)
    )
    assert withdrawn.status == "withdrawn"
    assert session.store.changesets[amended.changeset_id].status == "withdrawn"
    assert session.recurring_rules() == ()


def test_uncertain_mapping_and_stale_proposal_are_visible_before_confirm() -> None:
    """Originals are preserved; uncertain mappings and stale proposals block confirm."""
    session = IntakeSession()
    uncertain = session.submit(_screenshot_input())
    evidence = session.store.evidence[uncertain.evidence_id]
    assert evidence.source_digest == source_digest(_screenshot_input())
    assert evidence.original_description == "synthetic pension screenshot"

    with pytest.raises(UncertainMappingError):
        session.confirm(
            ConfirmRequest(proposal_id=uncertain.proposal_id, expected_revision=session.revision)
        )
    view = session.operator_view()
    assert view.payload["decisions"][0]["kind"] == "uncertain_account_mapping"
    assert "synthetic pension screenshot" not in view.human
    assert evidence.original_description not in str(view.payload)

    session.confirm_mapping(
        MappingRequest(proposal_id=uncertain.proposal_id, account_id="acct-irp")
    )
    ready = session.submit(_override_input())
    session.confirm(ConfirmRequest(proposal_id=ready.proposal_id, expected_revision=0))
    stale_view = session.operator_view()
    kinds = [item["kind"] for item in stale_view.payload["decisions"]]
    assert kinds == ["stale_proposal"]
    with pytest.raises(StaleRevisionError):
        session.confirm(ConfirmRequest(proposal_id=uncertain.proposal_id, expected_revision=0))


def test_operator_human_and_json_list_only_pending_decisions() -> None:
    """Hermes/CLI JSON and human output ask only for decisions that are still open."""
    session = IntakeSession()
    first = session.submit(_override_input())
    applied = session.confirm(
        ConfirmRequest(
            proposal_id=first.proposal_id,
            expected_revision=0,
            idempotency_key="confirm-override",
        )
    )
    replay = session.confirm(
        ConfirmRequest(
            proposal_id=first.proposal_id,
            expected_revision=0,
            idempotency_key="confirm-override",
        )
    )
    assert replay.replayed is True
    assert replay.changeset_id == applied.changeset_id

    pending = session.submit(_screenshot_input())
    payload = operator_payload(session.store)
    human = render_operator_view(payload)
    assert payload["command"] == "agent.intake"
    assert payload["pending_decision_count"] == 1
    assert payload["decisions"][0]["proposal_id"] == pending.proposal_id
    assert payload["applied_changeset_count"] == 1
    assert all(item["proposal_id"] != first.proposal_id for item in payload["decisions"])
    assert "대기 중인 결정: 1" in human
    assert "계좌 매핑을 확정하세요" in human
    assert "synthetic one-time memo fix" not in human


def test_certain_pending_proposal_is_awaiting_confirmation() -> None:
    """A mapped, current proposal asks only for confirm or withdraw."""
    session = IntakeSession()
    receipt = session.submit(_override_input())
    view = session.operator_view()
    assert view.payload["decisions"][0]["kind"] == "awaiting_confirmation"
    assert view.payload["decisions"][0]["proposal_id"] == receipt.proposal_id
    assert "확정하거나 철회하세요" in view.human
    """Confirmed work does not remain as an operator decision."""
    session = IntakeSession()
    receipt = session.submit(_override_input())
    session.confirm(ConfirmRequest(proposal_id=receipt.proposal_id, expected_revision=0))
    payload = operator_payload(session.store)
    human = render_operator_view(payload)
    assert payload["pending_decision_count"] == 0
    assert payload["decisions"] == []
    assert "필요한 운영 결정이 없습니다." in human


def test_submit_rejects_invalid_sources_and_unknown_records() -> None:
    """Invalid sources and missing records fail without writing a changeset."""
    session = IntakeSession()
    with pytest.raises(IntakeError):
        session.submit(
            IntakeInput(source_kind="screenshot", interpretation=_certain_account_fact())
        )
    with pytest.raises(IntakeError):
        session.submit(IntakeInput(source_kind="description"))
    with pytest.raises(IntakeError):
        session.submit(IntakeInput(source_kind="xlsx", interpretation=_certain_account_fact()))
    with pytest.raises(IntakeError):
        session.import_xlsx(_screenshot_input())
    with pytest.raises(UnknownRecordError):
        session.confirm(ConfirmRequest(proposal_id="missing", expected_revision=0))
    with pytest.raises(UnknownRecordError):
        session.withdraw(WithdrawRequest(changeset_id="missing", expected_revision=0))


def test_recurring_rule_stays_separate_from_account_facts() -> None:
    """Recurring rules are confirmed as their own change kind."""
    session = IntakeSession()
    with pytest.raises(ChangeKindLockedError):
        session.submit(
            IntakeInput(
                source_kind="description",
                description="synthetic account fact",
                interpretation=InterpretationDraft(
                    change_kind="account_fact",
                    impact=ImpactScope(applies_recurring=True),
                ),
            )
        )
    receipt = session.submit(
        IntakeInput(
            source_kind="description",
            description="synthetic recurring rule",
            interpretation=InterpretationDraft(
                change_kind="recurring_rule",
                account_mapping=AccountMapping(status="certain", candidate_account_id="acct-card"),
                impact=ImpactScope(applies_recurring=True),
            ),
        )
    )
    session.confirm(ConfirmRequest(proposal_id=receipt.proposal_id, expected_revision=0))
    rules = session.recurring_rules()
    assert len(rules) == 1
    assert rules[0].change_kind == "recurring_rule"
    assert session.confirmed_account_facts() == ()


def test_amend_and_withdraw_retries_replay_without_duplicate_changesets() -> None:
    """Tool retries of amend/withdraw return the original receipt."""
    session = IntakeSession()
    receipt = session.submit(_override_input())
    applied = session.confirm(ConfirmRequest(proposal_id=receipt.proposal_id, expected_revision=0))
    amended = session.amend(
        AmendRequest(
            changeset_id=applied.changeset_id,
            expected_revision=session.revision,
            idempotency_key="amend-1",
        )
    )
    replay_amend = session.amend(
        AmendRequest(
            changeset_id=applied.changeset_id,
            expected_revision=0,
            idempotency_key="amend-1",
        )
    )
    assert replay_amend.replayed is True
    assert replay_amend.changeset_id == amended.changeset_id
    withdrawn = session.withdraw(
        WithdrawRequest(
            changeset_id=amended.changeset_id,
            expected_revision=session.revision,
            idempotency_key="withdraw-1",
        )
    )
    replay_withdraw = session.withdraw(
        WithdrawRequest(
            changeset_id=amended.changeset_id,
            expected_revision=0,
            idempotency_key="withdraw-1",
        )
    )
    assert replay_withdraw.replayed is True
    assert replay_withdraw.changeset_id == withdrawn.changeset_id
    assert len(session.store.changesets) == 2


def test_stored_receipt_helpers_reject_invalid_values() -> None:
    """Corrupt idempotency receipts fail closed instead of coercing types."""
    with pytest.raises(IntakeError):
        stored_text({"k": 1}, "k")
    with pytest.raises(IntakeError):
        stored_int({"k": "1"}, "k")
    with pytest.raises(IntakeError):
        stored_int({"k": True}, "k")
    with pytest.raises(IntakeError):
        stored_changeset_status({"status": "pending"})
    assert stored_text({"k": "ok"}, "k") == "ok"
    assert stored_int({"k": 3}, "k") == 3
    assert stored_changeset_status({"status": "confirmed"}) == "confirmed"
    assert stored_changeset_status({"status": "withdrawn"}) == "withdrawn"
    assert stored_changeset_status({"status": "amended"}) == "amended"


def test_confirmed_lineage_rejects_a_different_extraction() -> None:
    """A confirmed screenshot lineage cannot be replaced by a later extraction."""
    session = IntakeSession()
    receipt = session.submit(_screenshot_input())
    session.confirm_mapping(MappingRequest(proposal_id=receipt.proposal_id, account_id="acct-irp"))
    session.confirm(ConfirmRequest(proposal_id=receipt.proposal_id, expected_revision=0))
    with pytest.raises(IdempotencyConflictError):
        session.submit(_screenshot_input(extracted={"account_kind": "pension", "label": "new"}))
    same = session.submit(_screenshot_input())
    assert same.evidence_id == receipt.evidence_id
    assert same.proposal_id == receipt.proposal_id


def _screenshot_input(*, extracted: dict[str, str] | None = None) -> IntakeInput:
    return IntakeInput(
        source_kind="screenshot",
        image_bytes=b"synthetic-irp-screenshot",
        description="synthetic pension screenshot",
        extracted=extracted or {"account_kind": "pension", "label": "irp"},
        interpretation=InterpretationDraft(
            change_kind="account_fact",
            account_mapping=AccountMapping(
                status="uncertain",
                account_kind="pension",
                label="irp",
            ),
        ),
    )


def _xlsx_input() -> IntakeInput:
    return IntakeInput(
        source_kind="xlsx",
        xlsx_bytes=b"synthetic-banksalad-xlsx",
        extracted={"account_kind": "checking"},
        interpretation=InterpretationDraft(
            change_kind="account_fact",
            account_mapping=AccountMapping(status="uncertain", account_kind="checking"),
        ),
    )


def _override_input(*, applies_recurring: bool = False) -> IntakeInput:
    return IntakeInput(
        source_kind="description",
        description="synthetic one-time memo fix",
        interpretation=InterpretationDraft(
            change_kind="transaction_override",
            account_mapping=AccountMapping(
                status="certain",
                candidate_account_id="acct-card",
            ),
            impact=ImpactScope(
                transaction_ids=("tx-synthetic-1",),
                applies_recurring=applies_recurring,
            ),
            target_id="tx-synthetic-1",
        ),
    )


def _certain_account_fact() -> InterpretationDraft:
    return InterpretationDraft(
        change_kind="account_fact",
        account_mapping=AccountMapping(status="certain", candidate_account_id="acct-1"),
    )
