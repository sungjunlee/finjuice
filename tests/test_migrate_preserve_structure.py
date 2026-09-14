"""Identity and preservation tests for frozen-source migration (issue #435)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from finjuice.pipeline import migrate
from finjuice.pipeline.migrate import inventory as inventory_module
from finjuice.pipeline.migrate import ops as ops_module
from finjuice.pipeline.migrate import preserve as preserve_module
from finjuice.pipeline.migrate.errors import MigrationError
from finjuice.pipeline.migrate.types import ORIGIN_KIND, SCHEMA_VERSION
from finjuice.pipeline.storage.sqlite import RepositoryReader
from finjuice.pipeline.tagging.manual import MANUAL_CATEGORY_PREFIX

MANUAL_A = f"{MANUAL_CATEGORY_PREFIX}커피"
MANUAL_B = f"{MANUAL_CATEGORY_PREFIX}카페"


def test_migrate_public_names_are_definition_site_aliases() -> None:
    """Public migrate names stay aliased to their definition modules."""
    assert migrate.plan_migration is ops_module.plan_migration
    assert migrate.build_migration is ops_module.build_migration
    assert migrate.verify_migration is ops_module.verify_migration
    assert migrate.write_plan is ops_module.write_plan
    assert migrate.notify_build_progress is ops_module.notify_build_progress
    assert migrate.capture_frozen_inputs is inventory_module.capture_frozen_inputs
    assert migrate.write_capture_manifest is inventory_module.write_capture_manifest
    assert migrate.split_hidden_category is preserve_module.split_hidden_category
    assert migrate.SCHEMA_VERSION == SCHEMA_VERSION
    assert migrate.ORIGIN_KIND == ORIGIN_KIND
    assert callable(migrate.plan_migration)
    assert callable(migrate.build_migration)
    assert callable(migrate.verify_migration)


def test_split_hidden_category_keeps_visible_order_and_last_marker() -> None:
    """P02: visible order is preserved and the last non-empty marker wins."""
    visible, selected, markers = migrate.split_hidden_category(
        ["식비", MANUAL_A, "카페방문", MANUAL_B, f"{MANUAL_CATEGORY_PREFIX}  "]
    )
    assert visible == ["식비", "카페방문"]
    assert selected == "카페"
    assert markers == [MANUAL_A, MANUAL_B, f"{MANUAL_CATEGORY_PREFIX}  "]


def _write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _transaction_row(**overrides: str) -> dict[str, str]:
    row = {
        "row_hash": "duphash01234567",
        "date": "2024-01-15",
        "time": "12:00:00",
        "type_raw": "지출",
        "type_norm": "expense",
        "major_raw": "식비",
        "minor_raw": "카페",
        "merchant_raw": "합성카페",
        "memo_raw": "원문메모",
        "notes_manual": "수동메모",
        "amount": "10.10",
        "account": "국민 111",
        "currency": "KRW",
        "counterparty": "",
        "datetime": "2024-01-15 12:00:00",
        "category_rule": "식비",
        "category_final": "카페",
        "tags_rule": '["규칙"]',
        "tags_ai": "[]",
        "tags_manual": json.dumps(["식비", MANUAL_A, MANUAL_B], ensure_ascii=False),
        "tags_final": '["규칙","식비"]',
        "confidence": "0.9",
        "needs_review": "1",
        "is_transfer_candidate": "0",
        "is_transfer": "",
        "transfer_group_id": "",
        "file_id": "240115_1",
        "source_row": "2",
        "mystery_field": "원문보존",
    }
    row.update(overrides)
    return row


def _frozen_dataset(root: Path) -> Path:
    source = root / "frozen"
    headers = list(_transaction_row().keys())
    first = _transaction_row()
    second = _transaction_row(
        source_row="3",
        account="우리 999",
        amount="0.0037",
        currency="USD",
        notes_manual="",
        confidence="n/a",
        tags_manual='["이체"]',
        category_rule="이체",
        category_final="이체",
        is_transfer="1",
        transfer_group_id="T0001",
        mystery_field="",
    )
    _write_csv(
        source / "transactions" / "2024" / "01" / "transactions.csv",
        headers,
        [first, second],
    )
    _write_csv(
        source / "banksalad" / "overview_facts" / "2024" / "01" / "facts.csv",
        [
            "fact_id",
            "snapshot_date",
            "sheet_name",
            "block_id",
            "block_title",
            "fact_kind",
            "row_label",
            "column_label",
            "value_numeric",
            "value_text",
            "value_type",
            "file_id",
            "source_row",
            "source_col",
        ],
        [
            {
                "fact_id": "fact-cash",
                "snapshot_date": "2024-01-31",
                "sheet_name": "overview",
                "block_id": "assets",
                "block_title": "자산",
                "fact_kind": "amount",
                "row_label": "현금",
                "column_label": "금액",
                "value_numeric": "1234.00",
                "value_text": "1234.00",
                "value_type": "number",
                "file_id": "240131_1",
                "source_row": "4",
                "source_col": "2",
            },
            {
                "fact_id": "fact-bad",
                "snapshot_date": "2024-01-31",
                "sheet_name": "overview",
                "block_id": "assets",
                "block_title": "자산",
                "fact_kind": "amount",
                "row_label": "기타",
                "column_label": "금액",
                "value_numeric": "not-a-number",
                "value_text": "not-a-number",
                "value_type": "number",
                "file_id": "240131_1",
                "source_row": "5",
                "source_col": "2",
            },
        ],
    )
    _write_csv(
        source / "banksalad" / "balance" / "2024" / "01" / "balance.csv",
        [
            "snapshot_date",
            "side",
            "category",
            "item_name",
            "amount",
            "currency",
            "source_fact_id",
            "file_id",
            "source_row",
        ],
        [
            {
                "snapshot_date": "2024-01-31",
                "side": "asset",
                "category": "cash",
                "item_name": "현금",
                "amount": "1234.00",
                "currency": "KRW",
                "source_fact_id": "fact-cash",
                "file_id": "240131_1",
                "source_row": "5",
            }
        ],
    )
    (source / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    (source / "goals.yaml").write_text("version: 1\ngoals: []\n", encoding="utf-8")
    (source / "assets.yaml").write_text("assets: []\n", encoding="utf-8")
    (source / "scenarios.yaml").write_text("scenarios: []\n", encoding="utf-8")
    (source / "imports").mkdir(parents=True)
    (source / "imports" / "2024-01.xlsx").write_bytes(b"synthetic-xlsx")
    (source / "audit").mkdir()
    (source / "audit" / "events.jsonl").write_text(
        '{"op":"tag","status":"legacy"}\n', encoding="utf-8"
    )
    (source / "metadata").mkdir()
    (source / "metadata" / "import_history.csv").write_text(
        "file_id,filename\n240115_1,2024-01.xlsx\n", encoding="utf-8"
    )
    return source


def _tree_state(root: Path) -> dict[str, tuple[int, bytes | None]]:
    state: dict[str, tuple[int, bytes | None]] = {}
    for path in (root, *sorted(root.rglob("*"))):
        relative = "." if path == root else path.relative_to(root).as_posix()
        entry = path.lstat()
        contents = path.read_bytes() if path.is_file() else None
        state[relative] = (entry.st_mode, contents)
    return state


def _prepare(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = _frozen_dataset(tmp_path)
    overlay = tmp_path / "overlay.yaml"
    overlay.write_text("overlay: true\n", encoding="utf-8")
    capture = migrate.capture_frozen_inputs(source, extra_roots={"overlay": overlay})
    capture_path = tmp_path / "capture-manifest.json"
    migrate.write_capture_manifest(capture, capture_path)
    return source, overlay, capture_path


def _assert_hidden_override_and_unknown_fields(staging: Path) -> None:
    with RepositoryReader(staging / "finjuice.sqlite3") as reader:
        transactions = reader.rows("transactions")
        assert len(transactions) == 2
        hashes = [
            row["identifier_value"]
            for row in reader.rows("legacy_identifiers")
            if row["identifier_kind"] == "row_hash"
        ]
        assert hashes == ["duphash01234567", "duphash01234567"]
        tagged = [row for row in transactions if row["category_manual"] == "카페"][0]
        assert json.loads(tagged["tags_manual_json"]) == ["식비"]
        assert tagged["category_final"] == "카페"
        assert tagged["category_rule"] == "식비"
        assert tagged["notes_manual"] == "수동메모"
        assert tagged["needs_review"] == 1
        assert tagged["is_transfer"] is None
        payloads = [json.loads(row["payload_json"]) for row in reader.rows("legacy_payloads")]
        hidden = [item for item in payloads if item.get("category_override_markers")][0]
        assert hidden["tags_manual_raw"][0] == "식비"
        assert MANUAL_A in hidden["category_override_markers"]
        assert hidden["unknown_fields"]["mystery_field"] == "원문보존"
        accounts = reader.rows("accounts")
        assert {row["display_name"] for row in accounts} >= {"국민 111", "우리 999"}
        assert all(row["ownership_state"] == "unknown" for row in accounts)
        origins = [
            json.loads(row["canonical_payload_json"])
            for row in reader.rows("config_revisions")
            if row["config_kind"] == "other"
        ]
        assert any(item.get("origin_kind") == ORIGIN_KIND for item in origins)
        amounts = {
            row["lexical"]: (row["coefficient"], row["scale"])
            for row in reader.rows("exact_values")
            if row["lexical"] in {"10.10", "0.0037"}
        }
        assert amounts["10.10"] == ("1010", 2)
        assert amounts["0.0037"] == ("37", 4)
        config_kinds = {row["config_kind"] for row in reader.rows("config_revisions")}
        assert {"rules", "goals", "assets", "scenarios", "other"} <= config_kinds
        issues = reader.rows("preservation_issues")
        assert any(row["field_name"] == "confidence" for row in issues)
        assert any(
            row["field_name"] == "value_numeric" and row["issue_kind"] == "unparseable_amount"
            for row in issues
        )
        opaque = [
            row
            for row in reader.rows("migration_dispositions")
            if row["disposition"] == "preserved_opaque"
        ]
        assert opaque
        assert reader.rows("overview_facts")
        assert reader.rows("overview_balances")
        roles = {row["occurrence_kind"] for row in reader.rows("source_occurrences")}
        assert "source_workbook" in roles
        assert "audit_history" in roles


def test_plan_build_verify_preserves_baseline_without_writing_source(
    tmp_path: Path,
) -> None:
    """Same frozen input is semantically identical and the source tree is untouched."""
    source, _overlay, capture_path = _prepare(tmp_path)
    before = _tree_state(source)
    plan = migrate.plan_migration(capture_path)
    plan_path = tmp_path / "migration-plan.json"
    migrate.write_plan(plan, plan_path)
    assert plan.capture_digest.startswith("sha256:")
    assert plan.counts_by_kind()["transaction"] == 2
    assert plan.to_public_dict()["absent_count"] >= 1

    staging = tmp_path / "candidate-a"
    first = migrate.build_migration(plan_path, staging, active_data_dir=source)
    assert first.status == "ok"
    assert first.origin_kind == ORIGIN_KIND
    assert first.unexplained_loss_count == 0
    assert first.dispositions.get("migrated", 0) >= 2
    assert _tree_state(source) == before

    verified = migrate.verify_migration(staging)
    assert verified.status == "ok"
    assert verified.candidate_digest == first.candidate_digest
    assert {item["check_id"] for item in verified.checks} >= {"P01", "P02", "P03", "P04", "I01"}
    _assert_hidden_override_and_unknown_fields(staging)

    repeat = migrate.build_migration(plan_path, staging, active_data_dir=source)
    assert repeat.status == "already_complete"
    assert repeat.candidate_digest == first.candidate_digest
    assert _tree_state(source) == before

    staging_b = tmp_path / "candidate-b"
    second = migrate.build_migration(plan, staging_b, active_data_dir=source)
    assert second.status == "ok"
    assert second.candidate_digest == first.candidate_digest
    assert _tree_state(source) == before


def test_source_change_missing_file_disk_full_and_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Input mutation, missing files, disk exhaustion, and interrupted retry."""
    source, _overlay, capture_path = _prepare(tmp_path)
    plan = migrate.plan_migration(capture_path)
    plan_path = tmp_path / "plan.json"
    migrate.write_plan(plan, plan_path)
    before = _tree_state(source)

    changed = source / "transactions" / "2024" / "01" / "transactions.csv"
    changed.write_text(changed.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    with pytest.raises(MigrationError, match="changed"):
        migrate.build_migration(plan_path, tmp_path / "changed", active_data_dir=source)
    changed.write_bytes(before["transactions/2024/01/transactions.csv"][1] or b"")
    assert (
        _tree_state(source)["transactions/2024/01/transactions.csv"][1]
        == (before["transactions/2024/01/transactions.csv"][1])
    )

    missing = source / "imports" / "2024-01.xlsx"
    original_xlsx = missing.read_bytes()
    missing.unlink()
    with pytest.raises(MigrationError, match="missing"):
        migrate.build_migration(plan_path, tmp_path / "missing", active_data_dir=source)
    missing.write_bytes(original_xlsx)

    class Usage:
        free = 1
        total = 1
        used = 0

    monkeypatch.setattr(inventory_module.shutil, "disk_usage", lambda _path: Usage())
    with pytest.raises(MigrationError, match="Insufficient disk space"):
        migrate.build_migration(plan_path, tmp_path / "nospace", active_data_dir=source)
    monkeypatch.setattr(
        inventory_module.shutil,
        "disk_usage",
        lambda _path: type("U", (), {"free": 10**12, "total": 10**12, "used": 0})(),
    )

    original_progress = ops_module.notify_build_progress

    def interrupt(stage: str) -> None:
        if stage == "transaction_partition":
            raise RuntimeError("simulated interrupt")

    monkeypatch.setattr(ops_module, "notify_build_progress", interrupt)
    interrupted = tmp_path / "interrupted"
    with pytest.raises(RuntimeError, match="simulated interrupt"):
        migrate.build_migration(plan_path, interrupted, active_data_dir=source)
    assert not (interrupted / "FINJUICE_MIGRATION_COMPLETE").exists()
    monkeypatch.setattr(ops_module, "notify_build_progress", original_progress)
    retried = migrate.build_migration(plan_path, tmp_path / "retry", active_data_dir=source)
    assert retried.status == "ok"
    assert _tree_state(source) == before
    assert migrate.verify_migration(tmp_path / "retry").status == "ok"


def test_build_refuses_source_as_staging(tmp_path: Path) -> None:
    """Build must not target the frozen or live source directory."""
    source, _overlay, capture_path = _prepare(tmp_path)
    plan = migrate.plan_migration(capture_path)
    with pytest.raises(MigrationError, match="outside the frozen source"):
        migrate.build_migration(plan, source, active_data_dir=source)
