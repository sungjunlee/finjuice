"""Structure tests for the forecast.py lifecycle/opening event helper split.

Lifecycle and opening-event apply helpers live in ``forecast_events`` and must
stay identity-equal when re-exported from ``forecast``, so existing import
paths and monkeypatches keep working after the split. The split also keeps
``forecast_events`` as the single canonical home for the moved cluster.
"""

from __future__ import annotations

import importlib
from pathlib import Path

PIPELINE_DIR = Path("src/finjuice/pipeline")


def test_forecast_reexports_event_helpers_identity() -> None:
    """Event apply helpers stay on forecast as re-exports after the split."""
    forecast = importlib.import_module("finjuice.pipeline.forecast")
    events = importlib.import_module("finjuice.pipeline.forecast_events")

    assert forecast.ForecastEventHit is events.ForecastEventHit
    assert forecast._apply_opening_one_shot_events is events._apply_opening_one_shot_events
    assert forecast._apply_lifecycle_events is events._apply_lifecycle_events
    assert forecast._monthly_event_is_active is events._monthly_event_is_active
    assert forecast._resolve_target_reached_at is events._resolve_target_reached_at
    assert callable(forecast.build_forecast)
    assert callable(forecast.load_scenarios_config)
    assert callable(forecast.serialize_forecast_result)


def test_forecast_events_is_the_unique_home_for_moved_helpers() -> None:
    """The moved cluster is defined exactly once, in forecast_events."""
    events = importlib.import_module("finjuice.pipeline.forecast_events")
    canonical = "finjuice.pipeline.forecast_events"

    assert events.ForecastEventHit.__module__ == canonical
    assert events._apply_opening_one_shot_events.__module__ == canonical
    assert events._apply_lifecycle_events.__module__ == canonical
    assert events._monthly_event_is_active.__module__ == canonical
    assert events._resolve_target_reached_at.__module__ == canonical


def test_event_helpers_live_in_helper_module() -> None:
    """Lifecycle/opening event apply helpers should not live in forecast.py."""
    forecast_text = (PIPELINE_DIR / "forecast.py").read_text(encoding="utf-8")
    events_text = (PIPELINE_DIR / "forecast_events.py").read_text(encoding="utf-8")

    assert "def build_forecast" in forecast_text
    assert "def load_scenarios_config" in forecast_text
    assert "def serialize_forecast_result" in forecast_text
    assert "def _apply_opening_one_shot_events" not in forecast_text
    assert "def _apply_lifecycle_events" not in forecast_text
    assert "def _monthly_event_is_active" not in forecast_text
    assert "def _resolve_target_reached_at" not in forecast_text
    assert "def build_forecast" not in events_text
    assert "def load_scenarios_config" not in events_text
    assert "def serialize_forecast_result" not in events_text
    assert "def _apply_opening_one_shot_events" in events_text
    assert "def _apply_lifecycle_events" in events_text
    assert "def _monthly_event_is_active" in events_text
    assert "def _resolve_target_reached_at" in events_text
