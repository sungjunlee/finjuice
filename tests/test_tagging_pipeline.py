"""
Integration tests for tagging pipeline.

Tests cover:
- CSV partition interactions (read/update)
- Tag list serialization
- Coverage calculation
- Batch processing
- Empty rules handling
- Integration with CSV storage
"""

from pathlib import Path

import polars as pl

from finjuice.pipeline.storage import csv_partition
from finjuice.pipeline.tagging.models import TagRule
from finjuice.pipeline.tagging.pipeline import run_tagging, tag_all_transactions


def create_sample_transactions(csv_base_dir: Path) -> None:
    """Create sample transactions in CSV partitions for testing."""
    transactions = [
        {
            "date": "2025-10-27",
            "time": "10:00:00",
            "type_raw": "지출",
            "merchant_raw": "METLIFE 보험",
            "memo_raw": "월 납입",
            "amount": -150000,
            "account": "신한카드",
            "currency": "KRW",
            "row_hash": "test_hash_metlife",
            "source_file_path": "test.xlsx",
            "source_row": 1,
            "tags_rule": [],
            "tags_final": [],
        },
        {
            "date": "2025-10-27",
            "time": "12:30:00",
            "type_raw": "지출",
            "merchant_raw": "스타벅스 강남점",
            "memo_raw": "아이스 아메리카노",
            "amount": -5500,
            "account": "신한카드",
            "currency": "KRW",
            "row_hash": "test_hash_starbucks",
            "source_file_path": "test.xlsx",
            "source_row": 2,
            "tags_rule": [],
            "tags_final": [],
        },
        {
            "date": "2025-10-27",
            "time": "14:00:00",
            "type_raw": "지출",
            "merchant_raw": "GS25 편의점",
            "memo_raw": "간식",
            "amount": -3000,
            "account": "신한카드",
            "currency": "KRW",
            "row_hash": "test_hash_gs25",
            "source_file_path": "test.xlsx",
            "source_row": 3,
            "tags_rule": [],
            "tags_final": [],
        },
        {
            "date": "2025-10-27",
            "time": "16:00:00",
            "type_raw": "지출",
            "merchant_raw": "Unknown Merchant",
            "memo_raw": "No matching rule",
            "amount": -10000,
            "account": "신한카드",
            "currency": "KRW",
            "row_hash": "test_hash_unknown",
            "source_file_path": "test.xlsx",
            "source_row": 4,
            "tags_rule": [],
            "tags_final": [],
        },
        {
            "date": "2025-10-27",
            "time": "18:00:00",
            "type_raw": "지출",
            "merchant_raw": "관리비 납부",
            "memo_raw": "아파트 관리비",
            "amount": -200000,
            "account": "국민은행",
            "currency": "KRW",
            "row_hash": "test_hash_apartment",
            "source_file_path": "test.xlsx",
            "source_row": 5,
            "tags_rule": [],
            "tags_final": [],
        },
    ]

    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)


class TestTagAllTransactions:
    """Tests for tag_all_transactions() function."""

    def test_tag_all_transactions_basic(self, tmp_path: Path):
        """Test basic tagging functionality."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        rules = [
            TagRule(
                name="insurance",
                match="METLIFE|메트라이프",
                fields=["merchant_raw", "memo_raw"],
                tags=["보험", "정기지출"],
                priority=95,
            ),
            TagRule(
                name="cafe",
                match="스타벅스|STARBUCKS",
                fields=["merchant_raw"],
                tags=["카페", "커피"],
                priority=80,
            ),
        ]

        # Act
        result = tag_all_transactions(csv_base_dir, rules)

        # Assert
        assert result["total"] == 5
        assert result["tagged"] == 2  # METLIFE and Starbucks
        assert result["untagged"] == 3
        assert result["coverage_pct"] == 40.0

        # Verify CSV partition updates
        df = csv_partition.get_all_transactions(csv_base_dir)
        metlife_row = df.filter(pl.col("merchant_raw") == "METLIFE 보험").row(0, named=True)

        # Tags are Python lists (not JSON strings)
        assert metlife_row["tags_rule"] == ["보험", "정기지출"]
        assert metlife_row["tags_final"] == ["보험", "정기지출"]

        # Verify needs_review is set correctly
        assert metlife_row["needs_review"] == 0  # tagged → no review needed
        untagged_row = df.filter(pl.col("merchant_raw") == "GS25 편의점").row(0, named=True)
        assert untagged_row["needs_review"] == 1  # untagged → needs review

    def test_tag_all_transactions_empty_rules(self, tmp_path: Path):
        """Test tagging with empty rules list."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        rules: list[TagRule] = []

        # Act
        result = tag_all_transactions(csv_base_dir, rules)

        # Assert
        assert result["total"] == 5
        assert result["tagged"] == 0
        assert result["untagged"] == 5
        assert result["coverage_pct"] == 0.0

        # Verify all transactions have empty tag arrays and need review
        df = csv_partition.get_all_transactions(csv_base_dir)
        for row in df.iter_rows(named=True):
            assert row["tags_rule"] == []
            assert row["needs_review"] == 1

    def test_tag_all_transactions_multiple_matches(self, tmp_path: Path):
        """Test transaction matching multiple rules."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        rules = [
            TagRule(
                name="convenience",
                match="GS25|CU|세븐일레븐",
                fields=["merchant_raw"],
                tags=["편의점", "소액지출"],
                priority=80,
            ),
            TagRule(
                name="snacks",
                match="간식|스낵",
                fields=["memo_raw"],
                tags=["간식"],
                priority=70,
            ),
        ]

        # Act
        result = tag_all_transactions(csv_base_dir, rules)

        # Assert
        assert result["total"] == 5
        assert result["tagged"] == 1  # Only GS25 matches both rules

        # Verify GS25 transaction has tags from both rules
        df = csv_partition.get_all_transactions(csv_base_dir)
        gs25_row = df.filter(pl.col("merchant_raw") == "GS25 편의점").row(0, named=True)
        tags = gs25_row["tags_rule"]
        assert "편의점" in tags
        assert "소액지출" in tags
        assert "간식" in tags
        assert len(tags) == 3

    def test_tag_all_transactions_korean_text_handling(self, tmp_path: Path):
        """Test proper handling of Korean text in tags."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        rules = [
            TagRule(
                name="apartment",
                match="관리비|아파트관리비",
                fields=["merchant_raw", "memo_raw"],
                tags=["공과금", "주거", "정기지출"],
                priority=90,
            ),
        ]

        # Act
        tag_all_transactions(csv_base_dir, rules)

        # Assert
        df = csv_partition.get_all_transactions(csv_base_dir)
        apartment_row = df.filter(pl.col("merchant_raw") == "관리비 납부").row(0, named=True)

        # Verify tags are correctly stored as Python list
        tags = apartment_row["tags_rule"]
        assert tags == ["공과금", "주거", "정기지출"]
        assert isinstance(tags, list)

    def test_tag_all_transactions_coverage_calculation(self, tmp_path: Path):
        """Test coverage percentage calculation."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        # Rules matching 3 out of 5 transactions
        rules = [
            TagRule(
                name="insurance",
                match="METLIFE",
                fields=["merchant_raw"],
                tags=["보험"],
                priority=95,
            ),
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페"],
                priority=80,
            ),
            TagRule(
                name="convenience",
                match="GS25",
                fields=["merchant_raw"],
                tags=["편의점"],
                priority=80,
            ),
        ]

        # Act
        result = tag_all_transactions(csv_base_dir, rules)

        # Assert
        assert result["total"] == 5
        assert result["tagged"] == 3
        assert result["untagged"] == 2
        assert result["coverage_pct"] == 60.0

    def test_tag_all_transactions_empty_partitions(self, tmp_path: Path):
        """Test tagging with empty CSV partitions."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        # Don't insert any transactions

        rules = [
            TagRule(
                name="test",
                match="TEST",
                fields=["merchant_raw"],
                tags=["test"],
                priority=50,
            ),
        ]

        # Act
        result = tag_all_transactions(csv_base_dir, rules)

        # Assert
        assert result["total"] == 0
        assert result["tagged"] == 0
        assert result["untagged"] == 0
        assert result["coverage_pct"] == 0.0


class TestRunTagging:
    """Tests for run_tagging() function."""

    def test_run_tagging_with_rules_file(self, tmp_path: Path):
        """Test run_tagging with actual rules file."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        # Use the sample rules fixture
        fixture_path = Path(__file__).parent / "fixtures" / "sample_rules.yaml"

        # Act
        result = run_tagging(csv_base_dir, fixture_path)

        # Assert
        assert result["total"] == 5
        # At least insurance, cafe, and convenience should match
        assert result["tagged"] >= 3
        assert result["coverage_pct"] >= 60.0

    def test_run_tagging_empty_rules_file(self, tmp_path: Path):
        """Test run_tagging with empty rules file."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        # Create empty rules file
        rules_file = tmp_path / "empty.yaml"
        rules_file.write_text("", encoding="utf-8")

        # Act
        result = run_tagging(csv_base_dir, rules_file)

        # Assert
        assert result["total"] == 0
        assert result["tagged"] == 0
        assert result["untagged"] == 0
        assert result["coverage_pct"] == 0.0

    def test_run_tagging_nonexistent_rules_file(self, tmp_path: Path):
        """Test run_tagging with non-existent rules file."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        # Non-existent rules file
        rules_file = tmp_path / "nonexistent.yaml"

        # Act
        result = run_tagging(csv_base_dir, rules_file)

        # Assert
        assert result["total"] == 0
        assert result["tagged"] == 0
        assert result["untagged"] == 0
        assert result["coverage_pct"] == 0.0

    def test_run_tagging_idempotency(self, tmp_path: Path):
        """Test that running tagging multiple times produces same result."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        fixture_path = Path(__file__).parent / "fixtures" / "sample_rules.yaml"

        # Act - Run tagging twice
        result1 = run_tagging(csv_base_dir, fixture_path)
        result2 = run_tagging(csv_base_dir, fixture_path)

        # Assert - Results should be identical
        assert result1 == result2

        # Verify tags didn't get duplicated
        df = csv_partition.get_all_transactions(csv_base_dir)
        metlife_row = df.filter(pl.col("merchant_raw") == "METLIFE 보험").row(0, named=True)
        tags = metlife_row["tags_rule"]
        # Should still have same tags, not duplicated
        assert tags.count("보험") == 1


class TestTagDryRun:
    """Tests for dry-run functionality."""

    def test_dry_run_does_not_modify_files(self, tmp_path: Path):
        """Test that dry_run=True does not write to CSV files."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        # Get original file content
        partition_file = csv_base_dir / "2025" / "10" / "transactions.csv"
        original_content = partition_file.read_text(encoding="utf-8")
        original_mtime = partition_file.stat().st_mtime

        rules = [
            TagRule(
                name="insurance",
                match="METLIFE|메트라이프",
                fields=["merchant_raw"],
                tags=["보험", "정기지출"],
                priority=95,
            ),
        ]

        # Act - Run with dry_run=True
        result = tag_all_transactions(csv_base_dir, rules, dry_run=True)

        # Assert - File should not be modified
        new_content = partition_file.read_text(encoding="utf-8")
        new_mtime = partition_file.stat().st_mtime

        assert original_content == new_content
        assert original_mtime == new_mtime
        assert result["total"] == 5
        assert result["tagged"] == 1

    def test_dry_run_returns_changes(self, tmp_path: Path):
        """Test that dry_run returns list of changed transactions."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        rules = [
            TagRule(
                name="insurance",
                match="METLIFE|메트라이프",
                fields=["merchant_raw"],
                tags=["보험", "정기지출"],
                priority=95,
            ),
            TagRule(
                name="cafe",
                match="스타벅스|STARBUCKS",
                fields=["merchant_raw"],
                tags=["카페", "커피"],
                priority=80,
            ),
        ]

        # Act
        result = tag_all_transactions(csv_base_dir, rules, dry_run=True)

        # Assert
        assert "changes" in result
        assert "previously_tagged" in result
        assert result["previously_tagged"] == 0  # All were untagged initially
        assert len(result["changes"]) == 2  # Two transactions will get new tags

        # Verify change structure
        for change in result["changes"]:
            assert "date" in change
            assert "merchant_raw" in change
            assert "current_tags" in change
            assert "new_tags" in change
            assert change["current_tags"] == []  # Originally untagged
            assert len(change["new_tags"]) > 0  # Now has tags

    def test_dry_run_changes_limited_to_50(self, tmp_path: Path):
        """Test that changes list is limited to 50 entries for performance."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)

        # Create 100 transactions that will all match
        transactions = []
        for i in range(100):
            transactions.append(
                {
                    "date": "2025-10-27",
                    "time": f"{i % 24:02d}:00:00",
                    "type_raw": "지출",
                    "merchant_raw": f"스타벅스 매장{i}",
                    "memo_raw": "",
                    "amount": -5500,
                    "account": "신한카드",
                    "currency": "KRW",
                    "row_hash": f"test_hash_{i}",
                    "source_file_path": "test.xlsx",
                    "source_row": i + 1,
                    "tags_rule": [],
                    "tags_final": [],
                }
            )

        df = pl.DataFrame(transactions)
        csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

        rules = [
            TagRule(
                name="cafe",
                match="스타벅스",
                fields=["merchant_raw"],
                tags=["카페"],
                priority=80,
            ),
        ]

        # Act
        result = tag_all_transactions(csv_base_dir, rules, dry_run=True)

        # Assert
        assert result["total"] == 100
        assert result["tagged"] == 100
        assert len(result["changes"]) == 50  # Limited to 50

    def test_dry_run_tracks_previously_tagged(self, tmp_path: Path):
        """Test that dry_run correctly counts previously tagged transactions."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)

        # Create transactions with some already tagged
        transactions = [
            {
                "date": "2025-10-27",
                "time": "10:00:00",
                "type_raw": "지출",
                "merchant_raw": "스타벅스",
                "memo_raw": "",
                "amount": -5500,
                "account": "신한카드",
                "currency": "KRW",
                "row_hash": "hash1",
                "source_file_path": "test.xlsx",
                "source_row": 1,
                "tags_rule": ["기존태그"],
                "tags_final": ["기존태그"],
            },
            {
                "date": "2025-10-27",
                "time": "12:00:00",
                "type_raw": "지출",
                "merchant_raw": "투썸플레이스",
                "memo_raw": "",
                "amount": -6000,
                "account": "신한카드",
                "currency": "KRW",
                "row_hash": "hash2",
                "source_file_path": "test.xlsx",
                "source_row": 2,
                "tags_rule": [],
                "tags_final": [],
            },
        ]

        df = pl.DataFrame(transactions)
        csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

        rules = [
            TagRule(
                name="cafe",
                match="스타벅스|투썸",
                fields=["merchant_raw"],
                tags=["카페"],
                priority=80,
            ),
        ]

        # Act
        result = tag_all_transactions(csv_base_dir, rules, dry_run=True)

        # Assert
        assert result["previously_tagged"] == 1  # Only first one was tagged
        assert result["tagged"] == 2  # Both will be tagged after

    def test_run_tagging_dry_run(self, tmp_path: Path):
        """Test run_tagging with dry_run parameter."""
        # Arrange
        csv_base_dir = tmp_path / "transactions"
        csv_base_dir.mkdir(parents=True, exist_ok=True)
        create_sample_transactions(csv_base_dir)

        fixture_path = Path(__file__).parent / "fixtures" / "sample_rules.yaml"

        # Get original content
        partition_file = csv_base_dir / "2025" / "10" / "transactions.csv"
        original_content = partition_file.read_text(encoding="utf-8")

        # Act
        result = run_tagging(csv_base_dir, fixture_path, dry_run=True)

        # Assert
        assert "changes" in result
        assert "previously_tagged" in result
        # File should not be modified
        assert partition_file.read_text(encoding="utf-8") == original_content
