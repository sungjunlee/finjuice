"""Configuration-only assets validation from one canonical portfolio snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.asset_config import AssetsConfigValidationResult
from finjuice.pipeline.checkup.repository_inputs import checkup_assets
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.storage.read_facade import read_portfolio_snapshot


class NetworthValidationReadError(ValueError):
    """Static failure to read canonical configuration evidence."""


@dataclass(frozen=True)
class RepositoryAssetsValidation:
    """Validated selected assets plus their detached source identity."""

    validation: AssetsConfigValidationResult
    metadata: dict[str, object]
    selection_state: str
    revision_id: str | None


def compute_repository_networth_validate(
    data_dir: Path, provider: ActivationEvidenceProvider | None = None
) -> RepositoryAssetsValidation | None:
    """Validate assets only, without materializing or requiring complete transactions."""
    try:
        snapshot = read_portfolio_snapshot(data_dir, provider)
        if snapshot is None:
            return None
        selection = snapshot.assets
        return RepositoryAssetsValidation(
            checkup_assets(selection),
            {
                "authority": "repository",
                "dataset_generation": snapshot.info.dataset_generation,
                "dataset_revision": snapshot.info.dataset_revision,
                "sqlite_schema_version": snapshot.info.schema_version,
                "calculation_policy": "canonical_assets_validation.v1",
                "assets_selection_state": selection.selection_state,
            },
            selection.selection_state,
            selection.head.revision_id if selection.head else None,
        )
    except Exception:
        raise NetworthValidationReadError(
            "Canonical assets validation could not be read."
        ) from None
