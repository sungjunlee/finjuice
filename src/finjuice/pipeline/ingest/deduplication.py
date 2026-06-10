"""
Row Hash & Deduplication for transaction ingestion.

Provides content-based hashing for idempotent deduplication of transactions
across multiple Banksalad XLSX exports.
"""

import hashlib
from pathlib import Path
from typing import Any, Dict

from finjuice.pipeline.constants import HASH_LENGTH_CHARS


def calculate_row_hash(row: Dict[str, Any]) -> str:
    """
    Calculate unique hash for transaction deduplication.

    Uses only immutable bank data to generate a stable hash:
    - date, time, type, merchant, amount, currency, account

    Excludes mutable fields that may change over time:
    - major_category, minor_category (Banksalad's auto-categorization changes)
    - memo (user-editable notes)

    This ensures that re-importing the same transaction data produces the same hash,
    even if categories or memos have been updated in Banksalad.

    Args:
        row: Transaction dict with standardized column names from map_columns()

    Returns:
        str: SHA256 hash truncated to HASH_LENGTH_CHARS (16 characters)
             Optimized for token efficiency while maintaining <0.5% collision
             probability for realistic datasets (~100K transactions).

             See: finjuice.pipeline.constants.HASH_LENGTH_CHARS for rationale.

    Raises:
        ValueError: If required fields are missing or empty

    Example:
        >>> row = {
        ...     'date': '2025-10-27',
        ...     'time': '19:24',
        ...     'type': '지출',
        ...     'merchant': '스타벅스',
        ...     'amount': -5000,
        ...     'currency': 'KRW',
        ...     'account': '체크카드',
        ... }
        >>> hash_value = calculate_row_hash(row)
        >>> len(hash_value)
        10
    """
    required_fields = ["date", "time", "type", "merchant", "amount", "currency", "account"]

    # Validate required fields are present and not empty
    # Note: Empty string, None, and 0 are all checked, but 0 is valid for amount
    missing = []
    for field in required_fields:
        value = row.get(field)
        # Special case: 0 is valid for amount (could be a zero-value transaction)
        if field == "amount":
            if value is None or value == "":
                missing.append(field)
        else:
            if not value:  # Checks for None, empty string, etc.
                missing.append(field)

    if missing:
        raise ValueError(f"Cannot calculate hash: missing required fields {missing}")

    # Build hash string (order matters for consistency)
    # Strip whitespace from string fields to handle Excel formatting
    hash_parts = [
        str(row["date"]).strip(),
        str(row["time"]).strip(),
        str(row["type"]).strip(),
        str(row["merchant"]).strip(),
        str(row["amount"]),  # Number field - no strip needed
        str(row["currency"]).strip(),
        str(row["account"]).strip(),
    ]

    # Use pipe separator and UTF-8 encoding for consistent hashing
    hash_string = "|".join(hash_parts)
    # Truncate to HASH_LENGTH_CHARS for token efficiency
    return hashlib.sha256(hash_string.encode("utf-8")).hexdigest()[:HASH_LENGTH_CHARS]


def build_source_id(file_path: str, row_num: int) -> str:
    """
    Build source identifier for transaction traceability.

    The source ID format is "filename:rowN" where filename is extracted from
    the full path and N is the row number in the original XLSX file.

    Args:
        file_path: Full or relative path to source XLSX file
        row_num: Row number in source file (0-based or 1-based depending on usage)

    Returns:
        str: Source identifier in format "filename.xlsx:rowN"

    Example:
        >>> build_source_id('/path/to/data.xlsx', 42)
        'data.xlsx:row42'
        >>> build_source_id('imports/banksalad.xlsx', 1)
        'banksalad.xlsx:row1'
    """
    filename = Path(file_path).name
    return f"{filename}:row{row_num}"
