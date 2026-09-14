"""Account nature versus asset-class and liquidity policy tokens.

Account kind (deposit, pension, IRP) is not a liquidity or asset-class
policy. Callers must set those policies on resources explicitly.
"""

from __future__ import annotations

from typing import Final

ACCOUNT_KINDS: Final = frozenset(
    {
        "deposit.v1",
        "broker.v1",
        "pension.v1",
        "irp.v1",
    }
)
ASSET_CLASSES: Final = frozenset({"cash.v1", "equity.v1", "fund.v1"})
LIQUIDITY_POLICIES: Final = frozenset({"liquid.v1", "restricted.v1"})


def liquidity_for_account_kind(account_kind: str) -> None:
    """Return None. Liquidity is never inferred from account nature."""
    del account_kind
    return None
