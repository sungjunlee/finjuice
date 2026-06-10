"""Tests for manual tag editing via `finjuice tag --edit`."""

import json
from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.csv_partition import read_month, write_month
from finjuice.pipeline.tagging.manual import MANUAL_CATEGORY_PREFIX

runner = CliRunner()

STARBUCKS_HASH = "aaaaaaaaaaaaaaaa"
HOSPITAL_HASH = "bbbbbbbbbbbbbbbb"


def _get_transaction(data_dir: Path, row_hash: str) -> dict[str, object]:
    """Read a single transaction row from the October 2024 fixture partition."""
    df = read_month(data_dir / "transactions", 2024, 10)
    return df.filter(pl.col("row_hash") == row_hash).row(0, named=True)


def _read_audit_events(data_dir: Path) -> list[dict[str, object]]:
    """Read JSONL audit events from a test data directory."""
    audit_path = data_dir / ".execution_audit.jsonl"
    if not audit_path.exists():
        return []
    return [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture
def tag_edit_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with a taggable October 2024 partition."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()

    transactions = pl.DataFrame(
        [
            {
                "row_hash": STARBUCKS_HASH,
                "date": "2024-10-01",
                "time": "09:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "식비",
                "minor_raw": "카페",
                "merchant_raw": "스타벅스 강남점",
                "memo_raw": "",
                "amount": -5500.0,
                "account": "신한카드",
                "currency": "KRW",
                "counterparty": "",
                "datetime": "2024-10-01T09:00:00",
                "category_rule": None,
                "category_final": "카페",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 0.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": "",
                "file_id": "241001_1",
                "source_row": 1,
            },
            {
                "row_hash": HOSPITAL_HASH,
                "date": "2024-10-02",
                "time": "10:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "생활",
                "minor_raw": "병원",
                "merchant_raw": "서울여성병원",
                "memo_raw": "진료비",
                "amount": -120000.0,
                "account": "현대카드",
                "currency": "KRW",
                "counterparty": "",
                "datetime": "2024-10-02T10:00:00",
                "category_rule": None,
                "category_final": "병원",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 0.0,
                "needs_review": 0,
                "is_transfer": 0,
                "transfer_group_id": "",
                "file_id": "241002_1",
                "source_row": 2,
            },
        ]
    )
    write_month(data_dir / "transactions", transactions, 2024, 10)

    rules_yaml = """
version: 1
rules:
  - name: starbucks
    match: "스타벅스"
    fields: ["merchant_raw"]
    tags: ["카페", "커피"]
    priority: 90
    category: "카페"
"""
    (data_dir / "rules.yaml").write_text(rules_yaml.strip() + "\n", encoding="utf-8")

    return data_dir


def test_tag_edit_add_tag_updates_manual_and_final_tags(tag_edit_data_dir: Path) -> None:
    """`--add-tag` should persist to tags_manual and recalculate tags_final."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            STARBUCKS_HASH,
            "--add-tag",
            "검진",
        ],
    )

    assert result.exit_code == 0, result.output
    row = _get_transaction(tag_edit_data_dir, STARBUCKS_HASH)
    assert row["tags_manual"] == ["검진"]
    assert row["tags_final"] == ["검진"]

    events = _read_audit_events(tag_edit_data_dir)
    assert len(events) == 1
    assert events[0]["event"] == "financial_mutation"
    assert events[0]["command"] == "tag"
    assert events[0]["action"] == "manual_edit"
    assert events[0]["row_hash"] == STARBUCKS_HASH
    assert events[0]["fields_changed"] == ["tags_manual", "tags_final", "confidence"]
    assert events[0]["change_summary"] == "manual tag edit updated transaction"
    assert events[0]["success"] is True
    rendered_events = json.dumps(events, ensure_ascii=False)
    assert "스타벅스" not in rendered_events
    assert "검진" not in rendered_events
    assert "5500" not in rendered_events


def test_tag_edit_remove_tag_updates_manual_tags(tag_edit_data_dir: Path) -> None:
    """`--remove-tag` should remove only the requested manual tag."""
    add_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            STARBUCKS_HASH,
            "--add-tag",
            "식비",
            "--add-tag",
            "검진",
        ],
    )
    assert add_result.exit_code == 0, add_result.output

    remove_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            STARBUCKS_HASH,
            "--remove-tag",
            "식비",
        ],
    )

    assert remove_result.exit_code == 0, remove_result.output
    row = _get_transaction(tag_edit_data_dir, STARBUCKS_HASH)
    assert row["tags_manual"] == ["검진"]
    assert row["tags_final"] == ["검진"]


def test_tag_edit_manual_tags_persist_after_retagging(tag_edit_data_dir: Path) -> None:
    """Re-running `finjuice tag` should preserve tags_manual and merge tags_final."""
    edit_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            STARBUCKS_HASH,
            "--add-tag",
            "검진",
        ],
    )
    assert edit_result.exit_code == 0, edit_result.output

    tag_result = runner.invoke(app, ["--data-dir", str(tag_edit_data_dir), "tag"])

    assert tag_result.exit_code == 0, tag_result.output
    row = _get_transaction(tag_edit_data_dir, STARBUCKS_HASH)
    assert row["tags_rule"] == ["카페", "커피"]
    assert row["tags_manual"] == ["검진"]
    assert row["tags_final"] == ["카페", "커피", "검진"]


def test_tag_edit_notes_persist_after_retagging(tag_edit_data_dir: Path) -> None:
    """Re-running `finjuice tag` should not treat notes_manual as classification input."""
    edit_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            HOSPITAL_HASH,
            "--set-note",
            "융모막검사비용, 3개월 할부",
        ],
    )
    assert edit_result.exit_code == 0, edit_result.output

    tag_result = runner.invoke(app, ["--data-dir", str(tag_edit_data_dir), "tag"])

    assert tag_result.exit_code == 0, tag_result.output
    row = _get_transaction(tag_edit_data_dir, HOSPITAL_HASH)
    assert row["notes_manual"] == "융모막검사비용, 3개월 할부"
    assert row["tags_manual"] == []
    assert row["tags_final"] == []
    assert row["confidence"] == 0.0


def test_tag_edit_json_returns_transaction_payload(tag_edit_data_dir: Path) -> None:
    """`--edit <hash> --json` should return the current transaction view without mutating it."""
    edit_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            STARBUCKS_HASH,
            "--add-tag",
            "검진",
        ],
    )
    assert edit_result.exit_code == 0, edit_result.output

    result = runner.invoke(
        app,
        ["--data-dir", str(tag_edit_data_dir), "tag", "--edit", STARBUCKS_HASH, "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["_meta"]["command"] == "tag"
    assert payload["operation"] == "edit"
    assert payload["updated"] is False
    assert payload["transaction"]["row_hash"] == STARBUCKS_HASH
    assert payload["transaction"]["notes_manual"] == ""
    assert payload["transaction"]["tags_manual"] == ["검진"]
    assert payload["transaction"]["tags_final"] == ["검진"]


def test_tag_edit_read_only_inspection_does_not_append_audit_event(
    tag_edit_data_dir: Path,
) -> None:
    """Inspecting a row without edit flags should not claim a mutation."""
    result = runner.invoke(
        app,
        ["--data-dir", str(tag_edit_data_dir), "tag", "--edit", STARBUCKS_HASH, "--json"],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["updated"] is False
    assert _read_audit_events(tag_edit_data_dir) == []


def test_tag_edit_no_op_does_not_append_audit_event(review_data_dir: Path) -> None:
    """Edit flags that do not change persisted state should not log success."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "tag",
            "--edit",
            REVIEW_HASH,
            "--remove-tag",
            "없는태그",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["updated"] is False
    assert _read_audit_events(review_data_dir) == []


def test_tag_edit_invalid_row_hash_returns_error(tag_edit_data_dir: Path) -> None:
    """Unknown row_hash should exit with a machine-readable NO_DATA error."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            "missinghash",
            "--add-tag",
            "검진",
            "--json",
        ],
    )

    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "NO_DATA"
    assert "row_hash" in payload["error"]["message"]


def test_tag_edit_set_category_overrides_category_final(tag_edit_data_dir: Path) -> None:
    """`--set-category` should persist a category override across re-tagging."""
    edit_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            HOSPITAL_HASH,
            "--set-category",
            "의료",
        ],
    )
    assert edit_result.exit_code == 0, edit_result.output

    row = _get_transaction(tag_edit_data_dir, HOSPITAL_HASH)
    assert row["category_final"] == "의료"
    assert row["tags_manual"] == [f"{MANUAL_CATEGORY_PREFIX}의료"]


def test_tag_edit_set_note_persists_without_changing_tags_or_confidence(
    tag_edit_data_dir: Path,
) -> None:
    """`--set-note` should store explanatory context outside analysis tags."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            HOSPITAL_HASH,
            "--set-note",
            "융모막검사비용, 3개월 할부",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["updated"] is True
    assert payload["would_update"] is True
    assert payload["transaction"]["notes_manual"] == "융모막검사비용, 3개월 할부"
    assert payload["transaction"]["tags_manual"] == []
    assert payload["transaction"]["tags_final"] == []

    row = _get_transaction(tag_edit_data_dir, HOSPITAL_HASH)
    assert row["notes_manual"] == "융모막검사비용, 3개월 할부"
    assert row["tags_manual"] == []
    assert row["tags_final"] == []
    assert row["confidence"] == 0.0

    events = _read_audit_events(tag_edit_data_dir)
    assert len(events) == 1
    assert events[0]["fields_changed"] == ["notes_manual"]
    rendered_events = json.dumps(events, ensure_ascii=False)
    assert "융모막검사" not in rendered_events
    assert "3개월" not in rendered_events


def test_tag_edit_set_note_can_clear_existing_note(tag_edit_data_dir: Path) -> None:
    """Passing an empty note value should clear notes_manual."""
    set_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            HOSPITAL_HASH,
            "--set-note",
            "초진",
        ],
    )
    assert set_result.exit_code == 0, set_result.output

    clear_result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            HOSPITAL_HASH,
            "--set-note",
            "",
            "--json",
        ],
    )

    assert clear_result.exit_code == 0, clear_result.output
    payload = json.loads(clear_result.output)
    assert payload["transaction"]["notes_manual"] == ""
    row = _get_transaction(tag_edit_data_dir, HOSPITAL_HASH)
    assert row["notes_manual"] == ""


def test_tag_edit_dry_run_previews_note_and_tag_without_writing(
    tag_edit_data_dir: Path,
) -> None:
    """Manual edit dry-run should return the would-be row and leave CSV/audit untouched."""
    partition_path = tag_edit_data_dir / "transactions" / "2024" / "10" / "transactions.csv"
    before_csv = partition_path.read_text(encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            HOSPITAL_HASH,
            "--add-tag",
            "의료",
            "--set-note",
            "검사비",
            "--dry-run",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["dry_run"] is True
    assert payload["updated"] is False
    assert payload["would_update"] is True
    assert payload["transaction"]["notes_manual"] == "검사비"
    assert payload["transaction"]["tags_manual"] == ["의료"]
    assert partition_path.read_text(encoding="utf-8") == before_csv
    assert _read_audit_events(tag_edit_data_dir) == []


def test_tag_edit_rejects_overlong_note(tag_edit_data_dir: Path) -> None:
    """Manual notes should have a bounded size for row-level CSV ergonomics."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(tag_edit_data_dir),
            "tag",
            "--edit",
            HOSPITAL_HASH,
            "--set-note",
            "x" * 1001,
            "--json",
        ],
    )

    assert result.exit_code == 3
    payload = json.loads(result.output)
    assert payload["error"]["code"] == "INVALID_ARGS"
    assert "Manual note" in payload["error"]["message"]


REVIEW_HASH = "cccccccccccccccc"


@pytest.fixture
def review_data_dir(tmp_path: Path) -> Path:
    """Data dir with a needs_review=1 transaction for regression testing."""
    data_dir = tmp_path / "data"
    (data_dir / "imports").mkdir(parents=True)
    (data_dir / "exports").mkdir()
    (data_dir / "metadata").mkdir()

    transactions = pl.DataFrame(
        [
            {
                "row_hash": REVIEW_HASH,
                "date": "2024-10-03",
                "time": "11:00",
                "type_raw": "지출",
                "type_norm": "expense",
                "major_raw": "",
                "minor_raw": "",
                "merchant_raw": "알수없는가맹점",
                "memo_raw": "",
                "amount": -30000.0,
                "account": "국민카드",
                "currency": "KRW",
                "counterparty": "",
                "datetime": "2024-10-03T11:00:00",
                "category_rule": None,
                "category_final": "미분류",
                "tags_rule": [],
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": [],
                "confidence": 0.0,
                "needs_review": 1,
                "is_transfer": 0,
                "transfer_group_id": "",
                "file_id": "241003_1",
                "source_row": 3,
            },
        ]
    )
    write_month(data_dir / "transactions", transactions, 2024, 10)

    rules_yaml = "version: 1\nrules: []\n"
    (data_dir / "rules.yaml").write_text(rules_yaml, encoding="utf-8")
    return data_dir


def test_tag_edit_clears_needs_review_after_manual_tag(review_data_dir: Path) -> None:
    """review → tag --edit → review: manual tag should clear needs_review."""
    # Arrange: verify transaction starts in review queue
    row_before = _get_transaction(review_data_dir, REVIEW_HASH)
    assert row_before["needs_review"] == 1
    assert row_before["confidence"] == 0.0

    # Act: add a manual tag
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "tag",
            "--edit",
            REVIEW_HASH,
            "--add-tag",
            "식비",
        ],
    )
    assert result.exit_code == 0, result.output

    # Assert: needs_review cleared, confidence set to 1.0
    row_after = _get_transaction(review_data_dir, REVIEW_HASH)
    assert row_after["confidence"] == 1.0
    assert row_after["needs_review"] == 0
    assert row_after["tags_final"] == ["식비"]


def test_tag_edit_set_category_clears_needs_review(review_data_dir: Path) -> None:
    """--set-category alone should also clear needs_review."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "tag",
            "--edit",
            REVIEW_HASH,
            "--set-category",
            "식비",
        ],
    )
    assert result.exit_code == 0, result.output

    row = _get_transaction(review_data_dir, REVIEW_HASH)
    assert row["needs_review"] == 0
    assert row["category_final"] == "식비"


def test_tag_edit_json_includes_needs_review(review_data_dir: Path) -> None:
    """JSON output should reflect updated needs_review after edit."""
    runner.invoke(
        app,
        [
            "--data-dir",
            str(review_data_dir),
            "tag",
            "--edit",
            REVIEW_HASH,
            "--add-tag",
            "의료",
        ],
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(review_data_dir), "tag", "--edit", REVIEW_HASH, "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    txn = payload["transaction"]
    assert txn["needs_review"] == 0
    assert txn["confidence"] == 1.0
