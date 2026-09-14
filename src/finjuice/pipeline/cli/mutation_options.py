"""Reusable Typer registration for authoritative mutation identity options."""

from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar, cast

import click
import typer

_Command = TypeVar("_Command", bound=Callable[..., Any])
_CONTEXT_KEY = "finjuice_mutation_options"


@dataclass(frozen=True)
class MutationCLIOptions:
    """Raw common CLI fields used to build a mutation identity."""

    idempotency_key: str | None = None
    expected_generation: str | None = None
    expected_revision: int | None = None


def with_mutation_options(command: _Command) -> _Command:
    """Register common mutation flags and store their values on the command context."""
    original_signature = inspect.signature(command)
    parameters = list(original_signature.parameters.values())
    parameters.extend(
        (
            inspect.Parameter(
                "idempotency_key",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str | None,
                default=typer.Option(
                    None,
                    "--idempotency-key",
                    help="Stable retry key for an authoritative mutation",
                ),
            ),
            inspect.Parameter(
                "expected_generation",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=str | None,
                default=typer.Option(
                    None,
                    "--expected-generation",
                    help="Expected active dataset generation",
                ),
            ),
            inspect.Parameter(
                "expected_revision",
                inspect.Parameter.KEYWORD_ONLY,
                annotation=int | None,
                default=typer.Option(
                    None,
                    "--expected-revision",
                    help="Expected active dataset revision",
                ),
            ),
        )
    )

    @wraps(command)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        options = MutationCLIOptions(
            idempotency_key=kwargs.pop("idempotency_key", None),
            expected_generation=kwargs.pop("expected_generation", None),
            expected_revision=kwargs.pop("expected_revision", None),
        )
        candidate = kwargs.get("ctx") or (args[0] if args else None)
        context = candidate if isinstance(candidate, click.Context) else None
        if context is None:
            context = click.get_current_context(silent=True)
        if context is None:
            raise RuntimeError("Mutation command context is unavailable.")
        context.meta[_CONTEXT_KEY] = options
        return command(*args, **kwargs)

    cast(Any, wrapped).__signature__ = original_signature.replace(parameters=parameters)
    return cast(_Command, wrapped)


def get_mutation_options(ctx: typer.Context) -> MutationCLIOptions:
    """Return values captured by :func:`with_mutation_options`."""
    options = ctx.meta.get(_CONTEXT_KEY)
    if not isinstance(options, MutationCLIOptions):
        return MutationCLIOptions()
    return options


__all__ = ["MutationCLIOptions", "get_mutation_options", "with_mutation_options"]
