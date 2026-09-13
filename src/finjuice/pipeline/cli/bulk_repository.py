"""CLI presentation and dispatch for authoritative bulk mutations."""

from __future__ import annotations

from typing import Any

import typer

from finjuice.pipeline.cli.mutation_options import get_mutation_options
from finjuice.pipeline.cli.utils import (
    get_mutation_facade,
    mutation_identity,
    mutation_metadata,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.mutation_facade import (
    BulkMutationPreview,
    MutationIdentity,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.sqlite.bulk_tagging import BulkTagCommand
from finjuice.pipeline.storage.sqlite.bulk_transfer import BulkTransferCommand
from finjuice.pipeline.storage.sqlite.errors import MutationValidationError
from finjuice.pipeline.storage.sqlite.mutations import MutationReceipt


def resolve_bulk_mutation(
    ctx: typer.Context, config: Config
) -> tuple[StorageMutationFacade | None, MutationIdentity]:
    """Resolve authority and reject repository-only options on legacy storage."""
    options = get_mutation_options(ctx)
    try:
        identity = mutation_identity(
            options.idempotency_key, options.expected_generation, options.expected_revision
        )
    except ValueError as exc:
        raise MutationValidationError(str(exc)) from exc
    facade = get_mutation_facade(ctx, config)
    if isinstance(facade.dispatch().authority, RepositoryAuthority):
        return facade, identity
    if any(
        value is not None
        for value in (
            identity.idempotency_key,
            identity.expected_generation,
            identity.expected_revision,
        )
    ):
        raise MutationValidationError(
            "Mutation identity options require an active SQLite repository."
        )
    return None, identity


def compute_repository_tag(
    facade: StorageMutationFacade,
    *,
    identity: MutationIdentity = MutationIdentity(),
    dry_run: bool = False,
) -> dict[str, Any]:
    """Present counts from the same snapshot that computes the derived tags."""
    receipt = facade.recompute_tags(BulkTagCommand(), identity=identity, dry_run=dry_run)
    counts = receipt.result
    total, tagged = int(counts["total"]), int(counts["tagged"])
    return {
        "status": "ok",
        "dry_run": dry_run,
        "total": total,
        "tagged": tagged,
        "untagged": int(counts["untagged"]),
        "coverage_pct": 100.0 * tagged / total if total else 0.0,
        "updated": int(counts["updated"]),
        **_metadata(identity, receipt),
    }


def compute_repository_transfer(
    facade: StorageMutationFacade,
    *,
    identity: MutationIdentity = MutationIdentity(),
    dry_run: bool = False,
) -> dict[str, Any]:
    """Present exact pairing counts without reading a second repository snapshot."""
    receipt = facade.recompute_transfers(BulkTransferCommand(), identity=identity, dry_run=dry_run)
    counts = receipt.result
    return {
        "status": "ok",
        "dry_run": dry_run,
        "candidate_rows": int(counts["candidate_rows"]),
        "candidates_considered": int(counts["candidates_considered"]),
        "pairs_found": int(counts["pairs_found"]),
        "pairs_linked": int(counts["pairs_linked"]),
        "confirmed_transfer_rows": int(counts["confirmed_transfer_rows"]),
        "unconfirmed_candidate_rows": int(counts["unconfirmed_candidate_rows"]),
        "unsupported": int(counts["unsupported"]),
        "updated": int(counts["updated"]),
        **_metadata(identity, receipt),
    }


def _metadata(
    identity: MutationIdentity, receipt: MutationReceipt | BulkMutationPreview
) -> dict[str, Any]:
    if isinstance(receipt, BulkMutationPreview):
        return {
            "authority": "repository",
            "dataset_revision": receipt.dataset_revision,
            "state_changed": False,
            "would_change": bool(receipt.result["changed"]),
        }
    return mutation_metadata(identity, receipt)
