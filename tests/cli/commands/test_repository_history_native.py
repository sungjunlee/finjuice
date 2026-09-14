"""Native exact imports expose honest nullable history fields and verified receipts."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.mutation_facade import MutationIdentity, StorageMutationFacade
from finjuice.pipeline.storage.sqlite.exact_import import ExactImportCommand, capture_exact_xlsx
from tests.cli.commands.test_repository_assets import _activate
from tests.pipeline.test_sqlite_exact_import import _tx_book, _tx_row
from tests.test_json_schemas import _load_schema, _validator_for


def _native_root(tmp_path: Path, filename: str | None = "synthetic.xlsx"):
    source = tmp_path / "source"
    source.mkdir()
    root = _activate(source, tmp_path)
    command = ExactImportCommand(capture_exact_xlsx(_tx_book(_tx_row(2)), filename=filename))
    facade = StorageMutationFacade(root.root, root.provider)
    receipt = facade.import_exact_xlsx(
        command, identity=MutationIdentity("first", root.generation, 0)
    )
    return root, command, facade, receipt


def _history(root, *, human: bool = False):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(root.root), "history", *([] if human else ["--json"])],
        obj={"activation_evidence_provider": root.provider},
    )


def test_native_json_schema_and_noop_keep_one_receipt(tmp_path: Path) -> None:
    root, command, facade, receipt = _native_root(tmp_path)
    first = _history(root)
    assert first.exit_code == 0, first.output
    payload = json.loads(first.output)
    _validator_for(_load_schema("history.schema.json")).validate(payload)
    assert payload["count"] == 1
    record = payload["records"][0]
    assert record["occurrence_id"] == receipt.result["occurrence_id"]
    assert record["origin"] == "native_import"
    assert record["original_filename"] == "synthetic.xlsx"
    assert record["file_id"] is None and record["legacy_file_ids"] == []
    assert record["source_rows"] is None and record["archived"] is None
    assert record["archived_path"] is None and record["source_artifact_preserved"] is True
    assert record["import_counts"]["transactions"]["inserted"] == 1
    assert payload["_meta"]["dataset_revision"] == 1
    noop = facade.import_exact_xlsx(command, identity=MutationIdentity("noop", root.generation, 1))
    assert noop.result["noop"] is True
    after = _history(root)
    assert after.exit_code == 0, after.output
    assert json.loads(after.output)["records"] == payload["records"]


def test_native_human_displays_unknown_instead_of_inferred_rows_or_archive(tmp_path: Path) -> None:
    root, *_ = _native_root(tmp_path)
    result = _history(root, human=True)
    assert result.exit_code == 0, result.output
    assert "Native import" in result.output
    assert "Unknown" in result.output
    assert "known source rows" in result.output
    assert "Repository revision 1" in result.output
    assert root.generation in result.output


def test_native_missing_filename_remains_null_and_does_not_use_live_history(tmp_path: Path) -> None:
    root, *_ = _native_root(tmp_path, filename=None)
    history = root.root / "metadata/import_history.csv"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text("file_id,original_filename\nPRIVATE_SENTINEL,fake.xlsx\n")
    result = _history(root)
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    _validator_for(_load_schema("history.schema.json")).validate(payload)
    assert payload["records"][0]["original_filename"] is None
    assert "PRIVATE_SENTINEL" not in result.output
