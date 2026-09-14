"""Role-specific mapping from frozen files onto BuildState."""

from __future__ import annotations

from typing import Any

import yaml

from finjuice.pipeline.migrate.csvio import read_csv_rows
from finjuice.pipeline.migrate.inventory import resolve_entry_path
from finjuice.pipeline.migrate.preserve import (
    canonical_tag_json,
    legacy_payload,
    normalize_type_norm,
    optional_flag,
    parse_tag_sequence,
    split_hidden_category,
)
from finjuice.pipeline.migrate.records import (
    _TRANSACTION_KNOWN,
    BuildState,
    RowWork,
    add_identity,
    add_issue,
    add_money,
    add_observation,
    add_provenance,
    add_row_identifiers,
    add_typed_number,
    close_record,
    ensure_account,
    publish_entry,
    row_locator,
    stable_id,
)
from finjuice.pipeline.migrate.types import (
    PARSER_VERSION,
    CaptureEntry,
    CaptureManifest,
    Disposition,
)
from finjuice.pipeline.storage.sqlite import ConfigRevisionRecord, TransactionRecord


def map_absent(state: BuildState, role: str) -> None:
    """Record an inventoried missing role with a reason."""
    locator = {"locator_version": 1, "logical_role": role, "state": "intentionally_absent"}
    provenance_id = add_provenance(
        state,
        state.origin_occurrence_id,
        locator,
        {"logical_role": role},
    )
    close_record(
        state,
        provenance_id,
        {"logical_role": role, "state": "intentionally_absent"},
        locator,
        ("intentionally_absent", "Inventoried source role is not present in the frozen copy."),
    )


def map_opaque_file(
    state: BuildState,
    manifest: CaptureManifest,
    entry: CaptureEntry,
    *,
    reason: str,
    disposition: Disposition = "preserved_opaque",
) -> str:
    """Preserve one file as source bytes without pretending it is typed history."""
    occurrence_id = publish_entry(state, manifest, entry)
    locator = {
        "locator_version": 1,
        "relative_path": entry.relative_path,
        "logical_role": entry.logical_role,
        "partition_digest": (entry.sha256 or "").removeprefix("sha256:"),
    }
    provenance_id = add_provenance(
        state,
        occurrence_id,
        locator,
        {"relative_path": entry.relative_path, "logical_role": entry.logical_role},
    )
    close_record(
        state,
        provenance_id,
        {
            "logical_role": entry.logical_role,
            "relative_path": entry.relative_path,
            "sha256": entry.sha256,
        },
        locator,
        (disposition, reason),
    )
    return occurrence_id


def _parse_yaml(text: str) -> tuple[str, dict[str, Any] | list[Any] | None]:
    try:
        payload = yaml.safe_load(text)
    except yaml.YAMLError:
        return "invalid", None
    if payload is None:
        return "parsed", None
    if not isinstance(payload, (dict, list)):
        return "opaque", None
    return "parsed", payload


def map_config_file(
    state: BuildState,
    manifest: CaptureManifest,
    entry: CaptureEntry,
    config_kind: str,
) -> None:
    """Preserve rules/goals/overlay bytes and parsed status without rewriting meaning."""
    path = resolve_entry_path(manifest, entry)
    occurrence_id = publish_entry(state, manifest, entry)
    locator = {
        "locator_version": 1,
        "relative_path": entry.relative_path,
        "config_kind": config_kind,
        "partition_digest": (entry.sha256 or "").removeprefix("sha256:"),
    }
    parsed_status, payload = _parse_yaml(path.read_text(encoding="utf-8"))
    revision_id = stable_id(state.digest, "config_revision", locator)
    artifact_id = state.builder.published_artifacts[-1].artifact_id
    state.builder.add_config_revision(
        ConfigRevisionRecord(
            revision_id=revision_id,
            config_kind=config_kind,  # type: ignore[arg-type]
            artifact_id=artifact_id,
            occurrence_id=occurrence_id,
            parsed_status=parsed_status,  # type: ignore[arg-type]
            parser_version=PARSER_VERSION,
            canonical_payload=payload,
        )
    )
    add_identity(state, revision_id, "config_revision", locator)
    provenance_id = add_provenance(
        state,
        occurrence_id,
        locator,
        {"relative_path": entry.relative_path, "config_kind": config_kind},
    )
    if parsed_status != "parsed":
        add_issue(state, provenance_id, f"config_{parsed_status}", {"field_name": "payload"})
    close_record(
        state,
        provenance_id,
        {"logical_role": entry.logical_role, "parsed_status": parsed_status},
        locator,
        (
            "migrated" if parsed_status == "parsed" else "preserved_opaque",
            f"Config {config_kind} preserved as {parsed_status} revision.",
        ),
    )


def map_transaction_row(work: RowWork) -> None:
    """Preserve one transaction occurrence, including hidden category markers."""
    state = work.state
    entry = work.entry
    row = work.row
    locator = row_locator(entry, work.ordinal, row)
    provenance_id = add_provenance(
        state,
        work.occurrence_id,
        locator,
        {
            "relative_path": entry.relative_path,
            "ordinal": work.ordinal,
            "row_hash": row.get("row_hash"),
        },
    )
    tags_raw, tag_issue = parse_tag_sequence(row.get("tags_manual"))
    visible, category_manual, markers = split_hidden_category(tags_raw)
    if tag_issue:
        add_issue(
            state,
            provenance_id,
            tag_issue,
            {"field_name": "tags_manual", "lexical_value": row.get("tags_manual")},
        )
    payload = legacy_payload(
        row,
        work.headers,
        _TRANSACTION_KNOWN,
        {"tags_manual_raw": tags_raw, "markers": markers},
    )
    amount_id, amount_issue = add_money(
        state,
        provenance_id,
        locator,
        ("amount", row.get("amount", ""), row.get("currency")),
    )
    if amount_id is None:
        close_record(
            state,
            provenance_id,
            payload,
            locator,
            ("preserved_opaque", amount_issue or "unparseable_amount"),
        )
        return
    type_norm, review, candidate, is_transfer = _transaction_flags(state, provenance_id, row)
    tags_rule, _rule_issue = parse_tag_sequence(row.get("tags_rule"))
    tags_ai, _ai_issue = parse_tag_sequence(row.get("tags_ai"))
    tags_final, _final_issue = parse_tag_sequence(row.get("tags_final"))
    confidence_id = None
    if row.get("confidence"):
        confidence_id = add_typed_number(
            state,
            provenance_id,
            locator,
            {
                "lexical": row["confidence"],
                "field_name": "confidence",
                "unit": "confidence.v1",
            },
        )
    observation_id = add_observation(
        state,
        work.occurrence_id,
        {**locator, "date": row.get("date") or ""},
    )
    account_text = row.get("account", "")
    account_id = ensure_account(state, "transaction", account_text, account_text)
    transaction_id = stable_id(state.digest, "transaction", locator)
    state.builder.add_transaction(
        TransactionRecord(
            transaction_id=transaction_id,
            observation_id=observation_id,
            provenance_id=provenance_id,
            account_id=account_id,
            amount_value_id=amount_id,
            date_raw=row.get("date") or "",
            time_raw=row.get("time") or "",
            datetime_raw=row.get("datetime") or "",
            type_raw=row.get("type_raw"),
            type_norm=type_norm,
            account_text=account_text,
            major_raw=row.get("major_raw") or None,
            minor_raw=row.get("minor_raw") or None,
            merchant_raw=row.get("merchant_raw") or None,
            memo_raw=row.get("memo_raw") or None,
            notes_manual=row.get("notes_manual"),
            counterparty=row.get("counterparty") or None,
            category_rule=row.get("category_rule") or None,
            category_manual=category_manual,
            category_final=row.get("category_final") or None,
            tags_rule_json=canonical_tag_json(tags_rule),
            tags_ai_json=canonical_tag_json(tags_ai),
            tags_manual_json=canonical_tag_json(visible),
            tags_final_json=canonical_tag_json(tags_final),
            confidence_value_id=confidence_id,
            needs_review=review,
            is_transfer_candidate=candidate,
            is_transfer=is_transfer,
            transfer_group_id=row.get("transfer_group_id") or None,
            timezone_state="unknown",
        )
    )
    add_identity(state, transaction_id, "transaction", locator)
    add_row_identifiers(work, transaction_id, provenance_id, locator)
    close_record(
        state,
        provenance_id,
        payload,
        locator,
        ("migrated", "Typed transaction preserved without reclassification."),
    )


def _transaction_flags(
    state: BuildState,
    provenance_id: str,
    row: dict[str, str],
) -> tuple[str, bool | None, bool | None, bool | None]:
    type_norm, type_issue = normalize_type_norm(row.get("type_norm"))
    if type_issue:
        add_issue(
            state,
            provenance_id,
            type_issue,
            {"field_name": "type_norm", "lexical_value": row.get("type_norm")},
        )
    review, review_issue = optional_flag(row.get("needs_review"))
    if review_issue:
        add_issue(state, provenance_id, review_issue, {"field_name": "needs_review"})
    candidate, candidate_issue = optional_flag(row.get("is_transfer_candidate"))
    if candidate_issue:
        add_issue(
            state,
            provenance_id,
            candidate_issue,
            {"field_name": "is_transfer_candidate"},
        )
    is_transfer, transfer_issue = optional_flag(row.get("is_transfer"))
    if transfer_issue:
        add_issue(state, provenance_id, transfer_issue, {"field_name": "is_transfer"})
    return type_norm, review, candidate, is_transfer


def map_csv_entry(
    state: BuildState,
    manifest: CaptureManifest,
    entry: CaptureEntry,
    handler: Any,
) -> None:
    """Publish a CSV partition and map each row with *handler*."""
    occurrence_id = publish_entry(state, manifest, entry)
    headers, rows = read_csv_rows(resolve_entry_path(manifest, entry))
    if not rows:
        locator = {
            "locator_version": 1,
            "relative_path": entry.relative_path,
            "logical_role": entry.logical_role,
        }
        provenance_id = add_provenance(
            state,
            occurrence_id,
            locator,
            {"relative_path": entry.relative_path},
        )
        close_record(
            state,
            provenance_id,
            {"relative_path": entry.relative_path, "row_count": 0},
            locator,
            ("intentionally_absent", "Captured CSV contains no data rows."),
        )
        return
    for ordinal, row in enumerate(rows):
        handler(
            RowWork(
                state=state,
                entry=entry,
                occurrence_id=occurrence_id,
                headers=headers,
                ordinal=ordinal,
                row=row,
            )
        )
