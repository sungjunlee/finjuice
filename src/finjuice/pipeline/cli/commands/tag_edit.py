"""Manual tag-edit helpers for ``finjuice tag --edit``.

Owns CLI tag normalization, single-row mutation, changed-field detection,
and human rendering for manual edits. Bulk rule tagging stays in
:mod:`finjuice.pipeline.cli.commands.tag`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import polars as pl

from finjuice.pipeline.cli.audit_log import append_financial_mutation_event
from finjuice.pipeline.cli.output import info, success
from finjuice.pipeline.cli.utils import mutation_metadata
from finjuice.pipeline.storage.mutation_facade import MutationIdentity, StorageMutationFacade
from finjuice.pipeline.storage.sqlite.mutations import ManualTransactionEdit
from finjuice.pipeline.tagging.manual import (
    build_manual_tags,
    merge_final_tags,
    normalize_tag_list,
    present_manual_state,
    resolve_category_final,
    split_manual_tags,
)

TAG_EDIT_AUDIT_FIELDS = [
    "tags_manual",
    "tags_final",
    "notes_manual",
    "category_final",
    "confidence",
    "needs_review",
]
MAX_MANUAL_NOTE_CHARS = 1000


@dataclass(frozen=True)
class TagEditRequest:
    """Stable manual-edit inputs shared by legacy and repository implementations."""

    identifier: str
    add_tags: list[str] | None
    remove_tags: list[str] | None
    set_category: str | None
    set_note: str | None
    dry_run: bool


def _changed_tag_edit_fields(
    current_row: dict[str, Any],
    updated_row: dict[str, Any],
) -> list[str]:
    """Return privacy-safe field names changed by a manual tag edit."""
    changed_fields: list[str] = []

    if normalize_tag_list(current_row.get("tags_manual")) != normalize_tag_list(
        updated_row.get("tags_manual")
    ):
        changed_fields.append("tags_manual")
    if normalize_tag_list(current_row.get("tags_final")) != normalize_tag_list(
        updated_row.get("tags_final")
    ):
        changed_fields.append("tags_final")
    if str(current_row.get("notes_manual") or "") != str(updated_row.get("notes_manual") or ""):
        changed_fields.append("notes_manual")
    if str(current_row.get("category_final") or "") != str(updated_row.get("category_final") or ""):
        changed_fields.append("category_final")
    if float(current_row.get("confidence") or 0.0) != float(updated_row.get("confidence") or 0.0):
        changed_fields.append("confidence")
    if int(current_row.get("needs_review") or 0) != int(updated_row.get("needs_review") or 0):
        changed_fields.append("needs_review")

    return [field for field in TAG_EDIT_AUDIT_FIELDS if field in changed_fields]


def _normalize_cli_tags(tags: list[str] | None) -> list[str]:
    """Normalize repeated CLI tag options."""
    cleaned: list[str] = []
    seen: set[str] = set()
    for tag in tags or []:
        normalized = tag.strip()
        if not normalized:
            raise ValueError("Tag values cannot be empty.")
        if normalized in seen:
            continue
        cleaned.append(normalized)
        seen.add(normalized)
    return cleaned


def _compute_tag_edit(
    config: Any,
    request: TagEditRequest,
    *,
    facade: StorageMutationFacade | None = None,
    identity: MutationIdentity = MutationIdentity(),
) -> dict[str, Any]:
    """Load, optionally mutate, and return a single transaction by row_hash."""
    if facade is not None:
        return _compute_repository_tag_edit(
            facade,
            identity,
            request,
        )

    from finjuice.pipeline.storage import csv_transactions

    row_hash = request.identifier
    requested_add_tags = _normalize_cli_tags(request.add_tags)
    requested_remove_tags = set(_normalize_cli_tags(request.remove_tags))
    classification_mutation_requested = bool(
        requested_add_tags or requested_remove_tags or request.set_category is not None
    )
    mutation_requested = bool(classification_mutation_requested or request.set_note is not None)

    category_override = request.set_category.strip() if request.set_category is not None else None
    if request.set_category is not None and not category_override:
        raise ValueError("Category override cannot be empty.")

    note_value = request.set_note.strip() if request.set_note is not None else None
    if note_value is not None and len(note_value) > MAX_MANUAL_NOTE_CHARS:
        raise ValueError(f"Manual note cannot exceed {MAX_MANUAL_NOTE_CHARS} characters.")

    partition_df, year, month = csv_transactions.find_transaction_by_hash(
        config.csv_base_dir,
        row_hash,
    )
    target_row = partition_df.filter(pl.col("row_hash") == row_hash).row(0, named=True)

    current_manual_tags, current_category_override = split_manual_tags(
        target_row.get("tags_manual")
    )
    next_manual_tags = [tag for tag in current_manual_tags if tag not in requested_remove_tags]
    next_manual_tags = merge_final_tags(next_manual_tags, requested_add_tags)
    next_category_override = (
        category_override if request.set_category is not None else current_category_override
    )

    persisted_manual_tags = build_manual_tags(next_manual_tags, next_category_override)
    updated_row = dict(target_row)
    updated_row["tags_manual"] = persisted_manual_tags
    if note_value is not None:
        updated_row["notes_manual"] = note_value
    updated_row["tags_final"] = merge_final_tags(
        updated_row.get("tags_rule"),
        updated_row.get("tags_ai"),
        next_manual_tags,
    )
    updated_row["category_final"] = resolve_category_final(
        updated_row.get("category_rule"),
        updated_row.get("minor_raw"),
        updated_row.get("major_raw"),
        tags_manual=persisted_manual_tags,
    )
    if classification_mutation_requested:
        has_manual_input = bool(updated_row["tags_final"]) or next_category_override is not None
        updated_row["confidence"] = 1.0 if has_manual_input else 0.0
        updated_row["needs_review"] = 1 if updated_row["confidence"] < 0.7 else 0

    current_persisted_tags = build_manual_tags(current_manual_tags, current_category_override)
    updated = mutation_requested and (
        normalize_tag_list(current_persisted_tags) != normalize_tag_list(persisted_manual_tags)
        or normalize_tag_list(target_row.get("tags_final"))
        != normalize_tag_list(updated_row["tags_final"])
        or str(target_row.get("notes_manual") or "") != str(updated_row.get("notes_manual") or "")
        or str(target_row.get("category_final") or "") != str(updated_row["category_final"] or "")
        or float(target_row.get("confidence") or 0.0) != float(updated_row["confidence"] or 0.0)
        or int(target_row.get("needs_review") or 0) != int(updated_row["needs_review"])
    )

    if updated and not request.dry_run:
        updated_partition_df = pl.concat(
            [partition_df.filter(pl.col("row_hash") != row_hash), pl.DataFrame([updated_row])],
            how="diagonal_relaxed",
        )
        csv_transactions.write_month(
            updated_partition_df,
            year,
            month,
            authority_data_dir=config.data_dir,
        )
        append_financial_mutation_event(
            config.data_dir,
            {
                "command": "tag",
                "action": "manual_edit",
                "row_hash": row_hash,
                "fields_changed": _changed_tag_edit_fields(target_row, updated_row),
                "change_summary": "manual tag edit updated transaction",
            },
        )

    return {
        "status": "ok",
        "operation": "edit",
        "row_hash": row_hash,
        "dry_run": request.dry_run,
        "updated": updated and not request.dry_run,
        "would_update": updated,
        "partition": {"year": year, "month": month},
        "transaction": present_manual_state(updated_row if mutation_requested else target_row),
    }


def _compute_repository_tag_edit(
    facade: StorageMutationFacade,
    identity: MutationIdentity,
    request: TagEditRequest,
) -> dict[str, Any]:
    """Inspect or mutate one transaction through the active repository authority."""
    identifier = request.identifier
    requested_add = _normalize_cli_tags(request.add_tags)
    requested_remove = _normalize_cli_tags(request.remove_tags)
    category = request.set_category.strip() if request.set_category is not None else None
    if request.set_category is not None and not category:
        raise ValueError("Category override cannot be empty.")
    note = request.set_note.strip() if request.set_note is not None else None
    if note is not None and len(note) > MAX_MANUAL_NOTE_CHARS:
        raise ValueError(f"Manual note cannot exceed {MAX_MANUAL_NOTE_CHARS} characters.")
    edit = ManualTransactionEdit(
        identifier=identifier,
        add_tags=tuple(requested_add),
        remove_tags=tuple(requested_remove),
        category_supplied=request.set_category is not None,
        category=category,
        note_supplied=request.set_note is not None,
        note=note,
    )
    mutation_requested = bool(
        requested_add
        or requested_remove
        or request.set_category is not None
        or request.set_note is not None
    )
    if not mutation_requested:
        transaction = dict(facade.read_manual_transaction(identifier))
        return _repository_tag_edit_result(identifier, transaction, dry_run=False)

    if request.dry_run:
        current = dict(facade.read_manual_transaction(identifier))
        transaction = _preview_repository_edit(current, edit)
        result = _repository_tag_edit_result(identifier, transaction, dry_run=True)
        result["would_update"] = transaction != current
        return result

    receipt = facade.edit_manual_transaction(edit, identity=identity)
    result = _repository_tag_edit_result(identifier, dict(receipt.result), dry_run=False)
    result["updated"] = receipt.state_changed
    result["would_update"] = receipt.state_changed
    result.update(mutation_metadata(identity, receipt))
    return result


def _preview_repository_edit(
    current: dict[str, Any], edit: ManualTransactionEdit
) -> dict[str, Any]:
    """Apply manual-edit semantics in memory for active-repository dry runs."""
    next_state = dict(current)
    remove = set(edit.remove_tags)
    manual_tags = [tag for tag in current.get("tags_manual", []) if tag not in remove]
    manual_tags = merge_final_tags(manual_tags, edit.add_tags)
    category = edit.category if edit.category_supplied else current.get("category_manual")
    classification_requested = bool(edit.add_tags or edit.remove_tags or edit.category_supplied)
    if classification_requested:
        final_tags = merge_final_tags(current.get("tags_rule"), current.get("tags_ai"), manual_tags)
        category_final = next(
            (
                str(value).strip()
                for value in (
                    category,
                    current.get("category_rule"),
                    current.get("minor_raw"),
                    current.get("major_raw"),
                )
                if value is not None and str(value).strip()
            ),
            "미분류",
        )
        next_state.update(
            {
                "tags_manual": manual_tags,
                "tags_final": final_tags,
                "category_manual": category,
                "category_final": category_final,
                "confidence_exact": "1" if final_tags or category is not None else "0",
                "needs_review": not bool(final_tags or category is not None),
            }
        )
    if edit.note_supplied:
        next_state["notes_manual"] = edit.note
    return next_state


def _repository_tag_edit_result(
    identifier: str,
    transaction: dict[str, Any],
    *,
    dry_run: bool,
) -> dict[str, Any]:
    transaction["row_hash"] = identifier
    transaction["notes_manual"] = str(transaction.get("notes_manual") or "")
    return {
        "status": "ok",
        "operation": "edit",
        "row_hash": identifier,
        "dry_run": dry_run,
        "updated": False,
        "would_update": False,
        "partition": None,
        "authority": "repository",
        "transaction": transaction,
    }


def _render_tag_edit(result: dict[str, Any]) -> None:
    """Render manual tag edit result."""
    transaction = result["transaction"]
    if result["updated"]:
        success(f"Updated transaction {result['row_hash']}")
    elif result.get("dry_run") and result.get("would_update"):
        info(f"Would update transaction {result['row_hash']}")
    else:
        info(f"No changes applied for {result['row_hash']}")

    info(f"Merchant: {transaction.get('merchant_raw') or '-'}")
    info(f"Category: {transaction.get('category_final') or '미분류'}")

    category_manual = transaction.get("category_manual")
    info(f"Manual category: {category_manual or '-'}")

    manual_tags = transaction.get("tags_manual") or []
    final_tags = transaction.get("tags_final") or []
    note = transaction.get("notes_manual") or ""
    info(f"Manual tags: {', '.join(manual_tags) if manual_tags else '-'}")
    info(f"Final tags: {', '.join(final_tags) if final_tags else '-'}")
    info(f"Note: {note or '-'}")
