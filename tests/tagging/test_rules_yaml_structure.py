"""Structure checks for the split rules.yaml IO implementation."""

from pathlib import Path

from finjuice.pipeline.tagging import (
    rules_yaml_append,
    rules_yaml_io,
    rules_yaml_load,
    rules_yaml_save,
)

TAGGING_DIR = Path("src/finjuice/pipeline/tagging")

LOAD_SAVE_APPEND_DEFS = (
    ("load_rules", "rules_yaml_load.py", rules_yaml_load),
    ("load_rules_collecting", "rules_yaml_load.py", rules_yaml_load),
    ("save_rules", "rules_yaml_save.py", rules_yaml_save),
    ("append_rule", "rules_yaml_append.py", rules_yaml_append),
)


def test_report_filter_helpers_live_in_helper_module() -> None:
    """report_filters schema parsing should not live in rules_yaml_io.py."""
    io_text = (TAGGING_DIR / "rules_yaml_io.py").read_text(encoding="utf-8")
    filters_text = (TAGGING_DIR / "rules_yaml_filters.py").read_text(encoding="utf-8")

    assert "def load_report_filters" in io_text
    assert "def _raise_filters_validation_error" not in io_text
    assert "def _parse_excluded_merchant_filter" not in io_text
    assert "def _parse_excluded_category_filter" not in io_text
    assert "def _parse_excluded_date_range_filter" not in io_text
    assert "def _parse_report_filters" in filters_text


def test_load_save_append_defs_do_not_leak_into_rules_yaml_io() -> None:
    """load/save/append function bodies must live in sibling modules, not io."""
    io_text = (TAGGING_DIR / "rules_yaml_io.py").read_text(encoding="utf-8")

    assert "def load_report_filters(" in io_text
    assert "def summarize_rule_notes(" in io_text

    for name, sibling_filename, sibling_module in LOAD_SAVE_APPEND_DEFS:
        sibling_text = (TAGGING_DIR / sibling_filename).read_text(encoding="utf-8")
        assert f"def {name}(" not in io_text
        assert f"def {name}(" in sibling_text
        assert name in io_text
        assert getattr(rules_yaml_io, name) is getattr(sibling_module, name)


def test_tagging_modules_do_not_import_cli() -> None:
    """Tagging pipeline modules must not import finjuice.pipeline.cli.*."""
    for path in sorted(TAGGING_DIR.glob("*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            assert "from finjuice.pipeline.cli" not in stripped
            assert "import finjuice.pipeline.cli" not in stripped
