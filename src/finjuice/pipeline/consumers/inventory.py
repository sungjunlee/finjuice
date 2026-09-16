"""Known CLI, Hermes, analysis, cron, and script consumers of finjuice data.

This catalog is the cutover inventory for issue #439. It names execution
paths, not host-specific locations. Private data-dir and overlay paths stay
outside this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ConsumerKind = Literal[
    "cli",
    "data_dir",
    "hermes_skill",
    "analysis_report",
    "cron",
    "manual_script",
]
AccessMode = Literal["read", "write"]
Authority = Literal["csv", "sqlite_revision"]

SCHEMA_VERSION = "finjuice.consumers.v1"


@dataclass(frozen=True)
class ConsumerSpec:
    """One inventoried read or write consumer of a data-dir profile."""

    consumer_id: str
    kind: ConsumerKind
    access: AccessMode
    cli_path: str | None = None
    skill_name: str | None = None

    def to_public_dict(self) -> dict[str, str | None]:
        """Return a privacy-safe inventory row."""
        return {
            "consumer_id": self.consumer_id,
            "kind": self.kind,
            "access": self.access,
            "cli_path": self.cli_path,
            "skill_name": self.skill_name,
        }


def _cli(consumer_id: str, cli_path: str, access: AccessMode) -> ConsumerSpec:
    return ConsumerSpec(
        consumer_id=consumer_id,
        kind="cli",
        access=access,
        cli_path=cli_path,
    )


def _skill(consumer_id: str, skill_name: str, access: AccessMode) -> ConsumerSpec:
    return ConsumerSpec(
        consumer_id=consumer_id,
        kind="hermes_skill",
        access=access,
        skill_name=skill_name,
    )


def _report(consumer_id: str, cli_path: str) -> ConsumerSpec:
    return ConsumerSpec(
        consumer_id=consumer_id,
        kind="analysis_report",
        access="read",
        cli_path=cli_path,
    )


KNOWN_CONSUMERS: tuple[ConsumerSpec, ...] = (
    ConsumerSpec(consumer_id="data_dir.runtime", kind="data_dir", access="read"),
    _cli("cli.show", "show", "read"),
    _cli("cli.status", "status", "read"),
    _cli("cli.query", "query", "read"),
    _cli("cli.explain", "explain", "read"),
    _cli("cli.template", "template", "read"),
    _cli("cli.review", "review", "read"),
    _cli("cli.checkup", "checkup", "read"),
    _cli("cli.doctor", "doctor", "read"),
    _cli("cli.index", "index", "read"),
    _cli("cli.inspect", "inspect", "read"),
    _cli("cli.assets", "assets", "read"),
    _cli("cli.networth", "networth", "read"),
    _cli("cli.budget", "budget", "read"),
    _cli("cli.context", "context", "read"),
    _cli("cli.ingest", "ingest", "write"),
    _cli("cli.tag", "tag", "write"),
    _cli("cli.transfer", "transfer", "write"),
    _cli("cli.import", "import", "write"),
    _cli("cli.refresh", "refresh", "write"),
    _cli("cli.rules", "rules", "write"),
    _cli("cli.reconcile", "reconcile", "write"),
    _cli("cli.export", "export", "read"),
    _cli("cli.backup", "backup", "read"),
    _cli("cli.automation", "automation", "read"),
    _skill("hermes.finjuice", "finjuice", "read"),
    _skill("hermes.finjuice-onboard", "finjuice-onboard", "write"),
    _skill("hermes.finjuice-curate", "finjuice-curate", "write"),
    _skill("hermes.finjuice-rule-cleanup", "finjuice-rule-cleanup", "write"),
    _skill("hermes.finjuice-review", "finjuice-review", "read"),
    _skill("hermes.finjuice-report", "finjuice-report", "read"),
    _skill("hermes.finjuice-diagnose", "finjuice-diagnose", "read"),
    _report("analysis.export_report", "export"),
    _report("analysis.template_report", "template"),
    _report("analysis.html_report", "export"),
    ConsumerSpec(
        consumer_id="cron.automation",
        kind="cron",
        access="read",
        cli_path="automation",
    ),
    ConsumerSpec(
        consumer_id="script.manual",
        kind="manual_script",
        access="write",
        cli_path=None,
    ),
)


def known_consumers() -> tuple[ConsumerSpec, ...]:
    """Return the frozen inventory of known consumers."""
    return KNOWN_CONSUMERS


def consumer_ids() -> frozenset[str]:
    """Return inventoried consumer identifiers."""
    return frozenset(spec.consumer_id for spec in KNOWN_CONSUMERS)


def get_consumer(consumer_id: str) -> ConsumerSpec:
    """Return one inventoried consumer or raise ``KeyError``."""
    for spec in KNOWN_CONSUMERS:
        if spec.consumer_id == consumer_id:
            return spec
    raise KeyError(consumer_id)


def consumers_by_kind(kind: ConsumerKind) -> tuple[ConsumerSpec, ...]:
    """Return inventoried consumers of one kind."""
    return tuple(spec for spec in KNOWN_CONSUMERS if spec.kind == kind)
