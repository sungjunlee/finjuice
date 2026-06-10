"""Shared helpers for appending CLI audit events."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

logger = logging.getLogger(__name__)


def append_audit_event(data_dir: Path, event: Mapping[str, Any]) -> None:
    """Append one JSONL event to ``.execution_audit.jsonl``.

    Raises:
        OSError: If the audit log file cannot be created or written.
        TypeError: If ``event`` contains non-serializable values.
        ValueError: If JSON serialization receives unsupported numeric values.
    """
    audit_log_path = data_dir / ".execution_audit.jsonl"
    audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(dict(event), ensure_ascii=False) + "\n")


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
        append_audit_event(data_dir, payload)
    except OSError as exc:
        logger.warning("Failed to write financial mutation audit event (%s)", type(exc).__name__)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "Failed to serialize financial mutation audit event (%s)",
            type(exc).__name__,
        )
