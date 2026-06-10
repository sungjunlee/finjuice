import csv

import pytest

from finjuice.pipeline.analytics.duckdb_layer import DuckDBAnalytics


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory with dummy transaction data."""
    data_dir = tmp_path / "data"
    transactions_dir = data_dir / "transactions" / "2024" / "10"
    transactions_dir.mkdir(parents=True)

    csv_file = transactions_dir / "transactions.csv"

    # Create CSV with JSON strings and integer flags
    with open(csv_file, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "date",
                "time",
                "amount",
                "merchant_raw",
                "is_transfer",
                "transfer_group_id",
                "needs_review",
                "tags_final",
                "tags_rule",
                "tags_manual",
                "tags_ai",
            ]
        )
        writer.writerow(
            [
                "2024-10-01",
                "12:00",
                "-1000",
                "Cafe",
                "0",
                "",
                "0",
                '["coffee"]',
                '["coffee"]',
                "[]",
                "[]",
            ]
        )
        writer.writerow(
            [
                "2024-10-02",
                "13:00",
                "-5000",
                "Transfer",
                "1",
                "T1",
                "1",
                "[]",
                "[]",
                "[]",
                "[]",
            ]
        )

    return data_dir


def test_duckdb_type_normalization(temp_data_dir):
    """Test that DuckDB view normalizes types correctly."""
    analytics = DuckDBAnalytics(temp_data_dir)

    # Verify the types in the view
    result = analytics.conn.execute("DESCRIBE transactions").fetchall()
    schema = {row[0]: row[1] for row in result}

    # Check boolean normalization
    assert schema.get("is_transfer_bool") == "BOOLEAN"

    # Check list normalization
    type_tags_list = schema.get("tags_list")
    assert type_tags_list is not None
    assert "[]" in type_tags_list or "LIST" in type_tags_list, (
        f"Expected tags_list to be a list type, got {type_tags_list}"
    )

    # Verify data content
    rows = analytics.conn.execute(
        "SELECT is_transfer_bool, tags_list FROM transactions ORDER BY date"
    ).fetchall()

    assert rows[0][0] is False
    assert isinstance(rows[0][1], list), f"Expected list, got {type(rows[0][1])}"
    assert rows[0][1] == ["coffee"]

    assert rows[1][0] is True
    assert rows[1][1] == []
