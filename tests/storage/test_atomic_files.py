"""Fault-injection tests for owned sibling staging files."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from finjuice.pipeline.storage import atomic_files

_SOURCE_STAMP_NS = 1_000_000_000_123_456_789


def test_replace_with_owned_temp_preserves_content_and_mode(tmp_path: Path) -> None:
    target = tmp_path / "rules.yaml"
    target.write_bytes(b"before\n")
    target.chmod(0o640)

    atomic_files.replace_with_owned_temp(target, b"after\n")

    assert target.read_bytes() == b"after\n"
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert list(tmp_path.glob(".rules.yaml.*.tmp")) == []


def test_partial_staging_write_preserves_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "goals.yaml"
    original = b"original goals\n"
    target.write_bytes(original)
    real_write = os.write
    calls = 0

    def fail_after_partial_write(descriptor: int, content: Any) -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_write(descriptor, bytes(content[:3]))
        raise OSError("synthetic write failure")

    monkeypatch.setattr(atomic_files.os, "write", fail_after_partial_write)

    with pytest.raises(OSError, match="synthetic write failure"):
        atomic_files.replace_with_owned_temp(target, b"replacement content\n")

    assert target.read_bytes() == original
    assert list(tmp_path.glob(".goals.yaml.*.tmp")) == []


def test_replace_failure_preserves_target_and_cleans_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "rules.yaml"
    original = b"original rules\n"
    target.write_bytes(original)

    def fail_replace(*_args: object, **_kwargs: object) -> None:
        raise OSError("synthetic replace failure")

    monkeypatch.setattr(atomic_files.os, "replace", fail_replace)

    with pytest.raises(OSError, match="synthetic replace failure"):
        atomic_files.replace_with_owned_temp(target, b"replacement content\n")

    assert target.read_bytes() == original
    assert list(tmp_path.glob(".rules.yaml.*.tmp")) == []


def test_precreated_staging_symlink_is_never_followed_or_removed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "rules.yaml"
    outside = tmp_path / "outside"
    target.write_bytes(b"original\n")
    outside.write_bytes(b"outside unchanged\n")
    staging = tmp_path / ".rules.yaml.fixed.tmp"
    staging.symlink_to(outside)
    monkeypatch.setattr(
        atomic_files.uuid,
        "uuid4",
        lambda: SimpleNamespace(hex="fixed"),
    )

    with pytest.raises(OSError, match="could not be created safely"):
        atomic_files.replace_with_owned_temp(target, b"replacement\n")

    assert target.read_bytes() == b"original\n"
    assert outside.read_bytes() == b"outside unchanged\n"
    assert staging.is_symlink()


def test_optional_metadata_sets_times_and_mode_before_publish(tmp_path: Path) -> None:
    target = tmp_path / "archive.xlsx"
    target.write_bytes(b"old\n")
    target.chmod(0o600)
    os.utime(target, ns=(1, 1))
    metadata = atomic_files.OwnedTempMetadata(
        atime_ns=_SOURCE_STAMP_NS, mtime_ns=_SOURCE_STAMP_NS, mode=0o640
    )

    atomic_files.replace_with_owned_temp(target, b"new\n", metadata=metadata)

    assert target.stat().st_mtime_ns == _SOURCE_STAMP_NS
    assert target.stat().st_atime_ns == _SOURCE_STAMP_NS
    assert stat.S_IMODE(target.stat().st_mode) == 0o640
    assert target.read_bytes() == b"new\n"
    assert list(tmp_path.glob(".archive.xlsx.*.tmp")) == []


def test_metadata_write_failure_preserves_bytes_and_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, original = _stamped_target(tmp_path)
    monkeypatch.setattr(atomic_files.os, "write", _fail_os("synthetic write failure"))

    with pytest.raises(OSError, match="synthetic write failure"):
        atomic_files.replace_with_owned_temp(target, b"new\n", metadata=_stamp_metadata())

    _assert_preserved(target, original)
    assert list(tmp_path.glob(".archive.xlsx.*.tmp")) == []


def test_metadata_apply_failure_preserves_bytes_and_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, original = _stamped_target(tmp_path)
    monkeypatch.setattr(atomic_files, "_apply_owned_times", _fail_os("synthetic metadata failure"))

    with pytest.raises(OSError, match="synthetic metadata failure"):
        atomic_files.replace_with_owned_temp(target, b"new\n", metadata=_stamp_metadata())

    _assert_preserved(target, original)
    assert list(tmp_path.glob(".archive.xlsx.*.tmp")) == []


def test_metadata_replace_failure_preserves_bytes_and_mtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, original = _stamped_target(tmp_path)
    monkeypatch.setattr(atomic_files.os, "replace", _fail_os("synthetic replace failure"))

    with pytest.raises(OSError, match="synthetic replace failure"):
        atomic_files.replace_with_owned_temp(target, b"new\n", metadata=_stamp_metadata())

    _assert_preserved(target, original)
    assert list(tmp_path.glob(".archive.xlsx.*.tmp")) == []


def test_metadata_precreated_staging_symlink_is_never_followed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target, original = _stamped_target(tmp_path)
    outside = tmp_path / "outside"
    outside.write_bytes(b"outside unchanged\n")
    staging = tmp_path / ".archive.xlsx.fixed.tmp"
    staging.symlink_to(outside)
    monkeypatch.setattr(atomic_files.uuid, "uuid4", lambda: SimpleNamespace(hex="fixed"))

    with pytest.raises(OSError, match="could not be created safely"):
        atomic_files.replace_with_owned_temp(target, b"new\n", metadata=_stamp_metadata())

    _assert_preserved(target, original)
    assert outside.read_bytes() == b"outside unchanged\n"
    assert staging.is_symlink()


def _stamped_target(tmp_path: Path) -> tuple[Path, bytes]:
    target = tmp_path / "archive.xlsx"
    original = b"original archive\n"
    target.write_bytes(original)
    os.utime(target, ns=(_SOURCE_STAMP_NS, _SOURCE_STAMP_NS))
    return target, original


def _stamp_metadata() -> atomic_files.OwnedTempMetadata:
    return atomic_files.OwnedTempMetadata(
        atime_ns=_SOURCE_STAMP_NS + 1, mtime_ns=_SOURCE_STAMP_NS + 1, mode=0o640
    )


def _fail_os(message: str) -> Any:
    def fail(*_args: object, **_kwargs: object) -> Any:
        raise OSError(message)

    return fail


def _assert_preserved(target: Path, original: bytes) -> None:
    assert target.read_bytes() == original
    assert target.stat().st_mtime_ns == _SOURCE_STAMP_NS
