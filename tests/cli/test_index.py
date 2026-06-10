"""Tests for the agent-facing workspace index command."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


def _index_payload(data_dir: Path, *args: str) -> dict[str, object]:
    result = runner.invoke(app, ["--data-dir", str(data_dir), "index", "--json", *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def _collections(payload: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        str(collection["name"]): collection
        for collection in payload["collections"]  # type: ignore[index]
    }


def test_index_json_handles_uninitialized_workspace(tmp_path: Path) -> None:
    """Missing data directories should still produce a catalog for first-run agents."""
    # Arrange
    data_dir = tmp_path / "missing-data"

    # Act
    payload = _index_payload(data_dir)
    collections = _collections(payload)

    # Assert
    assert payload["_meta"]["command"] == "index"  # type: ignore[index]
    assert payload["workspace"]["status"] == "uninitialized"  # type: ignore[index]
    assert payload["workspace"]["path"] is None  # type: ignore[index]
    assert collections["transactions"]["status"] == "missing"
    assert collections["transactions"]["count"] is None
    assert collections["rules"]["status"] == "missing"
    assert "finjuice init" in payload["recommended_next"]  # type: ignore[operator]


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
    assert payload["workspace"]["status"] == "initialized_empty"  # type: ignore[index]
    assert collections["transactions"]["status"] == "empty"
    assert collections["transactions"]["count"] == 0
    assert collections["rules"]["status"] == "populated"
    assert collections["rules"]["count"] == 0
    assert collections["goals"]["status"] == "populated"
    assert collections["scenarios"]["status"] == "populated"
    assert payload["workspace"]["path_included"] is False  # type: ignore[index]
    assert collections["transactions"]["path"] is None


def test_index_json_catalogs_populated_fixture_without_paths(
    json_output_data_dir: Path,
) -> None:
    """Populated fixture workspaces expose counts, privacy, and inspect commands."""
    # Act
    payload = _index_payload(json_output_data_dir)
    collections = _collections(payload)

    # Assert
    assert payload["workspace"]["status"] == "populated"  # type: ignore[index]
    assert payload["schema_ref"] == "schemas/index.schema.json"
    assert collections["transactions"]["count"] == 4
    assert collections["transactions"]["count_label"] == "transaction_rows"
    assert collections["transactions"]["privacy_level"] == "private_financial_rows"
    assert collections["transactions"]["path"] is None
    assert "finjuice status --json" in collections["transactions"]["recommended_commands"]
    assert collections["rules"]["count"] == 2
    assert collections["reports"]["count"] == 2
    assert collections["assets"]["count"] == 2
    assert collections["templates"]["count"] > 0  # type: ignore[operator]


def test_index_json_default_raw_profile_includes_privacy_meta(
    json_output_data_dir: Path,
) -> None:
    """The default JSON contract should explicitly identify the raw privacy profile."""
    # Act
    payload = _index_payload(json_output_data_dir)

    # Assert
    assert payload["_meta"]["privacy"]["profile"] == "raw"  # type: ignore[index]


def test_index_json_redacted_suppresses_paths_even_when_requested(
    json_output_data_dir: Path,
) -> None:
    """Redacted index output should not disclose local paths."""
    # Act
    payload = _index_payload(json_output_data_dir, "--privacy", "redacted", "--include-paths")
    collections = _collections(payload)

    # Assert
    assert payload["_meta"]["privacy"]["profile"] == "redacted"  # type: ignore[index]
    assert payload["workspace"]["path"] is None  # type: ignore[index]
    assert payload["workspace"]["path_included"] is False  # type: ignore[index]
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
    assert payload["_meta"]["privacy"]["profile"] == "compact"  # type: ignore[index]
    assert payload["workspace"]["path"] is None  # type: ignore[index]
    assert payload["workspace"]["path_included"] is False  # type: ignore[index]
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
    assert payload["workspace"]["path"] == str(json_output_data_dir.resolve())  # type: ignore[index]
    assert payload["workspace"]["path_included"] is True  # type: ignore[index]
    assert collections["transactions"]["path"] == str(
        (json_output_data_dir / "transactions").resolve()
    )
    assert collections["transactions"]["path_included"] is True
    assert collections["templates"]["path"] is None
    assert collections["templates"]["path_included"] is False
