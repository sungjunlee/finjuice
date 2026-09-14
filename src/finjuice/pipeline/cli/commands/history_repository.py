"""History display over complete source evidence from one canonical revision."""

from __future__ import annotations

import re
from copy import deepcopy
from typing import TYPE_CHECKING, Any

import typer
from rich.table import Table

from finjuice.pipeline.cli.output import ErrorCode, ExitCode, console, emit, emit_error, info
from finjuice.pipeline.cli.utils import get_activation_evidence_provider, get_config
from finjuice.pipeline.storage.read_facade import read_history_snapshot

if TYPE_CHECKING:
    from finjuice.pipeline.storage.sqlite.history_reads import (
        HistoryReadSnapshot,
        LegacyHistoryRecord,
        NativeImportHistoryRecord,
    )

_ARCHIVE_VALUES = {"yes", "true", "1", "no", "false", "0"}


def try_repository_history(ctx: typer.Context, *, json_output: bool) -> bool:
    """Render a verified history snapshot, returning False only for legacy authority."""
    config = get_config(ctx)
    try:
        snapshot = read_history_snapshot(config.data_dir, get_activation_evidence_provider(ctx))
        if snapshot is None:
            return False
        payload = history_payload(snapshot)
        if not json_output:
            info(
                f"Repository revision {snapshot.info.dataset_revision} "
                f"({snapshot.info.dataset_generation})"
            )
        emit(
            payload,
            json_output,
            _render_history,
            command="history",
            meta_extras={
                "authority": "repository",
                "dataset_generation": snapshot.info.dataset_generation,
                "dataset_revision": snapshot.info.dataset_revision,
                "sqlite_schema_version": snapshot.info.schema_version,
                "read_policy": "source_import_history.v1",
                "legacy_history_records": len(snapshot.legacy_records),
                "native_import_records": len(snapshot.native_records),
            },
        )
        return True
    except typer.Exit:
        raise
    except Exception:
        emit_error(
            "Canonical import history could not read complete validated source evidence.",
            error_code=ErrorCode.VALIDATION_FAILED,
            exit_code=ExitCode.VALIDATION_ERROR,
            json_output=json_output,
            command="history",
        )
        raise AssertionError("emit_error must exit") from None


def history_payload(snapshot: HistoryReadSnapshot) -> dict[str, Any]:
    """Preserve every source record while keeping unknown display values explicit."""
    records = [_legacy_record(row) for row in snapshot.legacy_records]
    records.extend(_native_record(row) for row in snapshot.native_records)
    return {"records": records, "count": len(records), "summary": _summary(records)}


def _legacy_record(row: LegacyHistoryRecord) -> dict[str, Any]:
    fields = row.fields
    count, count_issue = _source_rows(fields.get("source_rows"))
    archived, archive_issue = _archived(fields.get("archived"))
    return {
        "file_id": fields.get("file_id"),
        "original_filename": fields.get("original_filename"),
        "source_rows": count,
        "archived": archived,
        "archived_path": fields.get("archived_path"),
        "imported_at": fields.get("imported_at"),
        "imported_from": fields.get("imported_from"),
        "origin": "legacy_history",
        "occurrence_id": row.occurrence_id,
        "artifact_id": row.artifact_id,
        "provenance_id": row.provenance_id,
        "source_row": row.source_row,
        "source_fields": deepcopy(fields),
        "source_cells": deepcopy(row.raw_payload["cells"]),
        "field_issues": [value for value in (count_issue, archive_issue) if value is not None],
    }


def _native_record(row: NativeImportHistoryRecord) -> dict[str, Any]:
    return {
        "file_id": row.legacy_file_ids[0] if len(row.legacy_file_ids) == 1 else None,
        "legacy_file_ids": list(row.legacy_file_ids),
        "original_filename": row.original_filename,
        "source_rows": None,
        "archived": None,
        "archived_path": None,
        "imported_at": row.imported_at,
        "imported_from": None,
        "origin": "native_import",
        "occurrence_id": row.occurrence_id,
        "artifact_id": row.artifact_id,
        "provenance_id": row.provenance_id,
        "import_counts": deepcopy(row.counts),
        "source_artifact_preserved": True,
        "field_issues": [],
    }


def _source_rows(value: str | None) -> tuple[int | None, str | None]:
    if value is None or not value.strip():
        return None, None
    if re.fullmatch(r"\+?[0-9]+", value.strip()):
        try:
            return int(value), None
        except ValueError:
            pass
    return None, "source_rows_unavailable"


def _archived(value: str | None) -> tuple[str | None, str | None]:
    if value is None or not value.strip():
        return None, None
    if value.strip().lower() in _ARCHIVE_VALUES:
        return value, None
    return None, "archive_status_unavailable"


def _archive_label(value: str | None) -> str:
    if value is None:
        return "Unknown"
    return "Yes" if value.strip().lower() in {"yes", "true", "1"} else "No"


def _summary(records: list[dict[str, Any]]) -> dict[str, int]:
    return {
        "known_source_rows": sum(
            row["source_rows"] for row in records if row["source_rows"] is not None
        ),
        "unknown_source_rows_records": sum(row["source_rows"] is None for row in records),
        "archived_files": sum(_archive_label(row["archived"]) == "Yes" for row in records),
        "unknown_archive_records": sum(row["archived"] is None for row in records),
    }


def _render_history(payload: dict[str, Any]) -> None:
    records = payload["records"]
    if not records:
        info("No import history found in the verified repository.")
        return
    table = Table(title="Import History")
    for label in ("Source", "File ID", "Filename", "Rows", "Archived", "Imported At"):
        table.add_column(label)
    for row in records:
        filename = row["original_filename"] or "Unknown"
        if len(filename) > 40:
            filename = filename[:37] + "..."
        table.add_row(
            "Preserved history" if row["origin"] == "legacy_history" else "Native import",
            row["file_id"] or "Unknown",
            filename,
            str(row["source_rows"]) if row["source_rows"] is not None else "Unknown",
            _archive_label(row["archived"]),
            row["imported_at"][:16] if row["imported_at"] else "Unknown",
        )
    console.print(table)
    summary = payload["summary"]
    info(
        f"{payload['count']} records; {summary['known_source_rows']:,} known source rows; "
        f"row count unknown in {summary['unknown_source_rows_records']} records."
    )
    info(
        f"Archived: {summary['archived_files']}; "
        f"archive status unknown in {summary['unknown_archive_records']} records."
    )
