"""Shared pytest fixtures for all test modules.

This module provides reusable fixtures for:
- Directory creation (temporary import/export directories)
- File fixtures (sample XLSX files, rules files)
- Data fixtures (sample transactions, transfer pairs)
"""

import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Generator

import polars as pl
import pytest
import typer.rich_utils
from rich.console import Console

# Force the test run to import this checkout's src-layout package first.
ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

_TERMINAL_ENV_KEYS = ("COLUMNS", "NO_COLOR", "TERM", "FORCE_COLOR")
_ORIGINAL_TERMINAL_ENV = {key: os.environ.get(key) for key in _TERMINAL_ENV_KEYS}


def _apply_deterministic_terminal_env() -> None:
    """Pin terminal settings before CLI modules import their Rich consoles."""
    os.environ["COLUMNS"] = "120"
    os.environ["NO_COLOR"] = "1"
    os.environ["TERM"] = "dumb"
    # CI may set this; clear for deterministic Rich/Typer help rendering.
    os.environ.pop("FORCE_COLOR", None)


_apply_deterministic_terminal_env()


def cli_text(result: Any) -> str:
    """Return mixed CLI output for assertions."""
    return result.output


def _build_json_output_transactions() -> pl.DataFrame:
    """Create complete transaction rows for shared JSON output fixtures."""
    return pl.DataFrame(
        {
            "row_hash": ["row1", "row2", "row3", "row4"],
            "date": ["2024-10-01", "2024-10-05", "2024-11-10", "2024-11-20"],
            "time": ["09:00", "10:00", "11:00", "12:00"],
            "type_raw": ["지출", "지출", "지출", "수입"],
            "type_norm": ["expense", "expense", "expense", "income"],
            "major_raw": ["식비", "구독", "쇼핑", "급여"],
            "minor_raw": ["카페", "스트리밍", "온라인", "월급"],
            "merchant_raw": ["Starbucks Gangnam", "Netflix", "Coupang", "Acme Corp"],
            "memo_raw": ["Latte", "Monthly plan", "Order #123", "Salary"],
            "notes_manual": ["", "", "", ""],
            "amount": [-5000.0, -17000.0, -30000.0, 2000000.0],
            "account": ["신한카드", "신한카드", "신한카드", "우리은행"],
            "currency": ["KRW", "KRW", "KRW", "KRW"],
            "counterparty": ["", "", "", ""],
            "datetime": [
                "2024-10-01T09:00:00",
                "2024-10-05T10:00:00",
                "2024-11-10T11:00:00",
                "2024-11-20T12:00:00",
            ],
            "category_rule": ["카페", "구독", "쇼핑", ""],
            "category_final": ["카페", "구독", "쇼핑", "급여"],
            "tags_rule": ['["카페"]', '["구독"]', '["쇼핑"]', "[]"],
            "tags_ai": ["[]", "[]", "[]", "[]"],
            "tags_manual": ["[]", "[]", "[]", "[]"],
            "tags_final": ['["카페"]', "[]", '["쇼핑"]', '["급여"]'],
            "confidence": [0.95, 0.8, 0.9, 1.0],
            "needs_review": [0, 1, 0, 0],
            "is_transfer_candidate": [0, 0, 0, 0],
            "is_transfer": [0, 0, 0, 0],
            "transfer_group_id": ["", "", "", ""],
            "file_id": ["241001_1", "241005_1", "241110_1", "241120_1"],
            "source_row": [1, 2, 3, 4],
        }
    )


@pytest.fixture
def json_output_data_dir(tmp_path: Path) -> Path:
    """Create a data directory with enough structure for JSON contract tests."""
    data_dir = tmp_path / "data"
    imports_dir = data_dir / "imports"
    oct_dir = data_dir / "transactions" / "2024" / "10"
    nov_dir = data_dir / "transactions" / "2024" / "11"
    metadata_dir = data_dir / "metadata"
    reports_dir = data_dir / "exports" / "reports"
    assets_dir = data_dir / "assets" / "snapshots" / "2026" / "03"

    imports_dir.mkdir(parents=True)
    oct_dir.mkdir(parents=True)
    nov_dir.mkdir(parents=True)
    metadata_dir.mkdir(parents=True)
    reports_dir.mkdir(parents=True)
    assets_dir.mkdir(parents=True)

    transactions = _build_json_output_transactions()
    transactions.filter(pl.col("date").str.starts_with("2024-10")).write_csv(
        oct_dir / "transactions.csv"
    )
    transactions.filter(pl.col("date").str.starts_with("2024-11")).write_csv(
        nov_dir / "transactions.csv"
    )

    rules_yaml = """
version: 1
rules:
  - name: coffee
    match: "Starbucks"
    fields: ["merchant_raw"]
    tags: ["카페"]
    priority: 90
    category: "카페"
  - name: streaming
    match: "Netflix"
    fields: ["merchant_raw"]
    tags: ["구독"]
    priority: 80
    category: "구독"
"""
    (data_dir / "rules.yaml").write_text(rules_yaml.strip() + "\n", encoding="utf-8")

    import_history = pl.DataFrame(
        {
            "file_id": ["241120_1", "241001_1"],
            "original_filename": ["banksalad_202411.xlsx", "banksalad_202410.xlsx"],
            "imported_from": ["/tmp/banksalad_202411.xlsx", "/tmp/banksalad_202410.xlsx"],
            "archived": ["yes", "no"],
            "archived_path": ["/tmp/archive/banksalad_202411.xlsx", None],
            "imported_at": ["2024-11-20T12:30:00", "2024-10-01T09:30:00"],
            "source_rows": [2, 2],
        }
    )
    import_history.write_csv(metadata_dir / "import_history.csv")

    (reports_dir / "monthly.md").write_text("# Monthly Report\n", encoding="utf-8")
    (reports_dir / "tags.csv").write_text("tag,total\n카페,5000\n", encoding="utf-8")
    pl.DataFrame(
        {
            "snapshot_date": ["2026-03-15", "2026-03-15"],
            "account_id": ["증권계좌", "미래에셋"],
            "instrument_id": ["AAPL", "SPY"],
            "quantity": [10.0, 20.0],
            "market_value": [2500000.0, 5000000.0],
            "currency": ["KRW", "KRW"],
            "file_id": ["260315_1", "260315_1"],
            "source_row": [1, 2],
        }
    ).write_csv(assets_dir / "snapshots.csv")

    return data_dir


@pytest.fixture(autouse=True, scope="session")
def _pin_terminal_width() -> Generator[None, None, None]:
    """Pin COLUMNS + disable ANSI colors for deterministic Rich/Typer help rendering.

    Two independent environment pins:
    - COLUMNS=120: stabilize help panel width across macOS/Linux
    - NO_COLOR=1, TERM=dumb: disable Rich's ANSI styling so substring assertions
      against --flag names don't break on intra-token color codes in CI. See #416.
    """
    original_console = None
    original_rich_settings = (
        typer.rich_utils.COLOR_SYSTEM,
        typer.rich_utils.FORCE_TERMINAL,
        typer.rich_utils.MAX_WIDTH,
    )
    _apply_deterministic_terminal_env()

    if "finjuice.pipeline.cli.output" in sys.modules:
        import finjuice.pipeline.cli.output as cli_output

        original_console = cli_output.console
        cli_output.console = Console(
            stderr=True,
            no_color=True,
            color_system=None,
            force_terminal=False,
            width=120,
        )

    typer.rich_utils.COLOR_SYSTEM = None
    typer.rich_utils.FORCE_TERMINAL = False
    typer.rich_utils.MAX_WIDTH = 120
    yield

    if original_console is not None:
        import finjuice.pipeline.cli.output as cli_output

        cli_output.console = original_console

    (
        typer.rich_utils.COLOR_SYSTEM,
        typer.rich_utils.FORCE_TERMINAL,
        typer.rich_utils.MAX_WIDTH,
    ) = original_rich_settings

    for key, value in _ORIGINAL_TERMINAL_ENV.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


# ============================================================================
# Directory Fixtures
# ============================================================================


@pytest.fixture
def temp_csv_base_dir(tmp_path: Path) -> Path:
    """Create a temporary CSV partitions directory.

    Returns:
        Path: Path to temporary CSV partitions directory (e.g., data/transactions/)
    """
    csv_dir = tmp_path / "transactions"
    csv_dir.mkdir(parents=True, exist_ok=True)
    return csv_dir


@pytest.fixture
def temp_import_dir(tmp_path: Path) -> Path:
    """Create a temporary import directory for XLSX files.

    Returns:
        Path: Path to temporary import directory
    """
    import_dir = tmp_path / "imports"
    import_dir.mkdir(parents=True, exist_ok=True)
    return import_dir


@pytest.fixture
def temp_export_dir(tmp_path: Path) -> Path:
    """Create a temporary export directory for output files.

    Returns:
        Path: Path to temporary export directory
    """
    export_dir = tmp_path / "exports"
    export_dir.mkdir(parents=True, exist_ok=True)
    return export_dir


@pytest.fixture
def temp_finance_dir(tmp_path: Path) -> Path:
    """Create a temporary finance directory (root data directory).

    Returns:
        Path: Path to temporary finance directory
    """
    return tmp_path / "finance"


@pytest.fixture
def temp_data_dir(tmp_path: Path) -> Dict[str, Path]:
    """Create a complete temporary data directory structure.

    Creates the full directory tree:
    - data/
      - transactions/  (CSV partitions)
      - imports/
      - exports/
        - reports/
      - config/

    Returns:
        Dict[str, Path]: Dictionary with paths to all directories:
            - root: Main data directory
            - csv_base_dir: CSV partitions directory
            - imports: Import directory
            - exports: Export directory
            - reports: Reports subdirectory
            - config: Config directory
    """
    data_dir = tmp_path / "data"
    csv_base_dir = data_dir / "transactions"
    imports_dir = data_dir / "imports"
    exports_dir = data_dir / "exports"
    reports_dir = exports_dir / "reports"
    config_dir = data_dir / "config"

    for directory in [csv_base_dir, imports_dir, exports_dir, reports_dir, config_dir]:
        directory.mkdir(parents=True, exist_ok=True)

    return {
        "root": data_dir,
        "csv_base_dir": csv_base_dir,
        "imports": imports_dir,
        "exports": exports_dir,
        "reports": reports_dir,
        "config": config_dir,
    }


# ============================================================================
# File Fixtures
# ============================================================================


@pytest.fixture
def sample_xlsx_file(temp_import_dir: Path) -> Path:
    """Create a sample XLSX file with test transaction data.

    Contains 3 transactions with various types (expense, income, expense).

    Args:
        temp_import_dir: Temporary import directory fixture

    Returns:
        Path: Path to created XLSX file
    """
    df = pl.DataFrame(
        {
            "날짜": ["2025-10-27", "2025-10-28", "2025-10-29"],
            "시간": ["19:24", "08:30", "12:45"],
            "타입": ["지출", "수입", "지출"],
            "대분류": ["식비", "급여", "교통"],
            "중분류": ["카페", "월급", "지하철"],
            "내용": ["스타벅스", "회사", "교통카드"],
            "메모": ["회의", "", "출퇴근"],
            "금액": [-5000, 3000000, -1500],
            "화폐": ["KRW", "KRW", "KRW"],
            "결제수단": ["체크카드", "은행계좌", "교통카드"],
        }
    )

    file_path = temp_import_dir / "test_data.xlsx"
    df.write_excel(file_path)
    return file_path


@pytest.fixture
def sample_rules_file(tmp_path: Path) -> Path:
    """Get path to sample rules.yaml file.

    Uses the existing sample_rules.yaml from tests/fixtures/.

    Returns:
        Path: Path to sample rules file
    """
    return Path(__file__).parent / "fixtures" / "sample_rules.yaml"


# ============================================================================
# Data Fixtures
# ============================================================================


@pytest.fixture
def sample_transaction() -> Dict[str, Any]:
    """Single sample transaction for basic tests.

    Returns:
        Dict[str, Any]: Transaction dictionary with all required fields
    """
    return {
        "date": "2025-10-27",
        "time": "19:24",
        "type_raw": "지출",
        "type_norm": "expense",
        "major_raw": "식비",
        "minor_raw": "카페",
        "merchant_raw": "스타벅스",
        "memo_raw": "회의",
        "amount": -5000,
        "currency": "KRW",
        "account": "신한카드",
        "counterparty": "스타벅스",
        "datetime": "2025-10-27T19:24:00",
        "row_hash": "a" * 64,
    }


@pytest.fixture
def sample_transactions() -> list[Dict[str, Any]]:
    """Multiple sample transactions for testing reports and exports.

    Contains a diverse set of transactions:
    - Regular expenses (카페, 외식)
    - Income (급여)
    - Transfers (계좌이체)

    Note: Tags are Python lists (CSV storage format), not JSON strings.

    Returns:
        list[Dict[str, Any]]: List of transaction dictionaries
    """
    return [
        {
            "row_hash": "a" * 64,
            "file_id": "250101_1",
            "source_row": 1,
            "date": "2025-01-15",
            "time": "14:30",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "외식",
            "merchant_raw": "스타벅스",
            "memo_raw": "커피 구매",
            "amount": -5000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "스타벅스",
            "datetime": "2025-01-15T14:30:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["카페", "커피"],
            "tags_ai": [],
            "tags_final": ["카페", "커피"],
            "tags_manual": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "row_hash": "b" * 64,
            "file_id": "250101_1",
            "source_row": 2,
            "date": "2025-02-20",
            "time": "19:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "major_raw": "식비",
            "minor_raw": "외식",
            "merchant_raw": "맥도날드",
            "memo_raw": "저녁 식사",
            "amount": -10000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "맥도날드",
            "datetime": "2025-02-20T19:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["외식"],
            "tags_ai": [],
            "tags_final": ["외식"],
            "tags_manual": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "row_hash": "c" * 64,
            "file_id": "250101_1",
            "source_row": 3,
            "date": "2025-02-15",
            "time": "14:00",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한은행",
            "memo_raw": "계좌이체",
            "amount": -100000,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "신한은행",
            "datetime": "2025-02-15T14:00:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["이체"],
            "tags_ai": [],
            "tags_final": ["이체"],
            "tags_manual": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 1,
            "transfer_group_id": "transfer_001",
        },
        {
            "row_hash": "d" * 64,
            "file_id": "250101_1",
            "source_row": 4,
            "date": "2025-02-15",
            "time": "14:01",
            "type_raw": "이체",
            "type_norm": "transfer",
            "major_raw": "내계좌이체",
            "minor_raw": "이체",
            "merchant_raw": "신한은행",
            "memo_raw": "계좌이체",
            "amount": 100000,
            "account": "신한은행",
            "currency": "KRW",
            "counterparty": "신한카드",
            "datetime": "2025-02-15T14:01:00",
            "category_rule": None,
            "category_final": "미분류",
            "tags_rule": ["이체"],
            "tags_ai": [],
            "tags_final": ["이체"],
            "tags_manual": [],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 1,
            "transfer_group_id": "transfer_001",
        },
    ]


@pytest.fixture
def sample_transfer_pair() -> tuple[Dict[str, Any], Dict[str, Any]]:
    """Sample transfer pair for testing transfer detection.

    Returns:
        tuple: (outgoing_transfer, incoming_transfer)
    """
    timestamp = datetime(2025, 2, 15, 14, 0, 0)

    outgoing = {
        "date": "2025-02-15",
        "time": "14:00",
        "type_raw": "이체",
        "type_norm": "transfer",
        "amount": -100000,
        "account": "신한카드",
        "counterparty": "신한은행",
        "datetime": timestamp.isoformat(),
        "row_hash": "out_" + "a" * 61,
    }

    incoming = {
        "date": "2025-02-15",
        "time": "14:01",
        "type_raw": "이체",
        "type_norm": "transfer",
        "amount": 100000,
        "account": "신한은행",
        "counterparty": "신한카드",
        "datetime": timestamp.replace(minute=1).isoformat(),
        "row_hash": "in_" + "b" * 62,
    }

    return (outgoing, incoming)


# ============================================================================
# Configuration Fixtures
# ============================================================================


@pytest.fixture
def test_config(tmp_path: Path) -> Dict[str, Any]:
    """Test configuration dictionary.

    Returns:
        Dict[str, Any]: Configuration with test paths and settings
    """
    data_dir = tmp_path / "data"

    return {
        "data_dir": data_dir,
        "csv_base_dir": data_dir / "transactions",
        "imports_dir": data_dir / "imports",
        "exports_dir": data_dir / "exports",
        "rules_file": data_dir / "rules.yaml",
        "log_level": "DEBUG",
        "transfer_detection": {
            "time_window_minutes": 5,
            "amount_tolerance": 0.01,
        },
    }


# ============================================================================
# Benchmark Fixtures
# ============================================================================


@pytest.fixture
def generate_synthetic_transactions():
    """Factory fixture to generate synthetic transactions for benchmarks.

    Returns a callable that generates N synthetic transactions with realistic patterns.

    Usage:
        generator = generate_synthetic_transactions
        transactions = generator(size=1000)
    """
    import hashlib
    import random
    from datetime import timedelta

    def _generate(size: int) -> list[Dict[str, Any]]:
        """Generate N synthetic transactions.

        Args:
            size: Number of transactions to generate

        Returns:
            List of transaction dictionaries ready for database insertion
        """
        transactions = []
        base_date = datetime(2024, 1, 1)

        # Realistic merchant names
        merchants = [
            "스타벅스",
            "GS25",
            "세븐일레븐",
            "CU",
            "맥도날드",
            "롯데리아",
            "카카오모빌리티",
            "코레일",
            "한국전력공사",
            "SK브로드밴드",
            "METLIFE",
            "삼성서울병원",
            "고려대학교의료원",
            "롯데백화점",
            "신세계백화점",
            "이마트",
            "쿠팡",
            "배달의민족",
            "요기요",
        ]

        accounts = ["신한카드", "신한은행", "카카오뱅크", "우리은행", "하나카드"]
        categories = [
            ("식비", "외식"),
            ("식비", "카페"),
            ("교통", "지하철"),
            ("교통", "택시"),
            ("쇼핑", "생활용품"),
            ("의류", "의류"),
            ("의료", "병원"),
            ("문화", "영화"),
            ("통신", "인터넷"),
            ("통신", "휴대폰"),
        ]
        tags = ["커피", "외식", "교통", "쇼핑", "의료", "문화", "통신"]

        for i in range(size):
            # Generate date/time (spread over ~2 years)
            transaction_date = base_date + timedelta(
                days=i % 730, hours=random.randint(0, 23), minutes=random.randint(0, 59)
            )
            date_str = transaction_date.strftime("%Y-%m-%d")
            time_str = transaction_date.strftime("%H:%M")
            datetime_str = transaction_date.isoformat()

            # Randomly select transaction type
            type_rand = random.random()
            if type_rand < 0.75:  # 75% expenses
                type_raw = "지출"
                type_norm = "expense"
                amount = -random.randint(1000, 200000)
            elif type_rand < 0.85:  # 10% income
                type_raw = "입금"
                type_norm = "income"
                amount = random.randint(1000000, 5000000)
            else:  # 15% transfers
                type_raw = "이체"
                type_norm = "transfer"
                amount = random.choice([-1, 1]) * random.randint(50000, 1000000)

            merchant = random.choice(merchants)
            account = random.choice(accounts)
            major, minor = random.choice(categories)
            tag_list = random.sample(tags, k=random.randint(1, 3))

            # Create unique row hash
            hash_input = f"{date_str}{time_str}{merchant}{amount}{account}{i}"
            row_hash = hashlib.sha256(hash_input.encode()).hexdigest()

            transaction = {
                "row_hash": row_hash,
                "source_file_path": f"imports/synthetic_{i // 1000}.xlsx",
                "source_row": i + 1,
                "date": date_str,
                "time": time_str,
                "type_raw": type_raw,
                "type_norm": type_norm,
                "major_raw": major,
                "minor_raw": minor,
                "merchant_raw": merchant,
                "memo_raw": f"테스트 거래 {i}" if random.random() > 0.2 else None,
                "amount": amount,
                "account": account,
                "currency": "KRW",
                "counterparty": merchant,
                "datetime": datetime_str,
                "tags_rule": tag_list,  # CSV format: Python list, not JSON string
                "tags_ai": [],
                "tags_manual": [],
                "tags_final": tag_list,
                "confidence": round(random.uniform(0.7, 1.0), 2),
                "needs_review": 1 if random.random() < 0.1 else 0,
                "is_transfer": 1 if type_norm == "transfer" else 0,
                "transfer_group_id": (
                    f"transfer_{i // 2}" if type_norm == "transfer" and i % 2 == 0 else None
                ),
            }

            transactions.append(transaction)

        return transactions

    return _generate


# ============================================================================
# Pytest Configuration
# ============================================================================


def _is_focused_test_run(config: pytest.Config) -> bool:
    """Return True when pytest is running a filtered subset instead of the full suite."""
    if getattr(config.option, "collectonly", False):
        return True

    selected_targets = [str(arg).rstrip("/") for arg in config.args]
    runs_full_test_tree = selected_targets in ([], ["tests"])

    return bool(config.option.keyword or config.option.markexpr or not runs_full_test_tree)


def pytest_configure(config):
    """Configure pytest with custom markers."""
    config.addinivalue_line("markers", "unit: Unit tests (fast, isolated)")
    config.addinivalue_line("markers", "integration: Integration tests (slower, multi-component)")
    config.addinivalue_line("markers", "slow: Slow tests (large datasets, benchmarks)")
    config.addinivalue_line("markers", "idempotent: Idempotency verification tests")

    # The global fail-under gate is meaningful for full-suite runs only.
    # Focused commands like `pytest tests/cli/ -k context` should fail on broken
    # tests, not on unrelated package coverage outside the selected scope.
    if hasattr(config.option, "cov_fail_under") and _is_focused_test_run(config):
        config.option.cov_fail_under = 0
        cov_plugin = config.pluginmanager.getplugin("_cov")
        if cov_plugin is not None:
            cov_plugin.options.cov_fail_under = 0
