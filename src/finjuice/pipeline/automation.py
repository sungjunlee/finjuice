"""Reusable one-shot automation signal collection for workflow automation.

Pending-import, tagging-pressure, large-transaction, and next-step helpers live
in :mod:`finjuice.pipeline.automation_helpers` and are re-exported here so
existing callers can keep importing from this module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from finjuice.pipeline.automation_helpers import (
    AutomationHint,
    LargeTransactionSample,
    LargeTransactionSignal,
    MerchantPressureSample,
    PendingImportFailure,
    PendingImportFile,
    PendingImportsSignal,
    TaggingPressureSignal,
    _build_next_steps,
    _collect_large_transactions,
    _collect_pending_imports,
    _collect_tagging_pressure,
)
from finjuice.pipeline.config import Config


@dataclass(frozen=True)
class AutomationSummary:
    """Stable Python-level summary that later CLI surfaces can render."""

    data_dir: str
    actionable: bool
    pending_imports: PendingImportsSignal
    tagging_pressure: TaggingPressureSignal
    large_transactions: LargeTransactionSignal
    next_steps: list[AutomationHint]
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        """Serialize the summary for JSON or text rendering."""
        return asdict(self)


def collect_automation_signals(
    config: Config,
    *,
    large_transaction_threshold: int,
    import_sample_limit: int = 3,
    merchant_sample_limit: int = 5,
    merchant_min_count: int = 2,
    large_transaction_sample_limit: int = 5,
) -> AutomationSummary:
    """Collect a one-shot automation summary from existing pipeline surfaces."""
    if large_transaction_threshold < 0:
        raise ValueError("large_transaction_threshold must be >= 0")

    pending_imports = _collect_pending_imports(
        config=config,
        sample_limit=import_sample_limit,
    )

    warnings: list[str] = []
    tagging_pressure, tagging_warning = _collect_tagging_pressure(
        config=config,
        sample_limit=merchant_sample_limit,
        min_count=merchant_min_count,
    )
    if tagging_warning:
        warnings.append(tagging_warning)

    if large_transaction_threshold == 0:
        large_transactions = LargeTransactionSignal(
            status="clear",
            threshold=0,
            count=0,
            samples=[],
        )
    else:
        large_transactions, anomaly_warning = _collect_large_transactions(
            config=config,
            threshold=large_transaction_threshold,
            sample_limit=large_transaction_sample_limit,
        )
        if anomaly_warning:
            warnings.append(anomaly_warning)

    actionable = any(
        signal.status == "present"
        for signal in (pending_imports, tagging_pressure, large_transactions)
    )

    return AutomationSummary(
        data_dir=str(config.data_dir),
        actionable=actionable,
        pending_imports=pending_imports,
        tagging_pressure=tagging_pressure,
        large_transactions=large_transactions,
        next_steps=_build_next_steps(
            pending_imports=pending_imports,
            tagging_pressure=tagging_pressure,
            large_transactions=large_transactions,
        ),
        warnings=list(dict.fromkeys(warnings)),
    )


__all__ = [
    "AutomationHint",
    "AutomationSummary",
    "LargeTransactionSample",
    "LargeTransactionSignal",
    "MerchantPressureSample",
    "PendingImportFailure",
    "PendingImportFile",
    "PendingImportsSignal",
    "TaggingPressureSignal",
    "collect_automation_signals",
]
