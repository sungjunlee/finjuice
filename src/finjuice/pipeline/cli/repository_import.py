"""Thin CLI helpers for authoritative exact XLSX and JSON statement import."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import typer

from finjuice.pipeline.cli.mutation_options import get_mutation_options
from finjuice.pipeline.cli.pipeline_failure import FullPipelineError
from finjuice.pipeline.cli.utils import mutation_identity, mutation_metadata
from finjuice.pipeline.config import Config
from finjuice.pipeline.ingest.xlsx_evidence import XlsxEvidenceError
from finjuice.pipeline.statements.canonical import (
    STATEMENT_SCHEMA_VERSION,
    StatementImport,
    StatementPreviewState,
)
from finjuice.pipeline.storage.authority import RepositoryAuthority
from finjuice.pipeline.storage.mutation_facade import (
    BulkMutationPreview,
    ExactImportCommand,
    MutationIdentity,
    StorageMutationFacade,
)
from finjuice.pipeline.storage.sqlite.backup_io import BackupPayloadError, read_regular_bytes
from finjuice.pipeline.storage.sqlite.errors import (
    MutationConflictError,
    MutationError,
    MutationValidationError,
)
from finjuice.pipeline.storage.sqlite.exact_import import (
    ExactWorkbookCapture,
    capture_exact_xlsx,
)
from finjuice.pipeline.storage.sqlite.mutations import MutationReceipt
from finjuice.pipeline.storage.sqlite.objects import ObjectStoreError
from finjuice.pipeline.storage.sqlite.source_lookup import (
    SourceLookupError,
    resolve_archived_source,
)


@dataclass(frozen=True)
class ImportBatchResult:
    """Completed file receipts plus the first failed input, if any."""

    receipts: tuple[dict[str, Any], ...]
    failed_files: tuple[tuple[str, str], ...]
    typed_failure: MutationValidationError | MutationConflictError | None = None


def identity_from_context(ctx: typer.Context) -> MutationIdentity:
    """Build the caller-supplied mutation identity from registered CLI options."""
    options = get_mutation_options(ctx)
    try:
        return mutation_identity(
            options.idempotency_key,
            options.expected_generation,
            options.expected_revision,
        )
    except ValueError as exc:
        raise MutationValidationError(str(exc)) from exc


def reject_batch_identity(identity: MutationIdentity, file_count: int) -> None:
    """Reject explicit identity options that cannot name one file-level mutation."""
    if file_count == 1 or not _has_explicit_identity(identity):
        return
    raise MutationValidationError(
        "Explicit mutation identity options apply to a single-file import."
    )


def import_xlsx_paths(
    facade: StorageMutationFacade,
    paths: list[Path],
    identity: MutationIdentity,
    *,
    preview: bool,
) -> ImportBatchResult:
    """Import captured workbooks one file at a time and stop on the first failure."""
    return _import_path_batch(facade, paths, identity, preview=preview, importer=_import_one_path)


def present_ingest_step(
    batch: ImportBatchResult,
    *,
    source: str,
    dry_run: bool,
    archive_requested: bool,
    from_archive: str | None = None,
) -> dict[str, Any]:
    """Present file receipts as the composed-pipeline ingest step payload."""
    payload = _ingest_payload(batch, source, dry_run, archive_requested)
    if from_archive is not None:
        payload["from_archive"] = from_archive
    if batch.typed_failure is not None:
        raise FullPipelineError.from_exception(
            "ingest", {"ingest": payload}, batch.typed_failure
        ) from batch.typed_failure
    return payload


def _ingest_payload(
    batch: ImportBatchResult, source: str, dry_run: bool, archive_requested: bool
) -> dict[str, Any]:
    return {
        "archive_requested": archive_requested,
        "authority": "repository",
        "command": "ingest",
        "dry_run": dry_run,
        "receipts": [dict(item) for item in batch.receipts],
        "source": source,
        "summary": _summary_from_batch(batch),
    }


def ingest_import_directory(
    facade: StorageMutationFacade,
    config: Config,
    identity: MutationIdentity,
    *,
    preview: bool,
    archive_requested: bool,
) -> dict[str, Any]:
    """Import staged XLSX workbooks and canonical JSON statements from imports/."""
    paths = sorted(
        (*_xlsx_in(config.import_dir), *_canonical_statement_paths(config.import_dir)),
        key=lambda path: path.name,
    )
    batch = _import_path_batch(
        facade, paths, identity, preview=preview, importer=_import_one_ingest_path
    )
    return present_ingest_step(
        batch,
        source="imports",
        dry_run=preview,
        archive_requested=archive_requested,
    )


def ingest_archived_source(
    facade: StorageMutationFacade,
    selector: str,
    identity: MutationIdentity,
    *,
    preview: bool,
    archive_requested: bool,
) -> dict[str, Any]:
    """Re-import one resolved archived source occurrence, artifact, or file_id."""
    reject_batch_identity(identity, 1)
    presented = _import_resolved_archive(facade, selector, identity, preview)
    return present_ingest_step(
        ImportBatchResult((presented,), ()),
        source="archive",
        dry_run=preview,
        archive_requested=archive_requested,
        from_archive=selector,
    )


def _import_resolved_archive(
    facade: StorageMutationFacade,
    selector: str,
    identity: MutationIdentity,
    preview: bool,
) -> dict[str, Any]:
    authority = facade.dispatch().authority
    if not isinstance(authority, RepositoryAuthority):
        raise MutationValidationError("Archived source lookup requires an active repository.")
    resolved = resolve_archived_source(authority.paths, selector)
    receipt = _import_capture(facade, resolved.capture, identity, preview)
    return _present_receipt(resolved.original_filename or selector, identity, receipt)


def _has_explicit_identity(identity: MutationIdentity) -> bool:
    return any(
        value is not None
        for value in (
            identity.idempotency_key,
            identity.expected_generation,
            identity.expected_revision,
        )
    )


def _xlsx_in(directory: Path) -> list[Path]:
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.glob("*.xlsx") if path.is_file())


def _canonical_statement_paths(directory: Path) -> list[Path]:
    """Return JSON files that claim the canonical statement schema version."""
    if not directory.is_dir():
        return []
    return sorted(
        path
        for path in directory.glob("*.json")
        if path.is_file() and _claims_canonical_statement(path)
    )


def _claims_canonical_statement(path: Path) -> bool:
    try:
        payload: Any = json.loads(read_regular_bytes(path).decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, BackupPayloadError):
        return False
    return isinstance(payload, dict) and payload.get("schema_version") == STATEMENT_SCHEMA_VERSION


def _import_path_batch(
    facade: StorageMutationFacade,
    paths: list[Path],
    identity: MutationIdentity,
    *,
    preview: bool,
    importer: Callable[..., dict[str, Any]],
) -> ImportBatchResult:
    """Import one staged path at a time and stop on the first failure."""
    reject_batch_identity(identity, len(paths))
    receipts: list[dict[str, Any]] = []
    failed: list[tuple[str, str]] = []
    statement_preview = StatementPreviewState() if preview else None
    for path in paths:
        try:
            if path.suffix.lower() == ".json" and importer is _import_one_ingest_path:
                receipt = _import_one_statement(
                    facade, path, identity, preview=preview, preview_state=statement_preview
                )
            else:
                receipt = importer(facade, path, identity, preview=preview)
            receipts.append(receipt)
        except (MutationValidationError, MutationConflictError) as exc:
            failed.append((path.name, type(exc).__name__))
            return ImportBatchResult(tuple(receipts), tuple(failed), typed_failure=exc)
        except Exception as exc:
            failed.append((path.name, _safe_error(exc)))
            break
    return ImportBatchResult(tuple(receipts), tuple(failed))


def _import_one_ingest_path(
    facade: StorageMutationFacade,
    path: Path,
    identity: MutationIdentity,
    *,
    preview: bool,
) -> dict[str, Any]:
    if path.suffix.lower() == ".json":
        return _import_one_statement(facade, path, identity, preview=preview)
    return _import_one_path(facade, path, identity, preview=preview)


def _import_one_statement(
    facade: StorageMutationFacade,
    path: Path,
    identity: MutationIdentity,
    *,
    preview: bool,
    preview_state: StatementPreviewState | None = None,
) -> dict[str, Any]:
    command = StatementImport(
        content=read_regular_bytes(path),
        imported_at=None,
        preview=preview,
        skip_recorded=True,
        preview_state=preview_state,
    )
    receipt = facade.import_statement(command, identity=identity)
    return _present_statement_receipt(path.name, identity, receipt)


def _present_statement_receipt(
    filename: str,
    identity: MutationIdentity,
    receipt: MutationReceipt | BulkMutationPreview,
) -> dict[str, Any]:
    presented = _present_receipt(filename, identity, receipt)
    result = dict(presented["result"])
    result["counts"] = _with_transaction_counts(result.get("counts") or {})
    result["completed"] = not isinstance(receipt, BulkMutationPreview)
    presented["result"] = result
    return presented


def _with_transaction_counts(counts: Mapping[str, Any]) -> dict[str, Any]:
    mapped = dict(counts)
    created = int(counts.get("created", 0) or 0)
    reused = int(counts.get("reused", 0) or 0) + int(counts.get("linked", 0) or 0)
    mapped["transactions"] = {
        "inserted": created,
        "quarantined": 0,
        "reused": reused,
        "unsupported": 0,
    }
    return mapped


def _import_one_path(
    facade: StorageMutationFacade,
    path: Path,
    identity: MutationIdentity,
    *,
    preview: bool,
) -> dict[str, Any]:
    capture = capture_exact_xlsx(path, filename=path.name)
    receipt = _import_capture(facade, capture, identity, preview)
    return _present_receipt(path.name, identity, receipt)


def _import_capture(
    facade: StorageMutationFacade,
    capture: ExactWorkbookCapture,
    identity: MutationIdentity,
    preview: bool,
) -> MutationReceipt | BulkMutationPreview:
    command = ExactImportCommand(capture, preview=preview)
    return facade.import_exact_xlsx(command, identity=identity)


def _present_receipt(
    filename: str,
    identity: MutationIdentity,
    receipt: MutationReceipt | BulkMutationPreview,
) -> dict[str, Any]:
    result = _public_result(dict(receipt.result))
    payload: dict[str, Any] = {"filename": filename, "result": result}
    if isinstance(receipt, BulkMutationPreview):
        payload.update(
            {
                "authority": "repository",
                "dataset_revision": receipt.dataset_revision,
                "state_changed": False,
            }
        )
        return payload
    payload.update(mutation_metadata(identity, receipt))
    return payload


def _public_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "artifact_id": result.get("artifact_id"),
        "completed": result.get("completed"),
        "counts": result.get("counts"),
        "noop": result.get("noop"),
        "occurrence_id": result.get("occurrence_id"),
    }


def _summary_from_batch(batch: ImportBatchResult) -> dict[str, Any]:
    failed_files = [[name, message] for name, message in batch.failed_files]
    return {
        "failed": len(failed_files),
        "failed_files": failed_files,
        "files_processed": len(batch.receipts) + len(failed_files),
        "new_transactions": _count_field(batch.receipts, "inserted"),
        "updated": _count_field(batch.receipts, "reused"),
    }


def _count_field(receipts: tuple[dict[str, Any], ...], field: str) -> int:
    total = 0
    for item in receipts:
        counts = item.get("result", {}).get("counts", {}).get("transactions", {})
        total += int(counts.get(field, 0) or 0)
    return total


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, (MutationError, SourceLookupError, XlsxEvidenceError, ObjectStoreError)):
        return str(exc)
    return type(exc).__name__
