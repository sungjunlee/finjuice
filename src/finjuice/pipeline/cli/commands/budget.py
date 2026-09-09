"""Budget commands backed by goals.yaml.

Human rendering lives in :mod:`finjuice.pipeline.cli.commands.budget_rendering`
and is re-exported here so existing callers can keep importing from this
module. Validation error envelopes live in
:mod:`finjuice.pipeline.cli.commands.budget_errors`.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import typer

from finjuice.pipeline.budget_compute import (
    BUDGET_EDIT_UPDATE_HINT,
    BudgetEditCancelledError,
    GoalsFileInvalidError,
    compute_budget_edit,
    compute_budget_edit_bytes,
    compute_budget_status,
    compute_budget_validate,
)
from finjuice.pipeline.cli.commands.budget_errors import _raise_goals_validation_error
from finjuice.pipeline.cli.commands.budget_period import resolve_budget_period
from finjuice.pipeline.cli.commands.budget_rendering import (
    BUDGET_SPEND_INCLUSION,
    _display_change_value,  # noqa: F401 — re-exported for existing budget imports
    _format_currency,  # noqa: F401 — re-exported for existing budget imports
    _format_progress,  # noqa: F401 — re-exported for existing budget imports
    _render_budget_edit,
    _render_budget_status,
    _render_budget_validate,
    _render_unmatched_goal_warning,  # noqa: F401 — re-exported for existing budget imports
    _style_status,  # noqa: F401 — re-exported for existing budget imports
)
from finjuice.pipeline.cli.mutation_options import get_mutation_options, with_mutation_options
from finjuice.pipeline.cli.output import ErrorCode, ExitCode, _build_meta, emit_error
from finjuice.pipeline.cli.report_filters import load_cli_report_filters
from finjuice.pipeline.cli.utils import (
    get_config,
    get_mutation_facade,
    mutation_identity,
    mutation_metadata,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.mutation_facade import (
    ConfigDocument,
    ConfigMutation,
    ConfigTransformResult,
)
from finjuice.pipeline.storage.sqlite.errors import AuthorityError, MutationConflictError

budget_app = typer.Typer(
    name="budget",
    help="Track declarative monthly budgets from goals.yaml",
    no_args_is_help=True,
)

_BUDGET_EDIT_REASON = "budget values edited"


@budget_app.command("status")
def budget_status_command(
    ctx: typer.Context,
    month: str | None = typer.Option(None, "--month", help="Budget month (YYYY-MM)"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Show monthly budget targets vs actual consumption spend.

    Spend excludes savings/transfers/investments matching the shared
    non-consumption pattern used by monthly_consumption_summary.
    """
    config = get_config(ctx)
    try:
        resolved_month = resolve_budget_period(month, csv_base_dir=config.csv_base_dir)
        result = compute_budget_status(
            config,
            month=resolved_month,
            load_report_filters=lambda: load_cli_report_filters(
                ctx,
                config,
                command="budget status",
                json_output=json_output,
            ),
        )
    except GoalsFileInvalidError as exc:
        _raise_goals_validation_error(
            command="budget status",
            problems=exc.problems,
            json_output=json_output,
        )
    except ValueError as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="budget status",
        )
    if json_output:
        meta = _build_meta(
            "budget status",
            extras={
                "filters_applied": result["_filters_applied"],
                "month": result["month"],
                "inclusion": BUDGET_SPEND_INCLUSION,
            },
        )
        payload = {k: v for k, v in result.items() if not k.startswith("_")}
        typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))
        return

    _render_budget_status(result)


@budget_app.command("edit")
@with_mutation_options
def budget_edit_command(
    ctx: typer.Context,
    updates: list[str] = typer.Option(
        [],
        "--set",
        metavar="KEY=VALUE",
        help=("Update one field in goals.yaml. " + BUDGET_EDIT_UPDATE_HINT),
    ),
    yes: bool = typer.Option(False, "--yes", help="Skip the confirmation prompt"),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Edit monthly budget values in goals.yaml while preserving comments."""
    if not updates:
        emit_error(
            "At least one --set KEY=VALUE update is required",
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="budget edit",
        )

    config = get_config(ctx)
    options = get_mutation_options(ctx)
    try:
        identity = mutation_identity(
            options.idempotency_key,
            options.expected_generation,
            options.expected_revision,
        )
        facade = get_mutation_facade(ctx, config)
        repository_active = isinstance(facade.dispatch().authority, RepositoryAuthority)
        if not repository_active and any(
            value is not None
            for value in (
                options.idempotency_key,
                options.expected_generation,
                options.expected_revision,
            )
        ):
            raise ValueError("Mutation identity options require an active SQLite repository.")
        if repository_active:
            mutation = ConfigMutation(
                "goals",
                {"action": "budget_edit", "updates": updates},
                _budget_edit_transform(config, updates),
            )
            receipt = facade.find_config_mutation_replay(
                mutation,
                identity=identity,
                reason=_BUDGET_EDIT_REASON,
            )
            if receipt is not None:
                result = dict(receipt.result)
                result.update(mutation_metadata(identity, receipt))
                _emit_budget_edit(result, json_output=json_output)
                return
            identity = facade.pin_identity(identity)
            current_content = facade.read_config_bytes("goals")
            compute_budget_edit_bytes(config, current_content, updates=updates)
            if not yes and not typer.confirm(
                f"Write {len(updates)} change(s) to the active goals config?",
                default=False,
            ):
                raise BudgetEditCancelledError()
            receipt = facade.mutate_config(
                mutation,
                identity=identity,
                reason=_BUDGET_EDIT_REASON,
            )
            result = dict(receipt.result)
            result.update(mutation_metadata(identity, receipt))
        else:
            result = compute_budget_edit(
                config,
                updates=updates,
                confirm=(
                    None
                    if yes
                    else lambda count: typer.confirm(
                        f"Write {count} change(s) to {config.goals_file}?",
                        default=False,
                    )
                ),
            )
    except GoalsFileInvalidError as exc:
        _raise_goals_validation_error(
            command="budget edit",
            problems=exc.problems,
            json_output=json_output,
        )
    except BudgetEditCancelledError:
        raise typer.Exit(code=ExitCode.USER_CANCELLED) from None
    except (AuthorityError, MutationConflictError) as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="budget edit",
        )
    except ValueError as exc:
        emit_error(
            str(exc),
            error_code=ErrorCode.INVALID_ARGS,
            exit_code=ExitCode.USAGE_ERROR,
            json_output=json_output,
            command="budget edit",
        )
    _emit_budget_edit(result, json_output=json_output)


def _emit_budget_edit(result: dict[str, object], *, json_output: bool) -> None:
    """Render one budget edit or replay result."""
    if json_output:
        meta = _build_meta("budget edit")
        payload = {k: v for k, v in result.items() if not k.startswith("_")}
        typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))
        return
    _render_budget_edit(result)


def _budget_edit_transform(
    config: Config,
    updates: list[str],
) -> Callable[[bytes | None], ConfigTransformResult]:
    """Build a lock-scoped goals edit from stable CLI update strings."""

    def transform(content: bytes | None) -> ConfigTransformResult:
        result, updated_content = compute_budget_edit_bytes(
            config,
            content,
            updates=updates,
        )
        return ConfigTransformResult(
            document=ConfigDocument.from_validated_yaml(
                "goals", updated_content, parser_version="finjuice.goals.v1"
            ),
            result=result,
        )

    return transform


@budget_app.command("validate")
def budget_validate_command(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Validate goals.yaml against the monthly_budget schema."""
    config = get_config(ctx)
    result = compute_budget_validate(config)
    payload = {k: v for k, v in result.items() if not k.startswith("_")}

    if json_output:
        meta = _build_meta("budget validate")
        typer.echo(json.dumps({"_meta": meta, **payload}, ensure_ascii=False, indent=2))
    else:
        _render_budget_validate(result)

    if result["_has_errors"]:
        raise typer.Exit(ExitCode.VALIDATION_ERROR)
