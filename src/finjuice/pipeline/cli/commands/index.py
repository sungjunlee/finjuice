"""Workspace catalog command for agent-oriented discovery."""

from __future__ import annotations

from typing import Any

import typer
from rich.table import Table

from finjuice.pipeline.cli import output
from finjuice.pipeline.cli.commands.index_collections import (
    _assets_collection,
    _goals_collection,
    _journals_collection,
    _reports_collection,
    _rules_collection,
    _scenarios_collection,
    _templates_collection,
    _transactions_collection,
)
from finjuice.pipeline.cli.privacy import PrivacyProfile, privacy_meta
from finjuice.pipeline.cli.utils import get_config
from finjuice.pipeline.config import Config

INDEX_SCHEMA_REF = "schemas/index.schema.json"


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
