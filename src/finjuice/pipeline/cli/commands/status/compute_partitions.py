"""Transaction-partition discovery helpers for ``finjuice status``.

Owns CSV partition discovery, missing-data errors, and path-safety
validation. Fact orchestration stays in
:mod:`finjuice.pipeline.cli.commands.status.compute`, which re-exports
these names so existing callers can keep importing from that module.
"""

from __future__ import annotations

import logging
from pathlib import Path

from finjuice.pipeline.cli.output import ErrorCode, ExitCode

logger = logging.getLogger(__name__)


def _transaction_partitions_or_raise(data_dir: Path) -> list[Path]:
    """Return validated transaction partitions or raise a status error."""
    from .compute import StatusCommandError

    transactions_dir = data_dir / "transactions"
    if not transactions_dir.exists():
        if data_dir.exists():
            raise StatusCommandError(
                "No transactions directory. Run 'finjuice ingest' first.",
                error_code=ErrorCode.NO_DATA,
                exit_code=ExitCode.NO_DATA,
                suggestion="finjuice ingest",
            )
        raise StatusCommandError(
            "Data directory not initialized. Run 'finjuice init' first.",
            error_code=ErrorCode.DATA_DIR_NOT_INITIALIZED,
            exit_code=ExitCode.USAGE_ERROR,
            suggestion="finjuice init",
        )

    partitions = list(transactions_dir.rglob("*.csv"))
    if not partitions:
        raise StatusCommandError(
            "No CSV partitions found. Run 'finjuice ingest' first.",
            error_code=ErrorCode.NO_DATA,
            exit_code=ExitCode.NO_DATA,
            suggestion="finjuice ingest",
        )
    return _validated_partitions(transactions_dir, partitions)


def _validated_partitions(transactions_dir: Path, partitions: list[Path]) -> list[Path]:
    """Return partitions that resolve inside the transactions directory."""
    transactions_dir_resolved = transactions_dir.resolve()
    valid_partitions = []
    for partition_path in partitions:
        try:
            if partition_path.resolve().is_relative_to(transactions_dir_resolved):
                valid_partitions.append(partition_path)
            else:
                logger.warning("Skipping partition outside transactions dir: %s", partition_path)
        except (ValueError, OSError) as exc:
            logger.warning("Could not validate path %s: %s", partition_path, exc)
    return valid_partitions
