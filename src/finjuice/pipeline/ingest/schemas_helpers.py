"""Sheet-name matching helpers for Banksalad ingest schemas.

Owns case/space-insensitive sheet-name normalization and asset-sheet
candidate detection. Column mapping stays in
:mod:`finjuice.pipeline.ingest.schemas`, which re-exports these helpers
so existing callers can keep importing from that module.
"""

from __future__ import annotations

ASSET_SHEET_NAME_CANDIDATES = ("자산", "보유종목", "assets", "holdings")

ASSET_SHEET_NAME_NORMALIZED = {
    "".join(ch for ch in name.strip().lower() if ch not in {" ", "_", "-"})
    for name in ASSET_SHEET_NAME_CANDIDATES
}


def normalize_sheet_name(sheet_name: str) -> str:
    """
    Normalize sheet name for case/space-insensitive matching.

    Args:
        sheet_name: Raw sheet name

    Returns:
        Normalized sheet name
    """
    return "".join(ch for ch in sheet_name.strip().lower() if ch not in {" ", "_", "-"})


def is_asset_sheet_name(sheet_name: str) -> bool:
    """
    Check if a sheet name is an asset snapshot candidate.

    Args:
        sheet_name: Raw sheet name

    Returns:
        True if sheet likely contains asset snapshots
    """
    return normalize_sheet_name(sheet_name) in ASSET_SHEET_NAME_NORMALIZED
