"""Frozen legacy files to lossless evidence and conservative typed baseline rows."""

from __future__ import annotations

import csv
import hashlib
import io
from pathlib import Path, PurePosixPath

from finjuice.pipeline.migration.policy import OVERVIEW_REPORT_POLICY
from finjuice.pipeline.storage.sqlite.legacy_overview import LegacyOverviewCandidateRecord
from finjuice.pipeline.storage.sqlite.records import (
    MigrationIdentityRecord,
    ObservationRecord,
    SourceOccurrenceRecord,
)
from finjuice.pipeline.storage.sqlite.repository import RepositoryBuilder

from .configs import config, config_kind
from .csv_rows import rows
from .model import PARSER, Emitter, FileAnalysis, FileContext
from .observations import asset, fact
from .overview_reports import report, report_role
from .transactions import transaction

__all__ = ["FileContext", "FileAnalysis", "analyze_file", "preserve_file"]


def analyze_file(source: Path, context: FileContext) -> FileAnalysis:
    """Analyze immutable source input without writing files or repository state."""
    return _process(source, context, None)


def preserve_file(
    builder: RepositoryBuilder,
    source: Path,
    context: FileContext,
    *,
    pending: list[LegacyOverviewCandidateRecord] | None = None,
) -> FileAnalysis:
    """Preserve source bytes and baseline rows inside the caller's builder lifecycle."""
    return _process(source, context, builder, pending)


def _process(
    source: Path,
    context: FileContext,
    builder: RepositoryBuilder | None,
    pending: list[LegacyOverviewCandidateRecord] | None = None,
) -> FileAnalysis:
    data = source.read_bytes()
    artifact = "sha256:" + hashlib.sha256(data).hexdigest()
    emitter = Emitter(context, builder)
    if builder is not None:
        published = builder.publish_source(io.BytesIO(data))
        if published.artifact_id != artifact:
            raise ValueError("Published source identity does not match analyzed bytes")
    emitter.call(
        "add_source_occurrence",
        SourceOccurrenceRecord(
            emitter.occurrence,
            artifact,
            "legacy_capture",
            PurePosixPath(context.relative_path).name,
            parser_version=PARSER,
            source_schema_version=context.source_schema_version,
            legacy_path=context.relative_path,
        ),
    )
    emitter.records["source_occurrence"] += 1
    emitter.provenance(
        {
            "artifact_id": artifact,
            "byte_length": len(data),
            "locator": emitter.locator(),
            "encoding": "original_bytes",
        }
    )
    emitter.call(
        "add_migration_identity",
        MigrationIdentityRecord(
            emitter.occurrence, context.capture_digest, "source_occurrence", emitter.locator()
        ),
    )
    emitter.legacy(emitter.occurrence, "old_path", context.relative_path)
    kind = config_kind(context.relative_path)
    if kind is not None:
        success = config(emitter, data, artifact, kind)
        emitter.disposition("migrated" if success else "preserved_opaque", "configuration_source")
    elif context.relative_path.lower().endswith(".csv"):
        _csv(emitter, data, pending)
    else:
        emitter.issue("opaque_file_format")
        emitter.disposition("preserved_opaque", "original_source_bytes_retained")
    return emitter.finish()


def _csv(
    emitter: Emitter,
    data: bytes,
    pending: list[LegacyOverviewCandidateRecord] | None,
) -> None:
    failed = False
    try:
        for ordinal, payload, row in rows(data):
            emitter.row = ordinal
            emitter.provenance(payload)
            emitter.records["csv_row"] += 1
            if row is None:
                emitter.issue("ambiguous_csv_structure")
                emitter.disposition("preserved_opaque", "duplicate_columns_or_extra_cells")
                continue
            observation = emitter.identifier("observation")
            emitter.entity(
                "observation",
                ObservationRecord(observation, emitter.occurrence, None, None, None, "unknown"),
            )
            before = sum(emitter.issues.values())
            success = _row(emitter, row, observation, pending)
            if not success or sum(emitter.issues.values()) > before:
                emitter.disposition(
                    "preserved_opaque",
                    "typed_report_with_unverified_reference_or_extra_evidence"
                    if success
                    and emitter.context.migration_policy == OVERVIEW_REPORT_POLICY
                    and report_role(emitter.context.relative_path) is not None
                    else "row_contains_explicit_untyped_evidence",
                )
            else:
                emitter.disposition("migrated", "persisted_row_meaning_preserved")
    except (UnicodeError, csv.Error):
        emitter.row = None
        emitter.issue("invalid_csv")
        failed = True
    finally:
        emitter.row = None
    emitter.disposition(
        "preserved_opaque" if failed else "migrated",
        "csv_parse_failed" if failed else "csv_container_bytes_retained",
    )


def _row(
    emitter: Emitter,
    row: dict[str, str | None],
    observation: str,
    pending: list[LegacyOverviewCandidateRecord] | None,
) -> bool:
    parts = PurePosixPath(emitter.context.relative_path).parts
    if "transactions" in parts:
        return transaction(emitter, row, observation)
    role = report_role(emitter.context.relative_path)
    if emitter.context.migration_policy == OVERVIEW_REPORT_POLICY and role is not None:
        return report(emitter, row, observation, role, pending)
    if "fact_id" in row and "fact_kind" in row:
        return fact(emitter, row, observation)
    if "instrument_id" in row and "snapshot_date" in row:
        return asset(emitter, row, observation)
    if "source_fact_id" in row:
        emitter.issue("unresolved_source_fact", "source_fact_id", row["source_fact_id"])
    else:
        emitter.issue("unsupported_csv_role")
    return False
