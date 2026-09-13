"""Checkup command stable entrypoint and thin Typer wrapper."""

from __future__ import annotations

import typer

from finjuice.pipeline.checkup import collect_checkup_bundle
from finjuice.pipeline.checkup.repository_inputs import RepositoryCheckupError
from finjuice.pipeline.cli.output import ErrorCode, emit, emit_error, info
from finjuice.pipeline.cli.privacy import (
    PrivacyProfile,
    apply_privacy_profile,
    privacy_meta,
)
from finjuice.pipeline.cli.utils import get_activation_evidence_provider, get_config

from . import rendering as _rendering
from .compute import (
    CheckupDependencies,
    CheckupFacts,
    CheckupOptions,
    collect_checkup_facts,
)
from .detector import CheckupDiagnoses, detect_checkup_diagnoses
from .rendering import (
    CheckupDomainsPayload,
    CheckupNextActionPayload,
    CheckupPayload,
    CheckupPayloadBase,
    CheckupSummaryPayload,
    CompactCheckupPayload,
    render_text,
    serialize_checkup,
    serialize_checkup_payload,
)

__all__ = [
    "CheckupDependencies",
    "CheckupDiagnoses",
    "CheckupDomainsPayload",
    "CheckupFacts",
    "CheckupNextActionPayload",
    "CheckupOptions",
    "CheckupPayload",
    "CheckupPayloadBase",
    "CheckupSummaryPayload",
    "CompactCheckupPayload",
    "collect_checkup_bundle",
    "collect_checkup_facts",
    "detect_checkup_diagnoses",
    "register_checkup_command",
    "render_text",
    "serialize_checkup",
    "serialize_checkup_payload",
]


def _dependencies() -> CheckupDependencies:
    """Build dependencies from package globals for testability."""
    return CheckupDependencies(collect_checkup_bundle=collect_checkup_bundle)


def register_checkup_command(app: typer.Typer) -> None:
    """Register the checkup command with the root Typer app."""

    @app.command(name="checkup", rich_help_panel="Analysis")
    def checkup_command(
        ctx: typer.Context,
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        privacy: PrivacyProfile = typer.Option(
            PrivacyProfile.RAW,
            "--privacy",
            help="Privacy profile for JSON output: raw, redacted, or compact",
        ),
        stale_after: int = typer.Option(
            35,
            "--stale-after",
            help="Days after which data is considered stale (default: 35)",
        ),
        fast: bool = typer.Option(
            False,
            "--fast",
            help="Cheap posture summary; skip full detectors.",
        ),
    ) -> None:
        """
        Emit the recommended read-only runtime snapshot for agent inspect/decide loops.

        Pattern:
            agent -> `finjuice checkup --json` -> choose the next explicit finjuice command

        Use --fast for a cheap posture summary that skips full detectors.

        The finjuice CLI only emits structured data. It does not execute side effects here.
        """
        config = get_config(ctx)
        try:
            facts = collect_checkup_facts(
                CheckupOptions(
                    config=config,
                    stale_after_days=stale_after,
                    fast=fast,
                    evidence_provider=get_activation_evidence_provider(ctx),
                ),
                dependencies=_dependencies(),
            )
        except RepositoryCheckupError as exc:
            emit_error(
                str(exc),
                error_code=ErrorCode.INSPECTION_FAILED,
                json_output=json_output,
                command="checkup",
            )
            return
        diagnoses = detect_checkup_diagnoses(facts)
        result = serialize_checkup(facts, diagnoses)
        # Privacy profiles apply to both JSON and text rendering — the redacted
        # and compact profiles must not leak raw 원 amounts to the terminal
        # either. JSON output applies the profile as-is; text output also
        # honors the profile so `_format_won` renders nulled-out amounts as "-".
        output_result = (
            apply_privacy_profile(result, privacy, compact=_rendering._compact_checkup)
            if json_output or privacy is not PrivacyProfile.RAW
            else result
        )
        meta_extras = {**privacy_meta(privacy), **(facts.bundle.repository or {})}
        if fast:
            meta_extras = {**meta_extras, "fast": True}
        if facts.bundle.repository is not None and not json_output:
            source = facts.bundle.repository
            info(
                f"Repository revision {source['dataset_revision']} "
                f"({source['dataset_generation']}); policy {source['calculation_policy']}; "
                f"as of {source['calculation_as_of']}"
            )
        emit(
            output_result,
            json_output,
            lambda result: typer.echo(_rendering._render_text(result)),
            command="checkup",
            meta_extras=meta_extras,
        )
