"""Fast-mode coverage for the cheap checkup posture path."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from finjuice.pipeline.checkup.compose import NAMED_COLLECTORS, collect_checkup_bundle
from finjuice.pipeline.checkup.models import FAST_SKIP_WARNING
from finjuice.pipeline.config import Config
from tests.pipeline.checkup.helpers import init_data_dir


def test_collect_checkup_bundle_fast_skips_review_and_obligations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--fast must not invoke full review/obligation detectors."""

    def boom(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("expensive collector should not run")

    monkeypatch.setitem(NAMED_COLLECTORS, "review", boom)
    monkeypatch.setitem(NAMED_COLLECTORS, "obligations", boom)
    config = Config(data_dir=init_data_dir(tmp_path, "fast"))

    bundle = collect_checkup_bundle(config, today=date(2026, 4, 18), fast=True)

    assert bundle.review.status == "skipped"
    assert bundle.review.actionable is False
    assert bundle.obligations.status == "skipped"
    assert bundle.obligations.actionable is False
    assert FAST_SKIP_WARNING in bundle.warnings


def test_collect_checkup_bundle_default_still_runs_full_detectors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Default checkup must keep invoking review and obligations collectors."""
    called: list[str] = []
    original_review = NAMED_COLLECTORS["review"]
    original_obligations = NAMED_COLLECTORS["obligations"]

    def tracking_review(*args: object, **kwargs: object) -> object:
        called.append("review")
        return original_review(*args, **kwargs)

    def tracking_obligations(*args: object, **kwargs: object) -> object:
        called.append("obligations")
        return original_obligations(*args, **kwargs)

    monkeypatch.setitem(NAMED_COLLECTORS, "review", tracking_review)
    monkeypatch.setitem(NAMED_COLLECTORS, "obligations", tracking_obligations)
    config = Config(data_dir=init_data_dir(tmp_path, "full"))

    bundle = collect_checkup_bundle(config, today=date(2026, 4, 18))

    assert called == ["review", "obligations"]
    assert bundle.review.status == "empty"
    assert bundle.obligations.status == "empty"
    assert FAST_SKIP_WARNING not in bundle.warnings
