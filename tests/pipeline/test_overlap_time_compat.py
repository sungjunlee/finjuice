"""UTC overlap timestamps use the spelling accepted by Python 3.10."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from finjuice.pipeline.storage.sqlite.exact_import import overlap


@pytest.mark.parametrize(
    ("text", "normalized"),
    [
        ("2026-09-01T04:04:05Z", "2026-09-01T04:04:05+00:00"),
        ("2026-09-01T13:04:05+09:00", "2026-09-01T13:04:05+09:00"),
        ("2026-09-01", "2026-09-01"),
    ],
)
def test_overlap_normalizes_only_trailing_utc_z(monkeypatch, text: str, normalized: str) -> None:
    class Python310Datetime:
        @staticmethod
        def fromisoformat(value: str) -> datetime:
            assert value == normalized
            if value.endswith("Z"):
                raise ValueError("Python 3.10 does not accept Z")
            return datetime.fromisoformat(value)

    monkeypatch.setattr(overlap, "datetime", Python310Datetime)
    assert overlap._parse_instant(text) == datetime.fromisoformat(normalized)


def test_utc_z_and_offset_represent_the_same_overlap_instant() -> None:
    utc = overlap._parse_instant("2026-09-01T04:04:05Z")
    offset = overlap._parse_instant("2026-09-01T13:04:05+09:00")
    assert utc is not None and offset is not None
    assert utc.utcoffset() == timezone.utc.utcoffset(utc)
    assert overlap._same_known_instant(utc, offset)
