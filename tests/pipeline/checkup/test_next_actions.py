"""Identity coverage for the checkup next-action helper split."""

from pathlib import Path

from finjuice.pipeline.checkup import compose, next_actions

CHECKUP_DIR = Path("src/finjuice/pipeline/checkup")

_NEXT_ACTION_HELPERS = (
    "_PRIORITY_ORDER",
    "_build_next_actions",
)


def test_next_action_helpers_live_in_helper_module() -> None:
    """Next-action builders should not live in the composer module."""
    compose_text = (CHECKUP_DIR / "compose.py").read_text(encoding="utf-8")
    helpers_text = (CHECKUP_DIR / "next_actions.py").read_text(encoding="utf-8")

    assert "def collect_checkup_bundle" in compose_text
    assert "def run_named_collector" in compose_text
    assert "def _collect_warnings" in compose_text
    assert "NAMED_COLLECTORS" in compose_text
    assert "def _build_next_actions" not in compose_text
    assert "_PRIORITY_ORDER: dict[ActionPriority, int] =" not in compose_text

    assert "def _build_next_actions" in helpers_text
    assert "_PRIORITY_ORDER: dict[ActionPriority, int] =" in helpers_text


def test_next_action_helpers_reexport_from_compose() -> None:
    """Existing compose imports should keep resolving to the helper definitions."""
    compose_text = (CHECKUP_DIR / "compose.py").read_text(encoding="utf-8")

    for name in _NEXT_ACTION_HELPERS:
        assert name in compose_text
        assert getattr(compose, name) is getattr(next_actions, name)

    assert callable(compose.collect_checkup_bundle)
    assert callable(compose.run_named_collector)
    assert callable(compose._collect_warnings)
    assert callable(compose._build_next_actions)
