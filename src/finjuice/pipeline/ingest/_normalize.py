"""
Transaction type and amount normalization.

Pure functions for normalizing Korean transaction types and amount signs.
"""

import logging

from ..constants import MAX_REASONABLE_AMOUNT_KRW, MIN_REASONABLE_AMOUNT_KRW

logger = logging.getLogger(__name__)


def _normalize_type(type_raw: str) -> str:
    """
    Normalize transaction type from Korean to standard English values.

    Maps Korean type labels to standardized values:
    - expense: 지출, 출금, etc.
    - income: 수입, 입금, etc.
    - transfer: 이체
    - other: Everything else

    Args:
        type_raw: Raw transaction type from XLSX (Korean)

    Returns:
        str: Normalized type (expense|income|transfer|other)

    Example:
        >>> _normalize_type('지출')
        'expense'
        >>> _normalize_type('입금')
        'income'
        >>> _normalize_type('이체')
        'transfer'
    """
    if not type_raw:
        return "other"

    type_lower = str(type_raw).lower()

    if "지출" in type_lower or "출금" in type_lower:
        return "expense"
    elif "수입" in type_lower or "입금" in type_lower:
        return "income"
    elif "이체" in type_lower:
        return "transfer"
    else:
        return "other"


def _normalize_amount(amount: float, type_raw: str, row_idx: int | None = None) -> float:
    """
    Validate and normalize amount sign based on transaction type.

    Banksalad exports should already have signed amounts, but we validate
    that the sign matches the transaction type for data quality assurance.

    Amount sign rules:
    - 지출/출금 (expense/withdrawal): Normally negative
      - BUT positive amount = REFUND (keep positive to reduce total spend)
    - 수입/입금 (income/deposit): Must be positive
    - 이체 (transfer): Either sign is acceptable

    Refund handling:
    - Banksalad marks refunds as "지출" with positive amount
    - We keep the positive amount so monthly_spend aggregation works correctly
    - Example: 현대백화점 환불 +127,000원 reduces that month's total spending

    Args:
        amount: Amount value from XLSX
        type_raw: Transaction type (지출/수입/이체/etc.)
        row_idx: Optional row index for logging (default: None)

    Returns:
        float: Amount with appropriate sign

    Example:
        >>> _normalize_amount(-5000, '지출')
        -5000
        >>> _normalize_amount(5000, '지출')  # Refund - keep positive
        5000
        >>> _normalize_amount(-100000, '수입')  # Wrong sign, corrected
        100000
    """
    amount = float(amount)
    row_ref = f" at row {row_idx}" if row_idx else ""

    # Amount range validation (warning only, no hard fail) - Issue #91
    if abs(amount) > MAX_REASONABLE_AMOUNT_KRW:
        logger.warning(f"비정상적으로 큰 금액 감지{row_ref}")

    if 0 < abs(amount) < MIN_REASONABLE_AMOUNT_KRW:
        logger.warning(f"비정상적으로 작은 금액 감지{row_ref}")

    if "지출" in type_raw or "출금" in type_raw:
        # Expenses should be negative, but positive amount indicates REFUND
        if amount > 0:
            # This is a refund/cancellation - keep positive so it reduces total spend
            # Example: 현대백화점 환불 +127,000원 should reduce monthly spending
            logger.info(f"환불 감지{row_ref}: {type_raw}, 양수 유지")
            return amount  # Keep positive - refund reduces total spend
        return amount  # Already negative or zero

    elif "수입" in type_raw or "입금" in type_raw:
        # Income should be positive
        if amount < 0:
            logger.warning(
                f"Type='{type_raw}' but amount is negative{row_ref}. "
                f"Data quality issue. Using positive value."
            )
            return abs(amount)
        return amount  # Already positive or zero

    elif "이체" in type_raw:
        # Transfers can be either sign (outgoing = negative, incoming = positive)
        return amount

    else:
        # Unknown type - preserve amount and log warning
        logger.warning(f"Unknown type: '{type_raw}'{row_ref}, keeping amount as-is")
        return amount
