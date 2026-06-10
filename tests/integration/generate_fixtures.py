"""Generate anonymized test fixtures from a private Banksalad sample.

This script creates test fixtures by:
1. Selecting representative transactions from the real sample
2. Anonymizing sensitive data (merchants, memos, accounts)
3. Creating both standard and alternative schema variants
4. Generating expected output golden files

Usage:
    uv run python tests/integration/generate_fixtures.py /path/to/private-export.xlsx
"""

import argparse
from pathlib import Path

import pandas as pd  # Required for Excel file reading/writing with multiple sheets

# Transfer pairing thresholds
TRANSFER_AMOUNT_TOLERANCE = 100  # KRW - maximum difference for opposite amounts
TRANSFER_TIME_WINDOW_SECONDS = 300  # 5 minutes - maximum time difference for pairing

# Anonymization mappings
MERCHANT_MAP = {
    # Insurance
    "INSURANCE_SAMPLE": "TEST_INSURANCE_A",
    # Restaurants/Food
    "FASTFOOD_SAMPLE_A": "TEST_FASTFOOD_A",
    "FASTFOOD_SAMPLE_B": "TEST_FASTFOOD_B",
    "GS25": "TEST_CONVENIENCE_A",
    "세븐일레븐": "TEST_CONVENIENCE_B",
    "CU": "TEST_CONVENIENCE_C",
    "스타벅스": "TEST_CAFE_A",
    "STARBUCKS": "TEST_CAFE_A",
    # Shopping
    "DEPT_STORE_SAMPLE_A": "TEST_DEPT_STORE_A",
    "DEPT_STORE_SAMPLE_B": "TEST_DEPT_STORE_B",
    # Healthcare
    "HOSPITAL_SAMPLE_A": "TEST_HOSPITAL_A",
    "HOSPITAL_SAMPLE_B": "TEST_HOSPITAL_B",
    # Transportation
    "TRANSPORT_SAMPLE_A": "TEST_TRANSPORT_A",
    "TRANSPORT_SAMPLE_B": "TEST_TRANSPORT_B",
    # Utilities
    "UTILITY_ELECTRIC_SAMPLE": "TEST_UTILITY_ELECTRIC",
    "UTILITY_INTERNET_SAMPLE": "TEST_UTILITY_INTERNET",
}

ACCOUNT_MAP = {
    "BANK_SAVINGS_SAMPLE": "TEST_BANK_SAVINGS",
    "BANK_CHECKING_SAMPLE": "TEST_BANK_CHECKING",
    "CARD_SAMPLE_A": "TEST_CARD_A",
    "CARD_SAMPLE_B": "TEST_CARD_B",
}


def anonymize_merchant(merchant: str) -> str:
    """Anonymize merchant name."""
    if pd.isna(merchant):
        return merchant

    # Check exact matches first
    for original, anonymized in MERCHANT_MAP.items():
        if original in str(merchant):
            return anonymized

    # Generic anonymization for unmatched
    merchant_str = str(merchant)
    if "GS" in merchant_str or "편의점" in merchant_str:
        return "TEST_CONVENIENCE_X"
    elif "카페" in merchant_str or "커피" in merchant_str:
        return "TEST_CAFE_X"
    elif "은행" in merchant_str or "BANK" in merchant_str.upper():
        return "TEST_BANK_X"
    else:
        return "TEST_MERCHANT_X"


def anonymize_account(account: str) -> str:
    """Anonymize account/card name."""
    if pd.isna(account):
        return account

    for original, anonymized in ACCOUNT_MAP.items():
        if original in str(account):
            return anonymized

    # Generic
    if "카드" in str(account):
        return "TEST_CARD_X"
    else:
        return "TEST_ACCOUNT_X"


def select_representative_transactions(df: pd.DataFrame, n: int = 30) -> pd.DataFrame:
    """Select a representative sample of transactions.

    Strategy:
    - Include transfer pairs (must keep both sides)
    - Mix of expense/income/transfer types
    - Various categories
    - Different merchants
    - Edge cases (missing memo, etc.)
    """

    # Get column names (handle encoding issues)
    cols = df.columns.tolist()
    date_col = cols[0]
    time_col = cols[1]
    type_col = cols[2]
    major_col = cols[3]
    amount_col = cols[6]
    memo_col = cols[9]

    selected = []

    # 1. Find and include transfer pairs (10 transactions = 5 pairs)
    transfers = df[df[type_col] == "이체"].copy()

    # Group by date and approximate amount to find pairs
    transfer_pairs = []
    used_indices = set()

    for idx, row in transfers.iterrows():
        if idx in used_indices:
            continue

        amount = row[amount_col]
        date = row[date_col]
        time = pd.to_datetime(row[time_col], format="%H:%M:%S", errors="coerce")

        # Look for opposite amount within 5 minutes
        for idx2, row2 in transfers.iterrows():
            if idx2 in used_indices or idx == idx2:
                continue

            amount2 = row2[amount_col]
            date2 = row2[date_col]
            time2 = pd.to_datetime(row2[time_col], format="%H:%M:%S", errors="coerce")

            # Check if pair: same date, opposite amount, within time window
            if (
                date == date2
                and abs(amount + amount2) < TRANSFER_AMOUNT_TOLERANCE
                and abs((time - time2).total_seconds()) <= TRANSFER_TIME_WINDOW_SECONDS
            ):
                transfer_pairs.append((idx, idx2))
                used_indices.add(idx)
                used_indices.add(idx2)
                break

        if len(transfer_pairs) >= 3:  # 3 pairs = 6 transactions
            break

    # Add transfer pairs
    for idx1, idx2 in transfer_pairs:
        selected.append(df.loc[idx1])  # type: ignore[call-overload]
        selected.append(df.loc[idx2])  # type: ignore[call-overload]

    # 2. Add regular expenses (15 transactions)
    expenses = df[df[type_col] == "지출"].copy()

    # Sample from different categories
    expense_sample = expenses.groupby(major_col).head(2).head(15)
    selected.extend([row for _, row in expense_sample.iterrows()])

    # 3. Add income transactions (3 transactions)
    income = df[df[type_col] == "입금"].copy()
    income_sample = income.head(3)
    selected.extend([row for _, row in income_sample.iterrows()])

    # 4. Add edge cases (6 transactions)
    # - Missing memo
    # - Very large amounts
    # - Very small amounts
    edge_cases = []

    # Missing memo
    missing_memo = df[df[memo_col].isna()].head(2)
    edge_cases.extend([row for _, row in missing_memo.iterrows()])

    # Large amount
    large = df[df[amount_col].abs() > 1000000].head(2)
    edge_cases.extend([row for _, row in large.iterrows()])

    # Small amount
    small = df[(df[amount_col].abs() < 5000) & (df[amount_col].abs() > 0)].head(2)
    edge_cases.extend([row for _, row in small.iterrows()])

    selected.extend(edge_cases)

    # Create DataFrame and sort by date/time
    result_df = pd.DataFrame(selected)
    result_df = result_df.sort_values([date_col, time_col])
    result_df = result_df.reset_index(drop=True)

    return result_df.head(n)


def anonymize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Anonymize all sensitive fields in the dataframe."""
    result = df.copy()

    cols = result.columns.tolist()
    date_col = cols[0]
    merchant_col = cols[5]
    account_col = cols[8]
    memo_col = cols[9]

    # Convert date to date-only format (remove time component)
    if pd.api.types.is_datetime64_any_dtype(result[date_col]):
        result[date_col] = result[date_col].dt.date

    # Anonymize merchants
    result[merchant_col] = result[merchant_col].apply(anonymize_merchant)

    # Anonymize accounts
    result[account_col] = result[account_col].apply(anonymize_account)

    # Remove memos (or genericize)
    result[memo_col] = None

    return result


def create_alt_schema_variant(df: pd.DataFrame) -> pd.DataFrame:
    """Create alternative schema with different column names and order."""
    result = df.copy()

    # Rename columns to English variant
    result.columns = [
        "date",
        "time",
        "type",
        "major_category",
        "minor_category",
        "merchant",
        "amount",
        "currency",
        "account",
        "memo",
    ]

    # Reorder columns
    new_order = [
        "date",
        "time",
        "amount",
        "currency",
        "type",
        "account",
        "merchant",
        "major_category",
        "minor_category",
        "memo",
    ]

    return result[new_order]


def main() -> None:
    """Generate all test fixtures."""
    parser = argparse.ArgumentParser(description="Generate anonymized Banksalad test fixtures.")
    parser.add_argument("source_file", type=Path, help="Private Banksalad XLSX export to sample.")
    args = parser.parse_args()
    print("=== Generating Test Fixtures ===\n")

    # Paths
    source_file = args.source_file
    fixtures_dir = Path("tests/fixtures")

    # Read source data
    print(f"Reading source data from {source_file}...")
    # Note: Banksalad exports use sheet 0 for summary, sheet 1 for transaction details
    df_source = pd.read_excel(source_file, sheet_name=1, header=0)
    print(f"  Total transactions: {len(df_source)}\n")

    # Select representative sample
    print("Selecting representative transactions...")
    df_sample = select_representative_transactions(df_source, n=30)
    print(f"  Selected: {len(df_sample)} transactions")
    print(f"  Types: {df_sample.iloc[:, 2].value_counts().to_dict()}\n")

    # Anonymize
    print("Anonymizing sensitive data...")
    df_anonymized = anonymize_dataframe(df_sample)
    print("  [OK] Merchants anonymized")
    print("  [OK] Accounts anonymized")
    print("  [OK] Memos cleared\n")

    # Save standard schema
    output_standard = fixtures_dir / "sample_banksalad.xlsx"
    print(f"Saving standard schema to {output_standard}...")

    # Create Excel writer with proper formatting
    with pd.ExcelWriter(output_standard, engine="openpyxl") as writer:
        df_anonymized.to_excel(writer, sheet_name="가계부 내역", index=False)
    print("  [OK] Saved\n")

    # Create and save alternative schema
    print("Creating alternative schema variant...")
    df_alt = create_alt_schema_variant(df_anonymized)
    output_alt = fixtures_dir / "sample_banksalad_alt_schema.xlsx"

    with pd.ExcelWriter(output_alt, engine="openpyxl") as writer:
        df_alt.to_excel(writer, sheet_name="Transactions", index=False)
    print(f"  [OK] Saved to {output_alt}\n")

    # Summary
    print("=== Fixture Generation Complete ===")
    print(f"Standard schema: {output_standard}")
    print(f"Alternative schema: {output_alt}")
    print("\nNext steps:")
    print("  1. Review generated fixtures")
    print("  2. Run integration tests")
    print("  3. Generate expected outputs (golden files)")


if __name__ == "__main__":
    main()
