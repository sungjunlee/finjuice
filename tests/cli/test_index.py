"""Tests for the agent-facing workspace index command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _as_object(value: object, *, field: str) -> dict[str, Any]:
    assert isinstance(value, dict), f"{field} must be a JSON object, got {type(value).__name__}"
    return cast(dict[str, Any], value)


def _as_array(value: object, *, field: str) -> list[Any]:
    assert isinstance(value, list), f"{field} must be a JSON array, got {type(value).__name__}"
    return cast(list[Any], value)


def _index_payload(data_dir: Path, *args: str) -> dict[str, Any]:
    result = runner.invoke(app, ["--data-dir", str(data_dir), "index", "--json", *args])
    assert result.exit_code == 0, result.output
    return _as_object(json.loads(result.output), field="index payload")


def _collections(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    collections: dict[str, dict[str, Any]] = {}
    for collection in _as_array(payload["collections"], field="collections"):
        entry = _as_object(collection, field="collection")
        name = entry["name"]
        assert isinstance(name, str)
        collections[name] = entry
    return collections


def _workspace(payload: dict[str, Any]) -> dict[str, Any]:
    return _as_object(payload["workspace"], field="workspace")


def _meta(payload: dict[str, Any]) -> dict[str, Any]:
    return _as_object(payload["_meta"], field="_meta")


def _privacy_profile(payload: dict[str, Any]) -> object:
    privacy = _as_object(_meta(payload)["privacy"], field="_meta.privacy")
    return privacy["profile"]


def test_index_json_handles_uninitialized_workspace(tmp_path: Path) -> None:
    """Missing data directories should still produce a catalog for first-run agents."""
    # Arrange
    data_dir = tmp_path / "missing-data"

    # Act
    payload = _index_payload(data_dir)
    collections = _collections(payload)

    # Assert
    workspace = _workspace(payload)
    recommended_next = _as_array(payload["recommended_next"], field="recommended_next")
    assert _meta(payload)["command"] == "index"
    assert workspace["status"] == "uninitialized"
    assert workspace["path"] is None
    assert collections["transactions"]["status"] == "missing"
    assert collections["transactions"]["count"] is None
    assert collections["rules"]["status"] == "missing"
    assert "finjuice init" in recommended_next


def test_index_json_handles_initialized_empty_workspace(tmp_path: Path) -> None:
    """Initialized workspaces with no data should be distinct from missing workspaces."""
    # Arrange
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "transactions").mkdir()
    (data_dir / "exports" / "reports").mkdir(parents=True)
    (data_dir / "metadata").mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (data_dir / "goals.yaml").write_text(
        "version: 1\nmonthly_budget:\n  total: 2000000\n",
        encoding="utf-8",
    )
    (data_dir / "scenarios.yaml").write_text(
        "version: 1\nassumptions:\n  default_savings_per_month: 1000000\n",
        encoding="utf-8",
    )

    # Act
    payload = _index_payload(data_dir)
    collections = _collections(payload)

    # Assert
    workspace = _workspace(payload)
    assert workspace["status"] == "initialized_empty"
    assert collections["transactions"]["status"] == "empty"
    assert collections["transactions"]["count"] == 0
    assert collections["rules"]["status"] == "populated"
    assert collections["rules"]["count"] == 0
    assert collections["goals"]["status"] == "populated"
    assert collections["scenarios"]["status"] == "populated"
    assert workspace["path_included"] is False
    assert collections["transactions"]["path"] is None


def test_index_json_catalogs_populated_fixture_without_paths(
    json_output_data_dir: Path,
) -> None:
    """Populated fixture workspaces expose counts, privacy, and inspect commands."""
    # Act
    payload = _index_payload(json_output_data_dir)
    collections = _collections(payload)

    # Assert
    template_count = collections["templates"]["count"]
    assert _workspace(payload)["status"] == "populated"
    assert payload["schema_ref"] == "schemas/index.schema.json"
    assert collections["transactions"]["count"] == 4
    assert collections["transactions"]["count_label"] == "transaction_rows"
    assert collections["transactions"]["privacy_level"] == "private_financial_rows"
    assert collections["transactions"]["path"] is None
    assert "finjuice status --json" in collections["transactions"]["recommended_commands"]
    assert collections["rules"]["count"] == 2
    assert collections["reports"]["count"] == 2
    assert collections["assets"]["count"] == 2
    assert isinstance(template_count, int)
    assert template_count > 0


def test_index_json_default_raw_profile_includes_privacy_meta(
    json_output_data_dir: Path,
) -> None:
    """The default JSON contract should explicitly identify the raw privacy profile."""
    # Act
    payload = _index_payload(json_output_data_dir)

    # Assert
    assert _privacy_profile(payload) == "raw"


def test_index_json_redacted_suppresses_paths_even_when_requested(
    json_output_data_dir: Path,
) -> None:
    """Redacted index output should not disclose local paths."""
    # Act
    payload = _index_payload(json_output_data_dir, "--privacy", "redacted", "--include-paths")
    collections = _collections(payload)

    # Assert
    workspace = _workspace(payload)
    assert _privacy_profile(payload) == "redacted"
    assert workspace["path"] is None
    assert workspace["path_included"] is False
    for collection in collections.values():
        assert collection["path"] is None
        assert collection["path_included"] is False
    assert collections["transactions"]["recommended_commands"]


def test_index_json_compact_suppresses_paths_and_operational_detail(
    json_output_data_dir: Path,
) -> None:
    """Compact output should keep catalog signals while dropping command-level details."""
    # Act
    payload = _index_payload(json_output_data_dir, "--privacy", "compact", "--include-paths")
    collections = _collections(payload)

    # Assert
    workspace = _workspace(payload)
    assert _privacy_profile(payload) == "compact"
    assert workspace["path"] is None
    assert workspace["path_included"] is False
    assert payload["recommended_next"] == []
    assert collections["transactions"]["status"] == "populated"
    assert collections["transactions"]["count"] == 4
    assert collections["transactions"]["privacy_level"] == "private_financial_rows"
    for collection in collections.values():
        assert collection["path"] is None
        assert collection["path_included"] is False
        assert collection["recommended_commands"] == []
        assert collection["notes"] == []
        assert collection["latest_modified"] is None


def test_index_json_counts_goal_and_scenario_workspace_formats(
    json_output_data_dir: Path,
) -> None:
    """Goals and scenarios counts should reflect their real YAML shapes."""
    # Arrange
    (json_output_data_dir / "goals.yaml").write_text(
        """
version: 1
monthly_budget:
  total: 2000000
known_obligations:
  - label: rent
    amount: 900000
recurring_savings:
  - label: irp
    amount: 300000
net_worth_target: 10000000
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (json_output_data_dir / "scenarios.yaml").write_text(
        """
version: 1
assumptions:
  default_savings_per_month: 1000000
lifecycle_events:
  - name: move
    date: "2026-06-01"
    one_time_expense: 1000000
""".strip()
        + "\n",
        encoding="utf-8",
    )

    # Act
    payload = _index_payload(json_output_data_dir)
    collections = _collections(payload)

    # Assert
    assert collections["goals"]["count_label"] == "configured_signals"
    assert collections["goals"]["count"] == 4
    assert collections["scenarios"]["count_label"] == "configured_signals"
    assert collections["scenarios"]["count"] == 2


def test_index_json_includes_paths_only_when_requested(json_output_data_dir: Path) -> None:
    """Resolved local paths are opt-in to reduce accidental path disclosure."""
    # Act
    payload = _index_payload(json_output_data_dir, "--include-paths")
    collections = _collections(payload)

    # Assert
    workspace = _workspace(payload)
    assert workspace["path"] == str(json_output_data_dir.resolve())
    assert workspace["path_included"] is True
    assert collections["transactions"]["path"] == str(
        (json_output_data_dir / "transactions").resolve()
    )
    assert collections["transactions"]["path_included"] is True
    assert collections["templates"]["path"] is None
    assert collections["templates"]["path_included"] is False
