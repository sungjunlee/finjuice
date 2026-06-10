"""Unit tests for centralized analytics view (Issue #184)."""

import tempfile
from pathlib import Path

import polars as pl
import pytest

from finjuice.pipeline.analytics import DuckDBAnalytics
from finjuice.pipeline.cli.commands.template_cmd.execution import _render_sql
from finjuice.pipeline.cli.commands.template_cmd.param_coercion import _resolve_sql_params
from finjuice.pipeline.cli.commands.template_cmd.registry import _load_registry, _load_sql


def _render_template_sql(template_name: str, user_params: dict[str, str] | None = None) -> str:
    """Render a packaged SQL template with validated parameters."""
    template_spec = _load_registry()[template_name]
    sql_template = _load_sql(str(template_spec["sql_file"]))
    resolved_params = _resolve_sql_params(template_name, template_spec, user_params or {})
    return _render_sql(sql_template, resolved_params)


@pytest.fixture
def sample_csv_data():
    """Sample transaction data for testing."""
    return pl.DataFrame(
        {
            "row_hash": ["abc123", "def456", "ghi789"],
            "date": ["2024-10-01", "2024-10-15", "2024-11-03"],
            "time": ["10:30", "14:20", "08:15"],
            "type_raw": ["지출", "지출", "지출"],
            "major_raw": ["식비", "쇼핑", "생활"],
            "minor_raw": ["카페", "의류", "마트"],
            "merchant_raw": ["스타벅스", "유니클로", "홈플러스"],
            "memo_raw": ["", "", ""],
            "amount": [-4500.0, -29000.0, -18000.0],
            "currency": ["KRW", "KRW", "KRW"],
            "account": ["신한카드", "삼성카드", "국민카드"],
            "is_transfer": [0, 1, None],  # Int 0/1 with NULL defaulting to False
            "transfer_group_id": [None, "group1", None],
            "tags_rule": ['["카페","식비"]', '["쇼핑"]', '["마트","생활"]'],
            "tags_final": ['["카페","식비"]', '["쇼핑"]', '["마트","생활"]'],  # JSON string
        }
    )


@pytest.fixture
def temp_data_dir(sample_csv_data):
    """Create temporary data directory with CSV partitions."""
    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = Path(tmpdir)
        oct_dir = data_dir / "transactions" / "2024" / "10"
        oct_dir.mkdir(parents=True, exist_ok=True)
        sample_csv_data.write_csv(oct_dir / "transactions.csv")
        yield data_dir


class TestDuckDBAnalyticsView:
    """Test centralized transactions view."""

    def test_view_creation(self, temp_data_dir):
        """Test that transactions view is created automatically."""
        with DuckDBAnalytics(temp_data_dir) as analytics:
            # Query the view directly
            df = analytics.conn.execute("SELECT * FROM transactions").pl()

            assert len(df) == 3
            assert "is_transfer_bool" in df.columns
            assert "tags_list" in df.columns

            # Check type normalization (Issue #185)
            # is_transfer (0/1/NULL) -> is_transfer_bool (False/True/False)
            assert df["is_transfer_bool"].dtype == pl.Boolean
            assert df["is_transfer_bool"].null_count() == 0
            assert df["is_transfer_bool"][0] is False
            assert df["is_transfer_bool"][1] is True
            assert df["is_transfer_bool"][2] is False

            # tags_final (JSON string) -> tags_list
            # Issue #185: Now returns List(Utf8)
            assert df["tags_list"].dtype == pl.List(pl.Utf8)
            assert "카페" in df["tags_list"][0]

    def test_view_persistence(self, temp_data_dir):
        """Test that view persists across queries in same connection."""
        with DuckDBAnalytics(temp_data_dir) as analytics:
            # First query
            res1 = analytics.conn.execute("SELECT COUNT(*) FROM transactions").fetchone()
            assert res1 is not None
            c1 = res1[0]
            assert c1 == 3

            # Second query
            res2 = analytics.conn.execute(
                "SELECT COUNT(*) FROM transactions WHERE is_transfer_bool = true"
            ).fetchone()
            assert res2 is not None
            c2 = res2[0]
            assert c2 == 1

    def test_template_queries_include_null_transfer_rows(self, temp_data_dir):
        """Template SQL should treat NULL is_transfer as a non-transfer row."""
        monthly_spend_sql = _render_template_sql(
            "monthly_spend",
            {"since": "2024-11", "until": "2024-11"},
        )
        tag_breakdown_sql = _render_template_sql(
            "tag_breakdown",
            {"since": "2024-11", "until": "2024-11", "top_n": "10"},
        )

        with DuckDBAnalytics(temp_data_dir) as analytics:
            monthly_df = analytics.conn.execute(monthly_spend_sql).pl()
            tag_df = analytics.conn.execute(tag_breakdown_sql).pl()

        assert len(monthly_df) == 1
        assert monthly_df["month"][0] == "2024-11"
        assert monthly_df["transaction_count"][0] == 1
        assert monthly_df["total_spend"][0] == pytest.approx(18000.0)

        assert len(tag_df) == 2
        assert set(tag_df["tag"].to_list()) == {"마트", "생활"}

    def test_view_creation_no_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            (data_dir / "transactions").mkdir(parents=True)

            with pytest.raises(FileNotFoundError, match="No transaction data found"):
                DuckDBAnalytics(data_dir)

    def test_view_creation_invalid_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir)
            oct_dir = data_dir / "transactions" / "2024" / "10"
            oct_dir.mkdir(parents=True)

            (oct_dir / "transactions.csv").write_text("NOT,A,VALID,CSV\ngarbage data")

            with pytest.raises(RuntimeError, match="Failed to create transactions view"):
                DuckDBAnalytics(data_dir)
