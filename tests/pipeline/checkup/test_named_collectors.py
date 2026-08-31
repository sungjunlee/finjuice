"""Identity coverage for the checkup named-collector helper split."""

from pathlib import Path

from finjuice.pipeline.checkup import compose, named_collectors

CHECKUP_DIR = Path("src/finjuice/pipeline/checkup")

_NAMED_COLLECTOR_HELPERS = (
    "NAMED_COLLECTORS",
    "run_named_collector",
)


def test_named_collector_helpers_live_in_helper_module() -> None:
    """Named collector registry/runner should not live in the composer module."""
    compose_text = (CHECKUP_DIR / "compose.py").read_text(encoding="utf-8")
    helpers_text = (CHECKUP_DIR / "named_collectors.py").read_text(encoding="utf-8")

    assert "def collect_checkup_bundle" in compose_text
    assert "def _collect_warnings" in compose_text
    assert "def _build_next_actions" not in compose_text
    assert "def run_named_collector" not in compose_text
    assert "NAMED_COLLECTORS: dict[str, Callable[..., Any]] =" not in compose_text

    assert "def run_named_collector" in helpers_text
    assert "NAMED_COLLECTORS: dict[str, Callable[..., Any]] =" in helpers_text
    assert "def collect_checkup_bundle" not in helpers_text
    assert "def _collect_warnings" not in helpers_text
    assert "def _build_next_actions" not in helpers_text


def test_named_collector_helpers_reexport_from_compose() -> None:
    """Existing compose imports should keep resolving to the helper definitions."""
    compose_text = (CHECKUP_DIR / "compose.py").read_text(encoding="utf-8")

    for name in _NAMED_COLLECTOR_HELPERS:
        assert name in compose_text
        assert getattr(compose, name) is getattr(named_collectors, name)

    assert callable(compose.collect_checkup_bundle)
    assert callable(compose.run_named_collector)
    assert callable(compose._collect_warnings)
    assert callable(compose._build_next_actions)
