"""Identity tests for the csv_transactions read-normalization helper split."""

from pathlib import Path

from finjuice.pipeline.storage import csv_transactions, csv_transactions_read_normalize

STORAGE_DIR = Path("src/finjuice/pipeline/storage")


def test_read_normalization_helpers_live_in_helper_module() -> None:
    """Datetime/projection/tag-decode/empty-schema helpers should not live in the CRUD module."""
    transactions_text = (STORAGE_DIR / "csv_transactions.py").read_text(encoding="utf-8")
    normalize_text = (STORAGE_DIR / "csv_transactions_read_normalize.py").read_text(
        encoding="utf-8"
    )

    assert "def read_month" in transactions_text
    assert "def read_range" in transactions_text
    assert "def find_transaction_by_hash" in transactions_text
    assert "def get_all_transactions" in transactions_text
    for name in (
        "_empty_transactions_df",
        "_normalize_datetime_column",
        "_project_existing_columns",
        "_decode_tag_columns",
    ):
        assert f"def {name}" not in transactions_text
        assert f"def {name}" in normalize_text
    assert "TAG_JSON_COLUMNS" in normalize_text


def test_read_normalization_helpers_reexport_from_csv_transactions() -> None:
    """Existing csv_transactions imports should keep resolving to the read normalizers."""
    assert (
        csv_transactions._empty_transactions_df
        is csv_transactions_read_normalize._empty_transactions_df
    )
    assert (
        csv_transactions._normalize_datetime_column
        is csv_transactions_read_normalize._normalize_datetime_column
    )
    assert (
        csv_transactions._project_existing_columns
        is csv_transactions_read_normalize._project_existing_columns
    )
    assert (
        csv_transactions._decode_tag_columns is csv_transactions_read_normalize._decode_tag_columns
    )
    assert csv_transactions.TAG_JSON_COLUMNS is csv_transactions_read_normalize.TAG_JSON_COLUMNS
    assert callable(csv_transactions.read_month)
    assert callable(csv_transactions.read_range)
    assert callable(csv_transactions.get_all_transactions)
    assert "read_month" in csv_transactions.__all__
    assert "read_range" in csv_transactions.__all__
    assert "get_all_transactions" in csv_transactions.__all__
