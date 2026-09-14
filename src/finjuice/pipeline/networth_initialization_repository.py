"""Initialize absent canonical assets without replacing preserved configuration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from finjuice.pipeline.asset_config import validate_assets_config_bytes
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.mutation_facade import (
    ConfigDocument,
    MutationIdentity,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot

# An activated starter must not register the example file's fictitious holdings.
_STARTER = b"version: 1\nmanual_assets: []\nliabilities: []\n"


def initialize_repository_assets(
    data_dir: Path, provider: ActivationEvidenceProvider | None = None
) -> dict[str, Any] | None:
    """Create an empty selected config only when its pinned inventory is absent."""
    snapshot = read_portfolio_snapshot(data_dir, provider)
    if snapshot is None:
        return None
    selection = snapshot.assets
    created = selection.selection_state == "absent" and not selection.revisions
    revision = snapshot.info.dataset_revision
    revision_id = selection.head.revision_id if selection.head else None
    changeset_id = None
    if created:
        if not validate_assets_config_bytes(_STARTER).is_valid:
            raise ValueError("Canonical assets starter is invalid.")
        receipt = StorageMutationFacade(data_dir, provider).replace_config(
            ConfigDocument.from_validated_yaml(
                "assets", _STARTER, parser_version="canonical_assets_starter.v1"
            ),
            identity=MutationIdentity(
                expected_generation=snapshot.info.dataset_generation,
                expected_revision=revision,
            ),
        )
        revision = receipt.committed_revision
        revision_id = str(receipt.result["revision_id"])
        changeset_id = receipt.changeset_id
    return {
        "path": None,
        "created": created,
        "message": (
            "Created empty canonical assets configuration."
            if created
            else "Canonical assets evidence already exists; run networth validate."
        ),
        "authority": "repository",
        "selection_state": "selected" if created else selection.selection_state,
        "revision_id": revision_id,
        "_repository_meta": {
            "authority": "repository",
            "dataset_generation": snapshot.info.dataset_generation,
            "dataset_revision": revision,
            "sqlite_schema_version": snapshot.info.schema_version,
            "calculation_policy": "canonical_assets_initialization.v1",
            "changeset_id": changeset_id,
        },
    }
