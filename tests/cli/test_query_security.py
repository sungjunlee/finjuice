"""Security regression tests for read-only query validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.analytics import validate_readonly_sql
from finjuice.pipeline.cli.main import app

runner = CliRunner()


@pytest.fixture
def initialized_data_dir(tmp_path: Path) -> Path:
    """Create a minimal initialized data directory for CLI validation tests."""
    data_dir = tmp_path / "data"
    result = runner.invoke(app, ["--data-dir", str(data_dir), "init"])
    assert result.exit_code == 0, result.output
    return data_dir


@pytest.mark.parametrize(
    "function_name",
    [
        "read_blob",
        "read_csv",
        "read_csv_auto",
        "read_json",
        "read_json_auto",
        "read_json_objects",
        "read_json_objects_auto",
        "read_ndjson",
        "read_ndjson_auto",
        "read_ndjson_objects",
        "read_parquet",
        "read_text",
        "parquet_bloom_probe",
        "parquet_file_metadata",
        "parquet_kv_metadata",
        "parquet_metadata",
        "parquet_scan",
        "parquet_schema",
        "sniff_csv",
    ],
)
def test_validate_readonly_sql_rejects_external_file_table_functions(
    function_name: str,
) -> None:
    sql = f"SELECT * FROM {function_name}('/tmp/private.csv')"

    with pytest.raises(ValueError, match="restricted DuckDB table function"):
        validate_readonly_sql(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1 AS one",
        "WITH t AS (SELECT 1 AS one) SELECT one FROM t",
        "SELECT 'read_csv_auto is text only' AS note",
    ],
)
def test_validate_readonly_sql_allows_normal_readonly_queries(sql: str) -> None:
    assert validate_readonly_sql(sql) == sql.upper()


def test_query_json_rejects_read_csv_auto_with_structured_error(
    initialized_data_dir: Path,
) -> None:
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(initialized_data_dir),
            "query",
            "SELECT * FROM read_csv_auto('/tmp/private.csv')",
            "--json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "query"
    assert payload["error"]["code"] == "VALIDATION_FAILED"
    assert "restricted DuckDB table function" in payload["error"]["message"]
