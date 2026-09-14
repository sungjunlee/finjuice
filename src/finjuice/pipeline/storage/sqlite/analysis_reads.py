"""Minimal detached transactions and config selections for analysis consumers."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import dataclass

from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.portfolio_reads import PortfolioConfigSnapshot, _config, _rows
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo
from finjuice.pipeline.storage.sqlite.transaction_completeness import (
    unmaterialized_transaction_months,  # noqa: F401 — compatibility re-export
)
from finjuice.pipeline.storage.sqlite.transaction_reads import TransactionReadSnapshot


@dataclass(frozen=True)
class AnalysisReadSnapshot:
    """Caller-owned analysis payloads materialized from a single reader revision."""

    info: RepositoryInfo
    transactions: TransactionReadSnapshot
    rules: PortfolioConfigSnapshot
    goals: PortfolioConfigSnapshot
    unmaterialized_months: tuple[str, ...] = ()


def analysis_snapshot(
    connection: sqlite3.Connection, paths: GenerationPaths, transactions: TransactionReadSnapshot
) -> AnalysisReadSnapshot:
    """Read config inventories once without loading portfolio or import domains."""
    revisions = _rows(connection, "config_revisions")
    return deepcopy(
        AnalysisReadSnapshot(
            transactions.info,
            transactions,
            _config(connection, paths, "rules", revisions),
            _config(connection, paths, "goals", revisions),
            transactions.unmaterialized_months,
        )
    )
