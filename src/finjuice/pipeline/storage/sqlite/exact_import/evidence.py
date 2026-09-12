"""Shared provenance, payload, and issue writers for exact import."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from finjuice.pipeline.ingest.xlsx_evidence import CellEvidence
from finjuice.pipeline.storage.sqlite.exact_import.cells import json_ready, serialize_cells
from finjuice.pipeline.storage.sqlite.exact_import.constants import IMPORT_POLICY_VERSION
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.mutations import MutationContext
from finjuice.pipeline.storage.sqlite.records import PreservationIssueRecord, ProvenanceRecord

JSONValue = Any


@dataclass(frozen=True)
class SourcePlace:
    """Sheet/row/column coordinates for one preserved source fragment."""

    family: str
    sheet_name: str
    source_row: int
    column: str | None = None


@dataclass(frozen=True)
class PersistSession:
    """IDs and clocks shared by one accepted file-level persist."""

    context: MutationContext
    occurrence_id: str
    artifact_id: str
    imported_at: str
    collected_at: str | None
    parser_version: str


@dataclass(frozen=True)
class IssueView:
    """Family-agnostic mapping issue fields."""

    code: str
    field_name: str | None
    source_row: int | None
    column: str | None
    detail: str


def utc_now() -> str:
    """Return an RFC 3339 UTC timestamp for occurrence metadata only."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def add_row_provenance(
    session: PersistSession,
    place: SourcePlace,
    cells: Sequence[CellEvidence],
    extra: Mapping[str, JSONValue] | None = None,
) -> str:
    """Persist one source-row provenance plus its raw cell payload."""
    return _add_placed_provenance(session, place, "exact_xlsx_row", cells, extra)


def add_cell_provenance(
    session: PersistSession,
    place: SourcePlace,
    cells: Sequence[CellEvidence],
    extra: Mapping[str, JSONValue] | None = None,
) -> str:
    """Persist one source-cell provenance plus raw evidence."""
    return _add_placed_provenance(session, place, "exact_xlsx_cell", cells, extra)


def _add_placed_provenance(
    session: PersistSession,
    place: SourcePlace,
    kind: str,
    cells: Sequence[CellEvidence],
    extra: Mapping[str, JSONValue] | None,
) -> str:
    provenance_id = new_entity_id()
    coordinate = _place_coordinate(place, kind)
    locator = {"artifact_id": session.artifact_id, "locator_version": 1, **coordinate}
    _add_provenance(session, provenance_id, coordinate, locator)
    payload: dict[str, JSONValue] = {
        "cells": serialize_cells(cells),
        "family": place.family,
        "row": place.source_row,
        "sheet": place.sheet_name,
    }
    if place.column is not None:
        payload["column"] = place.column
    if extra:
        payload.update(extra)
    session.context.add_legacy_payload(provenance_id, json_ready(payload))
    return provenance_id


def _place_coordinate(place: SourcePlace, kind: str) -> dict[str, JSONValue]:
    coordinate: dict[str, JSONValue] = {
        "family": place.family,
        "kind": kind,
        "row": place.source_row,
        "sheet": place.sheet_name,
    }
    if place.column is not None:
        coordinate["column"] = place.column
    return coordinate


def add_issues(
    session: PersistSession,
    provenance_id: str,
    issues: Sequence[IssueView],
    *,
    sheet_name: str | None = None,
) -> None:
    """Persist structured issues without logging source values."""
    for issue in issues:
        detail: dict[str, JSONValue] = {
            "code": issue.code,
            "column": issue.column,
            "detail": issue.detail,
            "sheet": sheet_name,
            "source_row": issue.source_row,
        }
        session.context.add_preservation_issue(
            PreservationIssueRecord(
                provenance_id=provenance_id,
                issue_kind=issue.code,
                detail=json_ready(detail),
                field_name=issue.field_name,
            )
        )


def add_mapper_issues(
    session: PersistSession,
    provenance_id: str,
    issues: Sequence[object],
    *,
    sheet_name: str | None,
) -> None:
    """Persist mapper issues for one provenance."""
    views = tuple(as_issue(item) for item in issues)
    add_issues(session, provenance_id, views, sheet_name=sheet_name)


def as_issue(issue: object) -> IssueView:
    """Adapt a mapper issue dataclass into the shared view."""
    return IssueView(
        code=str(getattr(issue, "code")),
        field_name=getattr(issue, "field_name", None),
        source_row=getattr(issue, "source_row", None),
        column=getattr(issue, "column", None),
        detail=str(getattr(issue, "detail", "")),
    )


def _add_provenance(
    session: PersistSession,
    provenance_id: str,
    coordinate: Mapping[str, JSONValue],
    locator: Mapping[str, JSONValue],
) -> None:
    session.context.add_provenance(
        ProvenanceRecord(
            provenance_id=provenance_id,
            occurrence_id=session.occurrence_id,
            source_coordinate=dict(coordinate),
            legacy_locator=dict(locator),
            parser_version=session.parser_version or IMPORT_POLICY_VERSION,
        )
    )
