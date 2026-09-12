"""Independent synthetic oracle across backup, CLI, and repository boundaries."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource
from typer.testing import CliRunner

from finjuice.pipeline.backup import (
    ConsistencyEvidence,
    CreateRequest,
    SourceRoot,
    create_backup,
)
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.migration import build_migration, plan_migration, verify_migration
from finjuice.pipeline.migration.common import tree_inventory
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import RepositoryReader

SCHEMAS = Path(__file__).resolve().parents[2] / "schemas"


def test_mixed_capture_cli_preserves_independent_expected_values(tmp_path: Path) -> None:
    source = tmp_path / "synthetic-source"
    partition = source / "transactions" / "2026" / "01"
    partition.mkdir(parents=True)
    fields = [
        "row_hash",
        "date",
        "time",
        "datetime",
        "type_norm",
        "account",
        "amount",
        "currency",
        "category_final",
        "notes_manual",
        "tags_rule",
        "tags_ai",
        "tags_manual",
        "tags_final",
        "is_transfer",
        "transfer_group_id",
    ]
    manual = ["visible", "__finjuice_category_override__:override", "visible"]
    row = [
        "duplicate",
        "2026-01-01",
        "00:00",
        "2026-01-01T00:00",
        "expense",
        "synthetic-account",
        "9007199254740993.0100",
        "USD",
        "persisted-category",
        "line one\nline two",
        "[]",
        "[]",
        json.dumps(manual),
        '["persisted-tag"]',
        "1",
        "legacy-group",
    ]
    with (partition / "transactions.csv").open("w", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows([row, row])
    (source / "rules.yaml").write_text("rules: []\n")
    (source / "raw.zip").write_bytes(b"synthetic opaque zip evidence")
    overlay = tmp_path / "overlay.json"
    overlay.write_text('{"unknown": null}')
    capture = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source,
            capture,
            ConsistencyEvidence("stopped_writers", ("synthetic",)),
            extra_roots=(
                SourceRoot("overlay", "required", overlay),
                SourceRoot("absent", "optional", None),
            ),
        )
    )
    before = tree_inventory(source), tree_inventory(capture)
    plan, candidate = tmp_path / "plan.json", tmp_path / "candidate"
    commands = [
        ("plan", ["--manifest", str(capture), "--output", str(plan)]),
        ("build", ["--plan", str(plan), "--staging", str(candidate)]),
        ("verify", ["--candidate", str(candidate)]),
    ]
    runner = CliRunner()
    registry: Registry = Registry().with_resources(
        (path.name, Resource.from_contents(json.loads(path.read_text())))
        for path in SCHEMAS.glob("*.schema.json")
    )
    for action, args in commands:
        result = runner.invoke(
            app, ["--data-dir", str(source), "ssot", "migrate", action, *args, "--json"]
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        schema = json.loads((SCHEMAS / f"ssot_migrate_{action}.schema.json").read_text())
        jsonschema.Draft202012Validator(schema, registry=registry).validate(payload)
        for private in (str(tmp_path), "synthetic-account", "transactions.csv", row[6]):
            assert private not in result.output
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        transactions = reader.rows("transactions")
        assert len(transactions) == 2
        assert len({item["entity_id"] for item in transactions}) == 2
        for item in transactions:
            assert item["category_final"] == "persisted-category"
            assert item["category_manual"] == "override"
            assert item["notes_manual"] == "line one\nline two"
            assert json.loads(item["tags_manual_json"]) == ["visible", "visible"]
            assert json.loads(item["tags_final_json"]) == ["persisted-tag"]
            assert item["is_transfer"] == 1
            assert item["transfer_group_id"] == "legacy-group"
        for value in reader.rows("exact_values"):
            assert (value["coefficient"], value["scale"], value["lexical"]) == (
                "90071992547409930100",
                4,
                "9007199254740993.0100",
            )
        assert reader.rows("audit_events") == []
        assert reader.info.dataset_revision == 0
    assert before == (tree_inventory(source), tree_inventory(capture))


@pytest.mark.parametrize(
    ("fact_rows", "fact_files", "source_fact_id", "expected_numbers"),
    [
        (
            b"unique,2026-01-01,sheet,block,title,total,number,10.10\r\n",
            ("overview/facts.csv",),
            "unique",
            [("1010", 2, "10.10")],
        ),
        (
            b"duplicate,2026-01-01,sheet,block,title,total,number,10.10\r\n"
            b"duplicate,2026-01-01,sheet,block,title,total,number,0.0037\r\n",
            ("overview/facts.csv", "overview/repeated-facts.csv"),
            "duplicate",
            [("1010", 2, "10.10"), ("37", 4, "0.0037")] * 2,
        ),
        (
            b"unrelated,2026-01-01,sheet,block,title,total,number,10.10\r\n",
            ("overview/facts.csv",),
            "missing",
            [("1010", 2, "10.10")],
        ),
    ],
    ids=["unique-id-separate-files", "duplicate-id-rows-and-files", "missing-fact"],
)
def test_cross_file_overview_preservation_seam(
    tmp_path: Path,
    fact_rows: bytes,
    fact_files: tuple[str, ...],
    source_fact_id: str,
    expected_numbers: list[tuple[str, int, str]],
) -> None:
    """Cross-file references remain explicit opaque evidence, even for a unique legacy ID."""
    header = (
        b"fact_id,snapshot_date,sheet_name,block_id,block_title,fact_kind,value_type,"
        b"value_numeric\r\n"
    )
    expected_files = {name: header + fact_rows for name in fact_files}
    expected_files["overview/balance.csv"] = (
        f"source_fact_id,amount,currency\r\n{source_fact_id},9007199254740993.0100,EUR\r\n"
    ).encode()
    source = tmp_path / "source"
    for name, original in expected_files.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(original)
    capture, plan = tmp_path / "capture", tmp_path / "plan.json"
    create_backup(
        CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("synthetic",)))
    )
    before = tree_inventory(source), tree_inventory(capture)
    plan_migration(capture, output=plan, active_data_dir=source)
    candidate = tmp_path / "candidate"
    build_migration(plan, candidate, active_data_dir=source)
    assert verify_migration(candidate).to_dict()["cutover_ready"] is False
    with RepositoryReader(candidate / "finjuice.sqlite3") as reader:
        _assert_overview_file_evidence(reader, candidate, expected_files)
        facts = reader.rows("overview_facts")
        assert len(facts) == len(expected_numbers)
        assert len({row["entity_id"] for row in facts}) == len(expected_numbers)
        values = {row["value_id"]: row for row in reader.rows("exact_values")}
        assert len(values) == len(expected_numbers)
        assert sorted(
            (value["coefficient"], value["scale"], value["lexical"])
            for row in facts
            for value in [values[row["numeric_value_id"]]]
        ) == sorted(expected_numbers)
        fact_ids = [
            row for row in reader.rows("legacy_identifiers") if row["identifier_kind"] == "fact_id"
        ]
        assert {row["entity_id"] for row in fact_ids} == {row["entity_id"] for row in facts}
        expected_id = "unrelated" if source_fact_id == "missing" else source_fact_id
        assert [row["identifier_value"] for row in fact_ids] == [expected_id] * len(facts)
        assert reader.rows("overview_balances") == []
        assert reader.rows("transactions") == []
    replay = tmp_path / "replay"
    build_migration(plan, replay, active_data_dir=source)
    assert semantic_snapshot(candidate / "finjuice.sqlite3") == semantic_snapshot(
        replay / "finjuice.sqlite3"
    )
    assert before == (tree_inventory(source), tree_inventory(capture))


def _assert_overview_file_evidence(
    reader: RepositoryReader, candidate: Path, expected_files: dict[str, bytes]
) -> None:
    """Join retained rows to literal input bytes rather than trusting replay verification."""
    occurrences = {
        row["entity_id"]: row
        for row in reader.rows("source_occurrences")
        if row["legacy_path"] in expected_files
    }
    assert len(occurrences) == len(expected_files)
    assert {row["legacy_path"] for row in occurrences.values()} == set(expected_files)
    artifacts = {row["source_artifact_id"]: row for row in reader.rows("source_artifacts")}
    for occurrence in occurrences.values():
        artifact = artifacts[occurrence["source_artifact_id"]]
        assert (candidate / artifact["object_path"]).read_bytes() == expected_files[
            occurrence["legacy_path"]
        ]
    provenance = {
        row["provenance_id"]: row
        for row in reader.rows("record_provenance")
        if row["source_occurrence_id"] in occurrences
    }
    expected_rows = {
        (name, ordinal): (line.decode(), next(csv.reader([line.decode()])))
        for name, data in expected_files.items()
        for ordinal, line in enumerate(data.splitlines(keepends=True)[1:], 1)
    }
    facts = {row["provenance_id"]: row for row in reader.rows("overview_facts")}
    numbers = {row["value_id"]: row for row in reader.rows("exact_values")}
    actual_rows = {}
    balance_provenance = None
    for record in reader.rows("legacy_payloads"):
        payload = json.loads(record["payload_json"])
        if record["provenance_id"] not in provenance or "raw_record" not in payload:
            continue
        origin = provenance[record["provenance_id"]]
        name = occurrences[origin["source_occurrence_id"]]["legacy_path"]
        ordinal = json.loads(origin["source_coordinate_json"])["row"]
        assert (name, ordinal) not in actual_rows
        actual_rows[name, ordinal] = (payload["raw_record"], payload["values"])
        if record["provenance_id"] in facts:
            value = numbers[facts[record["provenance_id"]]["numeric_value_id"]]
            assert value["provenance_id"] == record["provenance_id"]
            assert value["lexical"] == expected_rows[name, ordinal][1][7]
        if name == "overview/balance.csv":
            assert payload["columns"] == ["source_fact_id", "amount", "currency"]
            balance_provenance = record["provenance_id"]
    assert actual_rows == expected_rows
    assert balance_provenance is not None
    issues = reader.rows("preservation_issues")
    assert len(issues) == 1
    assert (issues[0]["provenance_id"], issues[0]["issue_kind"], issues[0]["field_name"]) == (
        balance_provenance,
        "unresolved_source_fact",
        "source_fact_id",
    )
    assert issues[0]["lexical_value"] == expected_rows["overview/balance.csv", 1][1][0]
    dispositions = {row["provenance_id"]: row for row in reader.rows("migration_dispositions")}
    assert dispositions[balance_provenance]["disposition"] == "preserved_opaque"
