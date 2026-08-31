"""Identity coverage for the checkup warning-collection helper split."""

from pathlib import Path

from finjuice.pipeline.checkup import compose, warnings

CHECKUP_DIR = Path("src/finjuice/pipeline/checkup")

_WARNING_HELPERS = ("_collect_warnings",)


def test_warning_helpers_live_in_helper_module() -> None:
    """Warning aggregation helpers should not live in the composer module."""
    compose_text = (CHECKUP_DIR / "compose.py").read_text(encoding="utf-8")
    helpers_text = (CHECKUP_DIR / "warnings.py").read_text(encoding="utf-8")

    assert "def collect_checkup_bundle" in compose_text
    assert "def _collect_warnings" not in compose_text

    assert "def _collect_warnings" in helpers_text
    assert "def collect_checkup_bundle" not in helpers_text
    assert "def _build_next_actions" not in helpers_text
    assert "def run_named_collector" not in helpers_text
    assert "NAMED_COLLECTORS" not in helpers_text


def test_warning_helpers_reexport_from_compose() -> None:
    """Existing compose imports should keep resolving to the helper definitions."""
    compose_text = (CHECKUP_DIR / "compose.py").read_text(encoding="utf-8")

    for name in _WARNING_HELPERS:
        assert name in compose_text
        assert getattr(compose, name) is getattr(warnings, name)

    assert callable(compose.collect_checkup_bundle)
    assert callable(compose.run_named_collector)
    assert callable(compose._collect_warnings)
    assert callable(compose._build_next_actions)


def test_collect_warnings_deduplicates_in_stable_order() -> None:
    """The helper drops empty messages and repeats while keeping first-seen order."""
    assert warnings._collect_warnings(None, "a", "", "b", "a", None) == ["a", "b"]
    assert compose._collect_warnings("x", "x", "y") == ["x", "y"]
    assert warnings._collect_warnings() == []
