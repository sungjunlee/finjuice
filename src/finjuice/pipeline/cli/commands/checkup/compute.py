"""Bundle collection for the ``finjuice checkup`` command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from finjuice.pipeline.checkup import CheckupBundle
from finjuice.pipeline.config import Config

# CLI boundary: compute collects facts, detector decides diagnoses, rendering
# serializes payloads. The Python bundle engine stays in pipeline.checkup.


@dataclass(frozen=True)
class CheckupOptions:
    """Normalized options for collecting a checkup bundle."""

    config: Config
    stale_after_days: int = 35
    fast: bool = False


@dataclass(frozen=True)
class CheckupFacts:
    """Collected checkup facts passed to detector and rendering stages."""

    bundle: CheckupBundle


@dataclass(frozen=True)
class CheckupDependencies:
    """Patchable dependencies used by the checkup command wrapper."""

    collect_checkup_bundle: Callable[..., CheckupBundle]


def collect_checkup_facts(
    options: CheckupOptions,
    *,
    dependencies: CheckupDependencies,
) -> CheckupFacts:
    """Collect the Python-level checkup bundle without rendering."""
    return CheckupFacts(
        bundle=dependencies.collect_checkup_bundle(
            options.config,
            stale_after_days=options.stale_after_days,
            fast=options.fast,
        )
    )
