"""Compose a canonical catalog with separately observed runtime collections."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any

from finjuice.pipeline.cli.commands.index_collections import (
    COLLECTION_SPECS,
    _journals_collection,
    _reports_collection,
    _templates_collection,
)
from finjuice.pipeline.config import Config
from finjuice.pipeline.index_repository import FinancialCollection, RepositoryIndexInputs

_ORDER = (
    "transactions",
    "rules",
    "reports",
    "journals",
    "templates",
    "assets",
    "goals",
    "scenarios",
)


def build_repository_index(
    config: Config, inputs: RepositoryIndexInputs, *, include_paths: bool
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Keep pinned financial facts distinct from external file observations."""
    entries = {item.name: _financial_entry(item) for item in inputs.collections}
    started_at = datetime.now(timezone.utc).isoformat()
    for name in ("reports", "journals"):
        entries[name] = _observe_files(name, config, include_paths=include_paths)
    entries["templates"] = {
        **_templates_collection(include_paths=include_paths),
        "basis": "runtime_inventory",
        "count_basis": "packaged_templates",
        "count_state": "known",
    }
    completed_at = datetime.now(timezone.utc).isoformat()
    collections = [entries[name] for name in _ORDER]
    status = _canonical_workspace_status(collections)
    path = str(config.data_dir.resolve()) if include_paths else None
    payload = {
        "workspace": {
            "status": status,
            "data_dir_source": "resolved_config",
            "path": path,
            "path_included": include_paths,
            "basis": "repository_with_external_observations",
        },
        "collections": collections,
        "recommended_next": _canonical_next(status),
        "schema_ref": "schemas/index.schema.json",
    }
    metadata = {
        "repository": inputs.metadata,
        "observations": {
            "basis": "external_runtime_observations",
            "started_at": started_at,
            "completed_at": completed_at,
        },
    }
    return payload, metadata


def _financial_entry(item: FinancialCollection) -> dict[str, Any]:
    spec = COLLECTION_SPECS[item.name]
    return {
        **asdict(item),
        "type": "repository_rows"
        if item.name in {"transactions", "assets"}
        else "repository_config",
        "latest_modified": None,
        "path": None,
        "path_included": False,
        "privacy_level": spec.privacy_level,
        "recommended_commands": list(spec.recommended_commands),
        "notes": (
            ["Canonical collection evidence is unavailable; run finjuice doctor --json."]
            if item.count_state == "unavailable"
            else []
        ),
    }


def _observe_files(name: str, config: Config, *, include_paths: bool) -> dict[str, Any]:
    collect = _reports_collection if name == "reports" else _journals_collection
    try:
        result = collect(config, include_paths=include_paths)
    except OSError:
        spec = COLLECTION_SPECS[name]
        result = {
            "name": name,
            "type": spec.collection_type,
            "status": "unavailable",
            "exists": None,
            "count": None,
            "count_label": "artifact_files" if name == "reports" else "journal_entries",
            "latest_modified": None,
            "privacy_level": spec.privacy_level,
            "path": None,
            "path_included": False,
            "recommended_commands": ["finjuice doctor --json"],
            "notes": ["External file inventory is unavailable; inspect filesystem access."],
            "unavailable_reason": "filesystem_observation_failed",
        }
    state = "known"
    if result["status"] == "unavailable":
        state = "unavailable"
    elif not result["exists"]:
        state = "absent"
    return {
        **result,
        "basis": "filesystem_observation",
        "count_basis": "artifact_files" if name == "reports" else "journal_entries",
        "count_state": state,
    }


def _canonical_workspace_status(collections: list[dict[str, Any]]) -> str:
    if any(
        item.get("count_state") == "unavailable"
        or (item["name"] in {"transactions", "rules"} and item["status"] == "missing")
        for item in collections
    ):
        return "incomplete"
    if any(
        item["name"] in {"transactions", "assets", "reports", "journals"}
        and item["status"] == "populated"
        for item in collections
    ):
        return "populated"
    return "initialized_empty"


def _canonical_next(status: str) -> list[str]:
    if status == "incomplete":
        return ["finjuice doctor --json", "finjuice status --json"]
    if status == "initialized_empty":
        return ["finjuice import <banksalad.xlsx> --json"]
    return ["finjuice status --json", "finjuice rules suggest --json --top 5"]
