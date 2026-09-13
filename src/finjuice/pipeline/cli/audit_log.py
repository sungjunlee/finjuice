"""Shared helpers for appending CLI audit events."""

import json
import logging
import os
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from finjuice.pipeline.storage.authority import legacy_write_lease
from finjuice.pipeline.storage.sqlite.objects import _assert_no_symlink_ancestors

logger = logging.getLogger(__name__)


class _AuditWriteError(OSError):
    """An append failure that may have left an incomplete suffix."""

    def __init__(self) -> None:
        super().__init__("Audit log append failed before the event was complete.")


def append_audit_event(data_dir: Path, event: Mapping[str, Any]) -> None:
    """Append one JSONL event to ``.execution_audit.jsonl``.

    A failed append may leave an incomplete suffix. Existing bytes are never
    truncated or deleted because another writer may have appended meanwhile.

    Raises:
        OSError: If the audit log file cannot be created or written.
        TypeError: If ``event`` contains non-serializable values.
        ValueError: If JSON serialization receives unsupported numeric values.
    """
    audit_log_path = data_dir / ".execution_audit.jsonl"
    content = (json.dumps(dict(event), ensure_ascii=False) + "\n").encode("utf-8")
    _append_regular_file(audit_log_path, content)


def _append_regular_file(path: Path, content: bytes) -> None:
    """Append bytes without following aliases or accepting a raced file entry."""
    path = path.expanduser().absolute()
    try:
        _assert_no_symlink_ancestors(path, allow_missing=True)
        path.parent.mkdir(parents=True, exist_ok=True)
        _assert_no_symlink_ancestors(path, allow_missing=True)
        before = _lstat_regular_file(path)
        descriptor = _open_append_descriptor(path, before is None)
    except OSError:
        raise
    except Exception as exc:
        raise OSError("Audit log path could not be opened safely.") from exc

    try:
        _validate_append_descriptor(descriptor, path, before)
        _write_all(descriptor, content)
    except BaseException:
        os.close(descriptor)
        descriptor = -1
        # Other appenders may already have written to this published path.
        # Neither size checks nor inode checks make truncate/unlink safe here.
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _validate_append_descriptor(
    descriptor: int,
    path: Path,
    before: os.stat_result | None,
) -> None:
    """Bind an opened regular file to the inspected final path entry."""
    opened = os.fstat(descriptor)
    identity = _file_identity(opened)
    if not stat.S_ISREG(opened.st_mode) or opened.st_nlink != 1:
        raise OSError("Audit log must be an unaliased regular file.")
    if before is not None and _file_identity(before) != identity:
        raise OSError("Audit log changed while it was opened.")
    try:
        _assert_no_symlink_ancestors(path)
    except Exception as exc:
        raise OSError("Audit log path changed while it was opened.") from exc
    current = path.lstat()
    if _file_identity(current) != identity or current.st_nlink != 1:
        raise OSError("Audit log changed while it was opened.")


def _lstat_regular_file(path: Path) -> os.stat_result | None:
    try:
        entry = path.lstat()
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(entry.st_mode) or entry.st_nlink != 1:
        raise OSError("Audit log must be an unaliased regular file.")
    return entry


def _open_append_descriptor(path: Path, create_exclusive: bool) -> int:
    flags = os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0)
    if hasattr(os, "O_NONBLOCK"):
        flags |= os.O_NONBLOCK
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if create_exclusive:
        flags |= os.O_CREAT | os.O_EXCL
    try:
        return os.open(path, flags, 0o600)
    except OSError as exc:
        raise OSError("Audit log could not be opened safely.") from exc


def _write_all(descriptor: int, content: bytes) -> None:
    remaining = memoryview(content)
    while remaining:
        try:
            written = os.write(descriptor, remaining)
        except OSError as exc:
            raise _AuditWriteError() from exc
        if written <= 0:
            raise _AuditWriteError()
        remaining = remaining[written:]


def _file_identity(entry: os.stat_result) -> tuple[int, int]:
    return entry.st_dev, entry.st_ino


def append_financial_mutation_event(data_dir: Path, event: Mapping[str, Any]) -> None:
    """Append a privacy-safe financial mutation audit event.

    Audit logging is an additive side effect. Serialization or filesystem errors
    are logged for debugging, but they do not change the caller's CLI contract.
    """
    payload = {
        "event": "financial_mutation",
        **{key: value for key, value in event.items() if value is not None},
        "success": True,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with legacy_write_lease(data_dir):
            append_audit_event(data_dir, payload)
    except OSError as exc:
        logger.warning("Failed to write financial mutation audit event (%s)", type(exc).__name__)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Failed to serialize financial mutation audit event (%s)",
            type(exc).__name__,
        )
