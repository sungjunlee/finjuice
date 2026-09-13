"""Tests for retained analysis commands (query and explain)."""

import json

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from tests.conftest import cli_text

runner = CliRunner()


@pytest.fixture
def mock_data_dir(tmp_path):
    """Create a temporary data directory with some transaction data."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Create transactions directory
    transactions_dir = data_dir / "transactions" / "2024" / "10"
    transactions_dir.mkdir(parents=True)

    # Create sample CSV with JSON-serialized tags
    df = pl.DataFrame(
        {
            "date": ["2024-10-01", "2024-10-02", "2024-10-03"],
            "merchant_raw": ["Starbucks", "Netflix", "Coupang"],
            "amount": [-5000, -15000, -30000],
            "memo_raw": ["Coffee", "Subscription", "Shopping"],
            "major_raw": ["Food", "Ent", "Shopping"],
            "minor_raw": ["Cafe", "Sub", "Online"],
            "type_norm": ["expense", "expense", "expense"],
            "is_transfer": [0, 0, 0],
            "row_hash": ["hash_starbucks", "hash_netflix", "hash_coupang"],
            # Serialize lists to JSON strings for CSV writing
            "tags_final": [json.dumps(["cafe"]), json.dumps([]), json.dumps(["shopping"])],
            "category_final": ["Cafe", "Entertainment", "Shopping"],
        }
    )

    csv_path = transactions_dir / "transactions.csv"
    df.write_csv(csv_path)

    # Create rules file
    # Config expects rules.yaml at root of data_dir
    (data_dir / "rules.yaml").write_text("""
version: 1
rules:
  - name: coffee
    match: "Starbucks"
    fields: ["merchant_raw"]
    tags: ["cafe"]
    priority: 50
""")

    return data_dir


@pytest.fixture
def multi_explain_data_dir(tmp_path):
    """Create a data directory with several Starbucks matches for selection tests."""
    data_dir = tmp_path / "data"
    transactions_dir = data_dir / "transactions" / "2024" / "10"
    transactions_dir.mkdir(parents=True)

    df = pl.DataFrame(
        {
            "date": ["2024-10-03", "2024-10-02", "2024-10-01"],
            "merchant_raw": ["Starbucks Gangnam", "Starbucks Jamsil", "Netflix"],
            "amount": [-5500, -4500, -15000],
            "memo_raw": ["Latte", "Americano", "Subscription"],
            "major_raw": ["Food", "Food", "Ent"],
            "minor_raw": ["Cafe", "Cafe", "Sub"],
            "type_norm": ["expense", "expense", "expense"],
            "is_transfer": [0, 0, 0],
            "row_hash": ["hash_gangnam", "hash_jamsil", "hash_netflix"],
            "tags_final": [json.dumps(["cafe"]), json.dumps(["cafe"]), json.dumps([])],
            "category_final": ["Cafe", "Cafe", "Entertainment"],
        }
    )
    df.write_csv(transactions_dir / "transactions.csv")
    (data_dir / "rules.yaml").write_text("""
version: 1
rules:
  - name: coffee
    match: "Starbucks"
    fields: ["merchant_raw"]
    tags: ["cafe"]
    priority: 50
""")
    return data_dir


def test_query_command_basic(mock_data_dir):
    """Test basic SELECT query."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(mock_data_dir),
            "query",
            "SELECT merchant_raw, amount FROM transactions ORDER BY date",
        ],
    )
    assert result.exit_code == 0
    assert "Starbucks" in cli_text(result)
    assert "-5000" in cli_text(result)


def test_query_command_safety(mock_data_dir):
    """Test that non-SELECT queries are rejected."""
    result = runner.invoke(
        app, ["--data-dir", str(mock_data_dir), "query", "DELETE FROM transactions"]
    )
    assert result.exit_code == 3  # VALIDATION_ERROR
    assert "Only SELECT or WITH" in cli_text(result)


def test_explain_command_match(mock_data_dir):
    """Test explaining a matching transaction."""
    # Input "1" to select the first transaction if prompted
    # (though with unique match it might not prompt)
    # But here "Starbucks" matches only one.
    result = runner.invoke(
        app, ["--data-dir", str(mock_data_dir), "explain", "Starbucks"], input="1\n"
    )  # Just in case it prompts

    assert result.exit_code == 0
    assert "Transaction Details" in cli_text(result)
    assert "Matched Rules: coffee" in cli_text(result)
    assert "Rule Trace" in cli_text(result)


def test_explain_command_no_match(mock_data_dir):
    """Test explain with no matching transaction."""
    result = runner.invoke(app, ["--data-dir", str(mock_data_dir), "explain", "UnknownMerchant"])
    assert result.exit_code == 0
    assert "No matching transactions found" in cli_text(result)


def test_query_command_sql_injection_attempt(mock_data_dir):
    """Test prevention of multi-statement SQL injection."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(mock_data_dir),
            "query",
            "SELECT * FROM transactions; DROP TABLE transactions",
        ],
    )
    assert result.exit_code == 3  # VALIDATION_ERROR
    assert "Multi-statement queries are not allowed" in cli_text(result)


def test_query_command_allows_dropbox_literal(mock_data_dir):
    """Restricted keyword substring in literal (Dropbox) should not be blocked."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(mock_data_dir),
            "query",
            "SELECT * FROM transactions WHERE merchant_raw = 'Dropbox'",
        ],
    )
    assert result.exit_code == 0


def test_query_command_markdown_output_without_pandas(mock_data_dir, monkeypatch):
    """Markdown output should not depend on pandas/tabulate via to_pandas()."""

    def _raise_no_pandas(*_args, **_kwargs):  # pragma: no cover - should not be called
        raise AssertionError("to_pandas should not be called for markdown output")

    monkeypatch.setattr(pl.DataFrame, "to_pandas", _raise_no_pandas)

    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(mock_data_dir),
            "query",
            "SELECT merchant_raw, amount FROM transactions ORDER BY date",
            "--output",
            "markdown",
        ],
    )

    assert result.exit_code == 0
    rendered = cli_text(result)
    assert "| merchant_raw | amount |" in rendered
    assert "| Starbucks | -5000 |" in rendered


def test_explain_command_date_format_validation(mock_data_dir):
    """Test validation of date format."""
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(mock_data_dir),
            "explain",
            "Starbucks",
            "--date",
            "2024/10/01",  # Invalid format
        ],
    )
    assert result.exit_code == 3  # VALIDATION_ERROR
    assert "Invalid date format" in cli_text(result)


def test_explain_pick_selects_nth_listed_candidate(multi_explain_data_dir):
    """--pick N should explain the Nth listed match without prompting."""
    # Arrange
    data_dir = multi_explain_data_dir

    # Act
    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "explain", "Starbucks", "--pick", "2"],
    )

    # Assert
    text = cli_text(result)
    assert result.exit_code == 0
    assert "Select transaction number" not in text
    assert "Starbucks Jamsil" in text
    assert "Americano" in text
    assert "Starbucks Gangnam" not in text

    json_result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "explain", "Starbucks", "--pick", "2", "--json"],
    )
    assert json_result.exit_code == 0
    payload = json.loads(json_result.output)
    assert payload["selected_index"] == 2
    assert payload["transaction"]["row_hash"] == "hash_jamsil"
    assert payload["transaction"]["merchant_raw"] == "Starbucks Jamsil"


def test_explain_json_returns_candidates_without_prompting(multi_explain_data_dir):
    """--json should return listed candidates with row_hash and skip the prompt."""
    # Arrange
    data_dir = multi_explain_data_dir

    # Act
    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "explain", "Starbucks", "--json"],
    )

    # Assert
    assert result.exit_code == 0
    assert "Select transaction number" not in result.output
    payload = json.loads(result.output)
    assert payload["match_count"] == 2
    assert payload["selected_index"] == 1
    assert [candidate["row_hash"] for candidate in payload["candidates"]] == [
        "hash_gangnam",
        "hash_jamsil",
    ]
    assert payload["transaction"]["row_hash"] == "hash_gangnam"
    assert payload["transaction"]["merchant_raw"] == "Starbucks Gangnam"


def test_explain_prompts_when_multiple_match_without_flags(multi_explain_data_dir):
    """Interactive selection remains the default when no --pick/--json is given."""
    # Arrange
    data_dir = multi_explain_data_dir

    # Act
    result = runner.invoke(
        app,
        ["--data-dir", str(data_dir), "explain", "Starbucks"],
        input="2\n",
    )

    # Assert
    text = cli_text(result)
    assert result.exit_code == 0
    assert "Select transaction number" in text
    assert "Starbucks Jamsil" in text
    assert "Americano" in text


def test_explain_pick_zero_raises_value_error():
    from finjuice.pipeline.cli.commands.explain import _validate_pick

    with pytest.raises(ValueError, match="Invalid --pick 0"):
        _validate_pick(0, 4)


def test_explain_pick_beyond_listed_top5_is_rejected():
    import pytest

    from finjuice.pipeline.cli.commands.explain import _validate_pick

    # 10 matches exist (search LIMIT 10) but only 5 are listed
    with pytest.raises(ValueError, match="top 5 listed"):
        _validate_pick(7, 10)


def test_explain_pick_within_listed_top5_accepted():
    from finjuice.pipeline.cli.commands.explain import _validate_pick

    _validate_pick(5, 10)  # should not raise
