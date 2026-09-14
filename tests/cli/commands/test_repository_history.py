"""Canonical history preserves uncertain values and refuses partial evidence."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.cli.commands.test_typed_json_payload_contracts import _validate_command_schema
from tests.pipeline.test_sqlite_history_reads import _active


def _invoke(root, *, human=False, evidence=True):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "history", *([] if human else ["--json"])],
        obj={"activation_evidence_provider": root.provider} if evidence else {},
    )


def test_history_preserves_duplicates_unknowns_and_ignores_live_csv(tmp_path: Path) -> None:
    root = _active(tmp_path)
    live = root.root / "metadata/import_history.csv"
    live.parent.mkdir(parents=True)
    live.write_text("PRIVATE_SENTINEL,broken\n")

    result = _invoke(root)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    first, second = payload["records"]
    assert payload["count"] == 2
    assert first["file_id"] == second["file_id"] == "same"
    assert first["source_rows"] == 4
    assert first["source_fields"]["source_rows"] == "004"
    assert first["imported_at"] == "not-a-date"
    assert second["source_rows"] is None and second["archived"] is None
    assert second["source_fields"]["archived"] == "unknown"
    assert second["field_issues"] == ["source_rows_unavailable", "archive_status_unavailable"]
    assert payload["summary"] == {
        "known_source_rows": 4,
        "unknown_source_rows_records": 1,
        "archived_files": 1,
        "unknown_archive_records": 1,
    }
    assert payload["_meta"]["dataset_revision"] == 0
    assert payload["_meta"]["read_policy"] == "source_import_history.v1"
    assert "PRIVATE_SENTINEL" not in result.output
    _validate_command_schema(payload, command="history", schema_file="history.schema.json")
    human = _invoke(root, human=True)
    assert human.exit_code == 0, human.output
    assert "Unknown" in human.output and "4 known source rows" in human.output


@pytest.mark.parametrize("human", [False, True])
def test_incomplete_history_and_missing_activation_fail_without_raw_detail(
    tmp_path: Path, human: bool
) -> None:
    root = _active(tmp_path, b"file_id,imported_at\nPRIVATE_SENTINEL,date,extra\n")
    result = _invoke(root, human=human)
    assert result.exit_code == 3, result.output
    assert "PRIVATE_SENTINEL" not in result.output
    assert "complete validated source evidence" in result.output
    missing = _invoke(root, human=human, evidence=False)
    assert missing.exit_code != 0
    assert "PRIVATE_SENTINEL" not in missing.output


def test_empty_history_is_verified_and_explicit(tmp_path: Path) -> None:
    root = _active(tmp_path, b"file_id,imported_at\n")
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["count"] == 0 and payload["records"] == []
    assert _invoke(root, human=True).exit_code == 0
    _validate_command_schema(payload, command="history", schema_file="history.schema.json")


def test_unrepresentable_count_is_preserved_without_losing_record(tmp_path: Path) -> None:
    value = "9" * 5000
    root = _active(tmp_path, f"file_id,imported_at,source_rows\nf,date,{value}\n".encode())
    result = _invoke(root)
    assert result.exit_code == 0, result.output
    record = json.loads(result.output)["records"][0]
    assert record["source_rows"] is None
    assert record["source_fields"]["source_rows"] == value
    assert record["field_issues"] == ["source_rows_unavailable"]
