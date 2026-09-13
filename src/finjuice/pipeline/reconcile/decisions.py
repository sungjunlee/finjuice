"""Confirm or withdraw a match without mutating source occurrences."""

from __future__ import annotations

from dataclasses import replace

from finjuice.pipeline.reconcile.models import MatchGroup


def confirm_match(group: MatchGroup) -> MatchGroup:
    """Return a confirmed copy of *group*. Source rows are not modified."""
    return replace(group, decision="confirmed")


def withdraw_match(group: MatchGroup) -> MatchGroup:
    """Return a withdrawn copy of *group*. Source rows are not modified."""
    return replace(group, decision="withdrawn")
