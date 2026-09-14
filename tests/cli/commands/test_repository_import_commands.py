"""Active import/ingest CLI must use exact domain before any legacy effects."""

from __future__ import annotations

import json
import sqlite3
import zipfile
from contextlib import closing
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import full_pipeline_orchestrator as pipeline
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.cli.output import ExitCode
from tests.cli.commands.test_repository_bulk_commands import _invoke, _rules
from tests.cli.commands.test_repository_mutation_fences import _ActiveRoot, _authority_state
from tests.cli.commands.test_repository_mutation_fences import active_root as _active_root_fixture
from tests.pipeline.test_sqlite_exact_import import _inline, _row, _tx_book, _tx_row
from tests.pipeline.test_sqlite_source_lookup import (
    _import_workbook,
    _insert_file_id,
    _provenance_id,
)

active_root = _active_root_fixture


def _assert_export_manifest(active: _ActiveRoot, exported: dict) -> None:
    manifest_path = Path(exported["manifest_path"])
    assert manifest_path.is_file()
    metadata = exported["_repository_meta"]
    assert metadata["dataset_generation"] == active.generation
    with closing(sqlite3.connect(active.database)) as connection:
        revision = connection.execute("SELECT dataset_revision FROM repository_meta").fetchone()[0]
    assert metadata["dataset_revision"] == revision
    assert exported["output_files"]
    assert all(Path(entry["path"]).is_file() for entry in exported["output_files"])


def _transaction_count(active: _ActiveRoot) -> int:
    with closing(sqlite3.connect(active.database)) as connection:
        return int(connection.execute("SELECT count(*) FROM transactions").fetchone()[0])


def _write_xlsx(path: Path, *, extra: str | None = None) -> None:
    extra_sheets = None
    if extra is not None:
        extra_sheets = {"notes": _row(1, _inline("A1", extra))}
    path.write_bytes(_tx_book(_tx_row(2), extra_sheets=extra_sheets))


def _import_cli(active: _ActiveRoot, *args: str):
    return CliRunner().invoke(
        app,
        ["--data-dir", str(active.root), "import", *args],
        obj={"activation_evidence_provider": active.provider},
    )


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_active_import_runs_before_legacy_init_and_copy(
    active_root: _ActiveRoot, tmp_path: Path, json_output: bool
) -> None:
    (active_root.root / "rules.yaml").unlink()
    source = tmp_path / "outside.xlsx"
    _write_xlsx(source)
    before_objects = _authority_state(active_root)

    result = _import_cli(active_root, str(source), *(["--json"] if json_output else []))

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert not (active_root.root / "rules.yaml").exists()
    assert not (active_root.root / "imports" / "outside.xlsx").exists()
    assert not list((active_root.root / "transactions").rglob("*.csv"))
    assert _authority_state(active_root) != before_objects
    if json_output:
        recorded = json.loads(result.output)
        _assert_export_manifest(active_root, recorded["steps"]["export"])
        receipts = recorded["steps"]["ingest"]["receipts"]
        assert receipts[0]["result"]["counts"]["transactions"]["inserted"] == 1
    else:
        assert "완료" in result.output


def test_same_bytes_replay_is_noop_and_force_does_not_duplicate(
    active_root: _ActiveRoot, tmp_path: Path
) -> None:
    source = tmp_path / "one.xlsx"
    _write_xlsx(source)
    first = _import_cli(active_root, str(source), "--json")
    assert first.exit_code == ExitCode.SUCCESS, first.output
    first_receipt = json.loads(first.output)["steps"]["ingest"]["receipts"][0]
    before = _authority_state(active_root)

    second = _import_cli(active_root, "--force", str(source), "--json")

    assert second.exit_code == ExitCode.SUCCESS, second.output
    replay = json.loads(second.output)["steps"]["ingest"]["receipts"][0]
    assert replay["result"]["noop"] is True
    assert replay["result"]["counts"]["transactions"]["inserted"] == 0
    assert replay["result"]["occurrence_id"] == first_receipt["result"]["occurrence_id"]
    assert replay["state_changed"] is False
    assert _transaction_count(active_root) == 1
    assert (active_root.root / "rules.yaml").read_bytes() == b"legacy sentinel unchanged\n"
    del before


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_active_dry_run_does_not_change_state(
    active_root: _ActiveRoot, tmp_path: Path, json_output: bool
) -> None:
    source = tmp_path / "preview.xlsx"
    _write_xlsx(source)
    before = _authority_state(active_root)

    result = _import_cli(
        active_root, "--dry-run", str(source), *(["--json"] if json_output else [])
    )

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert _authority_state(active_root) == before
    assert not (active_root.root / "imports" / "preview.xlsx").exists()
    if json_output:
        data = json.loads(result.output)
        assert data["dry_run"] is True
        assert data["authority"] == "repository"
        assert data["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 1
        assert data["receipts"][0]["state_changed"] is False
    else:
        assert "No changes written" in result.output
        assert "완료!" not in result.output


def test_encrypted_zip_dry_run_does_not_invent_counts(
    active_root: _ActiveRoot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    archive = tmp_path / "locked.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("hidden.xlsx", _tx_book(_tx_row(2)))
    monkeypatch.setattr(
        "finjuice.pipeline.cli.commands.import_cmd._zip_requires_password",
        lambda _path: True,
    )
    before = _authority_state(active_root)

    result = _import_cli(active_root, "--dry-run", str(archive), "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    data = json.loads(result.output)
    assert data["preview_unavailable"] is True
    assert data["receipts"] == []
    assert data["files_processed"] == 0
    assert data["unavailable_sources"][0]["reason"] == "encrypted_zip_requires_credentials"
    assert data["summary"]["new_transactions"] == 0
    assert data["summary"]["files_processed"] == 0
    assert _authority_state(active_root) == before


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_invalid_and_ambiguous_archive_selectors_have_no_effects(
    active_root: _ActiveRoot, json_output: bool
) -> None:
    first = _import_workbook(active_root)
    second = _import_workbook(active_root, extra="other")
    _insert_file_id(
        active_root.database,
        occurrence_id=first["occurrence_id"],
        file_id="dup-id",
        provenance_id=_provenance_id(active_root.database, first["occurrence_id"]),
        digest_hex=first["digest_hex"],
    )
    _insert_file_id(
        active_root.database,
        occurrence_id=second["occurrence_id"],
        file_id="dup-id",
        provenance_id=_provenance_id(active_root.database, second["occurrence_id"]),
        digest_hex=second["digest_hex"],
    )
    before = _authority_state(active_root)
    extra = ["--json"] if json_output else []

    unknown = _invoke(active_root, "ingest", "--from-archive", "missing", *extra)
    ambiguous = _invoke(active_root, "ingest", "--from-archive", "dup-id", *extra)

    assert unknown.exit_code == ExitCode.USAGE_ERROR, unknown.output
    assert ambiguous.exit_code == ExitCode.USAGE_ERROR, ambiguous.output
    assert _authority_state(active_root) == before
    if json_output:
        assert "unknown" in json.loads(unknown.output)["error"]["message"]
        assert "ambiguous" in json.loads(ambiguous.output)["error"]["message"]
    else:
        assert "unknown" in unknown.output
        assert "ambiguous" in ambiguous.output


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_partial_second_file_failure_keeps_first_receipt_and_stops_later_steps(
    active_root: _ActiveRoot,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    json_output: bool,
) -> None:
    good = tmp_path / "good.xlsx"
    bad = tmp_path / "bad.xlsx"
    _write_xlsx(good)
    bad.write_bytes(b"not-an-ooxml-workbook")

    def reject_later(*args, **kwargs):
        pytest.fail("A later pipeline step ran after partial ingest failure")

    for name in ("tag", "transfer", "export"):
        monkeypatch.setattr(pipeline, f"compute_full_pipeline_{name}", reject_later)

    result = _import_cli(active_root, str(good), str(bad), *(["--json"] if json_output else []))

    assert result.exit_code == ExitCode.GENERAL_ERROR, result.output
    if json_output:
        recorded = json.loads(result.output)["_meta"]["pipeline"]
        assert recorded["failed_step"] == "ingest"
        receipts = recorded["steps"]["ingest"]["receipts"]
        assert len(receipts) == 1
        assert receipts[0]["result"]["counts"]["transactions"]["inserted"] == 1
        assert recorded["steps"]["ingest"]["summary"]["failed"] == 1
        assert recorded["steps"]["ingest"]["summary"]["failed_files"][0][0] == "bad.xlsx"
    else:
        assert "완료!" not in result.output
        assert "ingest" in result.output


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_active_refresh_exports_and_preserves_mutation_receipts(
    active_root: _ActiveRoot, json_output: bool
) -> None:
    _rules(active_root)
    source = active_root.root / "imports" / "refresh.xlsx"
    _write_xlsx(source)

    result = _invoke(active_root, "refresh", *(["--json"] if json_output else []))

    assert result.exit_code == ExitCode.SUCCESS, result.output
    if json_output:
        recorded = json.loads(result.output)
        _assert_export_manifest(active_root, recorded["steps"]["export"])
        assert recorded["steps"]["ingest"]["receipts"][0]["changeset_id"]
        assert recorded["steps"]["tag"]["authority"] == "repository"
        assert recorded["steps"]["transfer"]["authority"] == "repository"
    else:
        assert "파이프라인 완료" in result.output
        assert "/exports/runs/" in result.output
        assert "export-manifest.json" in result.output
        assert "export" in result.output


def test_active_ingest_completes_without_export(active_root: _ActiveRoot) -> None:
    source = active_root.root / "imports" / "only-ingest.xlsx"
    _write_xlsx(source)

    result = _invoke(active_root, "ingest", "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    data = json.loads(result.output)
    assert data["authority"] == "repository"
    assert data["summary"]["failed"] == 0
    assert data["receipts"][0]["result"]["counts"]["transactions"]["inserted"] == 1


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
@pytest.mark.parametrize("dry_run", [False, True], ids=["write", "preview"])
def test_active_ingest_partial_failure_exits_nonzero(
    active_root: _ActiveRoot, json_output: bool, dry_run: bool
) -> None:
    source = active_root.root / "imports" / "a.xlsx"
    _write_xlsx(source)
    (source.parent / "b.xlsx").write_bytes(b"invalid workbook")
    flags = (["--json"] if json_output else []) + (["--dry-run"] if dry_run else [])

    result = _invoke(active_root, "ingest", *flags)

    assert result.exit_code == ExitCode.GENERAL_ERROR, result.output
    if json_output:
        recorded = json.loads(result.output)["_meta"]["pipeline"]
        step = recorded["steps"]["ingest"]
        assert recorded["failed_step"] == "ingest"
        assert len(step["receipts"]) == 1
        assert step["summary"]["failed"] == 1
        assert step["summary"]["failed_files"][0][0] == "b.xlsx"
    else:
        assert "Partial results" in result.output


@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_active_import_preview_failure_exits_nonzero_without_writes(
    active_root: _ActiveRoot, tmp_path: Path, json_output: bool
) -> None:
    good = tmp_path / "a.xlsx"
    bad = tmp_path / "b.xlsx"
    _write_xlsx(good)
    bad.write_bytes(b"invalid workbook")
    before = _authority_state(active_root)

    result = _import_cli(
        active_root, str(good), str(bad), "--dry-run", *(["--json"] if json_output else [])
    )

    assert result.exit_code == ExitCode.GENERAL_ERROR, result.output
    assert _authority_state(active_root) == before
    if json_output:
        step = json.loads(result.output)["_meta"]["pipeline"]["steps"]["ingest"]
        assert len(step["receipts"]) == 1
        assert step["summary"]["failed"] == 1


@pytest.mark.parametrize("count", [0, 2])
@pytest.mark.parametrize("json_output", [False, True], ids=["human", "json"])
def test_refresh_batch_identity_preserves_usage_error(
    active_root: _ActiveRoot, count: int, json_output: bool
) -> None:
    for index in range(count):
        _write_xlsx(active_root.root / "imports" / f"{index}.xlsx")
    before = _authority_state(active_root)

    result = _invoke(
        active_root,
        "refresh",
        "--idempotency-key",
        "single-file",
        "--expected-generation",
        active_root.generation,
        "--expected-revision",
        "0",
        *(["--json"] if json_output else []),
    )

    assert result.exit_code == ExitCode.USAGE_ERROR, result.output
    assert _authority_state(active_root) == before
    if json_output:
        data = json.loads(result.output)
        assert data["error"]["code"] == "INVALID_ARGS"
        assert data["_meta"]["pipeline"]["steps"] == {}


def test_batch_identity_is_rejected_before_file_effects(
    active_root: _ActiveRoot, tmp_path: Path
) -> None:
    first = tmp_path / "a.xlsx"
    second = tmp_path / "b.xlsx"
    _write_xlsx(first)
    _write_xlsx(second, extra="other")
    before = _authority_state(active_root)

    result = _import_cli(
        active_root,
        str(first),
        str(second),
        "--json",
        "--idempotency-key",
        "batch-key",
        "--expected-generation",
        active_root.generation,
        "--expected-revision",
        "0",
    )

    assert result.exit_code == ExitCode.USAGE_ERROR, result.output
    assert "single-file" in json.loads(result.output)["error"]["message"]
    assert _authority_state(active_root) == before


def test_zip_extraction_temp_dirs_are_cleaned(
    active_root: _ActiveRoot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    xlsx = tmp_path / "zipped.xlsx"
    _write_xlsx(xlsx)
    archive = tmp_path / "bundle.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.write(xlsx, "zipped.xlsx")
    created: list[str] = []
    real_mkdtemp = __import__("tempfile").mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    monkeypatch.setattr(
        "finjuice.pipeline.cli.commands.import_cmd.zip_extraction.tempfile.mkdtemp",
        tracking_mkdtemp,
    )

    result = _import_cli(active_root, str(archive), "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    assert created
    assert all(not Path(path).exists() for path in created)


def test_from_archive_occurrence_reimports_without_legacy_metadata(
    active_root: _ActiveRoot,
) -> None:
    imported = _import_workbook(active_root)
    before = _authority_state(active_root)

    result = _invoke(active_root, "ingest", "--from-archive", imported["occurrence_id"], "--json")

    assert result.exit_code == ExitCode.SUCCESS, result.output
    data = json.loads(result.output)
    assert data["source"] == "archive"
    assert data["receipts"][0]["result"]["noop"] is True
    assert data["receipts"][0]["result"]["occurrence_id"] == imported["occurrence_id"]
    assert not (active_root.root / "metadata" / "archives").exists()
    assert _transaction_count(active_root) == 1
    del before


@pytest.mark.parametrize("command", ["import", "refresh"])
def test_export_failure_keeps_completed_mutation_receipts(
    active_root: _ActiveRoot, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, command: str
) -> None:
    from finjuice.pipeline.export.source import RepositoryExportError

    _rules(active_root)
    source = (
        active_root.root / "imports" / "failure.xlsx"
        if command == "refresh"
        else tmp_path / "failure.xlsx"
    )
    _write_xlsx(source)

    def fail_export(*args, **kwargs):
        raise RepositoryExportError("Injected export publication failure.")

    monkeypatch.setattr("finjuice.pipeline.export.result._compute_export_result", fail_export)
    result = (
        _invoke(active_root, "refresh", "--json")
        if command == "refresh"
        else _import_cli(active_root, str(source), "--json")
    )
    assert result.exit_code == ExitCode.GENERAL_ERROR, result.output
    recorded = json.loads(result.output)["_meta"]["pipeline"]
    assert recorded["failed_step"] == "export"
    assert recorded["completed_steps"] == ["ingest", "tag", "transfer"]
    assert recorded["steps"]["ingest"]["receipts"][0]["changeset_id"]
    assert recorded["error_type"] == "RepositoryExportError"
    assert _transaction_count(active_root) == 1
