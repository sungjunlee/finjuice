"""Add/remove implementations for rules CLI commands.

Candidate upsert, dry-run impact preview, and human rendering live in
:mod:`finjuice.pipeline.cli.commands.rules_cmd.mutations_helpers`.
"""

from collections.abc import Callable
from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any, NoReturn, Optional

import typer
from click.core import ParameterSource

from finjuice.pipeline.cli.mutation_options import get_mutation_options, with_mutation_options
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, emit
from finjuice.pipeline.cli.utils import (
    get_config,
    get_mutation_facade,
    mutation_identity,
    mutation_metadata,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.constants import DEFAULT_RULE_PRIORITY
from finjuice.pipeline.storage.authority import RepositoryAuthority, legacy_write_lease
from finjuice.pipeline.storage.mutation_facade import (
    ConfigDocument,
    ConfigMutation,
    ConfigTransformResult,
    MutationIdentity,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.sqlite.errors import AuthorityError, MutationConflictError

from .mutations_helpers import (
    _compute_rule_impact_preview,
    _render_rule_mutation,
    _upsert_candidate_rules,
)
from .shared import (
    _append_rule_mutation_audit_event,
    _build_rule_dict_from_cli,
    _emit_rules_error,
    _serialize_rule_payload,
    _serialize_validation_summary,
)


@dataclass(frozen=True)
class RuleAddRequest:
    """Stable parsed CLI inputs for a rule upsert."""

    name: str
    match_pattern: str
    tags: str
    category: Optional[str]
    priority: int
    fields: str
    dry_run: bool
    json_output: bool
    explicit_optional_fields: frozenset[str] | None = None

    @property
    def update_fields(self) -> frozenset[str]:
        """Return optional fields the caller explicitly requested to change."""
        if self.explicit_optional_fields is None:
            return frozenset({"category", "priority", "fields"})
        return self.explicit_optional_fields


def _compute_add_rule(
    config: Config,
    request: RuleAddRequest,
    *,
    facade: StorageMutationFacade | None = None,
    identity: MutationIdentity = MutationIdentity(),
) -> dict[str, Any]:
    """Compute the result payload for `finjuice rules add`."""
    from finjuice.pipeline.tagging.models import TagRule

    command = "rules add"

    try:
        validated_dict = _build_rule_dict_from_cli(
            name=request.name,
            match_pattern=request.match_pattern,
            tags=request.tags,
            category=request.category,
            priority=request.priority,
            fields=request.fields,
        )
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules add --help",
            json_output=request.json_output,
            command=command,
        )
    candidate_rule = TagRule(**validated_dict)
    if facade is not None:
        return _compute_repository_rule_add(
            candidate_rule,
            validated_dict,
            request,
            facade,
            identity,
        )

    return _compute_legacy_rule_add(config, candidate_rule, validated_dict, request)


def _compute_repository_rule_add(
    candidate_rule: Any,
    validated_dict: dict[str, Any],
    request: RuleAddRequest,
    facade: StorageMutationFacade,
    identity: MutationIdentity,
) -> dict[str, Any]:
    """Apply one rule upsert to the active config head."""
    command = "rules add"
    if request.dry_run:
        _emit_rules_error(
            "Repository-backed rule impact preview is not available yet.",
            error_code=ErrorCode.SIMULATION_FAILED,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=request.json_output,
            command=command,
        )
    semantic_rule: dict[str, Any] = {
        "name": candidate_rule.name,
        "match": candidate_rule.match,
        "tags": list(candidate_rule.tags),
    }
    optional_values = {
        "category": candidate_rule.category,
        "priority": candidate_rule.priority,
        "fields": list(candidate_rule.fields),
    }
    semantic_rule.update({field: optional_values[field] for field in sorted(request.update_fields)})
    try:
        receipt = facade.mutate_config(
            ConfigMutation(
                "rules",
                {"action": "upsert", "rule": semantic_rule},
                _upsert_rule_transform(validated_dict, request.update_fields),
            ),
            identity=identity,
            reason=f"rule upsert: {candidate_rule.name}",
        )
    except (KeyError, ValueError) as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=request.json_output,
            command=command,
        )
    result = dict(receipt.result)
    result.update(mutation_metadata(identity, receipt))
    return result


def _compute_legacy_rule_add(
    config: Config,
    candidate_rule: Any,
    validated_dict: dict[str, Any],
    request: RuleAddRequest,
) -> dict[str, Any]:
    """Validate, preview, or persist one legacy rules.yaml upsert."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules, load_rules_bytes
    from finjuice.pipeline.tagging.rules_yaml_roundtrip import upsert_rule_roundtrip_bytes
    from finjuice.pipeline.tagging.validator import validate_rules

    command = "rules add"

    try:
        existing_rules = load_rules(config.rules_file)
    except ValueError as exc:
        _emit_rules_error(
            f"Failed to load rules: {exc}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=request.json_output,
            command=command,
        )

    try:
        action, _ = _upsert_candidate_rules(existing_rules, candidate_rule)
        current_content = config.rules_file.read_bytes() if config.rules_file.exists() else None
        updated_content = upsert_rule_roundtrip_bytes(
            validated_dict,
            current_content,
            update=action == "updated",
            explicit_fields=request.update_fields,
        )
        candidate_rules = load_rules_bytes(updated_content)
        merged_rule = _find_single_rule(candidate_rules, candidate_rule.name)
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=request.json_output,
            command=command,
        )
    except OSError as exc:
        _emit_rules_error(
            f"Failed to read rules file: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=request.json_output,
            command=command,
        )

    validation_result = validate_rules(candidate_rules)
    if validation_result.has_errors:
        _emit_rules_error(
            "Rule set validation failed. Resolve duplicate rule names and retry.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=request.json_output,
            command=command,
        )

    result: dict[str, Any] = {
        "action": action,
        "rule": _serialize_rule_payload(merged_rule),
        "validation": _serialize_validation_summary(validation_result),
    }

    if request.dry_run:
        return _preview_legacy_rule_add(
            config,
            merged_rule,
            request.json_output,
            action,
            result,
        )

    from finjuice.pipeline.tagging.rules_yaml_io import add_rule_roundtrip, update_rule_roundtrip

    try:
        if action == "updated":
            update_rule_roundtrip(
                validated_dict,
                config.rules_file,
                authority_data_dir=config.data_dir,
                explicit_fields=request.update_fields,
            )
        else:
            add_rule_roundtrip(
                validated_dict,
                config.rules_file,
                authority_data_dir=config.data_dir,
            )
    except KeyError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.RULE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules validate",
            json_output=request.json_output,
            command=command,
        )
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=request.json_output,
            command=command,
        )
    except OSError as exc:
        _emit_rules_error(
            f"Failed to write rules file: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=request.json_output,
            command=command,
        )

    _append_rule_mutation_audit_event(
        config,
        command=command,
        action=action,
        rule_name=merged_rule.name,
        change_summary=f"rule {action}",
    )
    return result


def _preview_legacy_rule_add(
    config: Config,
    merged_rule: Any,
    json_output: bool,
    action: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    """Attach transaction impact metadata to a legacy rule preview."""
    result.update(
        {
            "dry_run": True,
            "dry_run_action": action,
            "preview_action": "would_update" if action == "updated" else "would_add",
            "rules_file_modified": False,
        }
    )
    impact_preview = _compute_merged_rule_impact_preview(config, merged_rule, json_output)
    result["impact"] = dict(impact_preview)
    if action == "updated":
        result["impact"]["note"] = (
            "coverage_after omitted for updates: preview shows merged rule "
            "matches only and cannot subtract rows lost from the old rule."
        )
    else:
        result["coverage_after"] = float(impact_preview["coverage_after"])
    return result


def _find_single_rule(rules: list[Any], name: str) -> Any:
    matches = [rule for rule in rules if rule.name == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one merged rule named '{name}'.")
    return matches[0]


def _compute_merged_rule_impact_preview(
    config: Config,
    rule: Any,
    json_output: bool,
) -> dict[str, Any]:
    """Preview the matcher that the merged rule will actually use."""
    if not rule.conditions and rule.enabled:
        return _compute_rule_impact_preview(
            config,
            match_pattern=rule.match,
            field_list=list(rule.fields),
            json_output=json_output,
            command="rules add",
        )

    from finjuice.pipeline.storage.csv_transactions import get_all_transactions
    from finjuice.pipeline.tagging.matcher import _get_rule_match

    if not config.csv_base_dir.exists() or not any(
        config.csv_base_dir.glob("*/*/transactions.csv")
    ):
        _emit_rules_error(
            f"No transaction data found at {config.csv_base_dir}.",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            suggestion="finjuice ingest",
            json_output=json_output,
            command="rules add",
        )

    try:
        transactions = get_all_transactions(config.csv_base_dir)
    except (OSError, ValueError) as exc:
        _emit_rules_error(
            f"Dry-run impact preview failed: {exc}",
            error_code=ErrorCode.SIMULATION_FAILED,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=json_output,
            command="rules add",
        )

    matched_transactions = 0
    matched_amount = 0.0
    tagged_transactions = 0
    newly_tagged_transactions = 0
    for row in transactions.iter_rows(named=True):
        tags = row.get("tags_final")
        is_tagged = isinstance(tags, list) and bool(tags)
        tagged_transactions += int(is_tagged)
        if not rule.enabled or not _get_rule_match(row, rule):
            continue
        matched_transactions += 1
        matched_amount += float(row.get("amount") or 0.0)
        newly_tagged_transactions += int(not is_tagged)

    total_transactions = transactions.height
    coverage_after = (
        ((tagged_transactions + newly_tagged_transactions) / total_transactions) * 100
        if total_transactions
        else 0.0
    )
    serialized = _serialize_rule_payload(rule)
    matcher = "conditions" if rule.enabled else "disabled"
    matcher_detail = (
        {"conditions": serialized["conditions"], "logic": rule.logic}
        if rule.conditions
        else {
            "patterns": [part.strip() for part in rule.match.split("|") if part.strip()],
            "fields": list(rule.fields),
        }
    )
    return {
        "matcher": matcher,
        **matcher_detail,
        "matched_transactions": matched_transactions,
        "total_amount": matched_amount,
        "coverage_after": coverage_after,
    }


def _upsert_rule_transform(
    validated_dict: dict[str, Any],
    explicit_fields: frozenset[str],
) -> Callable[[bytes | None], ConfigTransformResult]:
    """Build a lock-scoped rules upsert from stable CLI intent."""
    from finjuice.pipeline.tagging.models import TagRule
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes
    from finjuice.pipeline.tagging.rules_yaml_roundtrip import upsert_rule_roundtrip_bytes
    from finjuice.pipeline.tagging.validator import validate_rules

    candidate_rule = TagRule(**validated_dict)

    def transform(content: bytes | None) -> ConfigTransformResult:
        existing_rules = load_rules_bytes(content or b"version: 1\nrules: []\n")
        action, _ = _upsert_candidate_rules(existing_rules, candidate_rule)
        updated_content = upsert_rule_roundtrip_bytes(
            validated_dict,
            content,
            update=action == "updated",
            explicit_fields=explicit_fields,
        )
        candidate_rules = load_rules_bytes(updated_content)
        merged_rule = _find_single_rule(candidate_rules, candidate_rule.name)
        validation_result = validate_rules(candidate_rules)
        if validation_result.has_errors:
            raise ValueError("Rule set validation failed. Resolve duplicate rule names and retry.")
        return ConfigTransformResult(
            document=ConfigDocument.from_validated_yaml(
                "rules", updated_content, parser_version="finjuice.rules.v1"
            ),
            result={
                "action": action,
                "rule": _serialize_rule_payload(merged_rule),
                "validation": _serialize_validation_summary(validation_result),
            },
        )

    return transform


def _explicit_rule_optional_fields(ctx: typer.Context) -> frozenset[str]:
    """Capture CLI option presence before validator defaults are applied."""
    return frozenset(
        field
        for field in ("category", "priority", "fields")
        if ctx.get_parameter_source(field) not in {None, ParameterSource.DEFAULT}
    )


@with_mutation_options
def add_rule_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Rule name (letters, numbers, underscores)"),
    match_pattern: str = typer.Option(..., "--match", help="Pipe-separated regex patterns"),
    tags: str = typer.Option(..., "--tags", help="Comma-separated tags"),
    category: Optional[str] = typer.Option(None, "--category", help="Optional category"),
    priority: int = typer.Option(
        DEFAULT_RULE_PRIORITY,
        "--priority",
        help="Rule priority (0-100, higher runs first)",
    ),
    fields: str = typer.Option(
        "merchant_raw",
        "--fields",
        help="Comma-separated transaction fields to match",
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Preview impact without writing"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Add or update a tagging rule programmatically."""
    config = get_config(ctx)
    options = get_mutation_options(ctx)
    try:
        active_facade, identity = _rules_mutation_runtime(
            ctx,
            config,
            options.idempotency_key,
            options.expected_generation,
            options.expected_revision,
        )
        edit_lease = (
            legacy_write_lease(config.data_dir)
            if active_facade is None and not dry_run
            else nullcontext()
        )
        with edit_lease:
            result = _compute_add_rule(
                config,
                RuleAddRequest(
                    name=name,
                    match_pattern=match_pattern,
                    tags=tags,
                    category=category,
                    priority=priority,
                    fields=fields,
                    dry_run=dry_run,
                    json_output=json_output,
                    explicit_optional_fields=_explicit_rule_optional_fields(ctx),
                ),
                facade=active_facade,
                identity=identity,
            )
    except typer.Exit:
        raise
    except (AuthorityError, MutationConflictError, ValueError) as exc:
        _emit_rules_runtime_error(exc, json_output=json_output, command="rules add")
    emit(result, json_output, _render_rule_mutation, command="rules add")


def _compute_remove_rule(
    config: Config,
    *,
    name: str,
    json_output: bool,
    facade: StorageMutationFacade | None = None,
    identity: MutationIdentity = MutationIdentity(),
) -> dict[str, Any]:
    """Compute the result payload for `finjuice rules remove`."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules, remove_rule_roundtrip

    command = "rules remove"

    if facade is not None:
        try:
            receipt = facade.mutate_config(
                ConfigMutation(
                    "rules",
                    {"action": "remove", "name": name},
                    _remove_rule_transform(name),
                ),
                identity=identity,
                reason=f"rule removed: {name}",
            )
        except KeyError:
            _emit_rules_error(
                f"Rule not found: {name}",
                error_code=ErrorCode.RULE_NOT_FOUND,
                exit_code=ExitCode.USAGE_ERROR,
                suggestion="finjuice rules validate",
                json_output=json_output,
                command=command,
            )
        except ValueError as exc:
            _emit_rules_error(
                str(exc),
                error_code=ErrorCode.VALIDATION_FAILED,
                exit_code=ExitCode.VALIDATION_ERROR,
                suggestion="finjuice rules validate",
                json_output=json_output,
                command=command,
            )
        result = dict(receipt.result)
        result.update(mutation_metadata(identity, receipt))
        return result

    try:
        existing_rules = load_rules(config.rules_file)
    except ValueError as exc:
        _emit_rules_error(
            f"Failed to load rules: {exc}",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )

    matching_rules = [rule for rule in existing_rules if rule.name == name]
    if not matching_rules:
        _emit_rules_error(
            f"Rule not found: {name}",
            error_code=ErrorCode.RULE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    if len(matching_rules) > 1:
        _emit_rules_error(
            f"Multiple rules named '{name}' found. Resolve duplicates before removing.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )

    try:
        remove_rule_roundtrip(
            name,
            config.rules_file,
            authority_data_dir=config.data_dir,
        )
    except KeyError:
        _emit_rules_error(
            f"Rule not found: {name}",
            error_code=ErrorCode.RULE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    except ValueError as exc:
        _emit_rules_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            suggestion="finjuice rules validate",
            json_output=json_output,
            command=command,
        )
    except OSError as exc:
        _emit_rules_error(
            f"Failed to write rules file: {exc}",
            error_code=ErrorCode.FILE_ACCESS_ERROR,
            exit_code=ExitCode.GENERAL_ERROR,
            json_output=json_output,
            command=command,
        )

    _append_rule_mutation_audit_event(
        config,
        command=command,
        action="removed",
        rule_name=name,
        change_summary="rule removed",
    )
    return {"action": "removed", "rule_name": name}


def _remove_rule_transform(name: str) -> Callable[[bytes | None], ConfigTransformResult]:
    """Build a lock-scoped rules removal from stable CLI intent."""
    from finjuice.pipeline.tagging.rules_yaml_io import load_rules_bytes
    from finjuice.pipeline.tagging.rules_yaml_roundtrip import remove_rule_roundtrip_bytes

    def transform(content: bytes | None) -> ConfigTransformResult:
        if content is None:
            raise KeyError(name)
        rules = load_rules_bytes(content)
        matching_rules = [rule for rule in rules if rule.name == name]
        if not matching_rules:
            raise KeyError(name)
        if len(matching_rules) > 1:
            raise ValueError(
                f"Multiple rules named '{name}' found. Resolve duplicates before removing."
            )
        updated_content = remove_rule_roundtrip_bytes(name, content)
        return ConfigTransformResult(
            document=ConfigDocument.from_validated_yaml(
                "rules", updated_content, parser_version="finjuice.rules.v1"
            ),
            result={"action": "removed", "rule_name": name},
        )

    return transform


@with_mutation_options
def remove_rule_command(
    ctx: typer.Context,
    name: str = typer.Option(..., "--name", help="Rule name to remove"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Remove a tagging rule by name."""
    config = get_config(ctx)
    options = get_mutation_options(ctx)
    try:
        active_facade, identity = _rules_mutation_runtime(
            ctx,
            config,
            options.idempotency_key,
            options.expected_generation,
            options.expected_revision,
        )
        edit_lease = legacy_write_lease(config.data_dir) if active_facade is None else nullcontext()
        with edit_lease:
            result = _compute_remove_rule(
                config,
                name=name,
                json_output=json_output,
                facade=active_facade,
                identity=identity,
            )
    except typer.Exit:
        raise
    except (AuthorityError, MutationConflictError, ValueError) as exc:
        _emit_rules_runtime_error(exc, json_output=json_output, command="rules remove")
    emit(result, json_output, _render_rule_mutation, command="rules remove")


def _rules_mutation_runtime(
    ctx: typer.Context,
    config: Config,
    idempotency_key: str | None,
    expected_generation: str | None,
    expected_revision: int | None,
) -> tuple[StorageMutationFacade | None, MutationIdentity]:
    """Resolve common mutation identity and authority for a rules command."""
    identity = mutation_identity(idempotency_key, expected_generation, expected_revision)
    facade = get_mutation_facade(ctx, config)
    if isinstance(facade.dispatch().authority, RepositoryAuthority):
        return facade, identity
    if any(
        value is not None for value in (idempotency_key, expected_generation, expected_revision)
    ):
        raise ValueError("Mutation identity options require an active SQLite repository.")
    return None, identity


def _emit_rules_runtime_error(
    exc: Exception,
    *,
    json_output: bool,
    command: str,
) -> NoReturn:
    """Emit a structured envelope for authority, identity, and concurrency failures."""
    conflict = isinstance(exc, MutationConflictError)
    _emit_rules_error(
        str(exc),
        error_code=ErrorCode.VALIDATION_FAILED if conflict else ErrorCode.INVALID_ARGS,
        exit_code=ExitCode.VALIDATION_ERROR if conflict else ExitCode.USAGE_ERROR,
        json_output=json_output,
        command=command,
    )
    raise AssertionError("rules error emitter returned unexpectedly")
