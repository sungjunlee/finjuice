"""Tests for the `finjuice show` command."""

from pathlib import Path

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.csv_transactions import write_month
from tests.conftest import cli_text

runner = CliRunner()


def _transaction(
    *,
    row_hash: str,
    date: str,
    time: str,
    merchant: str,
    amount: float,
    tags: list[str] | None = None,
    account: str = "신한카드",
) -> dict[str, object]:
    """Build a minimal transaction row for CLI tests."""
    return {
        "row_hash": row_hash,
        "date": date,
        "time": time,
        "datetime": f"{date}T{time}:00",
        "type_raw": "지출" if amount < 0 else "수입",
        "type_norm": "expense" if amount < 0 else "income",
        "merchant_raw": merchant,
        "amount": amount,
        "account": account,
        "tags_final": tags or [],
    }


def _write_partition(data_dir: Path, year: int, month: int, rows: list[dict[str, object]]) -> None:
    """Write one transaction partition for a CLI test."""
    write_month(data_dir / "transactions", pl.DataFrame(rows), year, month)


@pytest.fixture
def show_data_dir(tmp_path: Path) -> Path:
    """Create an isolated data directory for `show` command tests."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    return data_dir


def test_show_tag_scans_all_partitions(show_data_dir: Path) -> None:
    """`show --tag` should search across older partitions when `--month` is omitted."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-tag",
                date="2024-10-10",
                time="09:00",
                merchant="Earlier Tagged Merchant",
                amount=-12000.0,
                tags=["이전달태그"],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-other",
                date="2024-11-03",
                time="10:00",
                merchant="Latest Other Merchant",
                amount=-8000.0,
                tags=["최신달태그"],
            )
        ],
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(show_data_dir), "show", "--tag", "이전달태그"],
    )

    assert result.exit_code == 0
    assert "Earlier Tagged Merchant" in cli_text(result)
    assert "Showing 1 transactions across 2 partitions" in cli_text(result)


def test_show_tag_with_bracket(show_data_dir: Path) -> None:
    """Bracketed tags should match exactly across older partitions."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-bracket",
                date="2024-10-11",
                time="09:30",
                merchant="Bracket Tag Merchant",
                amount=-9000.0,
                tags=["[테스트]특수"],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-bracket",
                date="2024-11-05",
                time="10:15",
                merchant="Latest Merchant",
                amount=-7000.0,
                tags=["최신달태그"],
            )
        ],
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(show_data_dir), "show", "--tag", "[테스트]특수"],
    )

    assert result.exit_code == 0
    assert "Bracket Tag Merchant" in cli_text(result)
    assert "No transactions match the filters" not in cli_text(result)


def test_show_tag_korean_ascii_mixed(show_data_dir: Path) -> None:
    """Mixed Korean/ASCII tags should match exactly across older partitions."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-mixed",
                date="2024-10-12",
                time="11:00",
                merchant="Mixed Tag Merchant",
                amount=-15000.0,
                tags=["[test]한글"],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-mixed",
                date="2024-11-07",
                time="12:00",
                merchant="Latest Mixed Merchant",
                amount=-6000.0,
                tags=["다른태그"],
            )
        ],
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(show_data_dir), "show", "--tag", "[test]한글"],
    )

    assert result.exit_code == 0
    assert "Mixed Tag Merchant" in cli_text(result)


def test_show_tag_with_whitespace(show_data_dir: Path) -> None:
    """Whitespace tags should still match exactly across older partitions."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-space",
                date="2024-10-13",
                time="08:45",
                merchant="Whitespace Tag Merchant",
                amount=-5000.0,
                tags=["내 태그"],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-space",
                date="2024-11-09",
                time="13:00",
                merchant="Latest Space Merchant",
                amount=-4000.0,
                tags=["최신"],
            )
        ],
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(show_data_dir), "show", "--tag", "내 태그"],
    )

    assert result.exit_code == 0
    assert "Whitespace Tag Merchant" in cli_text(result)


def test_show_untagged_scans_all_partitions(show_data_dir: Path) -> None:
    """`show --untagged` should search across older partitions."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-untagged",
                date="2024-10-14",
                time="07:15",
                merchant="Earlier Untagged Merchant",
                amount=-3200.0,
                tags=[],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-tagged",
                date="2024-11-10",
                time="14:10",
                merchant="Latest Tagged Merchant",
                amount=-10200.0,
                tags=["식비"],
            )
        ],
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(show_data_dir), "show", "--untagged"],
    )

    assert result.exit_code == 0
    assert "Earlier Untagged Merchant" in cli_text(result)
    assert "Showing 1 transactions across 2 partitions" in cli_text(result)


def test_show_merchant_scans_all_partitions(show_data_dir: Path) -> None:
    """`show --merchant` should search across older partitions."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-merchant",
                date="2024-10-15",
                time="15:30",
                merchant="고양이마트 성수점",
                amount=-22000.0,
                tags=["생활"],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-merchant",
                date="2024-11-11",
                time="16:30",
                merchant="강아지마트 강남점",
                amount=-18000.0,
                tags=["생활"],
            )
        ],
    )

    result = runner.invoke(
        app,
        ["--data-dir", str(show_data_dir), "show", "--merchant", "고양이"],
    )

    assert result.exit_code == 0
    assert "고양이마트 성수점" in cli_text(result)
    assert "강아지마트 강남점" not in cli_text(result)
    assert "Showing 1 transactions across 2 partitions" in cli_text(result)


def test_show_bare_command_still_uses_latest_month(show_data_dir: Path) -> None:
    """Bare `show` should remain bounded to the latest month."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-bare",
                date="2024-10-16",
                time="09:20",
                merchant="Earlier Bare Merchant",
                amount=-6500.0,
                tags=["과거"],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-bare",
                date="2024-11-12",
                time="18:40",
                merchant="Latest Bare Merchant",
                amount=-7100.0,
                tags=["현재"],
            )
        ],
    )

    result = runner.invoke(app, ["--data-dir", str(show_data_dir), "show"])

    assert result.exit_code == 0
    assert "Transactions (2024-11)" in cli_text(result)
    assert "Latest Bare Merchant" in cli_text(result)
    assert "Earlier Bare Merchant" not in cli_text(result)
    assert "across 2 partitions" not in cli_text(result)


def test_show_tag_in_latest_month_still_matches(show_data_dir: Path) -> None:
    """Regression: --tag matches in latest partition still work (all-scan must include latest)."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-latest-tag-1",
                date="2024-10-05",
                time="09:00",
                merchant="Earlier Café",
                amount=-4500.0,
                tags=["과거카페"],
            )
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-latest-tag-1",
                date="2024-11-12",
                time="18:40",
                merchant="Latest Café",
                amount=-5500.0,
                tags=["현재카페"],
            )
        ],
    )

    result = runner.invoke(app, ["--data-dir", str(show_data_dir), "show", "--tag", "현재카페"])

    assert result.exit_code == 0
    assert "Latest Café" in cli_text(result)
    assert "Earlier Café" not in cli_text(result)


def test_show_tag_with_month_scopes_correctly(show_data_dir: Path) -> None:
    """Regression: --month X --tag Y narrows to that month and still applies the tag filter."""
    _write_partition(
        show_data_dir,
        2024,
        10,
        [
            _transaction(
                row_hash="oct-scoped-1",
                date="2024-10-05",
                time="09:00",
                merchant="October Matched",
                amount=-4500.0,
                tags=["공용태그"],
            ),
            _transaction(
                row_hash="oct-scoped-2",
                date="2024-10-06",
                time="10:00",
                merchant="October Unmatched",
                amount=-3000.0,
                tags=["다른태그"],
            ),
        ],
    )
    _write_partition(
        show_data_dir,
        2024,
        11,
        [
            _transaction(
                row_hash="nov-scoped-1",
                date="2024-11-12",
                time="18:40",
                merchant="November Matched",
                amount=-5500.0,
                tags=["공용태그"],
            )
        ],
    )

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(show_data_dir),
            "show",
            "--month",
            "2024-10",
            "--tag",
            "공용태그",
        ],
    )

    assert result.exit_code == 0
    assert "October Matched" in cli_text(result)
    assert "October Unmatched" not in cli_text(result)
    assert "November Matched" not in cli_text(result)
    assert "across" not in cli_text(result)
