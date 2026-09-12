"""Stable markers for exact XLSX import identity and manifests."""

from __future__ import annotations

from typing import Final

COMMAND_SCOPE: Final = "import.exact_xlsx"
IMPORT_POLICY_VERSION: Final = "finjuice.exact-import.v1"
PARSER_POLICY_VERSION: Final = "retain_completed_interpretation.v1"
MANIFEST_KIND: Final = "finjuice.exact_xlsx_import.v1"
MANIFEST_COORDINATE_KIND: Final = "exact_xlsx_import_manifest"
OCCURRENCE_KIND: Final = "exact_xlsx_import"
UNRESOLVED_ACCOUNT_KIND: Final = "unresolved.v1"
UNRESOLVED_RESOURCE_KIND: Final = "unresolved.v1"


def parser_versions() -> dict[str, str]:
    """Return mapper build versions stored on completed manifests and provenance."""
    from finjuice.pipeline.ingest import exact_assets, exact_overview, exact_transactions

    return {
        "assets": exact_assets.PARSER_VERSION,
        "import_policy": IMPORT_POLICY_VERSION,
        "overview": exact_overview.PARSER_VERSION,
        "parser_policy": PARSER_POLICY_VERSION,
        "temporal_policy": exact_transactions.TEMPORAL_POLICY,
        "transactions": exact_transactions.PARSER_VERSION,
    }
