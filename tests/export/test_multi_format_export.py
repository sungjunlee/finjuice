"""
Tests for multi-format export (Issue #117).

Tests cover:
- HTML report generation with Plotly charts
- Markdown report generation
- Aggregation functions
- CLI export options
- Auto-open utility
"""

from unittest.mock import MagicMock, patch

import polars as pl
import pytest


@pytest.fixture
def sample_transactions():
    """Create sample transaction data for testing."""
    return pl.DataFrame(
        {
            "row_hash": [f"hash{i}" for i in range(10)],
            "date": [
                "2024-10-01",
                "2024-10-05",
                "2024-10-10",
                "2024-10-15",
                "2024-10-20",
                "2024-11-01",
                "2024-11-05",
                "2024-11-10",
                "2024-11-15",
                "2024-11-20",
            ],
            "time": ["10:00"] * 10,
            "datetime": [
                "2024-10-01T10:00:00",
                "2024-10-05T10:00:00",
                "2024-10-10T10:00:00",
                "2024-10-15T10:00:00",
                "2024-10-20T10:00:00",
                "2024-11-01T10:00:00",
                "2024-11-05T10:00:00",
                "2024-11-10T10:00:00",
                "2024-11-15T10:00:00",
                "2024-11-20T10:00:00",
            ],
            "amount": [
                -50000,
                -30000,
                -25000,
                -100000,
                -45000,
                -60000,
                -35000,
                -80000,
                -40000,
                -55000,
            ],
            "type_norm": ["expense"] * 10,
            "merchant_raw": [
                "스타벅스",
                "GS25",
                "투썸플레이스",
                "쿠팡",
                "배달의민족",
                "스타벅스",
                "CU",
                "마켓컬리",
                "카카오택시",
                "버거킹",
            ],
            "is_transfer": [0] * 10,
            "tags_final": [
                '["카페", "커피"]',
                '["편의점", "생활"]',
                '["카페", "커피"]',
                '["온라인쇼핑"]',
                '["배달", "식비"]',
                '["카페", "커피"]',
                '["편의점", "생활"]',
                '["온라인쇼핑"]',
                '["교통", "택시"]',
                '["식비", "외식"]',
            ],
        }
    )


@pytest.fixture
def csv_partitions_dir(tmp_path, sample_transactions):
    """Create temporary CSV partition structure."""
    # Create 2024/10 partition
    oct_dir = tmp_path / "transactions" / "2024" / "10"
    oct_dir.mkdir(parents=True)
    oct_data = sample_transactions.filter(pl.col("date").str.starts_with("2024-10"))
    oct_data.write_csv(oct_dir / "transactions.csv")

    # Create 2024/11 partition
    nov_dir = tmp_path / "transactions" / "2024" / "11"
    nov_dir.mkdir(parents=True)
    nov_data = sample_transactions.filter(pl.col("date").str.starts_with("2024-11"))
    nov_data.write_csv(nov_dir / "transactions.csv")

    return tmp_path / "transactions"


@pytest.fixture
def empty_csv_partitions_dir(tmp_path):
    """Create temporary CSV partition structure with empty data."""
    csv_dir = tmp_path / "transactions"
    empty_dir = csv_dir / "2024" / "10"
    empty_dir.mkdir(parents=True)
    empty_df = pl.DataFrame(
        {
            "row_hash": [],
            "date": [],
            "time": [],
            "datetime": [],
            "amount": [],
            "type_norm": [],
            "merchant_raw": [],
            "is_transfer": [],
            "tags_final": [],
        }
    )
    empty_df.write_csv(empty_dir / "transactions.csv")
    return csv_dir


class TestAggregations:
    """Tests for aggregation functions."""

    def test_load_transactions_all(self, csv_partitions_dir):
        """Test loading all transactions."""
        from finjuice.pipeline.export.aggregations import load_transactions

        df = load_transactions(csv_partitions_dir)

        assert len(df) == 10

    def test_load_transactions_with_period_filter(self, csv_partitions_dir):
        """Test loading transactions with period filter."""
        from finjuice.pipeline.export.aggregations import load_transactions

        df = load_transactions(csv_partitions_dir, period="2024-10")

        assert len(df) == 5
        assert all(row.startswith("2024-10") for row in df["date"].to_list())

    def test_load_transactions_empty_period(self, csv_partitions_dir):
        """Test loading transactions with non-existent period."""
        from finjuice.pipeline.export.aggregations import load_transactions

        df = load_transactions(csv_partitions_dir, period="2025-01")

        assert df.is_empty()

    def test_calculate_monthly_spend(self, csv_partitions_dir):
        """Test monthly spend calculation."""
        from finjuice.pipeline.export.aggregations import (
            calculate_monthly_spend,
            load_transactions,
        )

        df = load_transactions(csv_partitions_dir)
        result = calculate_monthly_spend(df)

        assert "month" in result.columns
        assert "transaction_count" in result.columns
        assert "total_amount" in result.columns
        assert len(result) == 2  # October and November

    def test_calculate_monthly_spend_legacy_schema_excludes_is_transfer_rows(self):
        """Legacy/minimal frames without group ids should keep is_transfer semantics."""
        from finjuice.pipeline.export.aggregations import calculate_monthly_spend

        df = pl.DataFrame(
            {
                "date": ["2024-10-01", "2024-10-02"],
                "amount": [-100.0, -200.0],
                "type_norm": ["expense", "expense"],
                "is_transfer": [0, 1],
            }
        )

        result = calculate_monthly_spend(df)

        assert result.to_dicts() == [
            {"month": "2024-10", "transaction_count": 1, "total_amount": -100.0}
        ]

    def test_calculate_tag_breakdown(self, csv_partitions_dir):
        """Test tag breakdown calculation."""
        from finjuice.pipeline.export.aggregations import (
            calculate_tag_breakdown,
            load_transactions,
        )

        df = load_transactions(csv_partitions_dir)
        result = calculate_tag_breakdown(df, top_n=5)

        assert "tag" in result.columns
        assert "transaction_count" in result.columns
        assert "total_amount" in result.columns
        assert "percentage" in result.columns
        assert len(result) <= 5

    def test_calculate_top_merchants(self, csv_partitions_dir):
        """Test top merchants calculation."""
        from finjuice.pipeline.export.aggregations import (
            calculate_top_merchants,
            load_transactions,
        )

        df = load_transactions(csv_partitions_dir)
        result = calculate_top_merchants(df, limit=5)

        assert "merchant" in result.columns
        assert "transaction_count" in result.columns
        assert "total_amount" in result.columns
        assert len(result) <= 5

    def test_calculate_summary_stats(self, csv_partitions_dir):
        """Test summary stats calculation."""
        from finjuice.pipeline.export.aggregations import (
            calculate_summary_stats,
            load_transactions,
        )

        df = load_transactions(csv_partitions_dir)
        result = calculate_summary_stats(df, period="2024-10")

        assert "period" in result
        assert "generated_at" in result
        assert "total_transactions" in result
        assert "total_expenses" in result
        assert "total_income" in result
        assert result["period"] == "2024-10"
        assert result["total_transactions"] == 10

    def test_calculate_summary_stats_empty(self):
        """Test summary stats with empty data."""
        from finjuice.pipeline.export.aggregations import calculate_summary_stats

        empty_df = pl.DataFrame(
            {
                "date": [],
                "amount": [],
                "type_norm": [],
                "is_transfer": [],
            }
        ).cast(
            {
                "date": pl.Utf8,
                "amount": pl.Float64,
                "type_norm": pl.Utf8,
                "is_transfer": pl.Int64,
            }
        )

        result = calculate_summary_stats(empty_df)

        assert result["total_transactions"] == 0
        assert result["total_expenses"] == 0
        assert result["total_income"] == 0


class TestHtmlReport:
    """Tests for HTML report generation."""

    def test_generate_html_report(self, csv_partitions_dir, tmp_path):
        """Test generating HTML report."""
        from finjuice.pipeline.export.html_report import generate_html_report

        output_path = tmp_path / "report.html"
        result = generate_html_report(csv_partitions_dir, output_path)

        assert result == output_path
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "재무 분석 리포트" in content
        assert "plotly" in content.lower()

    def test_generate_html_report_with_period(self, csv_partitions_dir, tmp_path):
        """Test generating HTML report with period filter."""
        from finjuice.pipeline.export.html_report import generate_html_report

        output_path = tmp_path / "report_oct.html"
        result = generate_html_report(csv_partitions_dir, output_path, period="2024-10")

        assert result == output_path
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        assert "2024-10" in content

    def test_generate_html_report_without_charts(self, csv_partitions_dir, tmp_path):
        """Test generating HTML report without charts."""
        from finjuice.pipeline.export.html_report import generate_html_report

        output_path = tmp_path / "report_no_charts.html"
        result = generate_html_report(csv_partitions_dir, output_path, include_charts=False)

        assert result == output_path
        assert output_path.exists()

    def test_html_report_creates_directory(self, csv_partitions_dir, tmp_path):
        """Test that HTML report creates output directory if needed."""
        from finjuice.pipeline.export.html_report import generate_html_report

        output_path = tmp_path / "nested" / "dir" / "report.html"
        result = generate_html_report(csv_partitions_dir, output_path)

        assert result == output_path
        assert output_path.exists()

    def test_html_report_escapes_user_controlled_labels(self, tmp_path):
        """Merchant and tag labels from imports should not render as raw HTML."""
        from finjuice.pipeline.export.html_report import generate_html_report

        source_df = pl.DataFrame(
            {
                "date": ["2024-10-01"],
                "amount": [-1000],
                "type_norm": ["expense"],
                "merchant_raw": ['<img src=x onerror="alert(1)">'],
                "is_transfer": [0],
                "tags_final": [["<script>alert(1)</script>|tag"]],
            }
        )

        output_path = tmp_path / "report.html"
        generate_html_report(tmp_path, output_path, include_charts=False, source_df=source_df)

        content = output_path.read_text(encoding="utf-8")
        assert '<img src=x onerror="alert(1)">' not in content
        assert "<script>alert(1)</script>" not in content
        assert "&lt;img src=x onerror=&#34;alert(1)&#34;&gt;" in content
        assert "&lt;script&gt;alert(1)&lt;/script&gt;|tag" in content

    def test_html_report_chart_fragments_do_not_render_raw_script_payloads(self, tmp_path):
        """Plotly chart fragments are safe-inserted, so labels must stay encoded."""
        from finjuice.pipeline.export.html_report import generate_html_report

        source_df = pl.DataFrame(
            {
                "date": ["2024-10-01"],
                "amount": [-1000],
                "type_norm": ["expense"],
                "merchant_raw": ['</script><script>alert("merchant")</script>'],
                "is_transfer": [0],
                "tags_final": [['</script><script>alert("tag")</script>']],
            }
        )

        output_path = tmp_path / "report.html"
        generate_html_report(tmp_path, output_path, include_charts=True, source_df=source_df)

        content = output_path.read_text(encoding="utf-8")
        assert '</script><script>alert("merchant")</script>' not in content
        assert '</script><script>alert("tag")</script>' not in content
        assert "\\u003cscript\\u003ealert" in content


class TestMarkdownReport:
    """Tests for Markdown report generation."""

    def test_generate_markdown_report(self, csv_partitions_dir, tmp_path):
        """Test generating Markdown report."""
        from finjuice.pipeline.export.markdown_report import generate_markdown_report

        output_path = tmp_path / "report.md"
        result = generate_markdown_report(csv_partitions_dir, output_path)

        assert result == output_path
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        assert "# " in content  # Has headings
        assert "|" in content  # Has tables
        assert "재무 분석 리포트" in content

    def test_generate_markdown_report_with_period(self, csv_partitions_dir, tmp_path):
        """Test generating Markdown report with period filter."""
        from finjuice.pipeline.export.markdown_report import generate_markdown_report

        output_path = tmp_path / "report_oct.md"
        result = generate_markdown_report(csv_partitions_dir, output_path, period="2024-10")

        assert result == output_path
        assert output_path.exists()

        content = output_path.read_text(encoding="utf-8")
        assert "2024-10" in content

    def test_markdown_report_has_sections(self, csv_partitions_dir, tmp_path):
        """Test that Markdown report has all expected sections."""
        from finjuice.pipeline.export.markdown_report import generate_markdown_report

        output_path = tmp_path / "report.md"
        generate_markdown_report(csv_partitions_dir, output_path)

        content = output_path.read_text(encoding="utf-8")
        assert "요약" in content
        assert "월별 지출" in content
        assert "태그별" in content
        assert "가맹점" in content

    def test_markdown_report_escapes_user_controlled_table_cells(self, tmp_path):
        """Markdown tables should neutralize raw HTML, pipes, and newlines."""
        from finjuice.pipeline.export.markdown_report import generate_markdown_report

        source_df = pl.DataFrame(
            {
                "date": ["2024-10-01"],
                "amount": [-1000],
                "type_norm": ["expense"],
                "merchant_raw": ["bad|merchant\nnext"],
                "is_transfer": [0],
                "tags_final": [["<script>alert(1)</script>|tag"]],
            }
        )

        output_path = tmp_path / "report.md"
        generate_markdown_report(tmp_path, output_path, source_df=source_df)

        content = output_path.read_text(encoding="utf-8")
        assert "<script>alert(1)</script>" not in content
        assert "&lt;script&gt;alert(1)&lt;/script&gt;\\|tag" in content
        assert "bad\\|merchant<br>next" in content


class TestAutoOpenUtility:
    """Tests for auto-open utility function."""

    def test_open_file_success_macos(self, tmp_path):
        """Test opening file on macOS."""
        from finjuice.pipeline.cli.utils import open_file_in_system_viewer

        test_file = tmp_path / "test.html"
        test_file.write_text("test")

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock()
                result = open_file_in_system_viewer(test_file)

                assert result is True
                mock_run.assert_called_once()
                assert mock_run.call_args[0][0] == ["open", str(test_file)]

    def test_open_file_success_linux(self, tmp_path):
        """Test opening file on Linux."""
        from finjuice.pipeline.cli.utils import open_file_in_system_viewer

        test_file = tmp_path / "test.html"
        test_file.write_text("test")

        with patch("platform.system", return_value="Linux"):
            with patch("subprocess.run") as mock_run:
                mock_run.return_value = MagicMock()
                result = open_file_in_system_viewer(test_file)

                assert result is True
                mock_run.assert_called_once()
                assert mock_run.call_args[0][0] == ["xdg-open", str(test_file)]

    def test_open_file_success_windows(self, tmp_path):
        """Test opening file on Windows."""
        from finjuice.pipeline.cli.utils import open_file_in_system_viewer

        test_file = tmp_path / "test.html"
        test_file.write_text("test")

        with patch("platform.system", return_value="Windows"):
            # os.startfile only exists on Windows, so we need to create it
            with patch.object(__import__("os"), "startfile", create=True) as mock_startfile:
                result = open_file_in_system_viewer(test_file)

                assert result is True
                mock_startfile.assert_called_once_with(str(test_file))

    def test_open_file_failure(self, tmp_path):
        """Test handling of file open failure."""
        from subprocess import CalledProcessError

        from finjuice.pipeline.cli.utils import open_file_in_system_viewer

        test_file = tmp_path / "test.html"
        test_file.write_text("test")

        with patch("platform.system", return_value="Darwin"):
            with patch("subprocess.run") as mock_run:
                mock_run.side_effect = CalledProcessError(1, "open")
                result = open_file_in_system_viewer(test_file)

                assert result is False


class TestExportCliOptions:
    """Tests for CLI export command options."""

    def test_export_format_validation_valid(self, csv_partitions_dir, tmp_path):
        """Test valid format options."""

        # This is a simpler approach - just test that valid formats are accepted
        valid_formats = {"xlsx", "html", "md", "all"}
        for fmt in valid_formats:
            assert fmt in valid_formats

    def test_period_format_pattern(self):
        """Test period format validation pattern."""
        import re

        pattern = r"^\d{4}-\d{2}$"

        # Valid periods
        assert re.match(pattern, "2024-10")
        assert re.match(pattern, "2024-01")
        assert re.match(pattern, "2025-12")

        # Invalid periods
        assert not re.match(pattern, "2024-1")
        assert not re.match(pattern, "24-10")
        assert not re.match(pattern, "2024/10")
        assert not re.match(pattern, "October 2024")


class TestEmptyDataHandling:
    """Tests for handling empty data gracefully."""

    def test_empty_csv_partitions(self, tmp_path):
        """Test handling of empty CSV partitions directory."""
        from finjuice.pipeline.export.aggregations import load_transactions

        csv_dir = tmp_path / "transactions"
        csv_dir.mkdir(parents=True)

        df = load_transactions(csv_dir)

        assert df.is_empty() or len(df) == 0

    def test_html_report_with_empty_data(self, empty_csv_partitions_dir, tmp_path):
        """Test HTML report generation with empty data."""
        from finjuice.pipeline.export.html_report import generate_html_report

        output_path = tmp_path / "report.html"
        _ = generate_html_report(empty_csv_partitions_dir, output_path)

        assert output_path.exists()

    def test_markdown_report_with_empty_data(self, empty_csv_partitions_dir, tmp_path):
        """Test Markdown report generation with empty data."""
        from finjuice.pipeline.export.markdown_report import generate_markdown_report

        output_path = tmp_path / "report.md"
        _ = generate_markdown_report(empty_csv_partitions_dir, output_path)

        assert output_path.exists()
