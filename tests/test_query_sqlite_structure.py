"""Structure and M1 acceptance tests for SQLite query compatibility (#436)."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from polars.testing import assert_frame_equal
from typer.testing import CliRunner

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.query import (
    CALCULATION_POLICY,
    CATEGORY_REPORT_CSV,
    DERIVED_FORMAT,
    GENERATION_ENV_VAR,
    TRANSACTIONS_CSV,
    QuerySnapshot,
    QuerySourceError,
    classify_derived,
    configured_source_frame,
    display_row,
    load_query_snapshot,
    open_analytics,
    read_transactions_frame,
    resolve_generation_database,
    write_derived_outputs,
)
from finjuice.pipeline.tagging.manual import MANUAL_CATEGORY_PREFIX
from tests.conftest import cli_text
from tests.sqlite_compat_data import build_generation, logical_rows, write_csv_mirror

QUERY_DIR = Path("src/finjuice/pipeline/query")
PACKAGE = "finjuice.pipeline.query"
SNAPSHOT_MODULE = "finjuice.pipeline.query.snapshot"
ANALYTICS_MODULE = "finjuice.pipeline.query.analytics"
DERIVED_MODULE = "finjuice.pipeline.query.derived"
DISPLAY_MODULE = "finjuice.pipeline.query.display"
ERRORS_MODULE = "finjuice.pipeline.query.errors"

CLI_ADAPTERS = (
    Path("src/finjuice/pipeline/cli/commands/query.py"),
    Path("src/finjuice/pipeline/cli/commands/explain.py"),
    Path("src/finjuice/pipeline/cli/commands/show_cmd.py"),
    Path("src/finjuice/pipeline/cli/commands/status/compute.py"),
    Path("src/finjuice/pipeline/cli/commands/status/compute_sqlite.py"),
    Path("src/finjuice/pipeline/cli/commands/template_cmd/__init__.py"),
    # The CLI delegates source selection after the authority guard to this implementation.
    Path("src/finjuice/pipeline/export/result.py"),
)

REPRESENTATIVE_SQL = (
    "SELECT row_hash, date, merchant_raw, amount, category_final, "
    "is_transfer_bool, list_contains(tags_list, '카페') AS has_cafe "
    "FROM transactions ORDER BY datetime, row_hash"
)

runner = CliRunner()


@pytest.fixture
def mirrored_dataset(tmp_path: Path) -> dict[str, Path]:
    """Build the same logical dataset as CSV partitions and a SQLite generation."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    write_csv_mirror(data_dir)
    database = build_generation(tmp_path / "generation")
    return {"data_dir": data_dir, "database": database, "root": tmp_path}


def _payload_without_volatile_meta(payload: dict[str, Any]) -> dict[str, Any]:
    """Drop timestamp so same-revision JSON envelopes can be compared."""
    meta = dict(payload.get("_meta") or {})
    meta.pop("timestamp", None)
    return {**payload, "_meta": meta}


def _invoke_query_json(data_dir: Path, sql: str) -> dict[str, Any]:
    """Run ``finjuice query --json`` and return the parsed envelope."""
    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "query", sql, "--json", "--limit", "10000"],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_query_package_reexports_definition_identity() -> None:
    """Public query names stay identity-equal to their definition modules."""
    package = importlib.import_module(PACKAGE)
    snapshot = importlib.import_module(SNAPSHOT_MODULE)
    analytics = importlib.import_module(ANALYTICS_MODULE)
    derived = importlib.import_module(DERIVED_MODULE)
    display = importlib.import_module(DISPLAY_MODULE)
    errors = importlib.import_module(ERRORS_MODULE)

    assert package.QuerySnapshot is snapshot.QuerySnapshot
    assert package.load_query_snapshot is snapshot.load_query_snapshot
    assert package.configured_source_frame is snapshot.configured_source_frame
    assert package.open_analytics is analytics.open_analytics
    assert package.write_derived_outputs is derived.write_derived_outputs
    assert package.classify_derived is derived.classify_derived
    assert package.display_row is display.display_row
    assert package.QuerySourceError is errors.QuerySourceError
    assert callable(package.open_analytics)
    assert callable(package.write_derived_outputs)


def test_query_helpers_live_in_dedicated_modules() -> None:
    """Snapshot, DuckDB, derived CSV, and display stay split across modules."""
    snapshot_text = (QUERY_DIR / "snapshot.py").read_text(encoding="utf-8")
    analytics_text = (QUERY_DIR / "analytics.py").read_text(encoding="utf-8")
    derived_text = (QUERY_DIR / "derived.py").read_text(encoding="utf-8")
    display_text = (QUERY_DIR / "display.py").read_text(encoding="utf-8")

    assert "def load_query_snapshot" in snapshot_text
    assert "def configured_source_frame" in snapshot_text
    assert "def write_derived_outputs" not in snapshot_text
    assert "def open_analytics" in analytics_text
    assert "def write_derived_outputs" in derived_text
    assert "def classify_derived" in derived_text
    assert "def display_row" in display_text
    assert "class QuerySnapshot" not in derived_text


def test_cli_read_adapters_import_query_package_not_storage_read_compat() -> None:
    """Named CLI adapters read through the query package, not storage.read_compat."""
    export_cli = Path("src/finjuice/pipeline/cli/commands/export_cmd.py").read_text()
    assert "export_result._compute_export_result" in export_cli
    for path in CLI_ADAPTERS:
        text = path.read_text(encoding="utf-8")
        assert "finjuice.pipeline.query" in text
        assert "storage.sqlite.read_compat" not in text


def test_resolve_generation_database_missing_raises(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A locator without a published database fails closed."""
    monkeypatch.setenv(GENERATION_ENV_VAR, str(tmp_path / "absent-generation"))

    with pytest.raises(QuerySourceError):
        resolve_generation_database()


def test_duckdb_queries_match_csv_baseline(mirrored_dataset: dict[str, Path]) -> None:
    """SQLite-backed DuckDB views match CSV DuckDB results on representative SQL."""
    data_dir = mirrored_dataset["data_dir"]
    snapshot = load_query_snapshot(mirrored_dataset["database"])
    queries = [
        "SELECT COUNT(*) AS n FROM transactions",
        REPRESENTATIVE_SQL,
        "SELECT category_final, COUNT(*) AS n, SUM(amount) AS total "
        "FROM transactions GROUP BY category_final ORDER BY category_final",
    ]

    with (
        DuckDBAnalytics(data_dir) as csv_analytics,
        open_analytics(data_dir, source_frame=snapshot.frame) as sqlite_analytics,
    ):
        for sql in queries:
            csv_df = csv_analytics.query_readonly(sql).pl()
            sqlite_df = sqlite_analytics.query_readonly(sql).pl()
            assert_frame_equal(csv_df, sqlite_df, check_dtypes=False)


def test_query_cli_human_and_json_match_csv_baseline(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """query human and JSON output match the CSV baseline on synthetic SQLite data."""
    data_dir = mirrored_dataset["data_dir"]
    sql = (
        "SELECT merchant_raw, amount, category_final FROM transactions ORDER BY datetime, row_hash"
    )
    csv_json = _invoke_query_json(data_dir, sql)
    csv_human = runner.invoke(app, ["--data-dir", str(data_dir), "query", sql])
    assert csv_human.exit_code == 0, csv_human.output
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["database"].parent))

    sqlite_json = _invoke_query_json(data_dir, sql)
    sqlite_human = runner.invoke(app, ["--data-dir", str(data_dir), "query", sql])

    assert sqlite_human.exit_code == 0, sqlite_human.output
    assert _payload_without_volatile_meta(sqlite_json) == _payload_without_volatile_meta(csv_json)
    assert cli_text(sqlite_human) == cli_text(csv_human)


def test_manual_marker_is_internal_and_omitted_from_display(
    mirrored_dataset: dict[str, Path],
) -> None:
    """Manual classification markers stay in the frame but not typed display rows."""
    snapshot = load_query_snapshot(mirrored_dataset["database"])
    row = snapshot.frame.filter(pl.col("row_hash") == "abc1234567890006").to_dicts()[0]
    marker = f"{MANUAL_CATEGORY_PREFIX}수동분류"

    assert marker in row["tags_manual"]
    assert row["category_final"] == "수동분류"

    displayed = display_row(row)
    assert marker not in displayed["tags_manual"]
    assert displayed["category_manual"] == "수동분류"
    assert displayed["category_final"] == "수동분류"


def test_same_revision_derived_csv_and_report_are_deterministic(
    mirrored_dataset: dict[str, Path],
    tmp_path: Path,
) -> None:
    """Re-writing derived CSV/report for one revision yields identical bytes."""
    snapshot = load_query_snapshot(mirrored_dataset["database"])
    first = write_derived_outputs(snapshot, tmp_path / "derived-a")
    second = write_derived_outputs(snapshot, tmp_path / "derived-b")

    assert first.transactions_csv.read_bytes() == second.transactions_csv.read_bytes()
    assert first.category_report_csv.read_bytes() == second.category_report_csv.read_bytes()
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["format"] == DERIVED_FORMAT
    assert manifest["dataset_generation"] == snapshot.dataset_generation
    assert manifest["dataset_revision"] == snapshot.dataset_revision
    assert manifest["calculation_policy"] == CALCULATION_POLICY
    assert manifest["as_of"] == snapshot.as_of
    assert snapshot.calculation_policy == CALCULATION_POLICY
    assert snapshot.as_of == "2024-11-20"


def test_editing_derived_csv_does_not_change_authority_and_is_stale(
    mirrored_dataset: dict[str, Path],
    tmp_path: Path,
) -> None:
    """Editing compatibility CSV leaves SQLite unchanged and is reported stale."""
    snapshot = load_query_snapshot(mirrored_dataset["database"])
    bundle = write_derived_outputs(snapshot, tmp_path / "derived")
    assert classify_derived(bundle.directory, snapshot) == "fresh"

    original_sqlite = read_transactions_frame(mirrored_dataset["database"])
    stale_csv = bundle.transactions_csv.read_text(encoding="utf-8").replace("스타벅스", "STALE")
    bundle.transactions_csv.write_text(stale_csv, encoding="utf-8")

    after_edit = load_query_snapshot(mirrored_dataset["database"])
    assert_frame_equal(after_edit.frame, original_sqlite)
    assert "STALE" not in after_edit.frame["merchant_raw"].to_list()
    assert classify_derived(bundle.directory, snapshot) == "stale"
    assert classify_derived(tmp_path / "missing", snapshot) == "invalid"


def test_export_dry_run_uses_sqlite_when_csv_partitions_are_gone(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SQLite-backed export must not report zero rows after live CSV is removed."""
    data_dir = mirrored_dataset["data_dir"]
    generation_root = mirrored_dataset["database"].parent
    for csv_path in (data_dir / "transactions").rglob("transactions.csv"):
        csv_path.unlink()
    monkeypatch.setenv(GENERATION_ENV_VAR, str(generation_root))
    expected = read_transactions_frame(mirrored_dataset["database"]).height
    assert expected > 0

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "export",
            "--format",
            "xlsx",
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["transaction_count"] == expected
    xlsx_files = [item for item in payload["output_files"] if item["kind"] == "master_xlsx"]
    assert xlsx_files
    assert xlsx_files[0]["row_count"] == expected
    assert not any((generation_root / "derived").rglob("*.csv"))
    assert not any((generation_root / "derived").rglob("manifest.json"))


def test_export_dry_run_does_not_create_derived_files(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``export --dry-run`` must not write derived CSV or manifest files."""
    generation_root = mirrored_dataset["database"].parent
    monkeypatch.setenv(GENERATION_ENV_VAR, str(generation_root))
    derived_root = generation_root / "derived"

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(mirrored_dataset["data_dir"]),
            "export",
            "--format",
            "xlsx",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert not any(path.is_file() for path in derived_root.rglob("*"))


def test_export_master_xlsx_uses_unfiltered_sqlite_snapshot(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Master XLSX stays the full SQLite snapshot when report_filters exist."""
    data_dir = mirrored_dataset["data_dir"]
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["database"].parent))
    (data_dir / "rules.yaml").write_text(
        "version: 1\n"
        "report_filters:\n"
        "  excluded_merchants:\n"
        "    - pattern: 스타벅스\n"
        "      reason: test exclusion\n"
        "rules: []\n",
        encoding="utf-8",
    )
    expected = read_transactions_frame(mirrored_dataset["database"]).height
    assert expected > 0

    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "export", "--format", "xlsx", "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["filters_applied"] >= 1
    output_files = {item["kind"]: item for item in payload["output_files"]}
    assert output_files["master_xlsx"]["row_count"] == expected
    assert payload["transaction_count"] == expected

    master_df = pl.read_excel(
        Path(output_files["master_xlsx"]["path"]),
        sheet_name="Transactions",
        engine="openpyxl",
    )
    assert master_df.height == expected
    assert "스타벅스" in master_df["merchant_raw"].to_list()


def test_explicit_sqlite_query_ignores_csv_while_cli_preserves_selected_legacy(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Explicit SQLite reads stay pinned; CLI preserves selected legacy CSV authority."""
    data_dir = mirrored_dataset["data_dir"]
    csv_path = data_dir / "transactions" / "2024" / "10" / "transactions.csv"
    csv_path.write_text(
        csv_path.read_text(encoding="utf-8").replace("스타벅스", "STALE"),
        encoding="utf-8",
    )
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["database"].parent))

    sql = "SELECT merchant_raw FROM transactions WHERE row_hash = 'abc1234567890001'"
    selected = load_query_snapshot(mirrored_dataset["database"])
    with open_analytics(data_dir, source_frame=selected.frame) as analytics:
        rows = analytics.query_readonly(sql).pl().to_dicts()
    assert rows == [{"merchant_raw": "스타벅스"}]
    # A detached locator is not activation evidence for the CLI's selected legacy dataset.
    payload = _invoke_query_json(data_dir, sql)
    assert payload["rows"] == [{"merchant_raw": "STALE"}]
    frame = configured_source_frame()
    assert frame is not None
    assert "STALE" not in frame["merchant_raw"].to_list()


def test_explicit_source_frame_is_not_replaced_by_env_locator(
    mirrored_dataset: dict[str, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit DuckDB source_frame remains the selected authority."""
    other_rows = [
        {
            **row,
            "merchant_raw": "OTHER",
            "row_hash": f"other{row['row_hash'][-4:]}",
        }
        for row in logical_rows()
    ]
    other_db = build_generation(tmp_path / "other-generation", other_rows)
    monkeypatch.setenv(GENERATION_ENV_VAR, str(other_db.parent))
    selected = load_query_snapshot(mirrored_dataset["database"])

    with open_analytics(
        mirrored_dataset["data_dir"],
        source_frame=selected.frame,
    ) as analytics:
        merchants = analytics.query_readonly(
            "SELECT merchant_raw FROM transactions WHERE row_hash = 'abc1234567890001'"
        ).pl()

    assert merchants.to_dicts() == [{"merchant_raw": "스타벅스"}]
    located = configured_source_frame()
    assert located is not None
    assert "OTHER" in located["merchant_raw"].to_list()


def test_foreign_generation_derived_is_not_fresh(
    mirrored_dataset: dict[str, Path],
    tmp_path: Path,
) -> None:
    """A derived bundle from another generation is foreign, not fresh."""
    snapshot = load_query_snapshot(mirrored_dataset["database"])
    bundle = write_derived_outputs(snapshot, tmp_path / "derived")
    foreign = QuerySnapshot(
        database=snapshot.database,
        dataset_generation="00000000-0000-4000-8000-000000000099",
        dataset_revision=snapshot.dataset_revision,
        schema_version=snapshot.schema_version,
        calculation_policy=snapshot.calculation_policy,
        as_of=snapshot.as_of,
        frame=snapshot.frame,
    )

    assert classify_derived(bundle.directory, foreign) == "foreign_generation"


def test_classify_derived_empty_or_missing_required_files_is_not_fresh(
    mirrored_dataset: dict[str, Path],
    tmp_path: Path,
) -> None:
    """An empty or incomplete derived manifest must not be reported fresh."""
    snapshot = load_query_snapshot(mirrored_dataset["database"])
    bundle = write_derived_outputs(snapshot, tmp_path / "derived")
    manifest = json.loads(bundle.manifest_path.read_text(encoding="utf-8"))
    assert classify_derived(bundle.directory, snapshot) == "fresh"

    empty_files = {**manifest, "files": {}}
    bundle.manifest_path.write_text(
        json.dumps(empty_files, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert classify_derived(bundle.directory, snapshot) in {"invalid", "stale"}

    partial_files = {
        **manifest,
        "files": {TRANSACTIONS_CSV: manifest["files"][TRANSACTIONS_CSV]},
    }
    bundle.manifest_path.write_text(
        json.dumps(partial_files, sort_keys=True, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    assert classify_derived(bundle.directory, snapshot) in {"invalid", "stale"}
    assert CATEGORY_REPORT_CSV not in partial_files["files"]


@pytest.mark.parametrize("format_lower", ["html", "md"])
@pytest.mark.parametrize("dry_run", [False, True])
def test_export_html_md_transaction_count_honors_period_when_filters_empty(
    mirrored_dataset: dict[str, Path],
    monkeypatch: pytest.MonkeyPatch,
    format_lower: str,
    dry_run: bool,
) -> None:
    """Legacy html/md export counts its period even when a detached locator is set."""
    data_dir = mirrored_dataset["data_dir"]
    monkeypatch.setenv(GENERATION_ENV_VAR, str(mirrored_dataset["database"].parent))
    from finjuice.pipeline.query import configured_snapshot

    assert configured_snapshot(data_dir) is None  # Exercise the legacy CSV counting branch.
    snapshot = read_transactions_frame(mirrored_dataset["database"])
    period_count = snapshot.filter(pl.col("date").str.starts_with("2024-10")).height
    assert snapshot.height > period_count > 0

    args = [
        "--data-dir",
        str(data_dir),
        "export",
        "--format",
        format_lower,
        "--period",
        "2024-10",
        "--json",
    ]
    if dry_run:
        args.append("--dry-run")

    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["transaction_count"] == period_count
    assert payload["_meta"]["filters_applied"] == 0
    assert payload["dry_run"] is dry_run
