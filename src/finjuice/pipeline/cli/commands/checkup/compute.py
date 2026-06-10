"""Bundle collection for the ``finjuice checkup`` command."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from finjuice.pipeline.checkup import CheckupBundle
from finjuice.pipeline.config import Config

# TODO: engine split tracked in a follow-up to #654; this CLI layer now exposes
# compute/detector/rendering boundaries while the Python bundle engine remains stable.


@dataclass(frozen=True)
class CheckupOptions:
    """Normalized options for collecting a checkup bundle."""

    config: Config
    stale_after_days: int = 35


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
        )
    )
