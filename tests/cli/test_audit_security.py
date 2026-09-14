"""Path-safety regressions for CLI audit appends."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from finjuice.pipeline.cli import audit_log


def test_general_audit_append_rejects_symlink_without_changing_target(tmp_path: Path) -> None:
    data_dir = (tmp_path / "data").resolve()
    data_dir.mkdir()
    outside = tmp_path / "outside"
    outside.write_bytes(b"unchanged")
    (data_dir / ".execution_audit.jsonl").symlink_to(outside)

    with pytest.raises(OSError, match="opened safely"):
        audit_log.append_audit_event(data_dir, {"event": "synthetic"})

    assert outside.read_bytes() == b"unchanged"


@pytest.mark.parametrize("alias_kind", ["symlink", "hardlink"])
def test_financial_audit_alias_failure_is_best_effort_and_target_is_unchanged(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    data_dir = (tmp_path / "inactive").resolve()
    data_dir.mkdir()
    outside = tmp_path / "active-database"
    outside.write_bytes(b"sqlite sentinel unchanged")
    audit_path = data_dir / ".execution_audit.jsonl"
    if alias_kind == "symlink":
        audit_path.symlink_to(outside)
    else:
        os.link(outside, audit_path)

    audit_log.append_financial_mutation_event(data_dir, {"command": "synthetic"})

    assert outside.read_bytes() == b"sqlite sentinel unchanged"


def test_audit_append_detects_final_entry_replacement_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = (tmp_path / "data").resolve()
    data_dir.mkdir()
    audit_path = data_dir / ".execution_audit.jsonl"
    moved = tmp_path / "original-audit"
    raced = tmp_path / "raced-audit"
    audit_path.write_bytes(b"original\n")
    raced.write_bytes(b"raced unchanged\n")
    real_open = os.open

    def replace_then_open(path: Path, flags: int, mode: int = 0o777) -> int:
        if Path(path) == audit_path:
            audit_path.rename(moved)
            raced.rename(audit_path)
        return real_open(path, flags, mode)

    monkeypatch.setattr(audit_log.os, "open", replace_then_open)

    with pytest.raises(OSError, match="changed while it was opened"):
        audit_log.append_audit_event(data_dir, {"event": "synthetic"})

    assert moved.read_bytes() == b"original\n"
    assert audit_path.read_bytes() == b"raced unchanged\n"


def test_partial_audit_write_failure_preserves_existing_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = (tmp_path / "data").resolve()
    data_dir.mkdir()
    audit_path = data_dir / ".execution_audit.jsonl"
    original = b'{"event":"existing"}\n'
    audit_path.write_bytes(original)
    real_write = os.write
    calls = 0

    def fail_after_partial_write(descriptor: int, content: Any) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, bytes(content[:4]))
        raise OSError("synthetic append failure")

    monkeypatch.setattr(audit_log.os, "write", fail_after_partial_write)

    with pytest.raises(OSError, match="before the event was complete"):
        audit_log.append_audit_event(data_dir, {"event": "synthetic"})

    assert audit_path.read_bytes() == original + b'{"ev'


@pytest.mark.parametrize("existing", [False, True])
def test_partial_append_cleanup_preserves_another_successful_append(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    existing: bool,
) -> None:
    data_dir = (tmp_path / "data").resolve()
    data_dir.mkdir()
    audit_path = data_dir / ".execution_audit.jsonl"
    if existing:
        audit_path.write_bytes(b'{"event":"existing"}\n')
    real_write = os.write
    calls = 0

    def interleave_then_fail(descriptor: int, content: Any) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, bytes(content[:1]))
        if calls == 2:
            audit_log.append_audit_event(data_dir, {"event": "concurrent"})
            raise OSError("synthetic first append failure")
        return real_write(descriptor, content)

    monkeypatch.setattr(audit_log.os, "write", interleave_then_fail)

    with pytest.raises(OSError, match="before the event was complete"):
        audit_log.append_audit_event(data_dir, {"event": "failing"})

    assert audit_path.read_bytes().endswith(b'{"event": "concurrent"}\n')
