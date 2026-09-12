"""Tag command for finjuice CLI.

Applies tagging rules to all transactions in CSV partitions.
Split from pipeline.py as part of Issue #269.
"""

import logging
from contextlib import nullcontext
from typing import Any

import typer

from finjuice.pipeline.cli.audit_log import append_financial_mutation_event
from finjuice.pipeline.cli.bulk_repository import (
    compute_repository_tag,
    resolve_bulk_mutation,
)
from finjuice.pipeline.cli.commands.tag_edit import (
    TagEditRequest,
    _compute_tag_edit,
    _render_tag_edit,
)
from finjuice.pipeline.cli.mutation_options import get_mutation_options, with_mutation_options
from finjuice.pipeline.cli.output import (
    ErrorCode,
    ExitCode,
    emit,
    emit_error,
    info,
    success,
    warning,
)
from finjuice.pipeline.cli.utils import (
    get_config,
    get_mutation_facade,
    mutation_identity,
    warn_on_schema_mismatch,
)
from finjuice.pipeline.constants import SCHEMA_VERSION
from finjuice.pipeline.metadata import write_schema_version
from finjuice.pipeline.storage.authority import RepositoryAuthority, legacy_write_lease
from finjuice.pipeline.storage.sqlite.errors import (
    AuthorityError,
    MutationConflictError,
    MutationValidationError,
)

logger = logging.getLogger(__name__)

BULK_TAG_AUDIT_FIELDS = [
    "category_rule",
    "category_final",
    "tags_rule",
    "tags_final",
    "confidence",
    "needs_review",
]


def _count_transaction_partitions(csv_base_dir: Any) -> int:
    """Count transaction CSV partitions without reading private row contents."""
    return sum(1 for _ in csv_base_dir.glob("*/*/transactions.csv"))


def _compute_tag(config: Any, dry_run: bool, json_output: bool) -> dict[str, Any]:
    """Compute tagging results for JSON/text output."""
    from finjuice.pipeline.tagging.pipeline import run_tagging

    rules_path = config.data_dir / "rules.yaml"

    if not rules_path.exists():
        emit_error(
            f"Rules file not found at {rules_path}. "
            "Run 'finjuice init' to create a data directory with a template rules.yaml.",
            error_code=ErrorCode.RULES_FILE_NOT_FOUND,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice init",
            json_output=json_output,
            command="tag",
        )

    logger.info(f"Tagging from rules: {rules_path}")

    result = run_tagging(
        config.csv_base_dir,
        rules_path,
        dry_run=dry_run,
    )

    return {
        "status": "ok",
        "dry_run": dry_run,
        "total": int(result["total"]),
        "tagged": int(result["tagged"]),
        "untagged": int(result["untagged"]),
        "coverage_pct": float(result.get("coverage_pct", 0.0)),
    }


def _render_tag(result: dict[str, Any]) -> None:
    """Render human-readable tagging summary."""
    if result["dry_run"]:
        info("[Dry-run Summary]")
        info(f"  Total transactions: {result['total']}")
        info(f"  Would be tagged: {result['tagged']}")
        info(f"  Would remain untagged: {result['untagged']}")
        warning("No changes written (dry-run mode)")
        return

    success("[OK] Tagging complete:")
    info(f"  Total transactions: {result['total']}")
    info(f"  Tagged: {result['tagged']}")
    info(f"  Untagged: {result['untagged']}")


def _execute_tag_edit_command(
    ctx: typer.Context,
    config: Any,
    request: TagEditRequest,
    json_output: bool,
) -> None:
    """Resolve authority and execute one manual transaction edit command."""
    mutation_options = get_mutation_options(ctx)
    identity = mutation_identity(
        mutation_options.idempotency_key,
        mutation_options.expected_generation,
        mutation_options.expected_revision,
    )
    facade = get_mutation_facade(ctx, config)
    repository_active = isinstance(facade.dispatch().authority, RepositoryAuthority)
    if not repository_active and any(
        value is not None
        for value in (
            mutation_options.idempotency_key,
            mutation_options.expected_generation,
            mutation_options.expected_revision,
        )
    ):
        raise ValueError("Mutation identity options require an active SQLite repository.")
    legacy_mutation_requested = bool(
        request.add_tags
        or request.remove_tags
        or request.set_category is not None
        or request.set_note is not None
    )
    edit_lease = (
        legacy_write_lease(config.data_dir)
        if legacy_mutation_requested and not request.dry_run and not repository_active
        else nullcontext()
    )
    with edit_lease:
        result = _compute_tag_edit(
            config,
            request,
            facade=facade if repository_active else None,
            identity=identity,
        )
        if result["updated"] and not repository_active:
            write_schema_version(config.data_dir, SCHEMA_VERSION)
    emit(result, json_output, _render_tag_edit, command="tag")


def _execute_bulk_tag_command(
    ctx: typer.Context, config: Any, dry_run: bool, json_output: bool
) -> None:
    """Apply rules through the selected authority and render its result."""
    facade, identity = resolve_bulk_mutation(ctx, config)
    if facade is not None:
        result = compute_repository_tag(facade, identity=identity, dry_run=dry_run)
        emit(result, json_output, _render_tag, command="tag")
        return

    result = _compute_tag(config, dry_run, json_output)
    if not dry_run:
        write_schema_version(config.data_dir, SCHEMA_VERSION)
        if int(result["total"]) > 0:
            append_financial_mutation_event(
                config.data_dir,
                {
                    "command": "tag",
                    "action": "bulk_apply",
                    "fields_changed": BULK_TAG_AUDIT_FIELDS,
                    "change_summary": "bulk tag applied to transaction partitions",
                    "changed_rows": int(result["total"]),
                    "partition_count": _count_transaction_partitions(config.csv_base_dir),
                },
            )
    emit(result, json_output, _render_tag, command="tag")


@with_mutation_options
def tag_command(
    ctx: typer.Context,
    edit: str | None = typer.Option(
        None,
        "--edit",
        help="Inspect or edit a transaction's manual tags by row_hash",
    ),
    add_tag: list[str] | None = typer.Option(
        None,
        "--add-tag",
        help="Add one or more manual tags (repeatable)",
    ),
    remove_tag: list[str] | None = typer.Option(
        None,
        "--remove-tag",
        help="Remove one or more manual tags (repeatable)",
    ),
    set_category: str | None = typer.Option(
        None,
        "--set-category",
        help="Persist a manual category override for category_final",
    ),
    set_note: str | None = typer.Option(
        None,
        "--set-note",
        help="Persist a row-level manual note without changing analysis tags",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run/--no-dry-run",
        help="Preview changes without writing to the active storage",
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """
    Apply tagging rules to all transactions in the active storage.

    Loads rules from the canonical config or legacy rules.yaml.
    Updates tags_rule and tags_final fields.

    Use --dry-run to preview changes before applying them.
    """
    config = get_config(ctx)

    try:
        warn_on_schema_mismatch(config.data_dir)

        if edit is None and (
            add_tag or remove_tag or set_category is not None or set_note is not None
        ):
            emit_error(
                "Manual edit flags require --edit <row_hash>.",
                error_code=ErrorCode.INVALID_ARGS,
                exit_code=ExitCode.USAGE_ERROR,
                json_output=json_output,
                command="tag",
            )

        if edit is not None:
            _execute_tag_edit_command(
                ctx,
                config,
                TagEditRequest(
                    identifier=edit,
                    add_tags=add_tag,
                    remove_tags=remove_tag,
                    set_category=set_category,
                    set_note=set_note,
                    dry_run=dry_run,
                ),
                json_output,
            )
            return

        _execute_bulk_tag_command(ctx, config, dry_run, json_output)

    except typer.Exit:
        raise  # Re-raise typer.Exit without modification
    except (AuthorityError, MutationConflictError) as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="tag",
        )
    except MutationValidationError as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="tag",
        )
    except FileNotFoundError as e:
        logger.error("Tagging failed (%s)", type(e).__name__)
        if edit is not None:
            emit_error(
                str(e),
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                json_output=json_output,
                command="tag",
            )
        emit_error(
            f"File not found: {e}",
            error_code=ErrorCode.FILE_NOT_FOUND,
            json_output=json_output,
            command="tag",
        )
    except (ValueError, KeyError, RuntimeError) as e:
        logger.error(f"Tagging failed: {e}", exc_info=True)
        if edit is not None:
            emit_error(
                str(e),
                error_code=ErrorCode.INVALID_ARGS,
                exit_code=ExitCode.VALIDATION_ERROR,
                json_output=json_output,
                command="tag",
            )
        emit_error(
            f"Tagging failed: {e}",
            error_code=ErrorCode.TAGGING_FAILED,
            json_output=json_output,
            command="tag",
        )
    except KeyboardInterrupt:
        emit_error(
            "Tagging cancelled by user.",
            error_code=ErrorCode.USER_CANCELLED,
            exit_code=ExitCode.USER_CANCELLED,
            json_output=json_output,
            command="tag",
        )
    except Exception as e:  # intended catch-all for CLI robustness
        logger.error(f"Unexpected error during tagging: {type(e).__name__}: {e}", exc_info=True)
        emit_error(
            f"Unexpected error: {e}",
            error_code=ErrorCode.UNEXPECTED_ERROR,
            json_output=json_output,
            command="tag",
        )
