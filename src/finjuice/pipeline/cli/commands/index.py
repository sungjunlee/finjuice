"""Workspace catalog command for agent-oriented discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl
import typer
import yaml
from rich.table import Table

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.template_cmd.registry import _load_registry
from finjuice.pipeline.cli.privacy import PrivacyProfile, privacy_meta
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config

INDEX_SCHEMA_REF = "schemas/index.schema.json"


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


def _iso_mtime(path: Path) -> str | None:
    """Return a stable ISO timestamp for a file or directory mtime."""
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat()


def _latest_mtime(paths: list[Path]) -> str | None:
    """Return the latest mtime across existing paths."""
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    latest = max(path.stat().st_mtime for path in existing)
    return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat()


def _safe_yaml_count(path: Path, key: str) -> int | None:
    """Count top-level YAML list entries without exposing their contents."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    values = payload.get(key) if isinstance(payload, dict) else None
    return len(values) if isinstance(values, list) else 0


def _yaml_signal_count(path: Path, keys: tuple[str, ...]) -> int | None:
    """Count configured YAML sections and list entries without exposing values."""
    if not path.exists():
        return None
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return 0

    count = 0
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            count += len(value)
        elif isinstance(value, dict):
            count += 1 if value else 0
        elif value not in (None, ""):
            count += 1
    return count


def _csv_row_count(paths: list[Path]) -> int | None:
    """Count CSV rows without materializing row content into the output."""
    total = 0
    for path in paths:
        try:
            total += pl.scan_csv(path).select(pl.len()).collect().item()
        except (OSError, pl.exceptions.ComputeError):
            return None
    return total


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


def _workspace_status(config: Config, collections: list[dict[str, Any]]) -> str:
    if not config.data_dir.exists():
        return "uninitialized"
    missing_required = {
        item["name"]
        for item in collections
        if item["name"] in {"transactions", "rules"} and item["status"] == "missing"
    }
    if missing_required:
        return "incomplete"
    data_collections = {"transactions", "reports", "journals", "assets"}
    if any(
        item["name"] in data_collections and item["status"] == "populated" for item in collections
    ):
        return "populated"
    return "initialized_empty"


def _build_index(config: Config, *, include_paths: bool) -> dict[str, Any]:
    """Build the workspace catalog payload."""
    collections = [
        _transactions_collection(config, include_paths=include_paths),
        _rules_collection(config, include_paths=include_paths),
        _reports_collection(config, include_paths=include_paths),
        _journals_collection(config, include_paths=include_paths),
        _templates_collection(include_paths=include_paths),
        _assets_collection(config, include_paths=include_paths),
        _goals_collection(config, include_paths=include_paths),
        _scenarios_collection(config, include_paths=include_paths),
    ]
    workspace_status = _workspace_status(config, collections)
    workspace_path = (
        str(config.data_dir.resolve()) if include_paths and config.data_dir.exists() else None
    )
    return {
        "workspace": {
            "status": workspace_status,
            "data_dir_source": "resolved_config",
            "path": workspace_path,
            "path_included": include_paths and config.data_dir.exists(),
        },
        "collections": collections,
        "recommended_next": _recommended_next(workspace_status),
        "schema_ref": INDEX_SCHEMA_REF,
    }


def _without_index_paths(payload: dict[str, Any]) -> dict[str, Any]:
    """Return index output with local filesystem path disclosure suppressed."""
    redacted = dict(payload)
    workspace = dict(redacted["workspace"])
    workspace["path"] = None
    workspace["path_included"] = False
    redacted["workspace"] = workspace

    collections = []
    for item in redacted["collections"]:
        collection = dict(item)
        collection["path"] = None
        collection["path_included"] = False
        collections.append(collection)
    redacted["collections"] = collections
    return redacted


def _compact_index(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a compact index that keeps catalog signals and drops operational detail."""
    compact = _without_index_paths(payload)
    compact["recommended_next"] = []
    compact["collections"] = [
        {
            **collection,
            "recommended_commands": [],
            "notes": [],
            "latest_modified": None,
        }
        for collection in compact["collections"]
    ]
    return compact


def _apply_index_privacy(payload: dict[str, Any], profile: PrivacyProfile) -> dict[str, Any]:
    """Apply the index-specific privacy profile contract."""
    if profile is PrivacyProfile.RAW:
        return payload
    if profile is PrivacyProfile.REDACTED:
        return _without_index_paths(payload)
    return _compact_index(payload)


def _recommended_next(workspace_status: str) -> list[str]:
    if workspace_status == "uninitialized":
        return ["finjuice init", "finjuice import <banksalad.xlsx> --json"]
    if workspace_status == "incomplete":
        return ["finjuice doctor --json", "finjuice init"]
    if workspace_status == "initialized_empty":
        return ["finjuice import <banksalad.xlsx> --json"]
    return ["finjuice status --json", "finjuice rules suggest --json --top 5"]


def _render_index(result: dict[str, Any]) -> None:
    """Render a compact human-readable catalog."""
    workspace = result["workspace"]
    output.section("Workspace Index")
    output.table_summary(
        "Workspace",
        [
            ("Status", str(workspace["status"])),
            ("Path", str(workspace["path"] or "(hidden; use --include-paths)")),
        ],
    )

    table = Table(title="Collections")
    table.add_column("Name", style="cyan")
    table.add_column("Status")
    table.add_column("Count", justify="right")
    table.add_column("Privacy")
    table.add_column("Next inspect command")
    for item in result["collections"]:
        commands = item.get("recommended_commands") or []
        table.add_row(
            str(item["name"]),
            str(item["status"]),
            "-" if item["count"] is None else str(item["count"]),
            str(item["privacy_level"]),
            str(commands[0]) if commands else "-",
        )
    output.console.print(table)


def register_index_command(app: typer.Typer) -> None:
    """Register the `finjuice index` command."""

    @app.command(
        name="index",
        rich_help_panel="Commands",
        help="Emit an agent-friendly workspace collection catalog.",
        short_help="Emit workspace catalog",
    )
    def index(
        ctx: typer.Context,
        json_output: bool = typer.Option(False, "--json", help="Output as JSON"),
        privacy: PrivacyProfile = typer.Option(
            PrivacyProfile.RAW,
            "--privacy",
            help="Privacy profile for JSON output: raw, redacted, or compact.",
        ),
        include_paths: bool = typer.Option(
            False,
            "--include-paths",
            help="Include resolved local filesystem paths in the catalog.",
        ),
    ) -> None:
        """List workspace collections and safe next inspection commands."""
        config = get_config(ctx)
        result = _build_index(config, include_paths=include_paths)
        output_result = _apply_index_privacy(result, privacy)
        output.emit(
            output_result,
            json_output,
            _render_index,
            command="index",
            meta_extras=privacy_meta(privacy),
        )
