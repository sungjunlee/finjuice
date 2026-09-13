"""Checkup domains materialized from a single validated reader revision."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from dataclasses import dataclass

from finjuice.pipeline.storage.sqlite.exact_import.lookup import (
    load_completed_exact_imports,
    load_transaction_identity_snapshot,
)
from finjuice.pipeline.storage.sqlite.exact_import.preview import ImportPreviewSnapshot
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.portfolio_reads import (
    PortfolioConfigSnapshot,
    PortfolioReadSnapshot,
    _config,
    _rows,
)
from finjuice.pipeline.storage.sqlite.schema import RepositoryInfo
from finjuice.pipeline.storage.sqlite.status_reads import StatusReadSnapshot


@dataclass(frozen=True)
class CheckupReadSnapshot:
    """Independent caller-owned domain payloads with the same pinned revision."""

    info: RepositoryInfo
    status: StatusReadSnapshot
    portfolio: PortfolioReadSnapshot
    imports: ImportPreviewSnapshot
    rules: PortfolioConfigSnapshot


def import_preview_snapshot(
    connection: sqlite3.Connection, info: RepositoryInfo, digests: tuple[str, ...]
) -> ImportPreviewSnapshot:
    """Read existing verified closure lookups, distinguishing absent from unrequested."""
    identities = tuple(dict(row) for row in load_transaction_identity_snapshot(connection))
    completed = {
        digest: tuple(dict(row) for row in load_completed_exact_imports(connection, digest))
        for digest in dict.fromkeys(digests)
    }
    return deepcopy(ImportPreviewSnapshot(info, identities, completed))


def rules_config_snapshot(
    connection: sqlite3.Connection, paths: GenerationPaths
) -> PortfolioConfigSnapshot:
    """Keep unselected revisions distinct from explicit absence in this same reader."""
    return _config(connection, paths, "rules", _rows(connection, "config_revisions"))
