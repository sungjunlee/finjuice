"""Explicit delivery configuration and a failure-isolated durable commit boundary."""

from __future__ import annotations

import inspect
import json
from collections.abc import Callable
from dataclasses import replace
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar, cast

import typer

from finjuice.pipeline.cli.commands.sqlite_backup_deliver import _job, _render_status
from finjuice.pipeline.storage.sqlite.backup_delivery import DeliveryJob, run_backup_delivery
from finjuice.pipeline.storage.sqlite.backup_io import read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import BackupDeliveryError
from finjuice.pipeline.storage.sqlite.mutations import MutationReceipt

_REQUIRED = {"expected", "sender_store", "destination_store", "control_dir"}
_ARTIFACTS = {"wheel", "dependency_lock", "binding", "migration_candidate"}


def load_delivery_job(config: Path, data_dir: Path) -> DeliveryJob:
    """Validate an operator-selected private configuration before domain mutation."""
    try:
        raw = json.loads(read_regular_bytes(config))
        if not isinstance(raw, dict) or set(raw) - (_REQUIRED | _ARTIFACTS):
            raise ValueError
        if not _REQUIRED <= set(raw) or (set(raw) & _ARTIFACTS not in (set(), _ARTIFACTS)):
            raise ValueError
        if any(
            not isinstance(value, str) or not Path(value).is_absolute() for value in raw.values()
        ):
            raise ValueError
        paths = {key: Path(value) for key, value in raw.items()}
        return _job(
            data_dir,
            *(
                paths[key]
                for key in ("expected", "sender_store", "destination_store", "control_dir")
            ),
            *(
                paths.get(key)
                for key in ("wheel", "dependency_lock", "binding", "migration_candidate")
            ),
        )
    except Exception as exc:
        raise ValueError("Invalid explicit delivery configuration.") from exc


def execute_after_commit(job: DeliveryJob, receipt: MutationReceipt) -> dict[str, Any]:
    """Run backup after COMMIT without changing or invalidating its durable receipt."""
    try:
        payload = run_backup_delivery(replace(job, recording=receipt)).to_dict()
        payload["recording"] = _committed_recording(receipt)
        return payload
    except BackupDeliveryError as exc:
        if exc.report:
            payload = dict(exc.report)
            payload["recording"] = _committed_recording(receipt)
            return payload
    except Exception:
        pass
    return {
        "kind": "backup_delivery_run",
        "job_id": "",
        "recording": _committed_recording(receipt),
        "backup": {"local": "unknown", "destination": "unknown"},
        "source_observed_revision": None,
        "coverage_as_of": None,
        "pending_commit_count": None,
        "last_verified_at": None,
        "last_attempt_error_code": "delivery_unavailable",
        "history_unknown": True,
        "attempt": None,
    }


def _committed_recording(receipt: MutationReceipt) -> dict[str, Any]:
    return {
        "status": "committed",
        "changeset_id": receipt.changeset_id,
        "committed_revision": receipt.committed_revision,
        "replayed": receipt.replayed,
    }


def render_delivery(result: dict[str, Any]) -> None:
    """Render the mutable delivery projection separately from the domain result."""
    if "backup_delivery" in result:
        _render_status(result["backup_delivery"])


_Command = TypeVar("_Command", bound=Callable[..., Any])


def with_delivery_option(command: _Command) -> _Command:
    """Register the optional post-commit configuration using the CLI context."""
    signature = inspect.signature(command)
    option = inspect.Parameter(
        "delivery_config",
        inspect.Parameter.KEYWORD_ONLY,
        annotation=Path | None,
        default=typer.Option(
            None, "--delivery-config", help="Explicit delivery JSON after manual edit."
        ),
    )

    @wraps(command)
    def wrapped(*args: Any, **kwargs: Any) -> Any:
        ctx = kwargs.get("ctx") or (args[0] if args else None)
        if ctx is None:
            raise RuntimeError("Delivery command context is unavailable.")
        ctx.meta["finjuice_delivery_config"] = kwargs.pop("delivery_config", None)
        return command(*args, **kwargs)

    cast(Any, wrapped).__signature__ = signature.replace(
        parameters=[*signature.parameters.values(), option]
    )
    return cast(_Command, wrapped)
