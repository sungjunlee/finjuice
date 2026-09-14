"""Synthetic tests for SQLite bulk tagging and exact transfer domain adapters."""

from __future__ import annotations

import io
import json
import sqlite3
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.storage.authority import (
    ActivationEvidence,
    AuthorityDispatch,
    AuthorityPaths,
    require_repository_authority,
)
from finjuice.pipeline.storage.mutation_facade import (
    BulkMutationPreview,
    BulkTagCommand,
    BulkTransferCommand,
    ConfigDocument,
    MutationIdentity,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.sqlite import (
    AccountRecord,
    ExactValue,
    LegacyIdentifierRecord,
    MutationConflictError,
    MutationValidationError,
    ObservationRecord,
    ProvenanceRecord,
    RepositoryBuilder,
    SourceOccurrenceRecord,
    TransactionRecord,
    TransactionSourceLinkRecord,
    new_entity_id,
)
from finjuice.pipeline.storage.sqlite import mutations as mutations_mod
from finjuice.pipeline.storage.sqlite import schema as schema_module
from finjuice.pipeline.storage.sqlite.bulk_tagging import tagging_derived_state
from finjuice.pipeline.storage.sqlite.exact import UNKNOWN_CURRENCY
from finjuice.pipeline.storage.sqlite.mutations import (
    MutationContext,
    MutationOutcome,
    MutationReceipt,
    MutationRequest,
    MutationService,
)

_NOW = "2026-09-09T00:00:00Z"
_HUGE = str(2**53 + 1)
_TINY = "1e-40"
_RULES = (
    b"version: 1\n"
    b"rules:\n"
    b"  - name: cafe-high\n"
    b"    match: cafe\n"
    b"    fields: [merchant_raw]\n"
    b"    tags: [food]\n"
    b"    category: Food\n"
    b"    priority: 90\n"
    b"  - name: cafe-low\n"
    b"    match: cafe\n"
    b"    fields: [merchant_raw]\n"
    b"    tags: [cafe]\n"
    b"    category: Dining\n"
    b"    priority: 10\n"
    b"  - name: disabled\n"
    b"    match: cafe\n"
    b"    fields: [merchant_raw]\n"
    b"    tags: [disabled]\n"
    b"    category: Hidden\n"
    b"    priority: 100\n"
    b"    enabled: false\n"
    b"  - name: huge\n"
    b"    conditions:\n"
    b"      - field: amount\n"
    b"        op: greater_than\n"
    b"        value: 9007199254740992\n"
    b"    tags: [huge]\n"
    b"    priority: 70\n"
    b"  - name: tiny\n"
    b"    conditions:\n"
    b"      - field: amount\n"
    b"        op: less_than\n"
    b"        value: 1e-20\n"
    b"    tags: [tiny]\n"
    b"    priority: 70\n"
)


@dataclass(frozen=True)
class _Txn:
    name: str
    amount: str
    currency: str | object = "KRW"
    merchant: str = "other"
    major: str = "Living"
    category_manual: str | None = None
    tags_manual: str = "[]"
    tags_ai: str = "[]"
    row_hash: str = ""
    timezone_state: str = "unknown"
    observed_at: str | None = None
    effective_at: str | None = "2026-09-01"
    datetime_raw: str = "2026-09-01T12:00:00"
    is_transfer: bool | None = None
    transfer_group_id: str | None = None
    type_norm: str = "expense"
    type_raw: str | None = None


@dataclass
class _Seeded:
    paths: AuthorityPaths
    evidence: ActivationEvidence
    generation: str
    database: Path
    facade: StorageMutationFacade
    ids: dict[str, str]
    meta: dict[str, dict[str, str]] = field(default_factory=dict)

    def identity(self, key: str, revision: int) -> MutationIdentity:
        return MutationIdentity(
            idempotency_key=key,
            expected_generation=self.generation,
            expected_revision=revision,
        )

    def revision(self) -> int:
        return int(_query(self.database, "SELECT dataset_revision FROM repository_meta")[0][0])


def _evidence() -> ActivationEvidence:
    return ActivationEvidence(
        installed_release_version="0.7.3",
        installed_release_artifact_sha256="a" * 64,
        verified_migration_manifest_sha256="b" * 64,
        verified_pre_cutover_backup_manifest_sha256="c" * 64,
    )


def _write_activation(paths: AuthorityPaths, generation: str) -> None:
    paths.control_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    payload = {
        "activation_schema_version": 1,
        "release_version": "0.7.3",
        "release_artifact_sha256": "a" * 64,
        "dataset_generation": generation,
        "sqlite_schema_version": schema_module.SQLITE_SCHEMA_VERSION,
        "dataset_revision": 0,
        "migration_manifest_sha256": "b" * 64,
        "pre_cutover_backup_manifest_sha256": "c" * 64,
        "activated_at": _NOW,
    }
    paths.activation.write_text(json.dumps(payload), encoding="utf-8")


def _facade(
    paths: AuthorityPaths,
    evidence: ActivationEvidence,
    data_dir: Path,
) -> StorageMutationFacade:
    authority = require_repository_authority(paths, evidence)

    class FixedDispatchFacade(StorageMutationFacade):
        def dispatch(self) -> AuthorityDispatch:
            return AuthorityDispatch(paths=paths, authority=authority, evidence=evidence)

    return FixedDispatchFacade(data_dir)


def _query(database: Path, sql: str, parameters: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return connection.execute(sql, parameters).fetchall()
    finally:
        connection.close()


def _count(database: Path, table: str) -> int:
    allowed = {
        "exact_values",
        "transactions",
        "changesets",
        "changeset_entries",
        "audit_events",
        "idempotency_requests",
        "transaction_source_links",
        "number_values",
    }
    assert table in allowed
    return int(_query(database, f"SELECT count(*) FROM {table}")[0][0])  # nosec B608


def _reject_float(value: Any) -> None:
    if isinstance(value, float):
        raise AssertionError("float leaked into bulk result or audit")
    if isinstance(value, dict):
        for item in value.values():
            _reject_float(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _reject_float(item)


def _seed(tmp_path: Path, specs: tuple[_Txn, ...]) -> _Seeded:
    paths = AuthorityPaths(
        control_root=tmp_path / "control",
        generations_root=tmp_path / "generations",
    )
    generation = new_entity_id()
    repository_paths = paths.generation(generation)
    ids: dict[str, str] = {}
    meta: dict[str, dict[str, str]] = {}
    with RepositoryBuilder(repository_paths, generation) as builder:
        artifact = builder.publish_source(io.BytesIO(b"synthetic bulk source"))
        occurrence_id = new_entity_id()
        builder.add_source_occurrence(
            SourceOccurrenceRecord(
                occurrence_id=occurrence_id,
                artifact_id=artifact.artifact_id,
                occurrence_kind="synthetic",
                original_filename="bulk.xlsx",
                imported_at=_NOW,
            )
        )
        maps = _Maps(ids, meta)
        for index, spec in enumerate(specs, start=1):
            _add_transaction(builder, occurrence_id, spec, index, maps)
        builder.finalize()
    evidence = _evidence()
    _write_activation(paths, generation)
    return _Seeded(
        paths,
        evidence,
        generation,
        repository_paths.database,
        _facade(paths, evidence, tmp_path),
        ids,
        meta,
    )


@dataclass
class _Maps:
    ids: dict[str, str]
    meta: dict[str, dict[str, str]]


def _add_transaction(
    builder: RepositoryBuilder,
    occurrence_id: str,
    spec: _Txn,
    index: int,
    maps: _Maps,
) -> None:
    account_id = new_entity_id()
    observation_id = new_entity_id()
    provenance_id = new_entity_id()
    transaction_id = new_entity_id()
    amount_id = new_entity_id()
    confidence_id = new_entity_id()
    builder.add_account(AccountRecord(account_id=account_id, account_kind="bank.v1"))
    builder.add_observation(
        ObservationRecord(
            observation_id=observation_id,
            occurrence_id=occurrence_id,
            observed_at=spec.observed_at,
            effective_at=spec.effective_at,
            collected_at=_NOW,
            scope_state="partial",
        )
    )
    builder.add_provenance(
        ProvenanceRecord(
            provenance_id=provenance_id,
            occurrence_id=occurrence_id,
            source_coordinate={"row": index},
            legacy_locator={
                "sheet": "synthetic",
                "row": index,
                "row_hash": spec.row_hash or spec.name,
            },
        )
    )
    builder.add_exact_value(
        amount_id,
        ExactValue.from_lexical(spec.amount, value_kind="money", currency=spec.currency),
        provenance_id=provenance_id,
    )
    builder.add_exact_value(
        confidence_id,
        ExactValue(
            coefficient="5",
            scale=1,
            lexical=None,
            value_kind="number",
            origin_kind="calculated",
            unit="confidence.v1",
        ),
    )
    builder.add_transaction(
        TransactionRecord(
            transaction_id=transaction_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            account_id=account_id,
            amount_value_id=amount_id,
            date_raw="2026-09-01",
            time_raw="12:00:00",
            datetime_raw=spec.datetime_raw,
            type_raw=spec.type_norm if spec.type_raw is None else spec.type_raw,
            type_norm=spec.type_norm,
            account_text=f"account-{spec.name}",
            major_raw=spec.major,
            minor_raw="Meals",
            merchant_raw=spec.merchant,
            category_manual=spec.category_manual,
            category_final="Meals",
            tags_ai_json=spec.tags_ai,
            tags_manual_json=spec.tags_manual,
            tags_final_json='["seed"]',
            confidence_value_id=confidence_id,
            needs_review=True,
            timezone_state=spec.timezone_state,  # type: ignore[arg-type]
            is_transfer=spec.is_transfer,
            transfer_group_id=spec.transfer_group_id,
        )
    )
    if spec.row_hash:
        builder.add_legacy_identifier(
            LegacyIdentifierRecord(
                entity_id=transaction_id,
                identifier_kind="row_hash",
                identifier_value=spec.row_hash,
                capture_manifest_digest="f" * 64,
                provenance_id=provenance_id,
            )
        )
    maps.ids[spec.name] = transaction_id
    maps.meta[spec.name] = {
        "amount": amount_id,
        "confidence": confidence_id,
        "observation": observation_id,
        "provenance": provenance_id,
    }


def _publish_rules(seeded: _Seeded, revision: int, content: bytes = _RULES) -> MutationReceipt:
    return seeded.facade.replace_config(
        ConfigDocument.from_validated_yaml("rules", content, parser_version="finjuice.rules.v1"),
        identity=seeded.identity("rules-head", revision),
    )


def _txn_row(database: Path, transaction_id: str) -> sqlite3.Row:
    connection = sqlite3.connect(f"{database.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            "SELECT category_rule, category_manual, category_final, tags_rule_json, "
            "tags_ai_json, tags_manual_json, tags_final_json, notes_manual, "
            "confidence_value_id, needs_review, is_transfer, is_transfer_candidate, "
            "transfer_group_id, provenance_id, observation_id, amount_value_id "
            "FROM transactions WHERE entity_id = ?",
            (transaction_id,),
        ).fetchone()
    finally:
        connection.close()
    assert row is not None
    return row


def _tag_specs() -> tuple[_Txn, ...]:
    return (
        _Txn(
            "cafe_manual",
            "1000.00",
            merchant="synthetic cafe",
            category_manual="Travel",
            tags_manual='["keep"]',
            tags_ai='["ai"]',
            row_hash="dup-hash",
        ),
        _Txn("cafe_dup", "2000", merchant="cafe extra", row_hash="dup-hash"),
        _Txn("huge", _HUGE, merchant="other"),
        _Txn("tiny", _TINY, merchant="other"),
        _Txn("plain", "10", merchant="unrelated"),
    )


def test_bulk_tagging_priority_manual_exact_amounts_and_distinct_hashes(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, _tag_specs())
    rules = _publish_rules(seeded, 0)
    preview = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-bulk", rules.committed_revision),
        dry_run=True,
    )
    exact_before = _count(seeded.database, "exact_values")
    written = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-bulk", rules.committed_revision),
    )

    assert isinstance(preview, BulkMutationPreview)
    assert isinstance(written, MutationReceipt)
    assert preview.dataset_revision == rules.committed_revision
    assert preview.result == written.result
    _reject_float(written.result)
    assert written.state_changed is True
    assert written.result["changed"] is True
    assert written.result["tagged"] == 4
    assert written.result["untagged"] == 1
    assert written.result["total"] == 5
    cafe = _txn_row(seeded.database, seeded.ids["cafe_manual"])
    assert cafe["category_rule"] == "Food"
    assert cafe["category_manual"] == "Travel"
    assert cafe["category_final"] == "Travel"
    assert json.loads(cafe["tags_rule_json"]) == ["food", "cafe"]
    assert json.loads(cafe["tags_ai_json"]) == ["ai"]
    assert json.loads(cafe["tags_manual_json"]) == ["keep"]
    assert json.loads(cafe["tags_final_json"]) == ["food", "cafe", "ai", "keep"]
    assert cafe["needs_review"] == 0
    assert cafe["amount_value_id"] == seeded.meta["cafe_manual"]["amount"]
    assert cafe["provenance_id"] == seeded.meta["cafe_manual"]["provenance"]
    dup = _txn_row(seeded.database, seeded.ids["cafe_dup"])
    assert json.loads(dup["tags_rule_json"]) == ["food", "cafe"]
    assert seeded.ids["cafe_manual"] != seeded.ids["cafe_dup"]
    huge = _txn_row(seeded.database, seeded.ids["huge"])
    tiny = _txn_row(seeded.database, seeded.ids["tiny"])
    assert json.loads(huge["tags_final_json"]) == ["huge"]
    assert json.loads(tiny["tags_final_json"]) == ["tiny"]
    amount_text = _query(
        seeded.database,
        "SELECT coefficient, scale FROM exact_values WHERE value_id = ?",
        (seeded.meta["huge"]["amount"],),
    )
    assert amount_text == [(_HUGE, 0)]
    assert _count(seeded.database, "exact_values") == exact_before + 2


def test_bulk_tagging_noop_replay_opaque_head_and_stale_conflict(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, _tag_specs())
    rules = _publish_rules(seeded, 0)
    first = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-bulk", rules.committed_revision),
    )
    assert isinstance(first, MutationReceipt)
    exact_after_first = _count(seeded.database, "exact_values")
    revision_after_first = seeded.revision()
    noop = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-bulk-again", first.committed_revision),
    )
    assert isinstance(noop, MutationReceipt)
    assert noop.state_changed is False
    assert noop.result["changed"] is False
    assert noop.result["updated"] == 0
    assert seeded.revision() == revision_after_first
    assert _count(seeded.database, "exact_values") == exact_after_first

    seeded.facade.replace_config(
        ConfigDocument(
            config_kind="rules",
            content=b"\x00opaque-rules-head",
            parsed_status="opaque",
            canonical_payload=None,
            parser_version=None,
        ),
        identity=seeded.identity("opaque-rules", first.committed_revision),
    )
    replay = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-bulk", rules.committed_revision),
    )
    assert isinstance(replay, MutationReceipt)
    assert replay.replayed is True
    assert replay.changeset_id == first.changeset_id
    assert replay.result == first.result

    with pytest.raises(MutationConflictError, match="revision"):
        seeded.facade.recompute_tags(
            BulkTagCommand(),
            identity=seeded.identity("stale-tag", 0),
        )
    with pytest.raises(MutationValidationError, match="parsed canonical"):
        seeded.facade.recompute_tags(
            BulkTagCommand(),
            identity=MutationIdentity(expected_revision=seeded.revision()),
        )


def test_bulk_tagging_mid_row_failure_rolls_back_all_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _seed(tmp_path, _tag_specs())
    rules = _publish_rules(seeded, 0)
    original = MutationContext.update_transaction_derived_state
    calls = {"n": 0}

    def fail_second(
        self: MutationContext,
        transaction_id: str,
        after: Any,
        *,
        before: Any,
    ) -> bool:
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("injected mid-row failure")
        return original(self, transaction_id, after, before=before)

    monkeypatch.setattr(MutationContext, "update_transaction_derived_state", fail_second)
    before_rows = _query(
        seeded.database,
        "SELECT entity_id, category_rule, tags_final_json, confidence_value_id FROM transactions "
        "ORDER BY entity_id",
    )
    before_exact = _count(seeded.database, "exact_values")
    before_revision = seeded.revision()
    before_changesets = _count(seeded.database, "changesets")
    with pytest.raises(RuntimeError, match="injected mid-row"):
        seeded.facade.recompute_tags(
            BulkTagCommand(),
            identity=seeded.identity("tag-fail", rules.committed_revision),
        )
    assert (
        _query(
            seeded.database,
            "SELECT entity_id, category_rule, tags_final_json, confidence_value_id "
            "FROM transactions ORDER BY entity_id",
        )
        == before_rows
    )
    assert _count(seeded.database, "exact_values") == before_exact
    assert seeded.revision() == before_revision
    assert _count(seeded.database, "changesets") == before_changesets


def test_bulk_tagging_dry_run_does_not_publish_or_change_snapshot(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, _tag_specs())
    rules = _publish_rules(seeded, 0)
    before = (
        seeded.revision(),
        _count(seeded.database, "exact_values"),
        _count(seeded.database, "changesets"),
        _count(seeded.database, "idempotency_requests"),
    )
    preview = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-preview", rules.committed_revision),
        dry_run=True,
    )
    assert isinstance(preview, BulkMutationPreview)
    assert preview.result["updated"] > 0
    assert (
        seeded.revision(),
        _count(seeded.database, "exact_values"),
        _count(seeded.database, "changesets"),
        _count(seeded.database, "idempotency_requests"),
    ) == before


def test_unsupported_derived_keys_are_rejected(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, (_Txn("plain", "10"),))

    def handler(context: MutationContext) -> MutationOutcome:
        rows = context.load_bulk_transactions((seeded.ids["plain"],))
        before = {"category_rule": rows[0]["category_rule"]}
        context.update_transaction_derived_state(
            seeded.ids["plain"],
            {"category_rule": "x", "merchant_raw": "nope"},
            before=before,
        )
        return MutationOutcome(result={"ok": True})

    with pytest.raises(MutationValidationError, match="Unsupported derived field"):
        MutationService(seeded.paths, seeded.evidence).execute(
            MutationRequest(
                command_scope="test.derived",
                idempotency_key="bad-key",
                payload={"operation": "invalid"},
                expected_generation=seeded.generation,
                expected_revision=0,
                actor="test",
            ),
            handler,
        )


def test_source_links_survive_bulk_tagging(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, (_Txn("cafe_manual", "10", merchant="cafe"),))
    link_id = new_entity_id()
    meta = seeded.meta["cafe_manual"]

    def add_link(context: MutationContext) -> MutationOutcome:
        context.add_transaction_source_link(
            TransactionSourceLinkRecord(
                link_id=link_id,
                transaction_id=seeded.ids["cafe_manual"],
                provenance_id=meta["provenance"],
                observation_id=meta["observation"],
                link_kind="origin",
            )
        )
        return MutationOutcome(result={"link_id": link_id})

    MutationService(seeded.paths, seeded.evidence).execute(
        MutationRequest(
            command_scope="test.link",
            idempotency_key="origin-link",
            payload={"link_id": link_id},
            expected_generation=seeded.generation,
            expected_revision=0,
            actor="test",
        ),
        add_link,
    )
    rules = _publish_rules(seeded, 1)
    seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-after-link", rules.committed_revision),
    )
    assert _query(
        seeded.database,
        "SELECT link_id, provenance_id, observation_id FROM transaction_source_links",
    ) == [(link_id, meta["provenance"], meta["observation"])]


def _clocked(
    name: str,
    amount: str,
    *,
    at: str = "2026-09-01T12:00:00",
    **kwargs: Any,
) -> _Txn:
    kwargs.setdefault("type_norm", "transfer")
    kwargs.setdefault("timezone_state", "known")
    kwargs.setdefault("effective_at", at)
    return _Txn(name, amount, **kwargs)


def _transfer_specs() -> tuple[_Txn, ...]:
    return (
        _clocked("out", "-100.00", major="내계좌이체"),
        _clocked("in", "100.00", major="내계좌이체", at="2026-09-01T12:01:00"),
        _clocked("thresh_out", "-100", major="threshold"),
        _clocked("thresh_in", "99", major="threshold", at="2026-09-01T12:00:30"),
        _clocked("beyond_out", "-100", major="beyond"),
        _clocked("beyond_in", "98.99", major="beyond", at="2026-09-01T12:00:30"),
        _clocked(
            "stale_out",
            "-100",
            major="stale",
            is_transfer=True,
            transfer_group_id="T_old_old",
        ),
        _clocked(
            "stale_in",
            "50",
            major="stale",
            is_transfer=True,
            transfer_group_id="T_old_old",
            at="2026-09-01T12:00:30",
        ),
        _Txn(
            "unknown_clock",
            "-100.00",
            major="내계좌이체",
            type_norm="transfer",
            timezone_state="unknown",
            effective_at="2026-09-01T12:00:00",
        ),
        _Txn(
            "excel_serial",
            "100.00",
            major="내계좌이체",
            type_norm="transfer",
            timezone_state="known",
            effective_at="44927.5",
        ),
        _Txn(
            "date_only",
            "100.00",
            major="내계좌이체",
            type_norm="transfer",
            timezone_state="known",
            effective_at="2026-09-01",
        ),
        _clocked("unknown_ccy_out", "-100.00", currency=UNKNOWN_CURRENCY, major="fx"),
        _clocked(
            "unknown_ccy_in",
            "100.00",
            currency=UNKNOWN_CURRENCY,
            major="fx",
            at="2026-09-01T12:00:30",
        ),
        _clocked("hash_a", "-25", major="dup", row_hash="same-hash"),
        _clocked("hash_b", "25", major="dup", row_hash="same-hash", at="2026-09-01T12:00:10"),
        _clocked("tie_a", "-100", major="ties"),
        _clocked("tie_b", "-100", major="ties"),
        _clocked("tie_c", "100", major="ties", at="2026-09-01T12:00:01"),
        _clocked("tie_d", "100", major="ties", at="2026-09-01T12:00:01"),
        _clocked("lonely", "-33", major="lonely"),
        _clocked(
            "legacy_out",
            "-80",
            major="legacy",
            type_norm="expense",
            type_raw="계좌이체",
        ),
        _clocked(
            "legacy_in",
            "80",
            major="legacy",
            type_norm="income",
            type_raw="자동이체",
            at="2026-09-01T12:00:20",
        ),
        _Txn(
            "exp",
            "-50",
            major="Living",
            type_norm="expense",
            timezone_state="known",
            effective_at="2026-09-01T12:00:00",
        ),
        _Txn(
            "ref",
            "50",
            major="Living",
            type_norm="income",
            timezone_state="known",
            effective_at="2026-09-01T12:00:10",
        ),
    )


def test_bulk_transfer_pairs_thresholds_ties_removal_and_unknowns(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, _transfer_specs())
    preview = seeded.facade.recompute_transfers(
        BulkTransferCommand(),
        identity=seeded.identity("xfer", 0),
        dry_run=True,
    )
    written = seeded.facade.recompute_transfers(
        BulkTransferCommand(),
        identity=seeded.identity("xfer", 0),
    )
    assert isinstance(preview, BulkMutationPreview)
    assert isinstance(written, MutationReceipt)
    assert preview.result == written.result
    _reject_float(written.result)
    _assert_confirmed_pairs(seeded)
    _assert_unconfirmed_and_ordinary_rows(seeded)
    _assert_transfer_result_counts(written.result)
    noop = seeded.facade.recompute_transfers(
        BulkTransferCommand(),
        identity=seeded.identity("xfer-again", written.committed_revision),
    )
    assert isinstance(noop, MutationReceipt)
    assert noop.state_changed is False
    assert noop.result["updated"] == 0
    assert seeded.revision() == written.committed_revision


def _pair_group(left: str, right: str) -> str:
    return f"T_{min(left, right)}_{max(left, right)}"


def _assert_confirmed_pairs(seeded: _Seeded) -> None:
    out_id = seeded.ids["out"]
    in_id = seeded.ids["in"]
    paired_out = _txn_row(seeded.database, out_id)
    assert paired_out["is_transfer"] == 1
    assert paired_out["is_transfer_candidate"] == 1
    assert _txn_row(seeded.database, in_id)["transfer_group_id"] == _pair_group(out_id, in_id)
    assert paired_out["amount_value_id"] == seeded.meta["out"]["amount"]
    thresh_out = seeded.ids["thresh_out"]
    thresh_in = seeded.ids["thresh_in"]
    assert _txn_row(seeded.database, thresh_out)["transfer_group_id"] == _pair_group(
        thresh_out, thresh_in
    )
    hash_a = seeded.ids["hash_a"]
    hash_b = seeded.ids["hash_b"]
    assert hash_a != hash_b
    assert _txn_row(seeded.database, hash_a)["transfer_group_id"] == _pair_group(hash_a, hash_b)
    legacy_out = seeded.ids["legacy_out"]
    legacy_in = seeded.ids["legacy_in"]
    assert _txn_row(seeded.database, legacy_out)["transfer_group_id"] == _pair_group(
        legacy_out, legacy_in
    )
    tie_ids = [seeded.ids[name] for name in ("tie_a", "tie_b", "tie_c", "tie_d")]
    tie_groups = {_txn_row(seeded.database, item)["transfer_group_id"] for item in tie_ids}
    assert None not in tie_groups
    assert len(tie_groups) == 2


def _assert_unconfirmed_and_ordinary_rows(seeded: _Seeded) -> None:
    beyond_out = _txn_row(seeded.database, seeded.ids["beyond_out"])
    assert beyond_out["is_transfer"] == 0
    assert beyond_out["is_transfer_candidate"] == 1
    assert _txn_row(seeded.database, seeded.ids["beyond_in"])["transfer_group_id"] is None
    stale_out = _txn_row(seeded.database, seeded.ids["stale_out"])
    assert stale_out["is_transfer"] == 0
    assert stale_out["is_transfer_candidate"] == 1
    assert stale_out["transfer_group_id"] is None
    unknown_clock = _txn_row(seeded.database, seeded.ids["unknown_clock"])
    assert unknown_clock["is_transfer_candidate"] == 1
    assert unknown_clock["is_transfer"] == 0
    excel_serial = _txn_row(seeded.database, seeded.ids["excel_serial"])
    assert excel_serial["is_transfer_candidate"] == 1
    assert _txn_row(seeded.database, seeded.ids["date_only"])["is_transfer_candidate"] == 1
    lonely = _txn_row(seeded.database, seeded.ids["lonely"])
    assert lonely["is_transfer_candidate"] == 1
    assert lonely["is_transfer"] == 0
    expense = _txn_row(seeded.database, seeded.ids["exp"])
    refund = _txn_row(seeded.database, seeded.ids["ref"])
    assert expense["is_transfer_candidate"] == 0
    assert refund["is_transfer"] == 0
    assert refund["transfer_group_id"] is None


def _assert_transfer_result_counts(result: Any) -> None:
    assert result["total"] == 24
    assert result["candidate_rows"] == 22
    assert result["candidates_considered"] == 17
    assert result["pairs_found"] == 6
    assert result["paired_rows"] == 12
    assert result["confirmed_transfer_rows"] == 12
    assert result["pairs_linked"] == 12
    assert result["unconfirmed_candidate_rows"] == 10
    assert result["unsupported"] == 5
    assert result["unsupported_missing_timezone"] == 1
    assert result["unsupported_malformed_time"] == 2


def test_invalid_amount_tolerance_rejected_when_candidates_empty(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, (_Txn("plain", "10"),))
    for bad in ("nonsense", "nan", "-0.1", "1.01", "1e-999999"):
        with pytest.raises(MutationValidationError):
            BulkTransferCommand(amount_tolerance=bad)
    with pytest.raises(MutationValidationError):
        BulkTransferCommand(amount_tolerance=True)  # type: ignore[arg-type]
    written = seeded.facade.recompute_transfers(
        BulkTransferCommand(),
        identity=seeded.identity("empty-xfer", 0),
    )
    assert isinstance(written, MutationReceipt)
    assert written.result["candidate_rows"] == 0
    assert written.result["pairs_found"] == 0
    assert written.result["candidates_considered"] == 0


def test_missing_rules_head_leaves_state_unchanged(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, _tag_specs())
    before_rows = _query(
        seeded.database,
        "SELECT entity_id, category_rule, tags_final_json, confidence_value_id "
        "FROM transactions ORDER BY entity_id",
    )
    before_revision = seeded.revision()
    before_exact = _count(seeded.database, "exact_values")
    with pytest.raises(MutationValidationError, match="missing"):
        seeded.facade.recompute_tags(
            BulkTagCommand(),
            identity=seeded.identity("no-head", 0),
        )
    assert seeded.revision() == before_revision
    assert _count(seeded.database, "exact_values") == before_exact
    assert (
        _query(
            seeded.database,
            "SELECT entity_id, category_rule, tags_final_json, confidence_value_id "
            "FROM transactions ORDER BY entity_id",
        )
        == before_rows
    )


def test_empty_parsed_rules_clear_derived_rule_fields(tmp_path: Path) -> None:
    seeded = _seed(
        tmp_path,
        (
            _Txn(
                "cafe_manual",
                "10",
                merchant="synthetic cafe",
                category_manual="Travel",
                tags_manual='["keep"]',
                tags_ai='["ai"]',
            ),
        ),
    )
    empty = _publish_rules(seeded, 0, b"version: 1\nrules: []\n")
    written = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("empty-rules", empty.committed_revision),
    )
    assert isinstance(written, MutationReceipt)
    row = _txn_row(seeded.database, seeded.ids["cafe_manual"])
    assert row["category_rule"] is None
    assert json.loads(row["tags_rule_json"]) == []
    assert row["category_manual"] == "Travel"
    assert json.loads(row["tags_manual_json"]) == ["keep"]
    assert json.loads(row["tags_ai_json"]) == ["ai"]
    assert json.loads(row["tags_final_json"]) == ["ai", "keep"]


def test_wrong_confidence_recomputes_then_is_noop(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, (_Txn("cafe", "10", merchant="synthetic cafe"),))
    rules = _publish_rules(seeded, 0)
    first = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-conf", rules.committed_revision),
    )
    assert isinstance(first, MutationReceipt)
    tid = seeded.ids["cafe"]

    def plant_wrong_confidence(context: MutationContext) -> MutationOutcome:
        rows = context.load_bulk_transactions((tid,))
        before = tagging_derived_state(rows[0])
        value_id = new_entity_id()
        context.add_exact_value(
            value_id,
            ExactValue(
                coefficient="1",
                scale=0,
                lexical=None,
                value_kind="number",
                origin_kind="calculated",
                unit="ratio.v1",
            ),
        )
        context.update_transaction_derived_state(
            tid,
            {**dict(before), "confidence_value_id": value_id},
            before=before,
        )
        return MutationOutcome(result={"planted": True})

    MutationService(seeded.paths, seeded.evidence).execute(
        MutationRequest(
            command_scope="test.confidence",
            idempotency_key="plant-unit",
            payload={"operation": "plant"},
            expected_generation=seeded.generation,
            expected_revision=seeded.revision(),
            actor="test",
        ),
        plant_wrong_confidence,
    )
    repaired = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-repair", seeded.revision()),
    )
    assert isinstance(repaired, MutationReceipt)
    assert repaired.state_changed is True
    assert repaired.result["updated"] == 1
    exact_after = _count(seeded.database, "exact_values")
    noop = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-repair-again", repaired.committed_revision),
    )
    assert isinstance(noop, MutationReceipt)
    assert noop.state_changed is False
    assert noop.result["updated"] == 0
    assert _count(seeded.database, "exact_values") == exact_after


def test_derived_update_rejects_stale_before_and_audits_stored(
    tmp_path: Path,
) -> None:
    seeded = _seed(tmp_path, (_Txn("plain", "10"),))
    tid = seeded.ids["plain"]

    def handler(context: MutationContext) -> MutationOutcome:
        rows = context.load_bulk_transactions((tid,))
        before = tagging_derived_state(rows[0])
        first_after = {**dict(before), "category_rule": "First"}
        context.update_transaction_derived_state(tid, first_after, before=before)
        with pytest.raises(MutationValidationError, match="does not match stored"):
            context.update_transaction_derived_state(
                tid,
                {**first_after, "category_rule": "Second"},
                before=before,
            )
        context.update_transaction_derived_state(
            tid,
            {**first_after, "category_rule": "Second"},
            before=first_after,
        )
        return MutationOutcome(result={"ok": True})

    receipt = MutationService(seeded.paths, seeded.evidence).execute(
        MutationRequest(
            command_scope="test.derived",
            idempotency_key="stale-before",
            payload={"operation": "double"},
            expected_generation=seeded.generation,
            expected_revision=0,
            actor="test",
        ),
        handler,
    )
    assert _txn_row(seeded.database, tid)["category_rule"] == "Second"
    entries = _query(
        seeded.database,
        "SELECT before_json, after_json FROM changeset_entries "
        "WHERE entity_id = ? ORDER BY entry_index",
        (tid,),
    )
    assert json.loads(str(entries[0][0]))["category_rule"] is None
    assert json.loads(str(entries[0][1]))["category_rule"] == "First"
    assert json.loads(str(entries[1][0]))["category_rule"] == "First"
    assert json.loads(str(entries[1][1]))["category_rule"] == "Second"
    assert receipt.state_changed is True


def test_preview_begins_before_repository_revision_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seeded = _seed(tmp_path, (_Txn("cafe", "10", merchant="synthetic cafe"),))
    empty = _publish_rules(seeded, 0, b"version: 1\nrules: []\n")
    first = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-empty", empty.committed_revision),
    )
    assert isinstance(first, MutationReceipt)
    original = mutations_mod._validate_new_request
    injected = {"busy": False, "committed": False, "ran": False, "begun": False}

    def hooked(
        request: MutationRequest,
        authority: Any,
        current_revision: int,
    ) -> None:
        original(request, authority, current_revision)
        if injected["ran"]:
            return
        injected["ran"] = True
        _compete_for_write_lock(seeded.database, injected)

    monkeypatch.setattr(mutations_mod, "_validate_new_request", hooked)
    preview = seeded.facade.recompute_tags(
        BulkTagCommand(),
        identity=seeded.identity("tag-preview-pin", first.committed_revision),
        dry_run=True,
    )
    assert isinstance(preview, BulkMutationPreview)
    assert preview.dataset_revision == first.committed_revision
    assert preview.result["updated"] == 0
    assert injected["begun"] is True
    assert injected["busy"] is True
    assert injected["committed"] is False
    later = seeded.facade.replace_config(
        ConfigDocument.from_validated_yaml("rules", _RULES, parser_version="finjuice.rules.v1"),
        identity=seeded.identity("rules-after-preview", first.committed_revision),
    )
    assert later.committed_revision == first.committed_revision + 1


def _compete_for_write_lock(database: Path, injected: dict[str, bool]) -> None:
    journal = _query(database, "PRAGMA journal_mode")[0][0]
    assert str(journal).upper() == "DELETE"

    def worker() -> None:
        uri = f"{database.resolve().as_uri()}?mode=rw"
        connection = sqlite3.connect(uri, uri=True, timeout=0.05, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout = 50")
            try:
                connection.execute("BEGIN IMMEDIATE")
                injected["begun"] = True
                connection.execute(
                    "UPDATE repository_meta SET dataset_revision = dataset_revision + 1"
                )
                connection.execute("COMMIT")
            except sqlite3.OperationalError:
                injected["busy"] = True
                return
            injected["committed"] = True
        finally:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            connection.close()

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(1.0)
    assert not thread.is_alive()


def test_preview_connection_rejects_write_before_any_journaled_changes(tmp_path: Path) -> None:
    seeded = _seed(tmp_path, (_Txn("plain", "10"),))
    transaction_id = seeded.ids["plain"]
    before = seeded.database.read_bytes()

    def accidental_writer(context: MutationContext) -> MutationOutcome:
        context.update_transaction_derived_state(
            transaction_id, {"needs_review": False}, before={"needs_review": True}
        )
        return MutationOutcome(result={"changed": True})

    request = MutationRequest(
        command_scope="test.readonly_preview",
        idempotency_key="readonly-preview",
        payload={},
        expected_generation=seeded.generation,
        expected_revision=0,
        actor="test",
    )

    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        MutationService(seeded.paths, seeded.evidence).preview(request, accidental_writer)

    assert seeded.database.read_bytes() == before
    assert seeded.revision() == 0
    assert _count(seeded.database, "changesets") == 0
    assert _txn_row(seeded.database, transaction_id)["needs_review"] == 1


@pytest.mark.parametrize(
    "before,after",
    [
        ({"needs_review": True}, {"needs_review": 1}),
        ({"tags_rule": []}, {"tags_rule": "[]"}),
        ({"needs_review": "yes"}, {"needs_review": False}),
    ],
)
def test_derived_types_are_validated_even_for_semantically_equal_noops(
    tmp_path: Path, before: dict[str, Any], after: dict[str, Any]
) -> None:
    seeded = _seed(tmp_path, (_Txn("plain", "10"),))
    database_before = seeded.database.read_bytes()

    def handler(context: MutationContext) -> MutationOutcome:
        context.update_transaction_derived_state(seeded.ids["plain"], after, before=before)
        return MutationOutcome(result={"changed": True})

    request = MutationRequest(
        command_scope="test.derived_types",
        idempotency_key="invalid-derived-type",
        payload={},
        expected_generation=seeded.generation,
        expected_revision=0,
        actor="test",
    )
    with pytest.raises(MutationValidationError):
        MutationService(seeded.paths, seeded.evidence).execute(request, handler)
    assert seeded.database.read_bytes() == database_before
    assert seeded.revision() == 0
    assert _count(seeded.database, "changesets") == 0
