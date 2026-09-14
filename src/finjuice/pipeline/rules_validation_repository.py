"""Canonical configuration-only rule diagnostics from one analysis snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from finjuice.pipeline.analysis_source import analysis_metadata, read_analysis_source
from finjuice.pipeline.storage.authority import ActivationEvidenceProvider
from finjuice.pipeline.tagging.models import RuleValidationError, TagRule
from finjuice.pipeline.tagging.rules_yaml_io import (
    load_report_filters_bytes,
    load_rules_collecting_bytes,
)


@dataclass(frozen=True)
class RepositoryRulesValidation:
    """Loaded rules plus collected errors and pinned source metadata."""

    rules: list[TagRule]
    errors: list[RuleValidationError]
    metadata: dict[str, object]
    total_rules: int = 0


def load_repository_rules_validation(
    data_dir: Path, provider: ActivationEvidenceProvider | None = None, *, strict: bool = False
) -> RepositoryRulesValidation | None:
    """Diagnose selected bytes without requiring complete transaction projections."""
    snapshot = read_analysis_source(data_dir, provider)
    if snapshot is None:
        return None
    selection = snapshot.rules
    head = selection.head
    metadata = analysis_metadata(snapshot, "canonical_rules_validation.v1")
    metadata["rules_revision_id"] = head.revision_id if head is not None else None
    if head is None:
        message = (
            "Canonical rules are absent."
            if selection.selection_state == "absent" and not selection.revisions
            else "Canonical rules require explicit selection."
        )
        return RepositoryRulesValidation(
            [],
            [
                RuleValidationError(
                    rule_index=-1,
                    rule_name="Canonical rules",
                    message=message,
                    suggestion=None,
                )
            ],
            metadata,
        )
    try:
        load_report_filters_bytes(head.content)
        loaded = load_rules_collecting_bytes(
            head.content, validate_condition_regex=True, strict=strict
        )
        rules = loaded.rules
        errors = [_safe_rule_error(error) for error in loaded.errors]
    except Exception:
        raise ValueError("Canonical rules could not be loaded for validation.") from None
    total_rules = len(rules) + len(errors)
    if selection.selection_state != "selected" or head.parsed_status != "parsed":
        errors.append(
            RuleValidationError(
                rule_index=-1,
                rule_name="Canonical rules",
                message="Canonical rules selection is not marked parsed.",
                suggestion=None,
            )
        )
    return RepositoryRulesValidation(rules, errors, metadata, total_rules)


def _safe_rule_error(error: RuleValidationError) -> RuleValidationError:
    """Keep source indices without serializing malformed names or raw field values."""
    regex_message = "Rule condition contains an invalid regular expression."
    return RuleValidationError(
        rule_index=error.rule_index,
        rule_name=f"Rule at index {error.rule_index}",
        message=(
            regex_message
            if error.message == regex_message
            else "Canonical rule does not satisfy the schema."
        ),
        suggestion=None,
    )
