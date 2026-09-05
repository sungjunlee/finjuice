"""Identity tests for the csv_transactions write/upsert split."""

from pathlib import Path

from finjuice.pipeline.storage import csv_transactions, csv_transactions_write

STORAGE_DIR = Path("src/finjuice/pipeline/storage")


def test_write_upsert_functions_live_in_write_module() -> None:
    """write_month/append/upsert should not live in the reader module."""
    transactions_text = (STORAGE_DIR / "csv_transactions.py").read_text(encoding="utf-8")
    write_text = (STORAGE_DIR / "csv_transactions_write.py").read_text(encoding="utf-8")

    assert "def read_month" in transactions_text
    assert "def read_range" in transactions_text
    assert "def find_transaction_by_hash" in transactions_text
    assert "def get_all_transactions" in transactions_text
    assert "def write_month" not in transactions_text
    assert "def append_transactions" not in transactions_text
    assert "def upsert_transaction" not in transactions_text
    assert "def write_month" in write_text
    assert "def append_transactions" in write_text
    assert "def upsert_transaction" in write_text
    assert "def read_month" not in write_text
    assert "def read_range" not in write_text
    assert "def find_transaction_by_hash" not in write_text
    assert "def get_all_transactions" not in write_text


def test_write_upsert_functions_reexport_from_csv_transactions() -> None:
    """Existing csv_transactions imports should keep resolving to the writers."""
    assert csv_transactions.write_month is csv_transactions_write.write_month
    assert csv_transactions.append_transactions is csv_transactions_write.append_transactions
    assert csv_transactions.upsert_transaction is csv_transactions_write.upsert_transaction
    assert callable(csv_transactions.write_month)
    assert callable(csv_transactions.append_transactions)
    assert callable(csv_transactions.upsert_transaction)
    assert callable(csv_transactions.read_month)
    assert "write_month" in csv_transactions.__all__
    assert "append_transactions" in csv_transactions.__all__
    assert "upsert_transaction" in csv_transactions.__all__
    assert "read_month" in csv_transactions.__all__
