"""
Generate test fixtures for error handling tests.

This script creates malformed XLSX and YAML files to test error handling.
"""

from pathlib import Path

import pandas as pd  # Required for Excel file creation with multiple sheets

fixtures_dir = Path(__file__).parent


def write_banksalad_xlsx(df: pd.DataFrame, file_path: Path) -> None:
    """Write DataFrame to XLSX in Banksalad format (2 sheets).

    Banksalad exports have 2 sheets:
    - Sheet 0 ("요약"): Summary data
    - Sheet 1 ("가계부 내역"): Transaction details

    The ingest pipeline expects transaction data in sheet 1 (index 1).
    """
    summary_df = pd.DataFrame({"요약": ["테스트 데이터"]})
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="요약", index=False)
        df.to_excel(writer, sheet_name="가계부 내역", index=False)


def create_missing_date_column():
    """XLSX missing required 'date' column."""
    df = pd.DataFrame(
        {
            "시간": ["14:30", "15:45"],
            "타입": ["지출", "수입"],
            "내용": ["테스트", "테스트2"],
            "금액": [-10000, 50000],
            "결제수단": ["신한카드", "우리은행"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "missing_date.xlsx")


def create_missing_time_column():
    """XLSX missing 'time' column (should be handled gracefully)."""
    df = pd.DataFrame(
        {
            "날짜": ["2025-01-15", "2025-01-16"],
            "타입": ["지출", "수입"],
            "내용": ["테스트", "테스트2"],
            "금액": [-10000, 50000],
            "결제수단": ["신한카드", "우리은행"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "missing_time.xlsx")


def create_missing_amount_column():
    """XLSX missing required 'amount' column."""
    df = pd.DataFrame(
        {
            "날짜": ["2025-01-15", "2025-01-16"],
            "시간": ["14:30", "15:45"],
            "타입": ["지출", "수입"],
            "내용": ["테스트", "테스트2"],
            "결제수단": ["신한카드", "우리은행"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "missing_amount.xlsx")


def create_missing_account_column():
    """XLSX missing required 'account' column."""
    df = pd.DataFrame(
        {
            "날짜": ["2025-01-15", "2025-01-16"],
            "시간": ["14:30", "15:45"],
            "타입": ["지출", "수입"],
            "내용": ["테스트", "테스트2"],
            "금액": [-10000, 50000],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "missing_account.xlsx")


def create_empty_xlsx():
    """Empty XLSX file (headers only, no data rows)."""
    df = pd.DataFrame(columns=["날짜", "시간", "타입", "내용", "금액", "결제수단"])
    write_banksalad_xlsx(df, fixtures_dir / "empty.xlsx")


def create_malformed_date():
    """XLSX with invalid date formats."""
    df = pd.DataFrame(
        {
            "날짜": ["invalid-date", "2025/01/16", "2025-01-17"],
            "시간": ["14:30", "15:45", "16:00"],
            "타입": ["지출", "수입", "지출"],
            "내용": ["테스트", "테스트2", "테스트3"],
            "금액": [-10000, 50000, -20000],
            "결제수단": ["신한카드", "우리은행", "신한카드"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "malformed_date.xlsx")


def create_malformed_time():
    """XLSX with invalid time formats."""
    df = pd.DataFrame(
        {
            "날짜": ["2025-01-15", "2025-01-16", "2025-01-17"],
            "시간": ["25:30", "15:99", "16:00"],  # Invalid times
            "타입": ["지출", "수입", "지출"],
            "내용": ["테스트", "테스트2", "테스트3"],
            "금액": [-10000, 50000, -20000],
            "결제수단": ["신한카드", "우리은행", "신한카드"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "malformed_time.xlsx")


def create_non_numeric_amount():
    """XLSX with non-numeric amounts."""
    df = pd.DataFrame(
        {
            "날짜": ["2025-01-15", "2025-01-16"],
            "시간": ["14:30", "15:45"],
            "타입": ["지출", "수입"],
            "내용": ["테스트", "테스트2"],
            "금액": ["not-a-number", 50000],
            "화폐": ["KRW", "KRW"],
            "결제수단": ["신한카드", "우리은행"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "non_numeric_amount.xlsx")


def create_type_sign_mismatch():
    """XLSX with type/amount sign mismatches (should trigger warnings)."""
    df = pd.DataFrame(
        {
            "날짜": ["2025-01-15", "2025-01-16"],
            "시간": ["14:30", "15:45"],
            "타입": ["지출", "수입"],  # Expense and income
            "내용": ["테스트", "테스트2"],
            "금액": [10000, -50000],  # WRONG: positive expense, negative income
            "화폐": ["KRW", "KRW"],
            "결제수단": ["신한카드", "우리은행"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "type_sign_mismatch.xlsx")


def create_unknown_schema():
    """XLSX with completely different column names."""
    df = pd.DataFrame(
        {
            "col1": ["2025-01-15", "2025-01-16"],
            "col2": ["14:30", "15:45"],
            "col3": ["지출", "수입"],
            "col4": ["테스트", "테스트2"],
            "col5": [-10000, 50000],
            "col6": ["신한카드", "우리은행"],
        }
    )
    write_banksalad_xlsx(df, fixtures_dir / "unknown_schema.xlsx")


def create_corrupted_xlsx():
    """Binary corrupted XLSX file."""
    with open(fixtures_dir / "corrupted.xlsx", "wb") as f:
        # Write invalid binary data that's not a valid XLSX
        f.write(b"CORRUPT\x00\xff\xfe\xdeADBEEF" * 100)


def main():
    """Generate all test fixtures."""
    print("Generating error test fixtures...")

    create_missing_date_column()
    print("[OK] missing_date.xlsx")

    create_missing_time_column()
    print("[OK] missing_time.xlsx")

    create_missing_amount_column()
    print("[OK] missing_amount.xlsx")

    create_missing_account_column()
    print("[OK] missing_account.xlsx")

    create_empty_xlsx()
    print("[OK] empty.xlsx")

    create_malformed_date()
    print("[OK] malformed_date.xlsx")

    create_malformed_time()
    print("[OK] malformed_time.xlsx")

    create_non_numeric_amount()
    print("[OK] non_numeric_amount.xlsx")

    create_type_sign_mismatch()
    print("[OK] type_sign_mismatch.xlsx")

    create_unknown_schema()
    print("[OK] unknown_schema.xlsx")

    create_corrupted_xlsx()
    print("[OK] corrupted.xlsx")

    print("\nAll fixtures generated successfully!")


if __name__ == "__main__":
    main()
