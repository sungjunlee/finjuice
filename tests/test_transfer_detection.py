"""
Tests for transfer detection and pairing.

Tests cover:
- Basic transfer pair matching
- Time window enforcement
- Amount tolerance
- Currency matching
- Major category grouping
- Deterministic candidate selection
- CSV partition integration
- Idempotency
"""

from datetime import datetime
from pathlib import Path
from typing import Any, Dict

import polars as pl

from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.transfer.detection import (
    TransferCandidate,
    detect_transfer_pairs,
    run_transfer_detection,
)


class TestDetectTransferPairs:
    """Tests for detect_transfer_pairs() function."""

    def test_basic_pair(self) -> None:
        """Test basic transfer pair matching."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="내계좌이체",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="abc12345abcd1234",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="우리은행",
                counterparty="내계좌이체",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="def67890efgh5678",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 1
        # Deterministic group_id: T_{sorted_hash1[:8]}_{sorted_hash2[:8]}
        expected_id = "T_abc12345_def67890"
        assert expected_id in pairs
        assert sorted(pairs[expected_id]) == [1, 2]

    def test_opposite_signs_required(self) -> None:
        """Test that two outgoing transfers do NOT pair."""
        # Arrange - both negative amounts
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=-50000,
                account="우리은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 0

    def test_time_window_enforcement(self) -> None:
        """Test time window: within 5min pairs, >5min does not."""
        # Arrange
        candidates = [
            # Pair 1: 1 minute apart (should pair)
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-10000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_a1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=10000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_b2",
            ),
            # Pair 2: 6 minutes apart (should NOT pair)
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 15, 0),
                amount=-20000,
                account="C",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_c3",
            ),
            TransferCandidate(
                id=4,
                datetime=datetime(2025, 1, 15, 15, 7),
                amount=20000,
                account="D",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_d4",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates, time_window_minutes=5)

        # Assert
        assert len(pairs) == 1  # Only first pair matched
        group_id = list(pairs.keys())[0]
        assert pairs[group_id] == [1, 2]

    def test_amount_tolerance(self) -> None:
        """Test amount tolerance: 1% difference OK, 2% rejected."""
        # Arrange
        candidates = [
            # Pair 1: 1% difference (should pair)
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-100000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_a1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=100500,  # 0.5% difference
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_b2",
            ),
            # Pair 2: 2% difference (should NOT pair)
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 15, 0),
                amount=-100000,
                account="C",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_c3",
            ),
            TransferCandidate(
                id=4,
                datetime=datetime(2025, 1, 15, 15, 1),
                amount=102000,  # 2% difference
                account="D",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_d4",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates, amount_tolerance=0.01)

        # Assert
        assert len(pairs) == 1  # Only first pair matched
        group_id = list(pairs.keys())[0]
        assert pairs[group_id] == [1, 2]

    def test_currency_mismatch(self) -> None:
        """Test that different currencies do NOT pair."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-100,
                account="USD Account",
                counterparty="",
                major_category="외화이체",
                currency="USD",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=130000,  # Rough KRW equivalent
                account="원화계좌",
                counterparty="",
                major_category="외화이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 0

    def test_major_category_grouping(self) -> None:
        """Test that different major_category do NOT pair."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="우리은행",
                counterparty="",
                major_category="카드대금",  # Different category
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 0

    def test_deterministic_candidate_selection(self) -> None:
        """Test that the closest valid incoming candidate is selected."""
        # Arrange - one outgoing, two valid incoming transfers
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),  # First chronologically
                amount=50000,
                account="우리은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 14, 32),  # Second chronologically
                amount=50000,
                account="국민은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash3",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 1
        # Should pair with the closest valid match (id=2)
        group_id = list(pairs.keys())[0]
        assert pairs[group_id] == [1, 2]

    def test_no_match(self) -> None:
        """Test orphaned transfer returns no pairs."""
        # Arrange - single outgoing transfer
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 0

    def test_multiple_pairs_same_category(self) -> None:
        """Test multiple valid pairs in same category."""
        # Arrange
        candidates = [
            # Pair 1
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-10000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_a1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=10000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_b2",
            ),
            # Pair 2
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 15, 0),
                amount=-20000,
                account="C",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_c3",
            ),
            TransferCandidate(
                id=4,
                datetime=datetime(2025, 1, 15, 15, 1),
                amount=20000,
                account="D",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_d4",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 2
        # Check that both pairs exist with correct transaction IDs
        all_paired_ids = []
        for ids in pairs.values():
            all_paired_ids.extend(ids)
        assert sorted(all_paired_ids) == [1, 2, 3, 4]

    def test_empty_candidates(self) -> None:
        """Test empty candidates list."""
        # Arrange
        candidates: list[TransferCandidate] = []

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 0


class TestRunTransferDetection:
    """Integration tests for run_transfer_detection() with CSV partitions."""

    def test_integration_with_csv_storage(self, tmp_path: Path) -> None:
        """Test full integration with CSV partitions."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)

        # Create sample transfer transactions
        transfers: list[Dict[str, Any]] = [
            {
                "datetime": "2025-01-15T14:30:00",
                "date": "2025-01-15",
                "time": "14:30:00",
                "type_raw": "이체",
                "major_raw": "내계좌이체",
                "amount": -50000,
                "account": "신한카드",
                "merchant_raw": "우리은행으로이체",
                "currency": "KRW",
                "row_hash": "test_hash_1",
                "source_file_path": "test.xlsx",
                "source_row": 1,
            },
            {
                "datetime": "2025-01-15T14:31:00",
                "date": "2025-01-15",
                "time": "14:31:00",
                "type_raw": "이체",
                "major_raw": "내계좌이체",
                "amount": 50000,
                "account": "우리은행",
                "merchant_raw": "신한카드에서입금",
                "currency": "KRW",
                "row_hash": "test_hash_2",
                "source_file_path": "test.xlsx",
                "source_row": 2,
            },
            # Unpaired transfer
            {
                "datetime": "2025-01-16T10:00:00",
                "date": "2025-01-16",
                "time": "10:00:00",
                "type_raw": "이체",
                "major_raw": "내계좌이체",
                "amount": -30000,
                "account": "카카오뱅크",
                "merchant_raw": "이체",
                "currency": "KRW",
                "row_hash": "test_hash_3",
                "source_file_path": "test.xlsx",
                "source_row": 3,
            },
        ]

        df = pl.DataFrame(transfers)
        csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

        # Act
        result = run_transfer_detection(csv_base_dir)

        # Assert - summary counts
        assert result["candidates"] == 3
        assert result["pairs"] == 1
        assert result["paired"] == 2
        assert result["unpaired"] == 1

        # Verify CSV partition updates
        df_result = csv_partition.get_all_transactions(csv_base_dir)
        transfer_candidates = df_result.filter(pl.col("is_transfer_candidate") == 1).sort(
            "datetime"
        )
        transfer_txs = df_result.filter(pl.col("is_transfer") == 1).sort("datetime")

        # All 3 transfer-like rows are candidates, but only the confirmed pair is a transfer.
        assert len(transfer_candidates) == 3
        assert len(transfer_txs) == 2

        # Paired transfers share group_id
        row0 = transfer_txs.row(0, named=True)
        row1 = transfer_txs.row(1, named=True)
        assert row0["transfer_group_id"] == row1["transfer_group_id"]
        assert row0["transfer_group_id"].startswith("T")

        # Unpaired transfer-like rows remain candidates, not confirmed transfers.
        row2 = df_result.filter(pl.col("row_hash") == "test_hash_3").row(0, named=True)
        assert row2["is_transfer_candidate"] == 1
        assert row2["is_transfer"] == 0
        assert row2["transfer_group_id"] is None

    def test_idempotency(self, tmp_path: Path) -> None:
        """Test that running detection twice produces same results."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)

        # Create transfers
        transfers = [
            {
                "datetime": "2025-01-15T14:30:00",
                "date": "2025-01-15",
                "time": "14:30:00",
                "type_raw": "이체",
                "major_raw": "내계좌이체",
                "amount": -50000,
                "account": "신한카드",
                "merchant_raw": "이체",
                "currency": "KRW",
                "row_hash": "hash1",
                "source_file_path": "test.xlsx",
                "source_row": 0,
            },
            {
                "datetime": "2025-01-15T14:31:00",
                "date": "2025-01-15",
                "time": "14:31:00",
                "type_raw": "이체",
                "major_raw": "내계좌이체",
                "amount": 50000,
                "account": "우리은행",
                "merchant_raw": "이체",
                "currency": "KRW",
                "row_hash": "hash2",
                "source_file_path": "test.xlsx",
                "source_row": 1,
            },
        ]

        df = pl.DataFrame(transfers)
        csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

        # Act - run twice
        result1 = run_transfer_detection(csv_base_dir)
        result2 = run_transfer_detection(csv_base_dir)

        # Assert - results are identical
        assert result1 == result2

        # Verify group IDs didn't change
        df_result = csv_partition.get_all_transactions(csv_base_dir)
        paired = df_result.filter(pl.col("is_transfer") == 1).sort("datetime")
        group_ids = paired["transfer_group_id"].to_list()
        assert len(set(group_ids)) == 1  # Same group ID for both

    def test_empty_csv_partitions(self, tmp_path: Path) -> None:
        """Test with CSV partitions containing no transfers."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)

        # Insert non-transfer transaction
        transactions = [
            {
                "datetime": "2025-01-15T14:30:00",
                "date": "2025-01-15",
                "time": "14:30:00",
                "type_raw": "지출",
                "major_raw": "식비",
                "amount": -10000,
                "account": "신한카드",
                "merchant_raw": "스타벅스",
                "currency": "KRW",
                "row_hash": "hash1",
                "source_file_path": "test.xlsx",
                "source_row": 0,
            },
        ]

        df = pl.DataFrame(transactions)
        csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

        # Act
        result = run_transfer_detection(csv_base_dir)

        # Assert
        assert result["candidates"] == 0
        assert result["pairs"] == 0
        assert result["paired"] == 0
        assert result["unpaired"] == 0

    def test_non_transfer_rows_with_legacy_null_are_rewritten_to_zero(self, tmp_path: Path) -> None:
        """Legacy CSV rows with blank is_transfer should be normalized on detection."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        partition_dir = csv_base_dir / "2025" / "01"
        partition_dir.mkdir(parents=True, exist_ok=True)
        partition_path = partition_dir / "transactions.csv"

        legacy_df = pl.DataFrame(
            [
                {
                    "row_hash": "expense_hash",
                    "date": "2025-01-15",
                    "time": "09:00:00",
                    "datetime": "2025-01-15T09:00:00",
                    "type_raw": "지출",
                    "major_raw": "식비",
                    "merchant_raw": "스타벅스",
                    "amount": -4500,
                    "account": "신한카드",
                    "currency": "KRW",
                    "is_transfer": None,
                    "source_row": 0,
                },
                {
                    "row_hash": "transfer_out",
                    "date": "2025-01-15",
                    "time": "14:30:00",
                    "datetime": "2025-01-15T14:30:00",
                    "type_raw": "이체",
                    "major_raw": "내계좌이체",
                    "merchant_raw": "이체",
                    "amount": -50000,
                    "account": "신한카드",
                    "currency": "KRW",
                    "is_transfer": None,
                    "source_row": 1,
                },
                {
                    "row_hash": "transfer_in",
                    "date": "2025-01-15",
                    "time": "14:31:00",
                    "datetime": "2025-01-15T14:31:00",
                    "type_raw": "이체",
                    "major_raw": "내계좌이체",
                    "merchant_raw": "입금",
                    "amount": 50000,
                    "account": "우리은행",
                    "currency": "KRW",
                    "is_transfer": None,
                    "source_row": 2,
                },
            ]
        )
        legacy_df.write_csv(partition_path)

        # Act
        result = run_transfer_detection(csv_base_dir)

        # Assert
        assert result["pairs"] == 1
        assert result["paired"] == 2
        assert result["unpaired"] == 0

        df_result = csv_partition.get_all_transactions(csv_base_dir)
        by_hash = {row["row_hash"]: row for row in df_result.iter_rows(named=True)}
        assert by_hash["expense_hash"]["is_transfer"] == 0
        assert by_hash["expense_hash"]["is_transfer_candidate"] == 0
        assert by_hash["transfer_out"]["is_transfer"] == 1
        assert by_hash["transfer_out"]["is_transfer_candidate"] == 1
        assert by_hash["transfer_in"]["is_transfer"] == 1
        assert by_hash["transfer_in"]["is_transfer_candidate"] == 1

        stored_df = pl.read_csv(
            partition_path,
            schema_overrides={"is_transfer": pl.Int64, "is_transfer_candidate": pl.Int64},
            null_values=["", "NA", "NULL"],
        )
        assert stored_df["is_transfer"].null_count() == 0
        assert stored_df["is_transfer_candidate"].null_count() == 0


class TestTransferDetectionEdgeCases:
    """Additional edge case tests for transfer detection."""

    def test_time_window_boundary_exactly_5min(self) -> None:
        """Test edge case: exactly 5 minutes apart should pair."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 35),  # Exactly 5 minutes later
                amount=50000,
                account="우리은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates, time_window_minutes=5)

        # Assert - exactly 5 minutes should still pair (<=5)
        assert len(pairs) == 1
        group_id = list(pairs.keys())[0]
        assert pairs[group_id] == [1, 2]

    def test_time_window_boundary_over_5min(self) -> None:
        """Test edge case: just over 5 minutes should NOT pair."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30, 0),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 35, 1),  # 5min 1sec later
                amount=50000,
                account="우리은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates, time_window_minutes=5)

        # Assert - over 5 minutes should NOT pair
        assert len(pairs) == 0

    def test_amount_tolerance_boundary_exactly_1_percent(self) -> None:
        """Test edge case: exactly 1% difference should pair."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-100000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=101000,  # Exactly 1% higher
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates, amount_tolerance=0.01)

        # Assert - exactly 1% should pair (<=1%)
        assert len(pairs) == 1

    def test_same_account_can_pair(self) -> None:
        """Test that same account transfers CAN pair (algorithm doesn't check account equality)."""
        # Arrange - both transactions from same account
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",  # Same account
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="신한카드",  # Same account
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - same account transfers CAN pair (algorithm doesn't check account equality)
        assert len(pairs) == 1

    def test_multiple_candidates_different_amounts(self) -> None:
        """Test multiple outgoing with different amounts finds correct pair."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-10000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_a1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-20000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_b2",
            ),
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=20000,  # Matches id=2
                account="C",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_c3",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - only id=2 and id=3 should pair
        assert len(pairs) == 1
        group_id = list(pairs.keys())[0]
        assert pairs[group_id] == [2, 3]

    def test_custom_time_window(self) -> None:
        """Test with custom time window (10 minutes)."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 38),  # 8 minutes apart
                amount=50000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act - default 5min should NOT pair
        pairs_default = detect_transfer_pairs(candidates, time_window_minutes=5)
        # Act - 10min window should pair
        pairs_custom = detect_transfer_pairs(candidates, time_window_minutes=10)

        # Assert
        assert len(pairs_default) == 0
        assert len(pairs_custom) == 1

    def test_custom_amount_tolerance(self) -> None:
        """Test with custom amount tolerance (5%)."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-100000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash1",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=103000,  # 3% difference
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash2",
            ),
        ]

        # Act - default 1% should NOT pair
        pairs_default = detect_transfer_pairs(candidates, amount_tolerance=0.01)
        # Act - 5% tolerance should pair
        pairs_custom = detect_transfer_pairs(candidates, amount_tolerance=0.05)

        # Assert
        assert len(pairs_default) == 0
        assert len(pairs_custom) == 1


class TestRunTransferDetectionEmpty:
    """Tests for run_transfer_detection with empty/missing data."""

    def test_no_csv_partitions_exist(self, tmp_path: Path) -> None:
        """Test when CSV partition directory is empty."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        # No CSV files created

        # Act
        result = run_transfer_detection(csv_base_dir)

        # Assert
        assert result["candidates"] == 0
        assert result["pairs"] == 0
        assert result["paired"] == 0
        assert result["unpaired"] == 0

    def test_single_transfer_no_pair_available(self, tmp_path: Path) -> None:
        """Test handling of single transfer with no matching pair."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)

        # Create single transfer with valid datetime but no matching pair
        transfers = [
            {
                "datetime": "2025-01-15T14:30:00",
                "date": "2025-01-15",
                "time": "14:30:00",
                "type_raw": "이체",
                "major_raw": "내계좌이체",
                "amount": -50000,
                "account": "신한카드",
                "merchant_raw": "이체",
                "currency": "KRW",
                "row_hash": "hash1",
                "source_file_path": "test.xlsx",
                "source_row": 0,
            },
        ]

        df = pl.DataFrame(transfers)
        csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

        # Act - should not raise error
        result = run_transfer_detection(csv_base_dir)

        # Assert
        assert result["candidates"] == 1
        assert result["pairs"] == 0  # No pair available
        assert result["unpaired"] == 1

        df_result = csv_partition.get_all_transactions(csv_base_dir)
        row = df_result.row(0, named=True)
        assert row["is_transfer_candidate"] == 1
        assert row["is_transfer"] == 0
        assert row["transfer_group_id"] is None


class TestEmptyRowHashHandling:
    """Tests for empty row_hash edge cases (Issue #164 review feedback)."""

    def test_empty_row_hash_generates_fallback_id(self) -> None:
        """Test that empty row_hash generates fallback group_id instead of collision."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="",  # Empty hash
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="우리은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="",  # Empty hash
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 1
        group_id = list(pairs.keys())[0]
        # Should use fallback format, not "T__"
        assert group_id.startswith("T_NOHASH_")
        assert pairs[group_id] == [1, 2]

    def test_multiple_empty_hash_pairs_no_collision(self) -> None:
        """Test that multiple pairs with empty hashes get unique IDs."""
        # Arrange - two separate pairs with empty hashes
        candidates = [
            # Pair 1
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="",
            ),
            # Pair 2
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 14, 32),
                amount=-100000,
                account="C",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="",
            ),
            TransferCandidate(
                id=4,
                datetime=datetime(2025, 1, 15, 14, 33),
                amount=100000,
                account="D",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - both pairs should be detected with unique IDs
        assert len(pairs) == 2
        group_ids = list(pairs.keys())
        assert group_ids[0] != group_ids[1]  # Unique IDs
        assert all(gid.startswith("T_NOHASH_") for gid in group_ids)

    def test_partial_empty_hash_uses_fallback(self) -> None:
        """Test that if only one transaction has empty hash, fallback is used."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="abc12345def67890",  # Has hash
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="",  # Empty hash
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 1
        group_id = list(pairs.keys())[0]
        # Should use fallback since one hash is missing
        assert group_id.startswith("T_NOHASH_")

    def test_group_id_collision_handled(self) -> None:
        """Test that hash truncation collision is handled with suffix."""
        # Arrange - create candidates with same first 8 chars of hash
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="abcdefgh12345678",  # First 8: abcdefgh
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="ijklmnop87654321",  # First 8: ijklmnop
            ),
            # Second pair with SAME first 8 chars (collision scenario)
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 14, 32),
                amount=-100000,
                account="C",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="abcdefghAAAAAAAA",  # Same first 8: abcdefgh
            ),
            TransferCandidate(
                id=4,
                datetime=datetime(2025, 1, 15, 14, 33),
                amount=100000,
                account="D",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="ijklmnopBBBBBBBB",  # Same first 8: ijklmnop
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert - both pairs detected, no data loss
        assert len(pairs) == 2
        # All 4 transactions should be paired
        all_paired_ids = []
        for ids in pairs.values():
            all_paired_ids.extend(ids)
        assert sorted(all_paired_ids) == [1, 2, 3, 4]


class TestDeterministicOrdering:
    """Tests for deterministic ordering regardless of input order (Issue #164)."""

    def test_shuffled_input_produces_identical_group_ids(self) -> None:
        """Test that shuffled input produces identical group_ids."""
        # Arrange - same transactions, different order
        base_candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="abc12345def67890",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="우리은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="xyz98765uvw43210",
            ),
        ]
        shuffled = [base_candidates[1], base_candidates[0]]  # Reversed

        # Act
        pairs1 = detect_transfer_pairs(base_candidates)
        pairs2 = detect_transfer_pairs(shuffled)

        # Assert - group_ids must be identical
        assert list(pairs1.keys()) == list(pairs2.keys())
        # Transaction IDs should pair correctly in both cases
        assert sorted(pairs1[list(pairs1.keys())[0]]) == [1, 2]
        assert sorted(pairs2[list(pairs2.keys())[0]]) == [1, 2]

    def test_same_datetime_different_order(self) -> None:
        """Test determinism when multiple transactions have identical datetime."""
        # Arrange - all same datetime, should use row_hash for ordering
        candidates_order1 = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),  # Same datetime
                amount=-50000,
                account="A",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_a",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 30),  # Same datetime
                amount=50000,
                account="B",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="hash_b",
            ),
        ]
        # Shuffle order
        candidates_order2 = [candidates_order1[1], candidates_order1[0]]

        # Act
        pairs1 = detect_transfer_pairs(candidates_order1)
        pairs2 = detect_transfer_pairs(candidates_order2)

        # Assert - must be deterministic
        assert list(pairs1.keys()) == list(pairs2.keys())

    def test_incoming_first_bidirectional_match(self) -> None:
        """Incoming rows can appear before outgoing rows in Banksalad exports."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=50000,
                account="우리은행",
                counterparty="신한카드",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="incomingfirst0001",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=-50000,
                account="신한카드",
                counterparty="우리은행",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="outgoingfirst0002",
            ),
        ]

        # Act
        pairs = detect_transfer_pairs(candidates)

        # Assert
        assert len(pairs) == 1
        group_id = "T_incoming_outgoing"
        assert pairs[group_id] == [2, 1]

    def test_same_time_bidirectional_rows_pair_with_arbitrary_order(self) -> None:
        """Same-timestamp transfer rows should pair regardless of input sign order."""
        # Arrange
        candidates_order1 = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=50000,
                account="우리은행",
                counterparty="신한카드",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="same_time_in_0001",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="우리은행",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="same_time_out_0002",
            ),
        ]
        candidates_order2 = [candidates_order1[1], candidates_order1[0]]

        # Act
        pairs1 = detect_transfer_pairs(candidates_order1)
        pairs2 = detect_transfer_pairs(candidates_order2)

        # Assert
        assert pairs1 == pairs2
        assert len(pairs1) == 1
        assert list(pairs1.values()) == [[2, 1]]

    def test_shuffled_input_with_incoming_first_pair_is_stable(self) -> None:
        """Shuffling input rows should not change bidirectional transfer grouping."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 9, 58),
                amount=20000,
                account="우리은행",
                counterparty="카드",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="stable_pair_a_in",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 10, 0),
                amount=-20000,
                account="카드",
                counterparty="우리은행",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="stable_pair_a_out",
            ),
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 11, 0),
                amount=-30000,
                account="신한카드",
                counterparty="국민은행",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="stable_pair_b_out",
            ),
            TransferCandidate(
                id=4,
                datetime=datetime(2025, 1, 15, 11, 2),
                amount=30000,
                account="국민은행",
                counterparty="신한카드",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="stable_pair_b_in",
            ),
        ]
        shuffled = [candidates[3], candidates[1], candidates[0], candidates[2]]

        # Act
        pairs1 = detect_transfer_pairs(candidates)
        pairs2 = detect_transfer_pairs(shuffled)

        # Assert
        assert pairs1 == pairs2
        assert sorted(sorted(ids) for ids in pairs1.values()) == [[1, 2], [3, 4]]

    def test_bidirectional_multiple_candidate_tie_breaking_is_order_independent(self) -> None:
        """Equally close candidates use chronological span then row_hash as tie-breakers."""
        # Arrange
        candidates = [
            TransferCandidate(
                id=1,
                datetime=datetime(2025, 1, 15, 14, 30),
                amount=-50000,
                account="신한카드",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="multi_out",
            ),
            TransferCandidate(
                id=2,
                datetime=datetime(2025, 1, 15, 14, 29),
                amount=50000,
                account="우리은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="z_before_in",
            ),
            TransferCandidate(
                id=3,
                datetime=datetime(2025, 1, 15, 14, 31),
                amount=50000,
                account="국민은행",
                counterparty="",
                major_category="내계좌이체",
                currency="KRW",
                row_hash="a_after_in",
            ),
        ]
        shuffled = [candidates[2], candidates[0], candidates[1]]

        # Act
        pairs1 = detect_transfer_pairs(candidates)
        pairs2 = detect_transfer_pairs(shuffled)

        # Assert - the before-row wins the exact time-distance tie by earlier span.
        expected = {"T_multi_ou_z_before": [1, 2]}
        assert pairs1 == expected
        assert pairs2 == expected
