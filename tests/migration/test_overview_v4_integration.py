"""Independent source-to-report oracle for the five legacy overview roles."""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, SourceRoot, create_backup
from finjuice.pipeline.migration import build_migration, plan_migration, verify_migration
from finjuice.pipeline.migration.common import tree_inventory
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader


def write_overview_sources(source: Path) -> dict[str, bytes]:
    """Create literal synthetic reports without using the implementation's schema mapper."""
    files: dict[str, bytes] = {}

    def write(name: str, fields: str, values: list[list[str | None]]) -> None:
        stream = io.StringIO(newline="")
        writer = csv.writer(stream)
        writer.writerow(fields.split(","))
        writer.writerows(values)
        data = stream.getvalue().encode()
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files[name] = data

    fact_fields = (
        "fact_id,snapshot_date,sheet_name,block_id,block_title,fact_kind,"
        "value_type,value_numeric,file_id,source_row"
    )
    write(
        "banksalad/overview_facts/2026/01/facts.csv",
        fact_fields,
        [
            ["unique", "2026-01-31", "sheet", "block", "title", "total", "number", "1.0", "f", "1"],
            ["bad", "2026-01-31", "sheet", "block", "title", "total", "number", "oops", "f", "2"],
        ],
    )
    duplicate = [
        "duplicate",
        "2026-01-31",
        "sheet",
        "block",
        "title",
        "total",
        "number",
        "2.0",
        "f",
        "3",
    ]
    for month in ("02", "03"):
        write(f"banksalad/overview_facts/2026/{month}/facts.csv", fact_fields, [duplicate])
    write(
        "banksalad/balance/2026/01/balance.csv",
        "snapshot_date,side,category,item_name,amount,currency,source_fact_id,file_id,source_row",
        [
            [
                "2026-01-31",
                "asset",
                "cash",
                "synthetic-item",
                "9007199254740993.0100",
                "EUR",
                "unique",
                "f",
                "1",
            ]
        ],
    )
    write(
        "banksalad/cashflow/2026/01/cashflow.csv",
        "snapshot_date,period_month,category,amount,source_fact_id,file_id",
        [["2026-01-31", "2025-12", "income", "-0.0007", "missing", "f"]],
    )
    write(
        "banksalad/insurance/2026/01/insurance.csv",
        "snapshot_date,institution,policy_name,contract_status,paid_amount,contract_date,"
        "maturity_date,currency,source_fact_id,file_id,source_row",
        [
            [
                "2026-01-31",
                "synthetic-institution",
                "synthetic-policy",
                "active",
                None,
                "2020-01-01",
                None,
                "JPY",
                "duplicate",
                "f",
                "3",
            ]
        ],
    )
    write(
        "banksalad/investments/2026/01/investments.csv",
        "snapshot_date,product_type,institution,product_name,principal_amount,valuation_amount,"
        "return_rate,start_date,maturity_date,currency,source_fact_id,file_id,source_row",
        [
            [
                "2026-01-31",
                "fund",
                "synthetic-institution",
                "synthetic-product\nsecond line",
                "100.000",
                "101.123400",
                "0.003700",
                "2020-01-01",
                None,
                "USD",
                "bad",
                "f",
                "2",
            ]
        ],
    )
    write(
        "banksalad/loans/2026/01/loans.csv",
        "snapshot_date,loan_type,institution,product_name,principal_amount,balance_amount,"
        "interest_rate,start_date,maturity_date,currency,source_fact_id,file_id,source_row",
        [
            [
                "2026-01-31",
                "secured",
                "synthetic-institution",
                "synthetic-loan",
                "99.00",
                "-0.0000",
                "7.12500",
                None,
                "2030-01-01",
                "KRW",
                None,
                "f",
                "9",
            ]
        ],
    )
    return files


def test_five_report_roles_preserve_values_without_claiming_fact_resolution(tmp_path: Path) -> None:
    source = tmp_path / "source"
    files = write_overview_sources(source)
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    before = tree_inventory(source), tree_inventory(capture)
    plan_migration(capture, output=plan, active_data_dir=source)
    assert (
        json.loads(plan.read_text())["migration_policy"]
        == "legacy_preservation.overview_reports.v4"
    )
    build_migration(plan, candidate, active_data_dir=source)
    assert verify_migration(candidate).to_dict()["cutover_ready"] is False
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        assert reader.info.schema_version == 5
        reports = {row["report_kind"]: row for row in reader.rows("legacy_overview_reports")}
        assert set(reports) == {"balance", "cashflow", "insurance", "investment", "loan"}
        assert {row["snapshot_date"] for row in reports.values()} == {"2026-01-31"}
        values = {row["value_id"]: row for row in reader.rows("exact_values")}
        money = {row["value_id"]: row for row in reader.rows("money_values")}
        expected = {
            "balance": ("legacy_overview_balances", {"amount_value_id": "9007199254740993.0100"}),
            "cashflow": ("legacy_overview_cashflows", {"amount_value_id": "-0.0007"}),
            "insurance": ("legacy_overview_insurance", {"paid_amount_value_id": None}),
            "investment": (
                "legacy_overview_investments",
                {
                    "principal_value_id": "100.000",
                    "valuation_value_id": "101.123400",
                    "return_rate_value_id": "0.003700",
                },
            ),
            "loan": (
                "legacy_overview_loans",
                {
                    "principal_value_id": "99.00",
                    "balance_value_id": "-0.0000",
                    "interest_rate_value_id": "7.12500",
                },
            ),
        }
        for kind, (table, fields) in expected.items():
            (detail,) = reader.rows(table)
            assert detail["observation_id"] == reports[kind]["observation_id"]
            for field, lexical in fields.items():
                if lexical is None:
                    assert detail[field] is None
                else:
                    value = values[detail[field]]
                    assert value["lexical"] == lexical
                    assert value["provenance_id"] == reports[kind]["provenance_id"]
        (cashflow,) = reader.rows("legacy_overview_cashflows")
        assert money[cashflow["amount_value_id"]]["currency_code"] is None
        assert money[cashflow["amount_value_id"]]["currency_unknown"] == 1
        (insurance,) = reader.rows("legacy_overview_insurance")
        assert insurance["currency"] == "JPY"
        (investment,) = reader.rows("legacy_overview_investments")
        assert investment["product_name"] == "synthetic-product\nsecond line"
        assert {row["unit"] for row in reader.rows("rate_values")} == {
            "legacy_overview_return_rate.v1",
            "legacy_overview_interest_rate.v1",
        }
        assessments = {
            row["report_observation_id"]: row
            for row in reader.rows("legacy_overview_reference_assessments")
        }
        candidates = reader.rows("legacy_overview_reference_candidates")
        for kind, status, count in (
            ("balance", "unverified", 1),
            ("cashflow", "missing", 0),
            ("insurance", "ambiguous", 2),
            ("investment", "unverified", 1),
            ("loan", "missing", 0),
        ):
            observation = reports[kind]["observation_id"]
            assert assessments[observation]["status"] == status
            assert sum(row["report_observation_id"] == observation for row in candidates) == count
        assert len(reader.rows("overview_facts")) == 3
        assert reader.rows("overview_balances") == []
        assert reader.rows("transactions") == []
        _assert_original_files(reader, candidate, files)
    original_candidate = tree_inventory(candidate)
    assert (
        build_migration(plan, candidate, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    replay = tmp_path / "replay"
    build_migration(plan, replay, active_data_dir=source)
    assert semantic_snapshot(candidate / "finjuice.sqlite3") == semantic_snapshot(
        replay / "finjuice.sqlite3"
    )
    assert tree_inventory(candidate) == original_candidate
    assert (tree_inventory(source), tree_inventory(capture)) == before


def _assert_original_files(
    reader: RepositoryReader, candidate: Path, files: dict[str, bytes]
) -> None:
    artifacts = {row["source_artifact_id"]: row for row in reader.rows("source_artifacts")}
    occurrences = [row for row in reader.rows("source_occurrences") if row["legacy_path"] in files]
    assert len(occurrences) == len(files)
    for row in occurrences:
        artifact = artifacts[row["source_artifact_id"]]
        assert (candidate / artifact["object_path"]).read_bytes() == files[row["legacy_path"]]
    duplicates = [
        row
        for row in occurrences
        if row["legacy_path"]
        in {
            "banksalad/overview_facts/2026/02/facts.csv",
            "banksalad/overview_facts/2026/03/facts.csv",
        }
    ]
    assert len({row["entity_id"] for row in duplicates}) == 2
    assert len({row["source_artifact_id"] for row in duplicates}) == 1


def test_unmapped_fact_shaped_rows_do_not_abort_report_build(tmp_path: Path) -> None:
    source = tmp_path / "source"
    write_overview_sources(source)
    (source / "duplicate-columns.csv").write_text(
        "fact_id,fact_id,fact_kind\nunique,unique,total\n"
    )
    (source / "ragged.csv").write_text("fact_id,fact_kind\nunique,total,extra\n")
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    before = tree_inventory(source), tree_inventory(capture)
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    assert verify_migration(candidate).to_dict()["status"] == "ok"
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        assert len(reader.rows("legacy_overview_reports")) == 5
        assert len(reader.rows("legacy_overview_reference_candidates")) == 4
        assert (
            sum(
                row["issue_kind"] == "ambiguous_csv_structure"
                for row in reader.rows("preservation_issues")
            )
            == 2
        )
        unmapped = {
            row["entity_id"]
            for row in reader.rows("source_occurrences")
            if row["legacy_path"] in {"duplicate-columns.csv", "ragged.csv"}
        }
        assert len(unmapped) == 2
        assert not any(
            row["source_occurrence_id"] in unmapped for row in reader.rows("observations")
        )
    assert (tree_inventory(source), tree_inventory(capture)) == before


def test_report_paths_in_separate_capture_roots_keep_separate_occurrences(tmp_path: Path) -> None:
    source, extra = tmp_path / "source", tmp_path / "extra"
    write_overview_sources(source)
    write_overview_sources(extra)
    capture, plan, candidate = (tmp_path / name for name in ("capture", "plan.json", "candidate"))
    create_backup(
        CreateRequest(
            source,
            capture,
            ConsistencyEvidence("stopped_writers", ("test",)),
            extra_roots=(SourceRoot("other", "required", extra),),
        )
    )
    before = tree_inventory(source), tree_inventory(extra), tree_inventory(capture)
    plan_migration(capture, output=plan, active_data_dir=source)
    build_migration(plan, candidate, active_data_dir=source)
    assert verify_migration(candidate).to_dict()["status"] == "ok"
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        reports = reader.rows("legacy_overview_reports")
        assert len(reports) == 10
        assert len({row["observation_id"] for row in reports}) == 10
        provenance = {row["provenance_id"]: row for row in reader.rows("record_provenance")}
        assert {
            json.loads(provenance[row["provenance_id"]]["legacy_locator_json"])["root"]
            for row in reports
        } == {"data", "other"}
        assert len(reader.rows("legacy_overview_reference_candidates")) == 16
        assert reader.rows("parties") == []
        assert reader.rows("accounts") == []
    assert (tree_inventory(source), tree_inventory(extra), tree_inventory(capture)) == before
