"""Reported values reject partial decoding and preserve reference occurrence evidence."""

from __future__ import annotations

import csv
import io
import uuid
from pathlib import Path

import pytest

from finjuice.pipeline.migration.adapters import FileContext, analyze_file, preserve_file
from finjuice.pipeline.migration.adapters.overview_reports import report_role
from finjuice.pipeline.migration.plan import capture_fact_index
from finjuice.pipeline.migration.policy import OVERVIEW_REPORT_POLICY
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryBuilder, RepositoryReader


@pytest.mark.parametrize(
    "path",
    [
        "balance/2026/01/balance.csv",
        "banksalad/balance/2026/13/balance.csv",
        "banksalad/balance/26/01/balance.csv",
        "banksalad/balance/2026/01/other.csv",
        "other/banksalad/balance/2026/01/balance.csv",
    ],
)
def test_noncanonical_paths_do_not_claim_report_role(path: str) -> None:
    assert report_role(path) is None


@pytest.mark.parametrize("bad", ["oops", "", "NaN", "1/3"])
def test_invalid_optional_number_emits_no_partial_report(tmp_path: Path, bad: str) -> None:
    fields = (
        "snapshot_date,product_type,institution,product_name,principal_amount,valuation_amount,"
        "return_rate,start_date,maturity_date,currency,source_fact_id,file_id,source_row"
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(fields.split(","))
    writer.writerow(
        [
            "2026-01-01",
            "fund",
            "bank",
            "name",
            "1.00",
            bad,
            "0.012",
            "date",
            "date",
            "USD",
            "ref",
            "file",
            "1",
        ]
    )
    source = tmp_path / "source.csv"
    source.write_text(output.getvalue())
    context = FileContext(
        "a" * 64,
        "data",
        "banksalad/investments/2026/01/investments.csv",
        migration_policy=OVERVIEW_REPORT_POLICY,
    )
    analysis = analyze_file(source, context).to_dict()
    paths = GenerationPaths(tmp_path / "candidate")
    with RepositoryBuilder(paths, str(uuid.uuid4())) as builder:
        assert preserve_file(builder, source, context).to_dict() == analysis
        builder.finalize()
    with RepositoryReader(paths.database) as reader:
        assert list(reader.rows("legacy_overview_reports")) == []
        assert list(reader.rows("exact_values")) == []
        assert len(list(reader.rows("observations"))) == 1
    assert sum(analysis["issue_counts"].values()) >= 1


def test_fact_index_preserves_duplicate_occurrences_and_mapped_invalid_rows(tmp_path: Path) -> None:
    paths = ["one.csv", "two.csv", "ambiguous.csv", "blank.csv"]
    data = tmp_path / "payload" / "data"
    data.mkdir(parents=True)
    for name in paths[:2]:
        (data / name).write_text("fact_id,fact_kind,value_numeric\nx,total,oops\n")
    (data / "ambiguous.csv").write_text("fact_id,fact_id,fact_kind\nx,x,total\n")
    (data / "blank.csv").write_text('fact_id,fact_kind\n"",total\n,total\n')
    capture = {
        "canonical_digest": "sha256:" + "a" * 64,
        "entries": [{"root": "data", "path": path, "type": "file"} for path in paths],
    }
    result = capture_fact_index(tmp_path, capture, policy=OVERVIEW_REPORT_POLICY)
    assert [entry[0] for entry in result] == ["x", "x", ""]
    assert len({entry[1] for entry in result}) == 3
    capture["entries"].reverse()
    assert set(capture_fact_index(tmp_path, capture, policy=OVERVIEW_REPORT_POLICY)) == set(result)


@pytest.mark.parametrize("snapshot,extra_currency", [('""', False), ("2026-01-01", True)])
def test_blank_snapshot_and_extra_cashflow_currency_preserve_without_build_failure(
    tmp_path: Path, snapshot: str, extra_currency: bool
) -> None:
    from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
    from finjuice.pipeline.migration import build_migration, plan_migration, verify_migration

    source = tmp_path / "source"
    target = source / "banksalad/cashflow/2026/01/cashflow.csv"
    target.parent.mkdir(parents=True)
    header = "snapshot_date,period_month,category,amount,source_fact_id,file_id"
    line = f"{snapshot},2026-01,income,12.00,missing,file"
    if extra_currency:
        header += ",currency"
        line += ",USD"
    target.write_text(header + "\n" + line + "\n")
    capture, plan, candidate = [tmp_path / name for name in ("capture", "plan.json", "candidate")]
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    assert verify_migration(candidate).to_dict()["status"] == "ok"
    with RepositoryReader(GenerationPaths(candidate).database) as reader:
        reports = list(reader.rows("legacy_overview_reports"))
        values = list(reader.rows("exact_values"))
        issues = list(reader.rows("preservation_issues"))
        if extra_currency:
            assert len(reports) == 1
            money = list(reader.rows("money_values"))
            assert money[0]["currency_code"] is None
            assert money[0]["currency_unknown"] == 1
            assert any(issue["issue_kind"] == "unknown_field" for issue in issues)
        else:
            assert reports == values == []
            assert any(
                issue["issue_kind"] == "incomplete_legacy_overview_report" for issue in issues
            )


def test_fact_index_excludes_roles_that_precede_fact_dispatch(tmp_path: Path) -> None:
    paths = ["banksalad/balance/2026/01/balance.csv", "transactions/2026/01/data.csv", "facts.csv"]
    capture = {
        "canonical_digest": "sha256:" + "b" * 64,
        "entries": [{"root": "data", "path": path, "type": "file"} for path in paths],
    }
    for name in paths:
        target = tmp_path / "payload/data" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("fact_id,fact_kind,value_numeric\nx,total,oops\n")
    index = capture_fact_index(tmp_path, capture, policy=OVERVIEW_REPORT_POLICY)
    assert len(index) == 1
    assert index[0][0] == "x"
