"""Consumer inventory and isolated cutover compatibility path (issue #439).

Public names are defined in :mod:`inventory` and :mod:`compat`. Installing
this package does not switch operational authority off CSV.
"""

from finjuice.pipeline.consumers.compat import (
    CUTOVER_ISSUE,
    FENCE_PROCEDURE,
    LOCK_FILENAME,
    AnalysisReport,
    ConsumerCutoverError,
    ConsumerRead,
    DatasetPin,
    IsolatedCutover,
    LegacyCsvWriteBlockedError,
    ManualState,
    OverlayAlreadyAppliedError,
    OverlayApplyResult,
    OverlayBinding,
    RuntimeDefaults,
    attempt_direct_csv_write,
    operational_defaults,
    overlay_digest,
)
from finjuice.pipeline.consumers.inventory import (
    SCHEMA_VERSION,
    ConsumerSpec,
    consumer_ids,
    consumers_by_kind,
    get_consumer,
    known_consumers,
)

__all__ = [
    "CUTOVER_ISSUE",
    "FENCE_PROCEDURE",
    "LOCK_FILENAME",
    "SCHEMA_VERSION",
    "AnalysisReport",
    "ConsumerCutoverError",
    "ConsumerRead",
    "ConsumerSpec",
    "DatasetPin",
    "IsolatedCutover",
    "LegacyCsvWriteBlockedError",
    "ManualState",
    "OverlayAlreadyAppliedError",
    "OverlayApplyResult",
    "OverlayBinding",
    "RuntimeDefaults",
    "attempt_direct_csv_write",
    "consumer_ids",
    "consumers_by_kind",
    "get_consumer",
    "known_consumers",
    "operational_defaults",
    "overlay_digest",
]
