"""Public authority dispatch and repository mutation facade.

Config document types and lexical YAML helpers live in
:mod:`finjuice.pipeline.storage.mutation_config` and are re-exported
here so existing callers can keep importing from this module.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    AuthorityDispatch,
    RepositoryAuthority,
    resolve_storage_authority,
)
from finjuice.pipeline.storage.mutation_config import (
    ConfigDocument,
    ConfigKind,
    ConfigMutation,
    ConfigTransformResult,
    _publish_config_mutation,
)
from finjuice.pipeline.storage.sqlite.account_bindings import AccountBindingConfirmation
from finjuice.pipeline.storage.sqlite.account_decisions import OwnershipDecision
from finjuice.pipeline.storage.sqlite.asset_meanings import AssetMeaningDecision
from finjuice.pipeline.storage.sqlite.asset_reports import AssetRelationDecision, AssetReportQuery
from finjuice.pipeline.storage.sqlite.bulk_tagging import (
    BulkTagCommand,
    apply_bulk_tagging,
    preview_bulk_tagging,
)
from finjuice.pipeline.storage.sqlite.bulk_transfer import (
    BulkTransferCommand,
    apply_bulk_transfer,
    preview_bulk_transfer,
)
from finjuice.pipeline.storage.sqlite.exact_import import (
    COMMAND_SCOPE,
    ExactImportCommand,
    ExactImportIntent,
    ExactWorkbookCapture,
)
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.mutations import (
    ConfigRevisionMutation,
    ManualTransactionEdit,
    MutationContext,
    MutationOutcome,
    MutationReceipt,
    MutationRequest,
    MutationService,
)
from finjuice.pipeline.storage.sqlite.objects import SourceObjectStore
from finjuice.pipeline.storage.sqlite.schema import inspect_repository

if TYPE_CHECKING:
    from finjuice.pipeline.close.canonical import CloseCommand, ReopenCommand
    from finjuice.pipeline.reconcile.canonical import (
        AllocationConfirmation,
        AllocationWithdrawal,
        EvidenceSubmission,
    )
    from finjuice.pipeline.statements.canonical import StatementImport
    from finjuice.pipeline.storage.sqlite.intake_lifecycle import IntakeRevision, IntakeWithdrawal

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.intake_submission import IntakeSubmission

JSONValue = Any


@dataclass(frozen=True)
class BulkMutationPreview:
    """Dry-run counts from one pinned read snapshot with no receipt or revision."""

    result: Mapping[str, JSONValue]
    dataset_revision: int


@dataclass(frozen=True)
class MutationIdentity:
    """Optional caller-supplied request identity and concurrency preconditions."""

    idempotency_key: str | None = None
    expected_generation: str | None = None
    expected_revision: int | None = None

    def validate(self) -> None:
        """Reject an explicit replay key without its original preconditions."""
        if self.idempotency_key is not None and not self.idempotency_key:
            raise ValueError("Idempotency key must be non-empty when supplied.")
        if self.expected_generation is not None and not self.expected_generation:
            raise ValueError("Expected generation must be non-empty when supplied.")
        if self.idempotency_key is not None and (
            self.expected_generation is None or self.expected_revision is None
        ):
            raise ValueError(
                "An explicit idempotency key requires expected generation and revision."
            )


@dataclass(frozen=True)
class _RequestSpec:
    command_scope: str
    payload: Mapping[str, JSONValue]
    identity: MutationIdentity
    actor: str
    reason: str | None


class StorageMutationFacade:
    """Resolve one data authority and route typed writes to its repository service."""

    def __init__(
        self,
        data_dir: Path,
        evidence_provider: ActivationEvidenceProvider | None = None,
    ) -> None:
        self._data_dir = data_dir.expanduser().absolute()
        self._evidence_provider = evidence_provider

    def dispatch(self) -> AuthorityDispatch:
        """Resolve the current authority using only independently supplied evidence."""
        return resolve_storage_authority(self._data_dir, self._evidence_provider)

    def pin_identity(self, identity: MutationIdentity) -> MutationIdentity:
        """Fill omitted preconditions from one repository snapshot before confirmation."""
        _, authority = self._repository_dispatch()
        current_revision = inspect_repository(authority.paths.database).dataset_revision
        assert current_revision is not None
        return MutationIdentity(
            idempotency_key=identity.idempotency_key,
            expected_generation=(
                authority.activation.dataset_generation
                if identity.expected_generation is None
                else identity.expected_generation
            ),
            expected_revision=(
                current_revision
                if identity.expected_revision is None
                else identity.expected_revision
            ),
        )

    def revise_intake(
        self, revision: IntakeRevision, *, identity: MutationIdentity
    ) -> MutationReceipt:
        """Append a new typed proposal and retire a pending parent in a single commit."""
        from dataclasses import asdict

        identity.validate()
        if (
            identity.idempotency_key is None
            or identity.expected_generation is None
            or identity.expected_revision is None
        ):
            raise ValueError(
                "Explicit generation, current revision and new idempotency key are required."
            )
        dispatch, authority = self._repository_dispatch()
        request = self._request(
            dispatch,
            authority,
            _RequestSpec("agent.intake.revise", asdict(revision), identity, "cli", None),
        )
        assert dispatch.evidence is not None
        return MutationService(dispatch.paths, dispatch.evidence).execute(
            request,
            lambda context: MutationOutcome(result=context.revise_intake(revision, request)),
        )

    def withdraw_intake(
        self, withdrawal: IntakeWithdrawal, *, identity: MutationIdentity
    ) -> MutationReceipt:
        """Record explicit withdrawal without undoing an applied proposal."""
        from dataclasses import asdict

        identity.validate()
        if (
            identity.idempotency_key is None
            or identity.expected_generation is None
            or identity.expected_revision is None
        ):
            raise ValueError(
                "Explicit generation, current revision and new idempotency key are required."
            )
        dispatch, authority = self._repository_dispatch()
        request = self._request(
            dispatch,
            authority,
            _RequestSpec("agent.intake.withdraw", asdict(withdrawal), identity, "cli", None),
        )
        assert dispatch.evidence is not None
        return MutationService(dispatch.paths, dispatch.evidence).execute(
            request,
            lambda context: MutationOutcome(result=context.withdraw_intake(withdrawal, request)),
        )

    def import_reconcile_evidence(
        self, command: EvidenceSubmission, *, identity: MutationIdentity
    ) -> MutationReceipt:
        """Publish purchase source evidence through the canonical audited transaction."""
        return self._execute(
            _RequestSpec("reconcile.evidence.submit", command.payload(), identity, "cli", None),
            lambda context: MutationOutcome(context.import_reconcile_evidence(command)),
        )

    def confirm_reconcile(
        self, command: AllocationConfirmation, *, identity: MutationIdentity
    ) -> MutationReceipt:
        """Explicitly reserve an N:M settlement selection without altering payments."""
        from dataclasses import asdict

        return self._execute(
            _RequestSpec("reconcile.allocation.confirm", asdict(command), identity, "cli", None),
            lambda context: MutationOutcome(context.confirm_reconcile(command)),
        )

    def withdraw_reconcile(
        self, command: AllocationWithdrawal, *, identity: MutationIdentity
    ) -> MutationReceipt:
        """Append a settlement withdrawal and retain source/manual transaction state."""
        from dataclasses import asdict

        return self._execute(
            _RequestSpec("reconcile.allocation.withdraw", asdict(command), identity, "cli", None),
            lambda context: MutationOutcome(context.withdraw_reconcile(command)),
        )

    def close_period(self, command: CloseCommand, *, identity: MutationIdentity) -> MutationReceipt:
        """Publish one immutable canonical close revision through the audited transaction."""
        from dataclasses import asdict

        return self._execute(
            _RequestSpec("close.period.close", asdict(command), identity, "cli", command.reason),
            lambda context: MutationOutcome(context.close_period(command)),
        )

    def reopen_period(
        self, command: ReopenCommand, *, identity: MutationIdentity
    ) -> MutationReceipt:
        """Append an explicit reopen decision that never rewrites a stored close revision."""
        from dataclasses import asdict

        return self._execute(
            _RequestSpec("close.period.reopen", asdict(command), identity, "cli", command.reason),
            lambda context: MutationOutcome(context.reopen_period(command)),
        )

    def import_statement(
        self, command: StatementImport, *, identity: MutationIdentity
    ) -> MutationReceipt:
        """Publish one canonical JSON statement through the audited mutation boundary."""
        return self._execute(
            _RequestSpec("statement.json.import", command.payload(), identity, "cli", None),
            lambda context: MutationOutcome(context.import_statement(command)),
        )

    def read_statement_evidence(self, *, source_identity: str | None = None) -> dict[str, Any]:
        """Read preserved statement evidence from one authority-pinned snapshot."""
        from finjuice.pipeline.storage.authority import (
            require_repository_authority,
            shared_write_lease,
        )
        from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        with shared_write_lease(dispatch.paths):
            authority = require_repository_authority(dispatch.paths, dispatch.evidence)
            with RepositoryReader(authority.paths.database) as reader:
                return reader.statement_evidence(source_identity=source_identity)

    def read_close_history(self, *, period: str | None = None) -> dict[str, Any]:
        """Read immutable close revisions from one authority-pinned repository snapshot."""
        from finjuice.pipeline.storage.authority import (
            require_repository_authority,
            shared_write_lease,
        )
        from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        with shared_write_lease(dispatch.paths):
            authority = require_repository_authority(dispatch.paths, dispatch.evidence)
            with RepositoryReader(authority.paths.database) as reader:
                return reader.close_history(period=period)

    def read_reconcile_evidence(self, *, window_days: int = 14) -> dict[str, Any]:
        """Read exact candidates under the same active-generation lease."""
        from finjuice.pipeline.storage.authority import (
            require_repository_authority,
            shared_write_lease,
        )
        from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        with shared_write_lease(dispatch.paths):
            authority = require_repository_authority(dispatch.paths, dispatch.evidence)
            with RepositoryReader(authority.paths.database) as reader:
                return reader.reconcile_evidence(window_days=window_days)

    def submit_intake(self, submission: IntakeSubmission) -> MutationReceipt:
        """Capture canonical intake evidence through its authority-bound submission service."""
        from finjuice.pipeline.storage.sqlite.intake_submission import submit_intake

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        return submit_intake(MutationService(dispatch.paths, dispatch.evidence), submission)

    def read_intake_decisions(self) -> dict[str, Any]:
        """Return detached intake evidence from one authority-bound snapshot."""
        from finjuice.pipeline.storage.authority import (
            require_repository_authority,
            shared_write_lease,
        )
        from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        with shared_write_lease(dispatch.paths):
            authority = require_repository_authority(dispatch.paths, dispatch.evidence)
            with RepositoryReader(authority.paths.database) as reader:
                return reader.intake_decisions()

    def confirm_intake(
        self, proposal_id: str, *, identity: MutationIdentity, confirmed_at: str
    ) -> MutationReceipt:
        """Apply stored proposal preconditions while preserving original receipt replay."""
        from finjuice.pipeline.storage.sqlite.intake_application import confirm_intake

        identity.validate()
        if (
            identity.expected_generation is None
            or identity.expected_revision is None
            or identity.idempotency_key is None
        ):
            raise ValueError("Intake confirmation requires explicit mutation identity.")
        decision = next(
            (
                row
                for row in self.read_intake_decisions()["decisions"]
                if row["proposal_id"] == proposal_id
            ),
            None,
        )
        if decision is None:
            raise ValueError("Unknown intake proposal.")
        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        return confirm_intake(
            MutationService(dispatch.paths, dispatch.evidence),
            decision,
            expected_generation=identity.expected_generation,
            expected_revision=identity.expected_revision,
            idempotency_key=identity.idempotency_key,
            confirmed_at=confirmed_at,
        )

    def confirm_asset_meaning(
        self, command: AssetMeaningDecision, *, identity: MutationIdentity = MutationIdentity()
    ) -> MutationReceipt:
        """Confirm/correct a source-backed interpretation without editing its source."""
        from dataclasses import asdict

        scope = (
            "asset.meaning.correct" if command.supersedes_assertion_id else "asset.meaning.confirm"
        )
        return self._execute(
            _RequestSpec(scope, asdict(command), identity, "cli", None),
            lambda context: MutationOutcome(result=context.confirm_asset_meaning(command)),
        )

    def confirm_asset_relation(
        self, command: AssetRelationDecision, *, identity: MutationIdentity = MutationIdentity()
    ) -> MutationReceipt:
        """Confirm/correct canonical source inclusion and overlap evidence."""
        from dataclasses import asdict

        scope = (
            "asset.relation.correct"
            if command.supersedes_assertion_id
            else "asset.relation.confirm"
        )
        return self._execute(
            _RequestSpec(scope, asdict(command), identity, "cli", None),
            lambda context: MutationOutcome(result=context.confirm_asset_relation(command)),
        )

    def read_canonical_assets(self, query: AssetReportQuery | None = None) -> dict[str, Any]:
        """Read exact asset meaning and ownership from one authority-bound snapshot."""
        from finjuice.pipeline.storage.authority import (
            require_repository_authority,
            shared_write_lease,
        )
        from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        with shared_write_lease(dispatch.paths):
            authority = require_repository_authority(dispatch.paths, dispatch.evidence)
            with RepositoryReader(authority.paths.database) as reader:
                return reader.canonical_assets(query)

    def confirm_account_binding(
        self,
        command: AccountBindingConfirmation,
        *,
        identity: MutationIdentity = MutationIdentity(),
    ) -> MutationReceipt:
        """Persist an operator-confirmed source binding or explicit correction."""
        from dataclasses import asdict

        scope = (
            "account.binding.correct"
            if command.supersedes_binding_id
            else "account.binding.confirm"
        )
        return self._execute(
            _RequestSpec(scope, asdict(command), identity, "cli", None),
            lambda context: MutationOutcome(result=context.confirm_account_binding(command)),
        )

    def preview_account_binding(self, command: AccountBindingConfirmation) -> BulkMutationPreview:
        """Preview exact-key impact and optimistic-concurrency identity from one snapshot."""
        from dataclasses import asdict

        return self._preview(
            _RequestSpec(
                "account.binding.preview", asdict(command), MutationIdentity(), "cli", None
            ),
            lambda context: MutationOutcome(result=context.preview_account_binding(command)),
        )

    def confirm_ownership(
        self, command: OwnershipDecision, *, identity: MutationIdentity = MutationIdentity()
    ) -> MutationReceipt:
        """Confirm or correct exact ownership through canonical audit and validation."""
        from dataclasses import asdict

        scope = (
            "account.ownership.correct"
            if command.supersedes_assertion_id
            else "account.ownership.confirm"
        )
        return self._execute(
            _RequestSpec(scope, asdict(command), identity, "cli", None),
            lambda context: MutationOutcome(result=context.confirm_ownership(command)),
        )

    def read_account_bindings(self) -> dict[str, Any]:
        """Return candidates and history under the current authority and one validated view."""
        from finjuice.pipeline.storage.authority import (
            require_repository_authority,
            shared_write_lease,
        )
        from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        with shared_write_lease(dispatch.paths):
            authority = require_repository_authority(dispatch.paths, dispatch.evidence)
            with RepositoryReader(authority.paths.database) as reader:
                return reader.account_binding_snapshot()

    def read_account_ownership(self, account_id: str, *, as_of: str) -> dict[str, Any]:
        """Read dated ownership through the same authority-bound snapshot boundary."""
        from finjuice.pipeline.storage.authority import (
            require_repository_authority,
            shared_write_lease,
        )
        from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

        dispatch, _ = self._repository_dispatch()
        assert dispatch.evidence is not None
        with shared_write_lease(dispatch.paths):
            authority = require_repository_authority(dispatch.paths, dispatch.evidence)
            with RepositoryReader(authority.paths.database) as reader:
                return reader.account_ownership(account_id, as_of=as_of)

    def edit_manual_transaction(
        self,
        edit: ManualTransactionEdit,
        *,
        identity: MutationIdentity = MutationIdentity(),
        actor: str = "cli",
        reason: str | None = None,
    ) -> MutationReceipt:
        """Apply a typed manual edit to one active repository transaction."""
        payload: dict[str, JSONValue] = {
            "identifier": edit.identifier,
            "add_tags": list(edit.add_tags),
            "remove_tags": list(edit.remove_tags),
            "category_supplied": edit.category_supplied,
            "category": edit.category,
            "note_supplied": edit.note_supplied,
            "note": edit.note,
        }
        return self._execute(
            _RequestSpec("tag.manual_edit", payload, identity, actor, reason),
            lambda context: MutationOutcome(result=context.edit_manual_transaction(edit)),
        )

    def recompute_tags(
        self,
        command: BulkTagCommand,
        *,
        identity: MutationIdentity = MutationIdentity(),
        actor: str = "cli",
        reason: str | None = None,
        dry_run: bool = False,
    ) -> MutationReceipt | BulkMutationPreview:
        """Recompute derived tags from the pinned rules head, or preview the counts."""
        spec = _RequestSpec("tag.bulk_recompute", command.payload(), identity, actor, reason)
        if dry_run:
            return self._preview(spec, _tag_preview_handler(command))
        return self._execute(spec, _tag_write_handler(command))

    def recompute_transfers(
        self,
        command: BulkTransferCommand,
        *,
        identity: MutationIdentity = MutationIdentity(),
        actor: str = "cli",
        reason: str | None = None,
        dry_run: bool = False,
    ) -> MutationReceipt | BulkMutationPreview:
        """Recompute exact transfer pairs, or preview the counts without writing."""
        spec = _RequestSpec("transfer.bulk_recompute", command.payload(), identity, actor, reason)
        if dry_run:
            return self._preview(spec, _transfer_preview_handler(command))
        return self._execute(spec, _transfer_write_handler(command))

    def import_exact_xlsx(
        self,
        command: ExactImportCommand,
        *,
        identity: MutationIdentity = MutationIdentity(),
        actor: str = "cli",
        reason: str | None = None,
    ) -> MutationReceipt | BulkMutationPreview:
        """Import one captured XLSX workbook, or preview integer domain counts."""
        spec = _RequestSpec(COMMAND_SCOPE, command.payload(), identity, actor, reason)
        if command.preview:
            return self._preview(spec, _exact_import_handler(command))
        return self._execute(spec, _exact_import_handler(command))

    def replace_config(
        self,
        document: ConfigDocument,
        *,
        identity: MutationIdentity = MutationIdentity(),
        actor: str = "cli",
        reason: str | None = None,
    ) -> MutationReceipt:
        """Publish exact config bytes and atomically select their immutable revision."""
        identity.validate()
        dispatch, authority = self._repository_dispatch()
        mutation = _publish_config_mutation(authority, document)
        payload: dict[str, JSONValue] = {
            "config_kind": document.config_kind,
            "artifact_id": mutation.artifact.artifact_id,
            "parsed_status": document.parsed_status,
            "parser_version": document.parser_version,
            "canonical_payload": document.canonical_payload,
        }
        request = self._request(
            dispatch,
            authority,
            _RequestSpec(f"config.{document.config_kind}", payload, identity, actor, reason),
        )
        assert dispatch.evidence is not None
        service = MutationService(dispatch.paths, dispatch.evidence)
        return service.execute(
            request,
            self._config_handler(mutation),
        )

    def mutate_config(
        self,
        mutation: ConfigMutation,
        *,
        identity: MutationIdentity = MutationIdentity(),
        actor: str = "cli",
        reason: str | None = None,
    ) -> MutationReceipt:
        """Apply a stable semantic edit against the config head under the writer lock."""
        dispatch, authority = self._repository_dispatch()
        spec = _config_mutation_spec(mutation, identity, actor=actor, reason=reason)
        request = self._request(dispatch, authority, spec)
        assert dispatch.evidence is not None
        return MutationService(dispatch.paths, dispatch.evidence).execute(
            request,
            self._semantic_config_handler(
                authority,
                mutation.config_kind,
                mutation.transformer,
            ),
        )

    def find_config_mutation_replay(
        self,
        mutation: ConfigMutation,
        *,
        identity: MutationIdentity,
        actor: str = "cli",
        reason: str | None = None,
    ) -> MutationReceipt | None:
        """Find an exact explicit-key config replay without evaluating current config bytes."""
        identity.validate()
        if identity.idempotency_key is None:
            return None
        dispatch, authority = self._repository_dispatch()
        request = self._request(
            dispatch,
            authority,
            _config_mutation_spec(mutation, identity, actor=actor, reason=reason),
        )
        assert dispatch.evidence is not None
        return MutationService(dispatch.paths, dispatch.evidence).find_replay(request)

    def read_config_bytes(self, config_kind: ConfigKind) -> bytes | None:
        """Read and verify the active exact config object, or return no current head."""
        _, authority = self._repository_dispatch()
        connection = _open_read_only(authority.paths.database)
        try:
            row = connection.execute(
                "SELECT artifact.source_artifact_id, artifact.byte_length "
                "FROM config_heads AS head "
                "JOIN config_revisions AS revision ON revision.entity_id = head.revision_id "
                "JOIN source_artifacts AS artifact "
                "ON artifact.source_artifact_id = revision.source_artifact_id "
                "WHERE head.config_kind = ?",
                (config_kind,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            return None
        artifact = SourceObjectStore(authority.paths).verify(str(row[0]), int(row[1]))
        return (authority.paths.root / artifact.relative_path).read_bytes()

    def read_manual_transaction(self, identifier: str) -> Mapping[str, JSONValue]:
        """Read one unambiguous transaction for manual edit preview or inspection."""
        _, authority = self._repository_dispatch()
        connection = _open_read_only(authority.paths.database)
        try:
            transaction_id = _resolve_transaction_id(connection, identifier.strip())
            row = connection.execute(
                "SELECT txn.date_raw, txn.time_raw, txn.datetime_raw, txn.type_raw, "
                "txn.type_norm, txn.major_raw, txn.minor_raw, txn.merchant_raw, txn.memo_raw, "
                "txn.notes_manual, txn.account_text, txn.counterparty, txn.category_rule, "
                "txn.category_manual, txn.category_final, txn.tags_rule_json, txn.tags_ai_json, "
                "txn.tags_manual_json, txn.tags_final_json, txn.needs_review, "
                "confidence.coefficient, confidence.scale, amount.coefficient, amount.scale, "
                "money.currency_code, txn.is_transfer_candidate, txn.is_transfer, "
                "txn.transfer_group_id FROM transactions AS txn "
                "LEFT JOIN exact_values AS confidence "
                "ON confidence.value_id = txn.confidence_value_id "
                "JOIN exact_values AS amount ON amount.value_id = txn.amount_value_id "
                "JOIN money_values AS money ON money.value_id = txn.amount_value_id "
                "WHERE txn.entity_id = ?",
                (transaction_id,),
            ).fetchone()
        finally:
            connection.close()
        if row is None:
            raise ValueError("Transaction identifier was not found.")
        confidence_exact = _exact_decimal_text(row[20], row[21])
        return {
            "transaction_id": transaction_id,
            "date": row[0],
            "time": row[1],
            "datetime": row[2],
            "type_raw": row[3],
            "type_norm": row[4],
            "major_raw": row[5],
            "minor_raw": row[6],
            "merchant_raw": row[7],
            "memo_raw": row[8],
            "notes_manual": row[9],
            "account": row[10],
            "counterparty": row[11],
            "category_rule": row[12],
            "category_manual": row[13],
            "category_final": row[14],
            "tags_rule": _string_array(row[15]),
            "tags_ai": _string_array(row[16]),
            "tags_manual": _string_array(row[17]),
            "tags_final": _string_array(row[18]),
            "needs_review": None if row[19] is None else bool(row[19]),
            "confidence_exact": confidence_exact,
            "amount_exact": _exact_decimal_text(row[22], row[23]),
            "currency": row[24],
            "is_transfer_candidate": None if row[25] is None else bool(row[25]),
            "is_transfer": None if row[26] is None else bool(row[26]),
            "transfer_group_id": row[27],
        }

    def _execute(
        self,
        spec: _RequestSpec,
        handler: Callable[[Any], MutationOutcome],
    ) -> MutationReceipt:
        dispatch, authority = self._repository_dispatch()
        request = self._request(dispatch, authority, spec)
        assert dispatch.evidence is not None
        return MutationService(dispatch.paths, dispatch.evidence).execute(request, handler)

    def _preview(
        self,
        spec: _RequestSpec,
        handler: Callable[[MutationContext], MutationOutcome],
    ) -> BulkMutationPreview:
        dispatch, authority = self._repository_dispatch()
        request = self._request(dispatch, authority, spec)
        assert dispatch.evidence is not None
        result = MutationService(dispatch.paths, dispatch.evidence).preview(request, handler)
        return BulkMutationPreview(result=result, dataset_revision=request.expected_revision)

    def _repository_dispatch(self) -> tuple[AuthorityDispatch, RepositoryAuthority]:
        dispatch = self.dispatch()
        if not isinstance(dispatch.authority, RepositoryAuthority):
            raise ValueError("Repository mutation requires an active SQLite authority.")
        return dispatch, dispatch.authority

    @staticmethod
    def _request(
        dispatch: AuthorityDispatch,
        authority: RepositoryAuthority,
        spec: _RequestSpec,
    ) -> MutationRequest:
        spec.identity.validate()
        current_revision = inspect_repository(authority.paths.database).dataset_revision
        assert current_revision is not None
        return MutationRequest(
            command_scope=spec.command_scope,
            idempotency_key=(
                new_entity_id()
                if spec.identity.idempotency_key is None
                else spec.identity.idempotency_key
            ),
            payload=spec.payload,
            expected_generation=(
                authority.activation.dataset_generation
                if spec.identity.expected_generation is None
                else spec.identity.expected_generation
            ),
            expected_revision=(
                current_revision
                if spec.identity.expected_revision is None
                else spec.identity.expected_revision
            ),
            actor=spec.actor,
            reason=spec.reason,
        )

    @staticmethod
    def _config_handler(
        mutation: ConfigRevisionMutation,
    ) -> Callable[[Any], MutationOutcome]:
        def apply(context: Any) -> MutationOutcome:
            changed = context.replace_config(mutation)
            revision_id = mutation.revision.revision_id
            if not changed:
                current_revision_id = context.config_head_revision_id(mutation.revision.config_kind)
                if current_revision_id is None:
                    raise RuntimeError("Config no-op has no selected revision.")
                revision_id = current_revision_id
            return MutationOutcome(
                result={
                    "config_kind": mutation.revision.config_kind,
                    "changed": changed,
                    "artifact_id": mutation.artifact.artifact_id,
                    "revision_id": revision_id,
                },
                retained_artifacts=(mutation.artifact.artifact_id,),
            )

        return apply

    @staticmethod
    def _semantic_config_handler(
        authority: RepositoryAuthority,
        config_kind: ConfigKind,
        transformer: Callable[[bytes | None], ConfigTransformResult],
    ) -> Callable[[MutationContext], MutationOutcome]:
        def apply(context: MutationContext) -> MutationOutcome:
            transformed = transformer(context.read_config_bytes(config_kind))
            if transformed.document.config_kind != config_kind:
                raise ValueError("Config transformer returned the wrong config kind.")
            mutation = _publish_config_mutation(authority, transformed.document)
            changed = context.replace_config(mutation)
            revision_id = mutation.revision.revision_id
            if not changed:
                current_revision_id = context.config_head_revision_id(config_kind)
                if current_revision_id is None:
                    raise RuntimeError("Config no-op has no selected revision.")
                revision_id = current_revision_id
            result = {
                **transformed.result,
                "config_kind": config_kind,
                "changed": changed,
                "artifact_id": mutation.artifact.artifact_id,
                "revision_id": revision_id,
            }
            return MutationOutcome(
                result=result,
                retained_artifacts=(mutation.artifact.artifact_id,),
            )

        return apply


def _tag_write_handler(
    command: BulkTagCommand,
) -> Callable[[MutationContext], MutationOutcome]:
    def apply(context: MutationContext) -> MutationOutcome:
        return MutationOutcome(result=apply_bulk_tagging(context, command))

    return apply


def _tag_preview_handler(
    command: BulkTagCommand,
) -> Callable[[MutationContext], MutationOutcome]:
    def apply(context: MutationContext) -> MutationOutcome:
        return MutationOutcome(result=preview_bulk_tagging(context, command))

    return apply


def _transfer_write_handler(
    command: BulkTransferCommand,
) -> Callable[[MutationContext], MutationOutcome]:
    def apply(context: MutationContext) -> MutationOutcome:
        return MutationOutcome(result=apply_bulk_transfer(context, command))

    return apply


def _transfer_preview_handler(
    command: BulkTransferCommand,
) -> Callable[[MutationContext], MutationOutcome]:
    def apply(context: MutationContext) -> MutationOutcome:
        return MutationOutcome(result=preview_bulk_transfer(context, command))

    return apply


def _exact_import_handler(
    command: ExactImportCommand,
) -> Callable[[MutationContext], MutationOutcome]:
    from finjuice.pipeline.storage.sqlite.exact_import.handler import apply_exact_import

    def apply(context: MutationContext) -> MutationOutcome:
        return apply_exact_import(context, command)

    return apply


def _config_mutation_spec(
    mutation: ConfigMutation,
    identity: MutationIdentity,
    *,
    actor: str,
    reason: str | None,
) -> _RequestSpec:
    """Build the request fields shared by replay lookup and config mutation."""
    return _RequestSpec(
        f"config.{mutation.config_kind}.semantic",
        {
            "config_kind": mutation.config_kind,
            "operation": mutation.semantic_payload,
        },
        identity,
        actor,
        reason,
    )


def _open_read_only(database: Path) -> sqlite3.Connection:
    database_uri = f"{database.resolve().as_uri()}?mode=ro"
    return sqlite3.connect(database_uri, uri=True)


def _resolve_transaction_id(connection: sqlite3.Connection, identifier: str) -> str:
    direct = connection.execute(
        "SELECT entity_id FROM transactions WHERE entity_id = ?", (identifier,)
    ).fetchone()
    if direct is not None:
        return str(direct[0])
    rows = connection.execute(
        "SELECT DISTINCT mapping.entity_id FROM legacy_identifiers AS mapping "
        "LEFT JOIN legacy_identifier_supersessions AS supersession "
        "ON supersession.previous_mapping_id = mapping.mapping_id "
        "JOIN transactions AS txn ON txn.entity_id = mapping.entity_id "
        "WHERE mapping.identifier_kind = 'row_hash' AND mapping.identifier_value = ? "
        "AND supersession.previous_mapping_id IS NULL ORDER BY mapping.entity_id",
        (identifier,),
    ).fetchall()
    if not rows:
        raise ValueError("Transaction identifier was not found.")
    if len(rows) != 1:
        raise ValueError(
            "Legacy row_hash identifies multiple transactions; use a stable transaction ID."
        )
    return str(rows[0][0])


def _string_array(value: object) -> list[str]:
    parsed = json.loads(str(value))
    if not isinstance(parsed, list) or any(not isinstance(item, str) for item in parsed):
        raise ValueError("Stored transaction tags are invalid.")
    return parsed


def _exact_decimal_text(coefficient: object, scale: object) -> str | None:
    if coefficient is None or scale is None:
        return None
    digits = str(coefficient)
    decimal_places = int(str(scale))
    if decimal_places == 0:
        return digits
    negative = digits.startswith("-")
    unsigned = digits[1:] if negative else digits
    padded = unsigned.zfill(decimal_places + 1)
    rendered = f"{padded[:-decimal_places]}.{padded[-decimal_places:]}"
    return f"-{rendered}" if negative else rendered


__all__ = [
    "BulkMutationPreview",
    "BulkTagCommand",
    "BulkTransferCommand",
    "ConfigDocument",
    "ConfigTransformResult",
    "ExactImportCommand",
    "ExactImportIntent",
    "ExactWorkbookCapture",
    "MutationIdentity",
    "StorageMutationFacade",
]
