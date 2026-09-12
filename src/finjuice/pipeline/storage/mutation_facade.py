"""Public authority dispatch and repository mutation facade."""

from __future__ import annotations

import io
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from finjuice.pipeline.storage.authority import (
    ActivationEvidenceProvider,
    AuthorityDispatch,
    RepositoryAuthority,
    resolve_storage_authority,
)
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
from finjuice.pipeline.storage.sqlite.records import (
    ConfigRevisionRecord,
    SourceOccurrenceRecord,
)
from finjuice.pipeline.storage.sqlite.schema import inspect_repository

JSONValue = Any
ConfigKind = Literal["rules", "goals", "assets", "scenarios", "schema", "other"]
ParsedStatus = Literal["parsed", "invalid", "opaque"]

_YAML_SCALAR_TAGS = (
    "tag:yaml.org,2002:null",
    "tag:yaml.org,2002:bool",
    "tag:yaml.org,2002:int",
    "tag:yaml.org,2002:float",
    "tag:yaml.org,2002:binary",
    "tag:yaml.org,2002:timestamp",
    "tag:yaml.org,2002:str",
)


def _construct_lexical_scalar(loader: yaml.SafeLoader, node: yaml.ScalarNode) -> str:
    """Construct a permitted scalar as its source text."""
    return loader.construct_scalar(node)


class _LexicalSafeLoader(yaml.SafeLoader):
    """Safe YAML loader that leaves implicit scalar values as source text."""

    yaml_implicit_resolvers = yaml.BaseLoader.yaml_implicit_resolvers.copy()


for _scalar_tag in _YAML_SCALAR_TAGS:
    _LexicalSafeLoader.add_constructor(_scalar_tag, _construct_lexical_scalar)


def _load_lexical_yaml(content: bytes) -> JSONValue:
    """Parse YAML without executing application-specific object constructors."""
    loader = _LexicalSafeLoader(content)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


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
class ConfigDocument:
    """Exact config bytes plus their deterministic parser interpretation."""

    config_kind: ConfigKind
    content: bytes
    parsed_status: ParsedStatus
    canonical_payload: Mapping[str, JSONValue] | list[JSONValue] | None
    parser_version: str | None

    @classmethod
    def from_validated_yaml(
        cls,
        config_kind: ConfigKind,
        content: bytes,
        *,
        parser_version: str,
    ) -> ConfigDocument:
        """Build parsed config metadata without losing numeric lexical text."""
        try:
            canonical_payload = _load_lexical_yaml(content)
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("Validated YAML bytes could not be parsed canonically.") from exc
        if canonical_payload is not None and not isinstance(canonical_payload, (Mapping, list)):
            raise ValueError("A canonical config document must be a mapping or list.")
        return cls(
            config_kind=config_kind,
            content=content,
            parsed_status="parsed",
            canonical_payload=canonical_payload,
            parser_version=parser_version,
        )


@dataclass(frozen=True)
class ConfigTransformResult:
    """One semantic config transformation and its stable command result."""

    document: ConfigDocument
    result: Mapping[str, JSONValue]


@dataclass(frozen=True)
class ConfigMutation:
    """Stable semantic config intent plus its lock-scoped transformer."""

    config_kind: ConfigKind
    semantic_payload: Mapping[str, JSONValue]
    transformer: Callable[[bytes | None], ConfigTransformResult]


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _publish_config_mutation(
    authority: RepositoryAuthority,
    document: ConfigDocument,
) -> ConfigRevisionMutation:
    artifact = SourceObjectStore(authority.paths).publish(io.BytesIO(document.content))
    created_at = _now()
    occurrence_id = new_entity_id()
    return ConfigRevisionMutation(
        revision=ConfigRevisionRecord(
            revision_id=new_entity_id(),
            config_kind=document.config_kind,
            artifact_id=artifact.artifact_id,
            occurrence_id=occurrence_id,
            parsed_status=document.parsed_status,
            parser_version=document.parser_version,
            canonical_payload=document.canonical_payload,
        ),
        occurrence=SourceOccurrenceRecord(
            occurrence_id=occurrence_id,
            artifact_id=artifact.artifact_id,
            occurrence_kind="config_revision",
            original_filename=f"{document.config_kind}.yaml",
            imported_at=created_at,
            parser_version=document.parser_version,
            source_schema_version=None,
            legacy_path=None,
        ),
        artifact=artifact,
        updated_at=created_at,
    )


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
