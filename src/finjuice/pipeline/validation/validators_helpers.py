"""Column-name matching helpers for Banksalad XLSX validation.

Owns fuzzy column-name suggestions and sanitized error-message column lists.
XLSX load/schema validation stays in
:mod:`finjuice.pipeline.validation.validators`, which re-exports these helpers
so existing callers can keep importing from that module.
"""

from __future__ import annotations

from difflib import get_close_matches

# Maximum column name length in error messages
MAX_COLUMN_NAME_LENGTH = 50


def _suggest_column_mapping(
    missing_cols: set[str],
    actual_cols: set[str],
    cutoff: float = 0.5,
) -> dict[str, str]:
    """
    Suggest mappings for missing columns based on fuzzy string matching.

    Uses difflib.get_close_matches to find similar column names.
    Uses a moderate cutoff (0.5) to catch Korean character typos.

    Args:
        missing_cols: Set of required columns that are missing
        actual_cols: Set of actual column names from the DataFrame
        cutoff: Similarity threshold (0.0-1.0, default: 0.5)

    Returns:
        dict: Mapping of missing column to suggested column name

    Example:
        >>> _suggest_column_mapping({'날짜'}, {'날자', '시간'})
        {'날짜': '날자'}
        >>> _suggest_column_mapping({'결제수단'}, {'결제방법', '카드'})
        {'결제수단': '결제방법'}
    """
    suggestions = {}

    for missing in missing_cols:
        # Try to find close matches
        matches = get_close_matches(missing, actual_cols, n=1, cutoff=cutoff)
        if matches and matches[0] != missing:
            # Only suggest if it's not an exact match (shouldn't happen, but just in case)
            suggestions[missing] = matches[0]

    return suggestions


def _sanitize_column_names(cols: set[str], max_length: int = MAX_COLUMN_NAME_LENGTH) -> str:
    """
    Sanitize column names for error messages.

    Limits column name length to prevent exposing excessive information.

    Args:
        cols: Set of column names
        max_length: Maximum length per column name (default: 50)

    Returns:
        str: Comma-separated sanitized column names
    """
    sanitized = [col[:max_length] for col in sorted(cols)]
    return ", ".join(sanitized)
