"""
Shared filtering expressions for transaction data.

Provides consistent, well-documented filter expressions to avoid
scattered, inconsistent implementations across the codebase.

This module is the single source of truth for transaction filtering logic.
All commands and modules should import from here instead of writing
inline filter expressions.

Usage (Polars):
    from finjuice.pipeline.filters import exclude_transfers

    df.filter(exclude_transfers())
    df.filter(exclude_transfers() & (pl.col("type_norm") == "expense"))

Usage (SQL):
    from finjuice.pipeline.filters import exclude_transfers_sql

    sql = f"SELECT * FROM transactions WHERE {exclude_transfers_sql()}"
"""

import polars as pl

# Shared with monthly_consumption_summary and sibling consumption SQL templates.
NON_CONSUMPTION_PATTERN = (
    r"(카드대금|카드결제|결제대금|상환|이체|송금|투자|증권|주식|펀드|"
    r"isa|irp|연금|저축|적금|예금|savings?|investment|"
    r"소비제외|금융|금융비용|외화)"
)
_NON_CONSUMPTION_TEXT_COLUMNS = (
    "category_final",
    "major_raw",
    "minor_raw",
    "tags_final",
)


def exclude_transfers() -> pl.Expr:
    """
    Filter expression to exclude confirmed internal transfer pairs.

    Returns a Polars expression that filters out rows where is_transfer == 1
    and transfer_group_id is present. NULL values are treated as non-transfers
    (transfer detection not yet run).

    This is the canonical way to exclude transfers in Polars operations.
    All modules should use this instead of inline filter expressions.

    NULL Handling Strategy:
        - NULL values are INCLUDED (treated as non-transfers)
        - Rationale: Transactions without transfer detection haven't been
          processed yet and should appear in reports by default
        - Implementation: only rows with a confirmed group id are excluded

    Note:
        Polars follows SQL semantics where comparisons with NULL yield NULL
        (excluded from filter). The expression explicitly keeps NULL/blank
        transfer_group_id rows so legacy unpaired candidates stay reportable.

    Returns:
        pl.Expr: Filter expression that evaluates to True for non-transfers.
                 Semantically equivalent to:
                 NOT (is_transfer = 1 AND transfer_group_id is nonblank)

    Example:
        >>> df.filter(exclude_transfers())
        >>> df.filter(exclude_transfers() & (pl.col("amount") < 0))
    """
    return ~_confirmed_transfer_expr()


def exclude_transfers_for(df: pl.DataFrame) -> pl.Expr:
    """
    Return a transfer-exclusion expression compatible with the DataFrame schema.

    New schema frames exclude only confirmed transfer pairs
    (``is_transfer == 1`` with a nonblank ``transfer_group_id``). Legacy/minimal
    frames that only have ``is_transfer`` keep the previous filtering behavior
    by excluding rows where ``is_transfer == 1``.
    """
    if "is_transfer" not in df.columns:
        return pl.lit(True)
    if "transfer_group_id" not in df.columns:
        return pl.col("is_transfer").cast(pl.Int64, strict=False).fill_null(0) == 0
    return exclude_transfers()


def only_transfers() -> pl.Expr:
    """
    Filter expression to select only internal transfers.

    Returns a Polars expression that selects rows where is_transfer == 1 and
    transfer_group_id is present.

    NULL Handling:
        NULL values are EXCLUDED (correctly, as NULL means transfer status
        unknown, not confirmed as transfer).

    Returns:
        pl.Expr: Filter expression that evaluates to True only for confirmed
                 transfers (is_transfer == 1 and transfer_group_id is nonblank).

    Example:
        >>> transfers_df = df.filter(only_transfers())
    """
    return _confirmed_transfer_expr()


def exclude_transfers_sql() -> str:
    """
    SQL WHERE clause fragment for excluding transfers (NULL-safe).

    Returns a SQL expression that can be used in WHERE clauses.
    Handles NULL values correctly by treating them as non-transfers.

    Security Note:
        This function returns a static SQL fragment (no user parameters).
        Safe for string composition in trusted code paths.
        Do NOT concatenate with untrusted user input without parameterization.

        Safe usage::

            WHERE {exclude_transfers_sql()} AND account = ?  -- parameterized

        UNSAFE usage (SQL injection risk)::

            WHERE {exclude_transfers_sql()} AND account = '{user_input}'

    Returns:
        str: SQL WHERE clause fragment that excludes only confirmed transfer pairs.

    Example:
        >>> sql = f"SELECT * FROM transactions WHERE {exclude_transfers_sql()}"
        >>> sql = f"... WHERE {exclude_transfers_sql()} AND amount < 0"
    """
    return (
        "(is_transfer IS NULL OR is_transfer = 0 OR transfer_group_id IS NULL "
        "OR TRIM(CAST(transfer_group_id AS VARCHAR)) = '')"
    )


def exclude_non_consumption_for(df: pl.DataFrame) -> pl.Expr:
    """Exclude savings, transfers, investments, and card-payment-like rows.

    Matches ``NON_CONSUMPTION_PATTERN`` case-insensitively against the
    concatenation of ``category_final``, ``major_raw``, ``minor_raw``, and
    ``tags_final`` — the same fields the monthly_consumption_summary SQL
    template concatenates.

    Returns True for consumption rows (keep). Missing text columns are skipped.
    """
    parts = [
        pl.col(name).cast(pl.Utf8, strict=False).fill_null("")
        for name in _NON_CONSUMPTION_TEXT_COLUMNS
        if name in df.columns
    ]
    if not parts:
        return pl.lit(True)
    haystack = pl.concat_str(parts, separator=" ").str.to_lowercase()
    return ~haystack.str.contains(NON_CONSUMPTION_PATTERN)


def only_transfers_sql() -> str:
    """
    SQL WHERE clause fragment for selecting only transfers.

    Security Note:
        This function returns a static SQL fragment (no user parameters).
        Safe for string composition in trusted code paths.
        See exclude_transfers_sql() for detailed security guidance.

    Returns:
        str: SQL WHERE clause fragment selecting confirmed transfer pairs.

    Example:
        >>> sql = f"SELECT * FROM transactions WHERE {only_transfers_sql()}"
    """
    return (
        "(is_transfer = 1 AND transfer_group_id IS NOT NULL "
        "AND TRIM(CAST(transfer_group_id AS VARCHAR)) <> '')"
    )


def _confirmed_transfer_expr() -> pl.Expr:
    """Return True for rows confirmed as an internal transfer pair."""
    has_group_id = (
        pl.col("transfer_group_id").cast(pl.Utf8, strict=False).fill_null("").str.strip_chars()
        != ""
    )
    return (pl.col("is_transfer").fill_null(0) == 1) & has_group_id
