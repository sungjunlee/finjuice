"""Independent synthetic oracle across backup, CLI, and repository boundaries."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import jsonschema
from referencing import Registry, Resource
from typer.testing import CliRunner

from finjuice.pipeline.backup import (
    ConsistencyEvidence,
    CreateRequest,
    SourceRoot,
    create_backup,
)
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.migration.common import tree_inventory
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
