"""Next-step composition for one-shot workflow automation.

Owns CLI-oriented next-step hints. Tagging-pressure helpers live in
:mod:`finjuice.pipeline.automation_tagging_pressure`. Large-transaction
helpers live in :mod:`finjuice.pipeline.automation_large_transactions`.
Pending-import preview helpers live in
:mod:`finjuice.pipeline.automation_pending_imports`. Sibling collectors are
re-exported here so existing callers can keep importing from this module.
Public ``collect_automation_signals`` stays in :mod:`finjuice.pipeline.automation`.
"""

from __future__ import annotations

from dataclasses import dataclass

from finjuice.pipeline.automation_large_transactions import (
    LargeTransactionSample,  # noqa: F401 — re-exported for existing automation imports
    LargeTransactionSignal,
    _collect_large_transactions,  # noqa: F401 — re-exported for existing automation imports
    _optional_text,  # noqa: F401 — re-exported for existing automation imports
)
from finjuice.pipeline.automation_pending_imports import (
    PendingImportFailure,  # noqa: F401 — re-exported for existing automation imports
    PendingImportFile,  # noqa: F401 — re-exported for existing automation imports
    PendingImportsSignal,
    SignalStatus,  # noqa: F401 — re-exported for existing automation imports
    _basename,  # noqa: F401 — re-exported for existing automation imports
    _collect_pending_imports,  # noqa: F401 — re-exported for existing automation imports
)
from finjuice.pipeline.automation_tagging_pressure import (
    MerchantPressureSample,  # noqa: F401 — re-exported for existing automation imports
    TaggingPressureSignal,
    _collect_tagging_pressure,  # noqa: F401 — re-exported for existing automation imports
)


@dataclass(frozen=True)
class AutomationHint:
    """Existing commands a caller can surface as next-step guidance."""

    signal: str
    message: str
    command: str


def _build_next_steps(
    *,
    pending_imports: PendingImportsSignal,
    tagging_pressure: TaggingPressureSignal,
    large_transactions: LargeTransactionSignal,
) -> list[AutomationHint]:
    """Build CLI-oriented next-step hints without inventing new commands."""
    next_steps: list[AutomationHint] = []

    if pending_imports.status == "present":
        next_steps.append(
            AutomationHint(
                signal="pending_imports",
                message="New import files look ready for a one-shot pipeline pass.",
                command="finjuice refresh",
            )
        )

    if tagging_pressure.status == "present":
        next_steps.append(
            AutomationHint(
                signal="tagging_pressure",
                message=(
                    "Rule-suggestable untagged transactions are accumulating and need rule review."
                ),
                command="finjuice rules suggest",
            )
        )

    if large_transactions.status == "present":
        next_steps.append(
            AutomationHint(
                signal="large_transactions",
                message="Review large-expense anomalies with the existing template surface.",
                command=(
                    "finjuice template run anomaly_large_txn "
                    f"--param threshold={large_transactions.threshold}"
                ),
            )
        )

    return next_steps
