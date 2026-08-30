"""Structure checks for the split aggregations helper implementation."""

from pathlib import Path

from finjuice.pipeline.export import aggregations, aggregations_helpers

EXPORT_DIR = Path("src/finjuice/pipeline/export")


def test_table_aggregations_live_in_helper_module() -> None:
    """Monthly/tag/merchant table aggregations should not live in aggregations.py."""
    aggregations_text = (EXPORT_DIR / "aggregations.py").read_text(encoding="utf-8")
    helpers_text = (EXPORT_DIR / "aggregations_helpers.py").read_text(encoding="utf-8")

    assert "def load_transactions" in aggregations_text
    assert "def calculate_summary_stats" in aggregations_text
    assert "def calculate_monthly_spend" not in aggregations_text
    assert "def calculate_tag_breakdown" not in aggregations_text
    assert "def calculate_top_merchants" not in aggregations_text
    assert "def calculate_monthly_spend" in helpers_text
    assert "def calculate_tag_breakdown" in helpers_text
    assert "def calculate_top_merchants" in helpers_text


def test_table_aggregations_reexport_from_aggregations() -> None:
    """Existing aggregations imports should keep resolving to the helper functions."""
    assert aggregations.calculate_monthly_spend is aggregations_helpers.calculate_monthly_spend
    assert aggregations.calculate_tag_breakdown is aggregations_helpers.calculate_tag_breakdown
    assert aggregations.calculate_top_merchants is aggregations_helpers.calculate_top_merchants
    assert callable(aggregations.load_transactions)
    assert callable(aggregations.calculate_summary_stats)


def test_aggregations_modules_do_not_import_cli() -> None:
    """Export aggregation modules must not import finjuice.pipeline.cli.*."""
    for path in (
        EXPORT_DIR / "aggregations.py",
        EXPORT_DIR / "aggregations_helpers.py",
    ):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from finjuice.pipeline.cli" not in stripped
            assert "import finjuice.pipeline.cli" not in stripped
