"""Checkup domains materialized from a single validated reader revision."""

from __future__ import annotations

import hashlib
import sqlite3
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from finjuice.pipeline.storage.sqlite.errors import (
    IdentifierError,
    MutationConflictError,
    MutationValidationError,
)
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
    unmaterialized_months: tuple[str, ...] = ()


def import_preview_snapshot(
    connection: sqlite3.Connection,
    info: RepositoryInfo,
    digests: tuple[str, ...],
    statements: tuple[bytes, ...] = (),
) -> ImportPreviewSnapshot:
    """Read existing verified closure lookups, distinguishing absent from unrequested."""
    identities = tuple(dict(row) for row in load_transaction_identity_snapshot(connection))
    completed = {
        digest: tuple(dict(row) for row in load_completed_exact_imports(connection, digest))
        for digest in dict.fromkeys(digests)
    }
    statement_results = {
        hashlib.sha256(content).hexdigest(): _statement_preview(connection, content)
        for content in dict.fromkeys(statements)
    }
    return deepcopy(ImportPreviewSnapshot(info, identities, completed, statement_results))


def _statement_preview(connection: sqlite3.Connection, content: bytes) -> dict[str, Any]:
    """Evaluate one captured statement against this pinned revision, without mutations."""
    from finjuice.pipeline.statements.canonical import (
        StatementImport,
        _preview_statement,
        parse_document,
        plan_rows,
    )

    try:
        envelope = parse_document(content)
        return _preview_statement(
            connection,
            StatementImport(content, imported_at=None, preview=True),
            envelope,
            plan_rows(envelope),
        )
    except MutationConflictError:
        return {"failure_code": "statement_conflict"}
    except (MutationValidationError, IdentifierError):
        return {"failure_code": "statement_validation_failed"}


def rules_config_snapshot(
    connection: sqlite3.Connection, paths: GenerationPaths
) -> PortfolioConfigSnapshot:
    """Keep unselected revisions distinct from explicit absence in this same reader."""
    return _config(connection, paths, "rules", _rows(connection, "config_revisions"))
