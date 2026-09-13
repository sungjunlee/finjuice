"""Policy-versioned manual overrides preserve raw sequences and persisted results."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from finjuice.pipeline.backup import ConsistencyEvidence, CreateRequest, create_backup
from finjuice.pipeline.migration import build_migration, plan_migration, verify_migration
from finjuice.pipeline.migration.common import canonical, seal, tree_inventory
from finjuice.pipeline.migration.plan import analyze_capture
from finjuice.pipeline.migration.policy import (
    CONFIG_HEAD_POLICY,
    LEGACY_POLICY,
    MANUAL_STATE_POLICY,
    OVERVIEW_REPORT_POLICY,
    PORTFOLIO_CONFIG_POLICY,
    migration_schema_version,
)
from finjuice.pipeline.migration.verify import semantic_snapshot
from finjuice.pipeline.storage.sqlite import GenerationPaths, RepositoryReader

PREFIX = "__finjuice_category_override__:"
# Explicit expectations are independent of the runtime normalization helper.
CASES = [
    ([PREFIX + "A", PREFIX + "B", PREFIX + "A"], "B", "A", [], []),
    ([PREFIX + "A", PREFIX + "   "], "A", "   ", [], []),
    (["  " + PREFIX + " B  "], "B", None, [], ["  " + PREFIX + " B  "]),
    (
        [" x ", "x", " x ", "", "  ", PREFIX + " A "],
        "A",
        " A ",
        [" x ", "x", " x ", "", "  "],
        [" x ", "x", " x ", "", "  "],
    ),
    ([PREFIX, PREFIX + "  "], None, "  ", [], []),
    ([PREFIX + " A ", PREFIX + "B", " " + PREFIX + " A "], "B", "B", [], [" " + PREFIX + " A "]),
]


def _capture(tmp_path: Path) -> tuple[Path, Path, list[dict[str, str]]]:
    source = tmp_path / "source"
    partition = source / "transactions" / "2026" / "01"
    partition.mkdir(parents=True)
    rows = [
        {
            "row_hash": str(index),
            "date": "2026-01-01",
            "time": "00:00",
            "datetime": "2026-01-01T00:00",
            "type_norm": "expense",
            "account": "synthetic",
            "amount": "9007199254740993.0100",
            "category_final": "persisted-category",
            "notes_manual": "original\nnotes",
            "tags_rule": "[]",
            "tags_ai": "[]",
            "tags_manual": json.dumps(manual),
            "tags_final": '["persisted", "persisted"]',
        }
        for index, (manual, *_expected) in enumerate(CASES)
    ]
    with (partition / "transactions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (source / "rules.yaml").write_text("rules: []\n")
    (source / "goals.yaml").write_text("goals: []\n")
    capture = tmp_path / "capture"
    create_backup(CreateRequest(source, capture, ConsistencyEvidence("stopped_writers", ("test",))))
    return source, capture, rows


def _assert_rows(reader: RepositoryReader, policy: str, originals: list[dict[str, str]]) -> None:
    provenance = {
        row["provenance_id"]: json.loads(row["source_coordinate_json"])
        for row in reader.rows("record_provenance")
    }
    payloads = {
        row["provenance_id"]: json.loads(row["payload_json"])
        for row in reader.rows("legacy_payloads")
    }
    transactions = reader.rows("transactions")
    assert len(transactions) == len(CASES)
    assert {provenance[row["provenance_id"]]["row"] for row in transactions} == set(
        range(1, len(CASES) + 1)
    )
    for transaction in transactions:
        provenance_id = transaction["provenance_id"]
        index = provenance[provenance_id]["row"] - 1
        _manual, modern, legacy, visible_modern, visible_legacy = CASES[index]
        assert transaction["category_manual"] == (
            modern
            if policy in (MANUAL_STATE_POLICY, OVERVIEW_REPORT_POLICY, PORTFOLIO_CONFIG_POLICY)
            else legacy
        )
        assert json.loads(transaction["tags_manual_json"]) == (
            visible_modern
            if policy in (MANUAL_STATE_POLICY, OVERVIEW_REPORT_POLICY, PORTFOLIO_CONFIG_POLICY)
            else visible_legacy
        )
        assert transaction["category_final"] == "persisted-category"
        assert transaction["notes_manual"] == "original\nnotes"
        assert json.loads(transaction["tags_final_json"]) == ["persisted", "persisted"]
        assert (
            dict(
                zip(
                    payloads[provenance_id]["columns"],
                    payloads[provenance_id]["values"],
                    strict=True,
                )
            )
            == originals[index]
        )
    assert {row["config_kind"] for row in reader.rows("config_heads")} == (
        set() if policy == LEGACY_POLICY else {"rules", "goals"}
    )


@pytest.mark.parametrize(
    "policy",
    [
        LEGACY_POLICY,
        CONFIG_HEAD_POLICY,
        MANUAL_STATE_POLICY,
        OVERVIEW_REPORT_POLICY,
        PORTFOLIO_CONFIG_POLICY,
    ],
)
def test_manual_policy_replays_frozen_selection_without_changing_persisted_results(
    tmp_path: Path, policy: str
) -> None:
    source, capture, originals = _capture(tmp_path)
    before = tree_inventory(source), tree_inventory(capture)
    path = tmp_path / "plan.json"
    plan = plan_migration(capture, output=path, active_data_dir=source).to_dict()["plan"]
    assert plan["migration_policy"] == PORTFOLIO_CONFIG_POLICY
    plan.pop("canonical_digest")
    plan["migration_policy"] = policy
    plan["inputs"] = analyze_capture(capture, plan["capture"], policy=policy)
    path.write_text(canonical(seal(plan)))
    candidate = tmp_path / "candidate"
    build_migration(path, candidate, active_data_dir=source)
    with RepositoryReader(
        GenerationPaths(candidate).database,
        expected_schema_version=migration_schema_version(policy),
    ) as reader:
        _assert_rows(reader, policy, originals)
    assert verify_migration(candidate).to_dict()["status"] == "ok"
    candidate_before = tree_inventory(candidate)
    assert (
        build_migration(path, candidate, active_data_dir=source).to_dict()["status"]
        == "already_complete"
    )
    assert tree_inventory(candidate) == candidate_before
    replay = tmp_path / "replay"
    build_migration(path, replay, active_data_dir=source)
    assert semantic_snapshot(
        GenerationPaths(candidate).database,
        expected_schema_version=migration_schema_version(policy),
    ) == semantic_snapshot(
        GenerationPaths(replay).database, expected_schema_version=migration_schema_version(policy)
    )
    assert before == (tree_inventory(source), tree_inventory(capture))
