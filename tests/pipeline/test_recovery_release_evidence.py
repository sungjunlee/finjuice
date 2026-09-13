"""Exact release evidence checks use only synthetic byte inputs."""

import hashlib
import io
import json
import stat
import struct
import warnings
import zipfile
import zlib
from pathlib import Path

import pytest

from finjuice.pipeline.storage.authority import ActivationEvidence
from finjuice.pipeline.storage.sqlite import recovery_release_evidence as module
from finjuice.pipeline.storage.sqlite.errors import BackupVerificationError


def _digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _wheel(*, name="finjuice", version="1.2.3", extra=None) -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(
            "finjuice-1.2.3.dist-info/METADATA",
            f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n\n",
        )
        archive.writestr("finjuice/__init__.py", b"# synthetic")
        if extra is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", UserWarning)
                archive.writestr(extra, b"content")
    return stream.getvalue()


def _inputs(tmp_path: Path, *, wheel=None, changes=None, raw_transform=None):
    wheel = wheel if wheel is not None else _wheel()
    lock = b"version = 1\n# synthetic dependency lock\n"
    binding = {
        "binding_schema_version": 1,
        "package_name": "finjuice",
        "release_version": "1.2.3",
        "release_artifact_sha256": _digest(wheel),
        "dependency_lock_sha256": _digest(lock),
        "source_commit": "a" * 40,
        "build_id": "approved-build.123",
    }
    binding.update(changes or {})
    raw = json.dumps(binding).encode()
    if raw_transform:
        raw = raw_transform(raw)
    paths = module.ReleaseArtifactPaths(
        tmp_path / "release.whl", tmp_path / "dependency.lock", tmp_path / "binding.json"
    )
    for path, data in [(paths.wheel, wheel), (paths.dependency_lock, lock), (paths.binding, raw)]:
        path.write_bytes(data)
    evidence = ActivationEvidence("1.2.3", _digest(wheel), "b" * 64, "c" * 64)
    return paths, module.TrustedReleaseBinding(_digest(raw), evidence)


def test_verified_bytes_are_read_once_and_remain_detached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, expected = _inputs(tmp_path)
    original = module.read_regular_bytes
    reads = []

    def read(path):
        reads.append(path)
        return original(path)

    monkeypatch.setattr(module, "read_regular_bytes", read)
    result = module.verify_release_artifacts(paths, expected)
    assert reads == [paths.binding, paths.wheel, paths.dependency_lock]
    saved = result.wheel_bytes, result.dependency_lock_bytes, result.binding_bytes
    for path in reads:
        path.write_bytes(b"PRIVATE_CHANGED")
    assert saved == (result.wheel_bytes, result.dependency_lock_bytes, result.binding_bytes)
    assert result.release_artifact_sha256 == _digest(result.wheel_bytes)
    assert "synthetic" not in repr(result) and "PRIVATE" not in repr(result)


@pytest.mark.parametrize(
    "changes",
    [
        {"binding_schema_version": True},
        {"binding_schema_version": 2},
        {"package_name": "other"},
        {"release_version": "2"},
        {"release_artifact_sha256": "1" * 64},
        {"dependency_lock_sha256": "1" * 64},
        {"source_commit": "bad"},
        {"build_id": ""},
        {"build_id": "x" * 129},
        {"extra": 1},
    ],
)
def test_bad_binding_is_static(tmp_path: Path, changes) -> None:
    paths, expected = _inputs(tmp_path, changes=changes)
    with pytest.raises(BackupVerificationError, match="^Release artifacts do not match"):
        module.verify_release_artifacts(paths, expected)


@pytest.mark.parametrize(
    "transform",
    [
        lambda raw: raw.replace(b'"package_name": "finjuice", ', b""),
        lambda raw: b'{"package_name":"finjuice",' + raw[1:],
        lambda raw: b"PRIVATE_BAD_JSON",
        lambda raw: b"\xff",
    ],
)
def test_missing_duplicate_and_unreadable_binding(tmp_path: Path, transform) -> None:
    paths, expected = _inputs(tmp_path, raw_transform=transform)
    with pytest.raises(BackupVerificationError) as error:
        module.verify_release_artifacts(paths, expected)
    assert "PRIVATE_BAD" not in str(error.value)


def test_independent_raw_hash_not_binding_selfhash(tmp_path: Path) -> None:
    paths, expected = _inputs(tmp_path)
    changed = module.TrustedReleaseBinding("0" * 64, expected.activation_evidence)
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, changed)
    paths.binding.write_bytes(paths.binding.read_bytes() + b"\n")
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


@pytest.mark.parametrize("field", ["wheel", "dependency_lock"])
def test_changed_file_hash_rejected(tmp_path: Path, field: str) -> None:
    paths, expected = _inputs(tmp_path)
    getattr(paths, field).write_bytes(b"arbitrary unbound bytes")
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


@pytest.mark.parametrize(
    "metadata", [{"name": "other"}, {"version": "9"}, {"version": "1.2.3\nVersion: 1.2.3"}]
)
def test_wheel_metadata_must_match(tmp_path: Path, metadata) -> None:
    paths, expected = _inputs(tmp_path, wheel=_wheel(**metadata))
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


@pytest.mark.parametrize(
    "member",
    [
        "../escape",
        "/absolute",
        "a\\b",
        "C:/drive",
        "a//b",
        "a/./b",
        "finjuice/__init__.py",
        "other-1.dist-info/METADATA",
    ],
)
def test_unsafe_or_duplicate_zip_inventory(tmp_path: Path, member: str) -> None:
    paths, expected = _inputs(tmp_path, wheel=_wheel(extra=member))
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


@pytest.mark.parametrize("mode", [stat.S_IFLNK, stat.S_IFIFO, stat.S_IFSOCK])
def test_zip_special_member_rejected(tmp_path: Path, mode: int) -> None:
    entry = zipfile.ZipInfo("unsafe")
    entry.create_system = 3
    entry.external_attr = (mode | 0o600) << 16
    paths, expected = _inputs(tmp_path, wheel=_wheel(extra=entry))
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


@pytest.mark.parametrize("case", ["missing", "symlink", "changing"])
def test_unsafe_files_static(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str) -> None:
    paths, expected = _inputs(tmp_path)
    if case == "missing":
        paths.wheel.unlink()
    elif case == "symlink":
        paths.wheel.unlink()
        paths.wheel.symlink_to(paths.dependency_lock)
    else:

        def changed(path):
            raise OSError("PRIVATE_PATH changing file")

        monkeypatch.setattr(module, "read_regular_bytes", changed)
    with pytest.raises(BackupVerificationError) as error:
        module.verify_release_artifacts(paths, expected)
    assert "PRIVATE_PATH" not in str(error.value)


def test_duplicate_name_metadata_rejected(tmp_path: Path) -> None:
    paths, expected = _inputs(tmp_path, wheel=_wheel(name="finjuice\nName: finjuice"))
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


def test_changed_regular_file_during_read_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import os

    paths, expected = _inputs(tmp_path)
    wheel = paths.wheel.read_bytes()
    original = os.read

    def read(fd, count):
        chunk = original(fd, count)
        if chunk == wheel:
            paths.wheel.write_bytes(wheel + b"changed")
        return chunk

    monkeypatch.setattr(os, "read", read)
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


def test_sixty_four_character_source_commit_is_supported(tmp_path: Path) -> None:
    paths, expected = _inputs(tmp_path, changes={"source_commit": "a" * 64})
    assert module.verify_release_artifacts(paths, expected).source_commit == "a" * 64


def test_unreadable_zip_and_missing_metadata_are_static(tmp_path: Path) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("ordinary.txt", b"content")
    for wheel in (b"PRIVATE_NOT_ZIP", stream.getvalue()):
        paths, expected = _inputs(tmp_path, wheel=wheel)
        with pytest.raises(BackupVerificationError) as error:
            module.verify_release_artifacts(paths, expected)
        assert "PRIVATE_NOT_ZIP" not in str(error.value)


@pytest.mark.parametrize(
    "alias",
    ["../escape", "/absolute", "a\\b", "C:/drive", "a//b", "a/./b", "hidden.txt"],
)
def test_unicode_zip_path_alias_rejected(tmp_path: Path, alias: str) -> None:
    entry = zipfile.ZipInfo("safe.txt")
    payload = struct.pack("<BL", 1, zlib.crc32(b"safe.txt")) + alias.encode()
    entry.extra = struct.pack("<HH", 0x7075, len(payload)) + payload
    paths, expected = _inputs(tmp_path, wheel=_wheel(extra=entry))
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)


@pytest.mark.parametrize("extra", [b"x", b"xx", b"xxx", b"\x01\x00\x03\x00x"])
def test_malformed_zip_extra_rejected(tmp_path: Path, extra: bytes) -> None:
    entry = zipfile.ZipInfo("safe.txt")
    entry.extra = extra
    paths, expected = _inputs(tmp_path, wheel=_wheel(extra=entry))
    with pytest.raises(BackupVerificationError):
        module.verify_release_artifacts(paths, expected)
