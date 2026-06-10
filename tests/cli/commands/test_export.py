"""CLI integration tests for export command formats."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.cli.report_filter_support import build_cli_data_dir as _build_cli_data_dir

runner = CliRunner()


def test_export_format_xlsx_unaffected(tmp_path: Path) -> None:
    """xlsx dry-run JSON should keep its existing export shape."""
    # Arrange
    data_dir = _build_cli_data_dir(
        tmp_path,
        """
        version: 1
        rules: []
        """,
    )

    # Act
    result = runner.invoke(
        app,
        ["export", "--format", "xlsx", "--dry-run", "--json"],
        env={"FINJUICE_DATA_DIR": str(data_dir)},
    )

    # Assert
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["command"] == "export"
    assert payload["dry_run"] is True
    assert payload["format"] == "xlsx"
    assert payload["transaction_count"] == 0
    assert "domain" not in payload
    assert "summary" not in payload
    assert "assumptions" not in payload
