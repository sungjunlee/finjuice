"""Identity tests for the csv_transactions write-serialization helper split."""

from pathlib import Path

from finjuice.pipeline.storage import csv_transactions, csv_transactions_serialize

STORAGE_DIR = Path("src/finjuice/pipeline/storage")


def test_write_serialization_helpers_live_in_helper_module() -> None:
    """Integer-flag and tag JSON serializers should not live in the CRUD module."""
    transactions_text = (STORAGE_DIR / "csv_transactions.py").read_text(encoding="utf-8")
    serialize_text = (STORAGE_DIR / "csv_transactions_serialize.py").read_text(encoding="utf-8")

    assert "def read_month" in transactions_text
    assert "def read_range" in transactions_text
    assert "def find_transaction_by_hash" in transactions_text
    assert "def get_all_transactions" in transactions_text
    assert "def _cast_int_flag_columns" not in transactions_text
    assert "def _serialize_list" not in transactions_text
    assert "def serialize_list" not in transactions_text
    assert "def _serialize_tag_columns" not in transactions_text
    assert "def _cast_int_flag_columns" in serialize_text
    assert "def _serialize_list" in serialize_text
    assert "def _serialize_tag_columns" in serialize_text


def test_write_serialization_helpers_reexport_from_csv_transactions() -> None:
    """Existing csv_transactions imports should keep resolving to the serializers."""
    assert (
        csv_transactions._cast_int_flag_columns is csv_transactions_serialize._cast_int_flag_columns
    )
    assert csv_transactions._serialize_list is csv_transactions_serialize._serialize_list
    assert (
        csv_transactions._serialize_tag_columns is csv_transactions_serialize._serialize_tag_columns
    )
    assert callable(csv_transactions.write_month)
    assert callable(csv_transactions.append_transactions)
    assert callable(csv_transactions.read_month)
    assert "write_month" in csv_transactions.__all__
    assert "append_transactions" in csv_transactions.__all__
    assert "read_month" in csv_transactions.__all__
