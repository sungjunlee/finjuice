"""Workspace collection catalog helpers for ``finjuice index``.

Owns collection specs and per-collection catalog entries. Filesystem
counting helpers live in
:mod:`finjuice.pipeline.cli.commands.index_collections_helpers` and are
re-exported here so existing callers can keep importing from this module.
Catalog assembly, privacy projection, human rendering, and the Typer
command stay in :mod:`finjuice.pipeline.cli.commands.index`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from finjuice.pipeline.cli.commands.index_collections_helpers import (
    _csv_row_count,
    _iso_mtime,
    _latest_mtime,
    _safe_yaml_count,
    _yaml_signal_count,
)
from finjuice.pipeline.cli.commands.template_cmd.registry import _load_registry
from finjuice.pipeline.config import Config


@dataclass(frozen=True)
class _CollectionSpec:
    """Static metadata for one workspace collection."""

    name: str
    collection_type: str
    privacy_level: str
    recommended_commands: list[str]


@dataclass(frozen=True)
class _CollectionState:
    """Computed state for one workspace collection."""

    base_path: Path
    exists: bool
    status: str
    count: int | None
    count_label: str
    latest_modified: str | None
    notes: list[str]


COLLECTION_SPECS = {
    "transactions": _CollectionSpec(
        name="transactions",
        collection_type="csv_partitions",
        privacy_level="private_financial_rows",
        recommended_commands=[
            "finjuice status --json",
            "finjuice query --json 'SELECT * FROM transactions LIMIT 20'",
            "finjuice show --json --limit 20",
        ],
    ),
    "rules": _CollectionSpec(
        name="rules",
        collection_type="yaml",
        privacy_level="local_financial_rules",
        recommended_commands=[
            "finjuice rules validate --json",
            "finjuice rules list --json",
            "finjuice explain --json QUERY",
        ],
    ),
    "reports": _CollectionSpec(
        name="reports",
        collection_type="artifacts",
        privacy_level="private_financial_summaries",
        recommended_commands=[
            "finjuice export --dry-run --json",
            "finjuice open reports",
        ],
    ),
    "journals": _CollectionSpec(
        name="journals",
        collection_type="markdown",
        privacy_level="private_financial_notes",
        recommended_commands=[
            "finjuice journal list --json",
            "finjuice journal new --help",
        ],
    ),
    "templates": _CollectionSpec(
        name="templates",
        collection_type="packaged_sql",
        privacy_level="public_runtime_metadata",
        recommended_commands=[
            "finjuice template list --json",
            "finjuice template show NAME --json",
            "finjuice template run NAME --json",
        ],
    ),
    "assets": _CollectionSpec(
        name="assets",
        collection_type="csv_partitions",
        privacy_level="private_financial_rows",
        recommended_commands=[
            "finjuice assets status --json",
            "finjuice assets show --json",
        ],
    ),
    "goals": _CollectionSpec(
        name="goals",
        collection_type="yaml",
        privacy_level="private_financial_plans",
        recommended_commands=[
            "finjuice checkup --json",
            "finjuice networth forecast --json",
        ],
    ),
    "scenarios": _CollectionSpec(
        name="scenarios",
        collection_type="yaml",
        privacy_level="private_financial_plans",
        recommended_commands=[
            "finjuice checkup --json",
            "finjuice networth forecast --json",
        ],
    ),
}


def _collection_entry(
    spec: _CollectionSpec,
    *,
    state: _CollectionState,
    include_paths: bool,
) -> dict[str, Any]:
    """Build a collection catalog entry."""
    return {
        "name": spec.name,
        "type": spec.collection_type,
        "status": state.status,
        "exists": state.exists,
        "count": state.count,
        "count_label": state.count_label,
        "latest_modified": state.latest_modified,
        "privacy_level": spec.privacy_level,
        "path": str(state.base_path.resolve()) if include_paths and state.exists else None,
        "path_included": include_paths and state.exists,
        "recommended_commands": spec.recommended_commands,
        "notes": state.notes,
    }


def _transactions_collection(config: Config, *, include_paths: bool) -> dict[str, Any]:
    transactions_dir = config.csv_base_dir
    partitions = sorted(transactions_dir.rglob("*.csv")) if transactions_dir.exists() else []
    status = "populated" if partitions else "empty" if transactions_dir.exists() else "missing"
    notes = [] if partitions else ["Run finjuice import or finjuice ingest to create partitions."]
    count = _csv_row_count(partitions) if partitions else 0 if transactions_dir.exists() else None
    return _collection_entry(
        COLLECTION_SPECS["transactions"],
        state=_CollectionState(
            base_path=transactions_dir,
            exists=transactions_dir.exists(),
            status=status,
            count=count,
            count_label="transaction_rows",
            latest_modified=_latest_mtime(partitions) or _iso_mtime(transactions_dir),
            notes=notes,
        ),
        include_paths=include_paths,
    )


def _rules_collection(config: Config, *, include_paths: bool) -> dict[str, Any]:
    rules_path = config.rules_file
    exists = rules_path.exists()
    return _collection_entry(
        COLLECTION_SPECS["rules"],
        state=_CollectionState(
            base_path=rules_path,
            exists=exists,
            status="populated" if exists else "missing",
            count=_safe_yaml_count(rules_path, "rules") if exists else None,
            count_label="rules",
            latest_modified=_iso_mtime(rules_path),
            notes=[] if exists else ["Run finjuice init or restore rules.yaml."],
        ),
        include_paths=include_paths,
    )


def _reports_collection(config: Config, *, include_paths: bool) -> dict[str, Any]:
    reports_dir = config.reports_dir
    files = (
        sorted(path for path in reports_dir.rglob("*") if path.is_file())
        if reports_dir.exists()
        else []
    )
    status = "populated" if files else "empty" if reports_dir.exists() else "missing"
    return _collection_entry(
        COLLECTION_SPECS["reports"],
        state=_CollectionState(
            base_path=reports_dir,
            exists=reports_dir.exists(),
            status=status,
            count=len(files) if reports_dir.exists() else None,
            count_label="artifact_files",
            latest_modified=_latest_mtime(files) or _iso_mtime(reports_dir),
            notes=[] if files else ["Run finjuice export --json to generate report artifacts."],
        ),
        include_paths=include_paths,
    )


def _journals_collection(config: Config, *, include_paths: bool) -> dict[str, Any]:
    journal_dir = config.journal_dir
    entries = sorted(journal_dir.glob("*.md")) if journal_dir.exists() else []
    status = "populated" if entries else "empty" if journal_dir.exists() else "missing"
    return _collection_entry(
        COLLECTION_SPECS["journals"],
        state=_CollectionState(
            base_path=journal_dir,
            exists=journal_dir.exists(),
            status=status,
            count=len(entries) if journal_dir.exists() else None,
            count_label="journal_entries",
            latest_modified=_latest_mtime(entries) or _iso_mtime(journal_dir),
            notes=[] if entries else ["Run finjuice journal new to create a snapshot-backed note."],
        ),
        include_paths=include_paths,
    )


def _templates_collection(*, include_paths: bool) -> dict[str, Any]:
    templates = _load_registry()
    return _collection_entry(
        COLLECTION_SPECS["templates"],
        state=_CollectionState(
            base_path=Path("templates/sql"),
            exists=True,
            status="populated" if templates else "empty",
            count=len(templates),
            count_label="templates",
            latest_modified=None,
            notes=[] if not include_paths else ["Packaged templates do not expose a stable path."],
        ),
        include_paths=False,
    )


def _assets_collection(config: Config, *, include_paths: bool) -> dict[str, Any]:
    snapshots_dir = config.data_dir / "assets" / "snapshots"
    partitions = sorted(snapshots_dir.rglob("snapshots.csv")) if snapshots_dir.exists() else []
    status = "populated" if partitions else "empty" if snapshots_dir.exists() else "missing"
    return _collection_entry(
        COLLECTION_SPECS["assets"],
        state=_CollectionState(
            base_path=snapshots_dir,
            exists=snapshots_dir.exists(),
            status=status,
            count=_csv_row_count(partitions)
            if partitions
            else 0
            if snapshots_dir.exists()
            else None,
            count_label="snapshot_rows",
            latest_modified=_latest_mtime(partitions) or _iso_mtime(snapshots_dir),
            notes=[] if partitions else ["Import an export that includes asset snapshot sheets."],
        ),
        include_paths=include_paths,
    )


def _goals_collection(config: Config, *, include_paths: bool) -> dict[str, Any]:
    goals_path = config.goals_file
    exists = goals_path.exists()
    return _collection_entry(
        COLLECTION_SPECS["goals"],
        state=_CollectionState(
            base_path=goals_path,
            exists=exists,
            status="populated" if exists else "missing",
            count=(
                _yaml_signal_count(
                    goals_path,
                    (
                        "monthly_budget",
                        "net_worth_target",
                        "known_obligations",
                        "recurring_savings",
                        "financial_context",
                    ),
                )
                if exists
                else None
            ),
            count_label="configured_signals",
            latest_modified=_iso_mtime(goals_path),
            notes=[] if exists else ["Run finjuice init to seed goals.yaml."],
        ),
        include_paths=include_paths,
    )


def _scenarios_collection(config: Config, *, include_paths: bool) -> dict[str, Any]:
    scenarios_path = config.scenarios_file
    exists = scenarios_path.exists()
    return _collection_entry(
        COLLECTION_SPECS["scenarios"],
        state=_CollectionState(
            base_path=scenarios_path,
            exists=exists,
            status="populated" if exists else "missing",
            count=(
                _yaml_signal_count(scenarios_path, ("assumptions", "lifecycle_events"))
                if exists
                else None
            ),
            count_label="configured_signals",
            latest_modified=_iso_mtime(scenarios_path),
            notes=[] if exists else ["Run finjuice init to seed scenarios.yaml."],
        ),
        include_paths=include_paths,
    )
