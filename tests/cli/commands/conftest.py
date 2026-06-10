"""
Shared fixtures for AI commands testing.

Provides:
- Mock Claude CLI subprocess calls
- Temporary data directories with CSV partitions
- Sample transaction DataFrames
- Mock Config objects
"""

from pathlib import Path
from unittest.mock import MagicMock

import polars as pl
import pytest


@pytest.fixture
def sample_transactions_df() -> pl.DataFrame:
    """
    Create a sample Polars DataFrame with realistic transaction data.

    Returns:
        DataFrame with columns: row_hash, date, time, type_norm, is_transfer,
        amount, merchant_raw, tags_final, account, currency
    """
    return pl.DataFrame(
        {
            "row_hash": [f"hash{i:03d}" for i in range(20)],
            "date": [
                "2024-10-15",
                "2024-10-16",
                "2024-10-17",
                "2024-10-18",
                "2024-10-19",
                "2024-11-01",
                "2024-11-02",
                "2024-11-03",
                "2024-11-04",
                "2024-11-05",
                "2024-11-10",
                "2024-11-11",
                "2024-11-12",
                "2024-11-15",
                "2024-11-16",
                "2024-11-20",
                "2024-11-21",
                "2024-11-22",
                "2024-11-25",
                "2024-11-26",
            ],
            "time": ["14:30"] * 20,
            "type_norm": ["expense"] * 18 + ["income", "transfer"],
            "is_transfer": [0] * 18 + [0, 1],
            "amount": [
                -50000,
                -30000,
                -80000,
                -25000,
                -45000,  # Oct: -230K
                -60000,
                -40000,
                -90000,
                -35000,
                -55000,  # Nov 1-5: -280K
                -45000,
                -35000,
                -65000,
                -50000,
                -40000,  # Nov 10-16: -235K
                -30000,
                -25000,
                -35000,
                150000,  # Income
                100000,  # Transfer
            ],
            "merchant_raw": [
                "스타벅스 강남점",
                "GS25 역삼점",
                "쿠팡",
                "이마트",
                "카카오택시",
                "투썸플레이스",
                "세븐일레븐",
                "네이버페이",
                "올리브영",
                "CGV 판교",
                "맥도날드",
                "다이소",
                "교보문고",
                "스타벅스 판교점",
                "이디야커피",
                "배달의민족",
                "쿠팡이츠",
                "카카오페이",
                "급여",
                "내계좌이체",
            ],
            "tags_final": [
                '["카페","커피"]',
                '["편의점"]',
                '["온라인쇼핑"]',
                "[]",  # Untagged
                '["교통","택시"]',
                '["카페","커피"]',
                '["편의점"]',
                '["온라인결제"]',
                "[]",  # Untagged
                '["문화","영화"]',
                '["식비","패스트푸드"]',
                '["생활용품"]',
                '["문화","서적"]',
                '["카페","커피"]',
                '["카페","커피"]',
                '["식비","배달"]',
                "[]",  # Untagged
                '["온라인결제"]',
                '["수입"]',
                '["이체"]',
            ],
            "account": ["신한카드"] * 20,
            "currency": ["KRW"] * 20,
        }
    )


@pytest.fixture
def mock_data_dir(tmp_path: Path, sample_transactions_df: pl.DataFrame) -> Path:
    """
    Create a temporary data directory with CSV partitions.

    Args:
        tmp_path: pytest temporary directory
        sample_transactions_df: Sample transactions to write

    Returns:
        Path to data directory with structure:
        data/
          transactions/
            2024/
              10/transactions.csv
              11/transactions.csv
    """
    data_dir = tmp_path / "data"
    transactions_dir = data_dir / "transactions"

    # Create directory structure
    oct_dir = transactions_dir / "2024" / "10"
    nov_dir = transactions_dir / "2024" / "11"
    oct_dir.mkdir(parents=True)
    nov_dir.mkdir(parents=True)

    # Split data by month
    oct_data = sample_transactions_df.filter(pl.col("date").str.starts_with("2024-10"))
    nov_data = sample_transactions_df.filter(pl.col("date").str.starts_with("2024-11"))

    # Write CSV files
    oct_data.write_csv(oct_dir / "transactions.csv")
    nov_data.write_csv(nov_dir / "transactions.csv")

    return data_dir


@pytest.fixture
def mock_claude_cli_success() -> MagicMock:
    """
    Mock successful Claude CLI subprocess call.

    Returns:
        MagicMock that simulates successful Claude execution
    """
    mock = MagicMock()
    mock.return_value = MagicMock(
        returncode=0,
        stdout="10월 카페 지출은 ₩135,000입니다.",
        stderr="",
    )
    return mock


@pytest.fixture
def mock_claude_cli_not_found() -> MagicMock:
    """
    Mock Claude CLI not found scenario.

    Returns:
        MagicMock that raises FileNotFoundError
    """
    mock = MagicMock()
    mock.side_effect = FileNotFoundError("claude command not found")
    return mock


@pytest.fixture
def mock_claude_cli_timeout() -> MagicMock:
    """
    Mock Claude CLI timeout scenario.

    Returns:
        MagicMock that raises TimeoutExpired
    """
    from subprocess import TimeoutExpired

    mock = MagicMock()
    mock.side_effect = TimeoutExpired("claude", 60)
    return mock


@pytest.fixture
def mock_claude_cli_failure() -> MagicMock:
    """
    Mock Claude CLI execution failure.

    Returns:
        MagicMock that returns non-zero exit code
    """
    mock = MagicMock()
    mock.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="Error: Claude API request failed",
    )
    return mock


@pytest.fixture
def mock_config(mock_data_dir: Path) -> MagicMock:
    """
    Mock Config object with test settings.

    Args:
        mock_data_dir: Path to mock data directory

    Returns:
        MagicMock Config object
    """
    mock = MagicMock()
    mock.data_dir = mock_data_dir
    mock.get_transactions_dir.return_value = mock_data_dir / "transactions"
    return mock


@pytest.fixture
def spending_spike_data() -> tuple[pl.DataFrame, pl.DataFrame]:
    """
    Create data showing spending spike (>50% MoM increase).

    Returns:
        Tuple of (previous_month_df, current_month_df)
        Previous: ₩100,000 total
        Current: ₩200,000 total (100% increase)
    """
    prev_month = pl.DataFrame(
        {
            "date": ["2024-10-" + str(i).zfill(2) for i in range(1, 6)],
            "amount": [-20000] * 5,  # Total: -100,000
            "type_norm": ["expense"] * 5,
            "is_transfer": [0] * 5,
            "merchant_raw": ["스타벅스"] * 5,
            "tags_final": ['["카페"]'] * 5,
        }
    )

    current_month = pl.DataFrame(
        {
            "date": ["2024-11-" + str(i).zfill(2) for i in range(1, 11)],
            "amount": [-20000] * 10,  # Total: -200,000 (100% increase)
            "type_norm": ["expense"] * 10,
            "is_transfer": [0] * 10,
            "merchant_raw": ["스타벅스"] * 10,
            "tags_final": ['["카페"]'] * 10,
        }
    )

    return prev_month, current_month


@pytest.fixture
def untagged_transactions_data() -> pl.DataFrame:
    """
    Create data with multiple untagged transactions.

    Returns:
        DataFrame with 8 untagged transactions
    """
    return pl.DataFrame(
        {
            "date": ["2024-11-" + str(i).zfill(2) for i in range(1, 9)],
            "amount": [-30000] * 8,
            "type_norm": ["expense"] * 8,
            "is_transfer": [0] * 8,
            "merchant_raw": ["미분류가맹점"] * 8,
            "tags_final": ["[]"] * 8,  # All untagged
        }
    )


@pytest.fixture
def new_merchant_data() -> tuple[pl.DataFrame, pl.DataFrame]:
    """
    Create data showing new merchant appearing in current month.

    Returns:
        Tuple of (previous_months_df, current_month_df)
    """
    previous_months = pl.DataFrame(
        {
            "date": ["2024-09-15", "2024-10-15"],
            "amount": [-50000, -50000],
            "type_norm": ["expense", "expense"],
            "is_transfer": [0, 0],
            "merchant_raw": ["스타벅스", "이디야"],
            "tags_final": ['["카페"]', '["카페"]'],
        }
    )

    current_month = pl.DataFrame(
        {
            "date": ["2024-11-01", "2024-11-02", "2024-11-03"],
            "amount": [-50000, -50000, -6000],  # New merchant: 투썸 (₩6K)
            "type_norm": ["expense", "expense", "expense"],
            "is_transfer": [0, 0, 0],
            "merchant_raw": ["스타벅스", "이디야", "투썸플레이스"],  # New!
            "tags_final": ['["카페"]', '["카페"]', '["카페"]'],
        }
    )

    return previous_months, current_month


@pytest.fixture
def high_value_transaction_data() -> pl.DataFrame:
    """
    Create data with high-value transaction (>₩500K).

    Returns:
        DataFrame with one ₩600K transaction
    """
    return pl.DataFrame(
        {
            "date": ["2024-11-01", "2024-11-02", "2024-11-15"],
            "amount": [-50000, -30000, -600000],  # High-value!
            "type_norm": ["expense", "expense", "expense"],
            "is_transfer": [0, 0, 0],
            "merchant_raw": ["스타벅스", "GS25", "서울종합병원"],
            "tags_final": ['["카페"]', '["편의점"]', '["의료"]'],
        }
    )
