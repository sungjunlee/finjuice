"""Write the completed exact-import root manifest on source-bound provenance."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from finjuice.pipeline.storage.sqlite.exact_import.cells import json_ready
from finjuice.pipeline.storage.sqlite.exact_import.constants import (
    IMPORT_POLICY_VERSION,
    MANIFEST_COORDINATE_KIND,
    MANIFEST_KIND,
    PARSER_POLICY_VERSION,
    parser_versions,
)
from finjuice.pipeline.storage.sqlite.exact_import.evidence import (
    IssueView,
    PersistSession,
    add_issues,
)
from finjuice.pipeline.storage.sqlite.exact_import.models import ExactImportIntent, ImportCounts
from finjuice.pipeline.storage.sqlite.ids import new_entity_id
from finjuice.pipeline.storage.sqlite.records import ProvenanceRecord

JSONValue = Any


def persist_manifest(
    session: PersistSession,
    *,
    intent: ExactImportIntent,
    counts: ImportCounts,
    ids: Mapping[str, JSONValue],
    mapping_issue_codes: tuple[str, ...],
) -> str:
    """Persist one completed import marker sufficient for later identity lookup."""
    provenance_id = new_entity_id()
    session.context.add_provenance(
        ProvenanceRecord(
            provenance_id=provenance_id,
            occurrence_id=session.occurrence_id,
            source_coordinate={"kind": MANIFEST_COORDINATE_KIND, "role": "root"},
            legacy_locator={
                "artifact_id": session.artifact_id,
                "kind": MANIFEST_COORDINATE_KIND,
                "locator_version": 1,
            },
            parser_version=IMPORT_POLICY_VERSION,
        )
    )
    payload = {
        "counts": counts.as_dict(),
        "ids": dict(ids),
        "import_policy_version": IMPORT_POLICY_VERSION,
        "intent": intent.payload(),
        "manifest_kind": MANIFEST_KIND,
        "parser_policy_version": PARSER_POLICY_VERSION,
        "parser_versions": parser_versions(),
        "status": "completed",
    }
    session.context.add_legacy_payload(provenance_id, json_ready(payload))
    issues = tuple(
        IssueView(code, None, None, None, "Workbook-level mapping issue.")
        for code in mapping_issue_codes
    )
    add_issues(session, provenance_id, issues)
    return provenance_id
