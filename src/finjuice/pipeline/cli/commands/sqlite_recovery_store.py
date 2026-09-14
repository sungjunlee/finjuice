"""Operator CLI for an initialized local recovery-graph store."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.backup.retention import RetentionPolicy
from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.recovery_expected import load_expected_recovery_graph
from finjuice.pipeline.cli.commands.sqlite_backup import (
    _active_data_dir,
    _fail,
    _reject_active_restore,
    _render_restore,
    _unexpected,
    ssot_backup_app,
)
from finjuice.pipeline.cli.output import emit
from finjuice.pipeline.storage.authority import StaticActivationEvidenceProvider
from finjuice.pipeline.storage.sqlite.errors import RepositoryBackupError, RepositoryPathError
from finjuice.pipeline.storage.sqlite.recovery_bundle import RecoveryCaptureInput
from finjuice.pipeline.storage.sqlite.recovery_release_evidence import ReleaseArtifactPaths
from finjuice.pipeline.storage.sqlite.recovery_store import (
    capture_into_store,
    initialize_recovery_store,
    list_recovery_store,
    plan_recovery_store,
    protect_store_copy,
    prune_recovery_store,
    restore_store_copy,
    verify_store_copy,
)

store_app = typer.Typer(
    name="store",
    help="Initialize and retain complete local recovery graphs in one managed store.",
    no_args_is_help=True,
)
ssot_backup_app.add_typer(store_app, name="store")

_EXPECTED_HELP = "Independently retained expectation JSON; never derived from the store."
_WINDOW_HELP = "GFS window; omit unused fields to keep the default policy."


def _run(
    command: str,
    json_output: bool,
    action: Callable[[], Any],
    render: Callable[[dict[str, Any]], None],
) -> None:
    try:
        result = action()
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    payload = result.to_dict() if hasattr(result, "to_dict") else result
    emit(payload, json_output, render, command=command)


def _policy(daily: int | None, weekly: int | None, monthly: int | None) -> RetentionPolicy | None:
    if daily is None and weekly is None and monthly is None:
        return None
    kwargs: dict[str, int] = {}
    if daily is not None:
        kwargs["daily"] = daily
    if weekly is not None:
        kwargs["weekly"] = weekly
    if monthly is not None:
        kwargs["monthly"] = monthly
    return RetentionPolicy(**kwargs)


def _render_init(result: dict[str, Any]) -> None:
    output.success("Local recovery store initialized")
    output.info(f"  store: {result['store_id']}")
    output.info("Keep independently enrolled expectations; store metadata is not trust.")


def _render_capture(result: dict[str, Any]) -> None:
    output.success("Local recovery graph captured into the store")
    output.info(f"  copy: {result['copy_id']}")
    output.info(f"  digest: {result['graph_digest']}")
    output.info(f"  baseline registered: {result['baseline_registered']}")


def _render_list(result: dict[str, Any]) -> None:
    output.success("Local recovery store inventory")
    output.info(f"  healthy: {result['healthy_count']}")
    output.info(f"  held: {result['held_count']}")
    output.info(f"  latest healthy: {result['latest_healthy_id']}")
    output.info(f"  baselines: {', '.join(result['baseline_copy_ids']) or 'none'}")


def _render_verify(result: dict[str, Any]) -> None:
    output.success("Local recovery graph verified")
    output.info(f"  digest: {result['graph_digest']}")
    output.info(f"  generation: {result['snapshot_generation']}")


def _render_protect(result: dict[str, Any]) -> None:
    output.success("Local recovery graph protected as a baseline")
    output.info(f"  copy: {result['copy_id']}")
    output.info(f"  digest: {result['graph_digest']}")


def _render_plan(result: dict[str, Any]) -> None:
    output.success("Local recovery store retention plan")
    output.info(f"  keep: {result['keep_count']}")
    output.info(f"  delete: {result['delete_count']}")
    output.info(f"  protected: {result['protected_count']}")
    output.info(f"  plan digest: {result['plan_digest']}")


def _render_prune(result: dict[str, Any]) -> None:
    output.success("Local recovery store prune complete")
    output.info(f"  deleted: {result['deleted_count']}")
    output.info(f"  kept: {result['kept_count']}")
    output.info(f"  held: {result['held_count']}")
    output.info(f"  plan digest: {result['plan_digest']}")


@store_app.command("init")
def sqlite_backup_store_init(
    store: Path = typer.Option(..., "--store", help="Fresh directory for the initialized store."),
    expected: Path = typer.Option(
        ..., "--expected", help="Independently retained JSON for this activation."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Create one empty local store bound to independently enrolled expectations."""
    command = "ssot backup store init"
    _run(
        command,
        json_output,
        lambda: initialize_recovery_store(store, load_expected_recovery_graph(expected)),
        _render_init,
    )


@store_app.command("capture")
def sqlite_backup_store_capture(  # noqa: PLR0913 - explicit Typer operator options
    store: Path = typer.Option(..., "--store", help="Initialized local recovery-graph store."),
    source_data_dir: Path = typer.Option(
        ...,
        "--source-data-dir",
        help="Explicit live data directory to snapshot; not read from the host pointer.",
    ),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    wheel: Path = typer.Option(..., "--wheel", help="Operator-selected release wheel."),
    dependency_lock: Path = typer.Option(
        ..., "--dependency-lock", help="Operator-selected dependency lock file."
    ),
    binding: Path = typer.Option(..., "--binding", help="Operator-selected trusted binding file."),
    migration_candidate: Path = typer.Option(
        ..., "--migration-candidate", help="Immutable migration candidate directory."
    ),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Capture one verified recovery graph into the initialized store."""
    command = "ssot backup store capture"

    def action() -> Any:
        enrolled = load_expected_recovery_graph(expected)
        unused = source_data_dir / "unused-store-capture-destination"
        return capture_into_store(
            store,
            RecoveryCaptureInput(
                source_data_dir,
                unused,
                StaticActivationEvidenceProvider(enrolled.activation_evidence),
                ReleaseArtifactPaths(wheel, dependency_lock, binding),
                migration_candidate,
            ),
            enrolled,
        )

    _run(command, json_output, action, _render_capture)


@store_app.command("list")
def sqlite_backup_store_list(
    store: Path = typer.Option(..., "--store", help="Initialized local recovery-graph store."),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Verify and list complete graphs in one initialized local store."""
    command = "ssot backup store list"
    _run(
        command,
        json_output,
        lambda: list_recovery_store(store, load_expected_recovery_graph(expected)),
        _render_list,
    )


@store_app.command("verify")
def sqlite_backup_store_verify(
    store: Path = typer.Option(..., "--store", help="Initialized local recovery-graph store."),
    copy_id: str = typer.Option(..., "--copy-id", help="UUID identity of one published graph."),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Verify one managed recovery graph against independently enrolled evidence."""
    command = "ssot backup store verify"
    _run(
        command,
        json_output,
        lambda: verify_store_copy(store, load_expected_recovery_graph(expected), copy_id),
        _render_verify,
    )


@store_app.command("restore")
def sqlite_backup_store_restore(  # noqa: PLR0913 - explicit Typer operator options
    ctx: typer.Context,
    store: Path = typer.Option(..., "--store", help="Initialized local recovery-graph store."),
    copy_id: str = typer.Option(..., "--copy-id", help="UUID identity of one published graph."),
    target: Path = typer.Option(
        ..., "--target", help="Fresh isolated workspace directory; parent must exist."
    ),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Verify one managed graph, then restore its snapshot into an inactive workspace."""
    command = "ssot backup store restore"
    try:
        enrolled = load_expected_recovery_graph(expected)
        _reject_active_restore(target, _active_data_dir(ctx))
        _verified, restored = restore_store_copy(store, enrolled, copy_id, target)
        del _verified
        result = restored
    except (RepositoryBackupError, RepositoryPathError) as exc:
        _fail(exc, command=command, json_output=json_output)
        return
    except Exception as exc:  # intended catch-all for CLI robustness
        _unexpected(exc, command=command, json_output=json_output)
        return
    emit(result.to_dict(), json_output, _render_restore, command=command)


@store_app.command("protect")
def sqlite_backup_store_protect(
    store: Path = typer.Option(..., "--store", help="Initialized local recovery-graph store."),
    copy_id: str = typer.Option(..., "--copy-id", help="UUID identity of one published graph."),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Verify one graph and durably register it as an additional baseline."""
    command = "ssot backup store protect"
    _run(
        command,
        json_output,
        lambda: protect_store_copy(store, load_expected_recovery_graph(expected), copy_id),
        _render_protect,
    )


@store_app.command("plan")
def sqlite_backup_store_plan(  # noqa: PLR0913 - explicit Typer operator options
    store: Path = typer.Option(..., "--store", help="Initialized local recovery-graph store."),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    daily: int | None = typer.Option(None, "--daily", help=_WINDOW_HELP),
    weekly: int | None = typer.Option(None, "--weekly", help=_WINDOW_HELP),
    monthly: int | None = typer.Option(None, "--monthly", help=_WINDOW_HELP),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Recompute a GFS retention plan from verified local inventory."""
    command = "ssot backup store plan"
    _run(
        command,
        json_output,
        lambda: plan_recovery_store(
            store, load_expected_recovery_graph(expected), _policy(daily, weekly, monthly)
        ),
        _render_plan,
    )


@store_app.command("prune")
def sqlite_backup_store_prune(  # noqa: PLR0913 - explicit Typer operator options
    store: Path = typer.Option(..., "--store", help="Initialized local recovery-graph store."),
    expected: Path = typer.Option(..., "--expected", help=_EXPECTED_HELP),
    plan_digest: str | None = typer.Option(
        None,
        "--plan-digest",
        help="Optional reviewed plan digest; stale values are rejected.",
    ),
    daily: int | None = typer.Option(None, "--daily", help=_WINDOW_HELP),
    weekly: int | None = typer.Option(None, "--weekly", help=_WINDOW_HELP),
    monthly: int | None = typer.Option(None, "--monthly", help=_WINDOW_HELP),
    json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
) -> None:
    """Recompute under an exclusive lease and delete only unprotected local graphs."""
    command = "ssot backup store prune"
    _run(
        command,
        json_output,
        lambda: prune_recovery_store(
            store,
            load_expected_recovery_graph(expected),
            _policy(daily, weekly, monthly),
            plan_digest=plan_digest,
        ),
        _render_prune,
    )
