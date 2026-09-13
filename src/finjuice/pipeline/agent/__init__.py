"""Agent intake: evidence, change proposals, confirmation, and corrections.

This package is the M1 vertical slice for issue #444. Original evidence,
extraction, interpretation, confirmation, and applied changesets stay
separate records. Public names are defined in submodules and re-exported here
so monkeypatching the package still hits the same objects.
"""

from finjuice.pipeline.agent.apply import (
    amend_changeset,
    confirm_account_mapping,
    confirm_proposal,
    confirmed_account_facts,
    recurring_rules,
    withdraw_changeset,
)
from finjuice.pipeline.agent.intake import IntakeSession, import_xlsx_source, submit_intake
from finjuice.pipeline.agent.keys import (
    INTAKE_NAMESPACE,
    derived_submit_key,
    source_digest,
)
from finjuice.pipeline.agent.models import (
    CHANGE_KINDS,
    SOURCE_KINDS,
    AccountMapping,
    AmendRequest,
    ApplyReceipt,
    ChangeKindLockedError,
    ChangesetRecord,
    ConfirmRequest,
    EvidenceRecord,
    IdempotencyConflictError,
    ImpactScope,
    IntakeError,
    IntakeInput,
    IntakeReceipt,
    InterpretationDraft,
    MappingRequest,
    OperatorDecision,
    OperatorView,
    ProposalRecord,
    StaleRevisionError,
    UncertainMappingError,
    UnknownRecordError,
    WithdrawRequest,
    retained_original,
)
from finjuice.pipeline.agent.render import (
    operator_payload,
    pending_decisions,
    render_operator_view,
)

__all__ = [
    "CHANGE_KINDS",
    "INTAKE_NAMESPACE",
    "SOURCE_KINDS",
    "AccountMapping",
    "AmendRequest",
    "ApplyReceipt",
    "ChangeKindLockedError",
    "ChangesetRecord",
    "ConfirmRequest",
    "EvidenceRecord",
    "IdempotencyConflictError",
    "ImpactScope",
    "IntakeError",
    "IntakeInput",
    "IntakeReceipt",
    "IntakeSession",
    "InterpretationDraft",
    "MappingRequest",
    "OperatorDecision",
    "OperatorView",
    "ProposalRecord",
    "StaleRevisionError",
    "UncertainMappingError",
    "UnknownRecordError",
    "WithdrawRequest",
    "amend_changeset",
    "confirm_account_mapping",
    "confirm_proposal",
    "confirmed_account_facts",
    "derived_submit_key",
    "import_xlsx_source",
    "operator_payload",
    "pending_decisions",
    "recurring_rules",
    "render_operator_view",
    "retained_original",
    "source_digest",
    "submit_intake",
    "withdraw_changeset",
]
