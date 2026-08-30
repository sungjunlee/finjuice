"""Structure checks for the split rules.yaml IO implementation."""

from pathlib import Path

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")


def test_report_filter_helpers_live_in_helper_module() -> None:
    """report_filters schema parsing should not live in rules_yaml_io.py."""
    io_text = (TAGGING_DIR / "rules_yaml_io.py").read_text(encoding="utf-8")
    filters_text = (TAGGING_DIR / "rules_yaml_filters.py").read_text(encoding="utf-8")

    assert "def load_report_filters" in io_text
    assert "def load_rules" in io_text
    assert "def load_rules_collecting" in io_text
    assert "def save_rules" in io_text
    assert "def append_rule" in io_text
    assert "def _raise_filters_validation_error" not in io_text
    assert "def _parse_excluded_merchant_filter" not in io_text
    assert "def _parse_excluded_category_filter" not in io_text
    assert "def _parse_excluded_date_range_filter" not in io_text
    assert "def _raise_filters_validation_error" in filters_text
    assert "def _parse_excluded_merchant_filter" in filters_text
    assert "def _parse_excluded_category_filter" in filters_text
    assert "def _parse_excluded_date_range_filter" in filters_text
    assert "def _parse_report_filters" in filters_text


def test_tagging_modules_do_not_import_cli() -> None:
    """Tagging pipeline modules must not import finjuice.pipeline.cli.*."""
    for path in sorted(TAGGING_DIR.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from finjuice.pipeline.cli" not in stripped
            assert "import finjuice.pipeline.cli" not in stripped
