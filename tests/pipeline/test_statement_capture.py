"""Bound staged JSON reads before decoding, including files that grow during reads."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finjuice.pipeline.statements import staged
from finjuice.pipeline.storage.sqlite import backup_io


def test_statement_capture_accepts_exact_byte_limit(tmp_path: Path, monkeypatch) -> None:
    content = json.dumps({"schema_version": "finjuice.statement.v1"}).encode()
    path = tmp_path / "statement.json"
    path.write_bytes(content)
    monkeypatch.setattr(staged, "MAX_STATEMENT_BYTES", len(content))

    capture = staged.capture_statement(path)

    assert capture is not None and capture.content == content
    assert backup_io.read_regular_bytes(path) == content


def test_oversized_statement_is_rejected_before_read_or_decode(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "oversized.json"
    path.write_bytes(b" " * 9)
    monkeypatch.setattr(staged, "MAX_STATEMENT_BYTES", 8)

    def forbidden(*args, **kwargs):
        pytest.fail("Oversized bytes must not be read or decoded")

    monkeypatch.setattr(backup_io.os, "read", forbidden)
    monkeypatch.setattr(staged.json, "loads", forbidden)
    assert staged.capture_statement(path) is None


def test_growing_read_stops_after_one_byte_beyond_budget(tmp_path: Path, monkeypatch) -> None:
    path = tmp_path / "growing.json"
    path.write_bytes(b"")
    requested = []
    consumed = []

    def growing_read(descriptor: int, size: int) -> bytes:
        requested.append(size)
        return b"x" * min(size, 3)

    monkeypatch.setattr(backup_io.os, "read", growing_read)
    with pytest.raises(backup_io.BackupPayloadError) as error:
        backup_io._read(path, consumed.append, max_bytes=8)

    assert error.value.reason == "payload_too_large"
    assert requested == [9, 6, 3]
    assert sum(min(size, 3) for size in requested) == 9
    assert b"".join(consumed) == b"x" * 6


def test_statement_capture_preserves_symlink_rejection(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    content = b'{"schema_version":"finjuice.statement.v1"}'
    target.write_bytes(content)
    link = tmp_path / "link.json"
    link.symlink_to(target)

    assert staged.capture_statement(link) is None
    assert link.is_symlink()
    assert target.read_bytes() == content
