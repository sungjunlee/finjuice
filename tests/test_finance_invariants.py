"""Property-style tests for finance data invariants."""

from __future__ import annotations

import json
from datetime import datetime
from itertools import permutations
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import review as review_module
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.ingest.deduplication import calculate_row_hash
from finjuice.pipeline.storage.csv_partition import append_transactions, read_month, read_range
from finjuice.pipeline.tagging.pipeline import run_tagging
from finjuice.pipeline.transfer.detection import TransferCandidate, detect_transfer_pairs

runner = CliRunner()


def _invoke_query_page(
    data_dir: Path,
    *,
    total_rows: int,
    limit: int,
    cursor: str,
) -> dict[str, object]:
    sql = f"SELECT range AS n FROM range({total_rows}) ORDER BY n"
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "query",
            sql,
            "--json",
            "--limit",
            str(limit),
            "--cursor",
            cursor,
        ],
    )
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_query_pagination_pages_cover_each_row_once(tmp_path: Path) -> None:
    """Offset pagination should walk deterministic result sets without gaps or duplicates."""
    data_dir = tmp_path / "query-pagination"
    init_result = runner.invoke(app, ["--data-dir", str(data_dir), "init"])
    assert init_result.exit_code == 0, init_result.output

    cases = [
        (0, 5),
        (1, 2),
        (2, 1),
        (5, 2),
        (17, 5),
        (20, 10),
    ]

    for total_rows, limit in cases:
        cursor = "0"
        seen_values: list[int] = []
        seen_cursors: set[str] = set()

        while True:
            assert cursor not in seen_cursors
            seen_cursors.add(cursor)

            payload = _invoke_query_page(
                data_dir,
                total_rows=total_rows,
                limit=limit,
                cursor=cursor,
            )
            rows = payload["rows"]
            assert isinstance(rows, list)
            page_values = [row["n"] for row in rows]
            assert len(page_values) == len(set(page_values))
            seen_values.extend(page_values)

            pagination = payload["pagination"]
            assert isinstance(pagination, dict)
            assert pagination["limit"] == limit
            assert pagination["cursor"] == cursor

            next_cursor = pagination["next_cursor"]
            if next_cursor is None:
                assert pagination["has_more"] is False
                break

            assert pagination["has_more"] is True
            cursor = str(next_cursor)

        assert seen_values == list(range(total_rows))
        assert len(seen_values) == len(set(seen_values))


def test_review_queue_sorting_uses_row_hash_tie_breaker_for_equal_dates() -> None:
    """Equal-date review rows should sort the same way for every input ordering."""
    rows = [
        {"row_hash": "hash-b", "date": "2025-11-12"},
        {"row_hash": "hash-new", "date": "2025-11-13"},
        {"row_hash": "hash-a", "date": "2025-11-12"},
        {"row_hash": "hash-old", "date": "2025-11-11"},
        {"row_hash": "hash-c", "date": "2025-11-12"},
    ]
    expected_order = ["hash-new", "hash-a", "hash-b", "hash-c", "hash-old"]

    for ordered_rows in permutations(rows):
        sorted_df = review_module._sort_review_rows(pl.DataFrame(list(ordered_rows)))

        assert sorted_df.get_column("row_hash").to_list() == expected_order


def test_row_hash_is_stable_under_reordered_columns() -> None:
    """A logical bank row should keep the same row_hash across column and row ordering."""
    row = {
        "date": "2026-04-15",
        "time": "08:33",
        "type": "지출",
        "merchant": "Invariant Coffee",
        "amount": -12345,
        "currency": "KRW",
        "account": "Invariant Card",
        "memo": "mutable note excluded from row_hash",
        "major_category": "old category",
    }
    baseline_hash = calculate_row_hash(row)
    required_keys = ["date", "time", "type", "merchant", "amount", "currency", "account"]

    for ordered_keys in permutations(required_keys):
        reordered_row = {key: row[key] for key in ordered_keys}
        reordered_row["major_category"] = row["major_category"]
        reordered_row["memo"] = row["memo"]

        assert calculate_row_hash(reordered_row) == baseline_hash

    rows = [
        row,
        {
            **row,
            "time": "09:10",
            "merchant": "Invariant Grocery",
            "amount": -54321,
        },
        {
            **row,
            "time": "10:05",
            "type": "수입",
            "merchant": "Invariant Payroll",
            "amount": 3456789,
        },
    ]
    expected_by_transaction = {
        (item["date"], item["time"], item["merchant"]): calculate_row_hash(item) for item in rows
    }

    for ordered_rows in permutations(rows):
        hashes_by_transaction = {
            (item["date"], item["time"], item["merchant"]): calculate_row_hash(item)
            for item in ordered_rows
        }

        assert hashes_by_transaction == expected_by_transaction


def _boundary_transaction(case_id: str, date: str, index: int) -> dict[str, object]:
    return {
        "row_hash": f"{case_id}-{date}",
        "date": date,
        "time": f"09:0{index}",
        "datetime": f"{date}T09:0{index}:00",
        "type_norm": "expense",
        "merchant_raw": f"Boundary Merchant {case_id} {index}",
        "amount": -1000.0 - index,
        "currency": "KRW",
        "needs_review": 0,
        "is_transfer": 0,
        "tags_rule": [],
        "tags_ai": [],
        "tags_manual": [],
        "tags_final": [],
        "source_row": index,
    }


def _transaction(
    row_hash: str,
    date: str,
    merchant: str,
    amount: float,
    overrides: dict[str, object] | None = None,
) -> dict[str, object]:
    values = dict(overrides or {})
    time = str(values.pop("time", "09:00"))
    major = str(values.pop("major", "생활"))
    minor = str(values.pop("minor", "미분류"))
    memo = str(values.pop("memo", ""))
    account = str(values.pop("account", "합성카드"))
    tags_ai = values.pop("tags_ai", [])
    tags_manual = values.pop("tags_manual", [])
    source_row = int(values.pop("source_row", 1))

    type_raw = "입금" if amount > 0 else "지출"
    type_norm = "income" if amount > 0 else "expense"
    row = {
        "row_hash": row_hash,
        "date": date,
        "time": time,
        "type_raw": type_raw,
        "type_norm": type_norm,
        "major_raw": major,
        "minor_raw": minor,
        "merchant_raw": merchant,
        "memo_raw": memo,
        "amount": amount,
        "account": account,
        "currency": "KRW",
        "counterparty": "",
        "datetime": f"{date}T{time}:00",
        "category_rule": None,
        "category_final": minor or major or "미분류",
        "tags_rule": [],
        "tags_ai": tags_ai or [],
        "tags_manual": tags_manual or [],
        "tags_final": [],
        "confidence": 0.0,
        "needs_review": 0,
        "is_transfer": 0,
        "transfer_group_id": None,
        "file_id": "260415_1",
        "source_row": source_row,
    }
    row.update(values)
    return row


def test_csv_partition_append_read_is_idempotent_across_month_boundaries(
    tmp_path: Path,
) -> None:
    """Appending the same boundary-spanning batch twice should not duplicate rows."""
    cases = [
        ("jan_feb", "2024-01-31", "2024-02-01"),
        ("leap_feb_mar", "2024-02-29", "2024-03-01"),
        ("dec_jan", "2024-12-31", "2025-01-01"),
    ]

    for case_id, start_date, end_date in cases:
        storage_dir = tmp_path / case_id / "transactions"
        batch = pl.DataFrame(
            [
                _boundary_transaction(case_id, start_date, 1),
                _boundary_transaction(case_id, end_date, 2),
            ]
        )

        first_append = append_transactions(storage_dir, batch, deduplicate=True)
        second_append = append_transactions(storage_dir, batch, deduplicate=True)

        assert first_append["partitions_updated"] == 2
        assert first_append["rows_inserted"] == 2
        assert first_append["rows_skipped"] == 0
        assert second_append["partitions_updated"] == 0
        assert second_append["rows_inserted"] == 0
        assert second_append["rows_skipped"] == 2

        rows = read_range(storage_dir, start_date, end_date, columns=["row_hash", "date"])
        row_hashes = rows.get_column("row_hash").to_list()
        assert row_hashes == [f"{case_id}-{start_date}", f"{case_id}-{end_date}"]
        assert len(row_hashes) == len(set(row_hashes))

        for date in (start_date, end_date):
            year, month, _day = date.split("-")
            month_rows = read_month(storage_dir, int(year), int(month))
            assert month_rows.height == 1


def test_transfer_pairing_is_symmetric() -> None:
    """Detected transfer groups should assign both sides of every pair consistently."""
    candidates = [
        TransferCandidate(
            id=1,
            datetime=datetime(2026, 4, 15, 10, 0),
            amount=-50_000.0,
            account="Checking",
            counterparty="Savings",
            major_category="내계좌이체",
            currency="KRW",
            row_hash="hash_alpha_out_0001",
        ),
        TransferCandidate(
            id=2,
            datetime=datetime(2026, 4, 15, 10, 2),
            amount=50_000.0,
            account="Savings",
            counterparty="Checking",
            major_category="내계좌이체",
            currency="KRW",
            row_hash="hash_alpha_in_0002",
        ),
        TransferCandidate(
            id=3,
            datetime=datetime(2026, 4, 15, 11, 0),
            amount=-75_000.0,
            account="Card",
            counterparty="Checking",
            major_category="내계좌이체",
            currency="KRW",
            row_hash="hash_bravo_out_0003",
        ),
        TransferCandidate(
            id=4,
            datetime=datetime(2026, 4, 15, 11, 3),
            amount=75_000.0,
            account="Checking",
            counterparty="Card",
            major_category="내계좌이체",
            currency="KRW",
            row_hash="hash_bravo_in_0004",
        ),
        TransferCandidate(
            id=5,
            datetime=datetime(2026, 4, 15, 12, 0),
            amount=-125_000.0,
            account="Brokerage",
            counterparty="Checking",
            major_category="내계좌이체",
            currency="KRW",
            row_hash="hash_charlie_out_0005",
        ),
        TransferCandidate(
            id=6,
            datetime=datetime(2026, 4, 15, 12, 1),
            amount=125_000.0,
            account="Checking",
            counterparty="Brokerage",
            major_category="내계좌이체",
            currency="KRW",
            row_hash="hash_charlie_in_0006",
        ),
    ]

    first_groups = detect_transfer_pairs(candidates)
    second_groups = detect_transfer_pairs(candidates)
    reversed_groups = detect_transfer_pairs(list(reversed(candidates)))

    assert first_groups == second_groups == reversed_groups
    assert len(first_groups) == 3

    group_by_id: dict[int, str] = {}
    pairmate_by_id: dict[int, int] = {}
    for group_id, transaction_ids in first_groups.items():
        assert len(transaction_ids) == 2
        left_id, right_id = transaction_ids
        group_by_id[left_id] = group_id
        group_by_id[right_id] = group_id
        pairmate_by_id[left_id] = right_id
        pairmate_by_id[right_id] = left_id

    assert sorted(group_by_id) == [1, 2, 3, 4, 5, 6]
    for transaction_id, pairmate_id in pairmate_by_id.items():
        assert pairmate_by_id[pairmate_id] == transaction_id
        assert group_by_id[transaction_id] == group_by_id[pairmate_id]


def test_tagging_pipeline_is_deterministic(tmp_path: Path) -> None:
    """Repeated tagging should produce the same final tags and one scalar category."""
    data_dir = tmp_path / "tagging-determinism"
    transactions_dir = data_dir / "transactions"
    rules_path = data_dir / "rules.yaml"
    rules_path.parent.mkdir(parents=True)
    rules_path.write_text(
        """
version: 1
rules:
  - name: delivery_food
    match: "배달"
    fields: ["merchant_raw"]
    tags: ["food", "delivery", "food"]
    priority: 90
    category: "식비"
  - name: coffee
    match: "스타벅스|카페"
    fields: ["merchant_raw", "memo_raw"]
    tags: ["coffee", "food"]
    priority: 80
    category: "카페"
  - name: shopping
    match: "쿠팡"
    fields: ["merchant_raw"]
    tags: ["shopping"]
    priority: 70
    category: "쇼핑"
  - name: insurance
    match: "보험"
    fields: ["merchant_raw", "major_raw"]
    tags: ["insurance", "fixed"]
    priority: 60
    category: "보험"
""".lstrip(),
        encoding="utf-8",
    )
    transactions = pl.DataFrame(
        [
            _transaction(
                "tag-001",
                "2026-04-01",
                "배달의민족",
                -23_000.0,
                {"time": "08:00", "minor": "외식", "source_row": 1},
            ),
            _transaction(
                "tag-002",
                "2026-04-02",
                "스타벅스",
                -5_500.0,
                {
                    "time": "09:00",
                    "minor": "카페",
                    "tags_manual": ["manual", "food"],
                    "source_row": 2,
                },
            ),
            _transaction(
                "tag-003",
                "2026-04-03",
                "쿠팡",
                -45_000.0,
                {
                    "time": "10:00",
                    "minor": "생활용품",
                    "tags_ai": ["ai_tag"],
                    "source_row": 3,
                },
            ),
            _transaction(
                "tag-004",
                "2026-04-04",
                "건강보험",
                -120_000.0,
                {
                    "time": "11:00",
                    "major": "보험",
                    "minor": "사회보험",
                    "source_row": 4,
                },
            ),
            _transaction(
                "tag-005",
                "2026-04-05",
                "무규칙상점",
                -9_900.0,
                {
                    "time": "12:00",
                    "major": "생활",
                    "minor": "잡화",
                    "source_row": 5,
                },
            ),
        ]
    )
    append_transactions(transactions_dir, transactions, deduplicate=True)

    first_summary = run_tagging(transactions_dir, rules_path)
    first_rows = (
        read_month(
            transactions_dir,
            2026,
            4,
            columns=["row_hash", "tags_final", "category_final"],
        )
        .sort("row_hash")
        .to_dicts()
    )

    second_summary = run_tagging(transactions_dir, rules_path)
    second_rows = (
        read_month(
            transactions_dir,
            2026,
            4,
            columns=["row_hash", "tags_final", "category_final"],
        )
        .sort("row_hash")
        .to_dicts()
    )

    assert first_summary == second_summary
    assert first_rows == second_rows
    assert first_rows == [
        {"row_hash": "tag-001", "tags_final": ["food", "delivery"], "category_final": "식비"},
        {
            "row_hash": "tag-002",
            "tags_final": ["coffee", "food", "manual"],
            "category_final": "카페",
        },
        {
            "row_hash": "tag-003",
            "tags_final": ["shopping", "ai_tag"],
            "category_final": "쇼핑",
        },
        {
            "row_hash": "tag-004",
            "tags_final": ["insurance", "fixed"],
            "category_final": "보험",
        },
        {"row_hash": "tag-005", "tags_final": [], "category_final": "잡화"},
    ]
    for row in first_rows:
        tags = row["tags_final"]
        category = row["category_final"]
        assert tags == list(dict.fromkeys(tags))
        assert category is not None
        assert not isinstance(category, list)


def test_compact_privacy_profile_omits_raw_amounts(tmp_path: Path) -> None:
    """Compact JSON should not expose exact transaction amounts from synthetic data."""
    data_dir = tmp_path / "compact-privacy"
    for child in ("imports", "transactions", "exports", "metadata"):
        (data_dir / child).mkdir(parents=True, exist_ok=True)
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    append_transactions(
        data_dir / "transactions",
        pl.DataFrame(
            [
                _transaction(
                    "privacy-income",
                    "2026-04-10",
                    "Synthetic Employer",
                    6_533_333.0,
                    {
                        "time": "09:00",
                        "major": "수입",
                        "minor": "급여",
                        "source_row": 1,
                    },
                ),
                _transaction(
                    "privacy-expense",
                    "2026-04-11",
                    "Synthetic Private Merchant",
                    -271_111.0,
                    {
                        "time": "10:00",
                        "major": "생활",
                        "minor": "비공개지출",
                        "source_row": 2,
                    },
                ),
            ]
        ),
        deduplicate=True,
    )

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "checkup",
            "--json",
            "--privacy",
            "compact",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["_meta"]["privacy"]["profile"] == "compact"
    assert "data_dir" not in payload
    assert "amount" not in serialized.lower()
    for forbidden_token in (
        "6533333",
        "6,533,333",
        "271111",
        "271,111",
        "Synthetic Employer",
        "Synthetic Private Merchant",
        "합성카드",
        "비공개지출",
    ):
        assert forbidden_token not in serialized
