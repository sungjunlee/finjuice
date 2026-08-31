"""JSON payload helpers for ``finjuice rules suggest``.

Owns compute-error emission, apply-audit callbacks, and the JSON payload
wrapper around tagging suggest compute. The Typer command stays in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.suggest`, which re-exports
these helpers so existing callers can keep importing from that module.
"""

from __future__ import annotations

from typing import Any

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit_error
from finjuice.pipeline.cli.privacy import PrivacyProfile
from finjuice.pipeline.config import Config
from finjuice.pipeline.tagging.suggest_compute import (
    SuggestComputeError,
    _compute_rules_suggest_json,
)

from .shared import _append_rule_mutation_audit_event


def _audit_applied_suggestion(config: Config, rule_name: str) -> None:
    _append_rule_mutation_audit_event(
        config,
        command="rules suggest",
        action="applied",
        rule_name=rule_name,
        change_summary="suggestion rule applied",
    )


def _emit_suggest_compute_error(
    exc: SuggestComputeError,
    *,
    json_output: bool,
    privacy: PrivacyProfile,
) -> None:
    emit_error(
        exc.message,
        error_code=ErrorCode(exc.error_code),
        exit_code=ExitCode(exc.exit_code),
        suggestion=exc.suggestion,
        json_output=json_output,
        command="rules suggest",
        privacy=privacy,
    )


def _rules_suggest_json_payload(
    config: Config,
    privacy: PrivacyProfile,
    json_output: bool,
    compute_kwargs: dict[str, Any],
) -> dict[str, Any]:
    try:
        return _compute_rules_suggest_json(
            config=config,
            json_output=json_output,
            on_applied=lambda rule_name: _audit_applied_suggestion(config, rule_name),
            **compute_kwargs,
        )
    except SuggestComputeError as exc:
        _emit_suggest_compute_error(exc, json_output=json_output, privacy=privacy)
        raise
