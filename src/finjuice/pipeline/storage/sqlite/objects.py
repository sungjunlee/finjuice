"""Content-addressed publication for immutable source bytes."""

from __future__ import annotations

import hashlib
import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Final

from finjuice.pipeline.storage.sqlite.errors import (
    ObjectCorruptionError,
    ObjectStoreError,
    RepositoryPathError,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

_CHUNK_SIZE: Final = 1024 * 1024
_DIGEST_LENGTH: Final = 64


@dataclass(frozen=True)
class SourceArtifact:
    """One verified immutable source object."""

    artifact_id: str
    digest_hex: str
    byte_length: int
    relative_path: str
    reused: bool


class SourceObjectStore:
    """Publish and verify source bytes below one generation object root."""

    def __init__(self, paths: GenerationPaths) -> None:
        self.paths = paths

    def prepare(self) -> None:
        """Create the private object namespace without accepting symlink aliases."""
        _mkdir_checked(self.paths.root)
        _mkdir_checked(self.paths.objects, boundary=self.paths.root)
        _mkdir_checked(self.paths.sha256_objects, boundary=self.paths.root)

    def publish_path(self, source: Path) -> SourceArtifact:
        """Publish one regular source file without following its final symlink."""
        source = source.expanduser().absolute()
        _assert_no_symlink_ancestors(source)
        try:
            before = source.lstat()
        except OSError as exc:
            raise ObjectStoreError("Source artifact could not be inspected safely.") from exc
        if not stat.S_ISREG(before.st_mode):
            raise ObjectStoreError("Source artifact must be a regular file.")
        flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(source, flags)
        except OSError as exc:
            raise ObjectStoreError("Source artifact could not be opened safely.") from exc
        try:
            opened = os.fstat(fd)
            if not stat.S_ISREG(opened.st_mode):
                raise ObjectStoreError("Source artifact must be a regular file.")
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise ObjectStoreError("Source artifact changed while it was opened.")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                return self.publish(stream)
        finally:
            os.close(fd)

    def publish(self, source: BinaryIO) -> SourceArtifact:
        """Stream, hash, fsync, and exclusively publish one immutable object."""
        self.prepare()
        temp_path = self.paths.sha256_objects / f".object-{uuid.uuid4().hex}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            temp_fd = os.open(temp_path, flags, 0o600)
        except OSError as exc:
            raise ObjectStoreError("Object staging file could not be created.") from exc

        digest = hashlib.sha256()
        byte_length = 0
        try:
            while True:
                chunk = source.read(_CHUNK_SIZE)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise ObjectStoreError("Object streams must return bytes.")
                digest.update(chunk)
                byte_length += len(chunk)
                _write_all(temp_fd, chunk)
            os.fchmod(temp_fd, 0o444)
            os.fsync(temp_fd)
        except Exception:
            os.close(temp_fd)
            temp_path.unlink(missing_ok=True)
            raise
        os.close(temp_fd)

        digest_hex = digest.hexdigest()
        target = self.paths.object_path(digest_hex)
        try:
            _mkdir_checked(target.parent, boundary=self.paths.root)
            _assert_real_directory_chain(self.paths.root, target.parent)
            reused = self._publish_or_reuse(temp_path, target, digest_hex, byte_length)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise
        return SourceArtifact(
            artifact_id=f"sha256:{digest_hex}",
            digest_hex=digest_hex,
            byte_length=byte_length,
            relative_path=target.relative_to(self.paths.root).as_posix(),
            reused=reused,
        )

    def verify(self, artifact_id: str, expected_size: int | None = None) -> SourceArtifact:
        """Rehash an existing object and return its verified identity."""
        digest_hex = _parse_artifact_id(artifact_id)
        target = self.paths.object_path(digest_hex)
        _assert_real_directory_chain(self.paths.root, target.parent)
        size, actual_digest = _fingerprint_regular_file(target)
        if actual_digest != digest_hex or (expected_size is not None and size != expected_size):
            raise ObjectCorruptionError("Existing source object does not match its identity.")
        return SourceArtifact(
            artifact_id=artifact_id,
            digest_hex=digest_hex,
            byte_length=size,
            relative_path=target.relative_to(self.paths.root).as_posix(),
            reused=True,
        )

    def _publish_or_reuse(
        self,
        temp_path: Path,
        target: Path,
        digest_hex: str,
        byte_length: int,
    ) -> bool:
        try:
            os.link(temp_path, target, follow_symlinks=False)
        except FileExistsError:
            temp_path.unlink(missing_ok=True)
            self.verify(f"sha256:{digest_hex}", byte_length)
            return True
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise ObjectStoreError("Source object could not be published atomically.") from exc
        try:
            _fsync_directory(target.parent)
        except OSError as exc:
            try:
                target.unlink(missing_ok=True)
                _fsync_directory(target.parent)
            except OSError:
                pass
            raise ObjectStoreError("Source object could not be published durably.") from exc
        try:
            temp_path.unlink()
            _fsync_directory(target.parent)
        except OSError as exc:
            raise ObjectStoreError("Source object could not be published durably.") from exc
        return False


def _parse_artifact_id(artifact_id: str) -> str:
    prefix = "sha256:"
    if not artifact_id.startswith(prefix):
        raise ObjectStoreError("Source artifact ID must use the sha256 prefix.")
    digest_hex = artifact_id.removeprefix(prefix)
    if (
        len(digest_hex) != _DIGEST_LENGTH
        or digest_hex.lower() != digest_hex
        or any(character not in "0123456789abcdef" for character in digest_hex)
    ):
        raise ObjectStoreError("Source artifact ID must contain 64 lowercase hex digits.")
    return digest_hex


def _mkdir_checked(path: Path, *, boundary: Path | None = None) -> None:
    _assert_no_symlink_ancestors(path.absolute(), allow_missing=True)
    missing = _missing_directory_chain(path)
    for directory in reversed(missing):
        _create_private_directory(directory)
    _validate_directory_entry(_read_directory_entry(path), require_private=True)
    if boundary is not None:
        _assert_real_directory_chain(boundary, path)


def _missing_directory_chain(path: Path) -> list[Path]:
    """Return missing directories below the nearest safe existing ancestor."""
    missing: list[Path] = []
    current_path = path
    while True:
        try:
            current = current_path.lstat()
        except FileNotFoundError:
            missing.append(current_path)
            parent = current_path.parent
            if parent == current_path:
                raise RepositoryPathError(
                    "Repository object directory could not be created."
                ) from None
            current_path = parent
            continue
        except OSError as exc:
            raise RepositoryPathError("Repository object directory could not be created.") from exc
        _validate_directory_entry(current, require_private=not missing)
        return missing


def _create_private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700)
        _validate_directory_entry(_read_directory_entry(path), require_private=True)
        _fsync_directory(path.parent)
    except RepositoryPathError:
        raise
    except OSError as exc:
        raise RepositoryPathError("Repository object directory could not be created.") from exc


def _read_directory_entry(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError as exc:
        raise RepositoryPathError("Repository object directory could not be created.") from exc


def _validate_directory_entry(entry: os.stat_result, *, require_private: bool) -> None:
    if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
        raise RepositoryPathError("Repository object path must be a real directory.")
    if require_private and stat.S_IMODE(entry.st_mode) & 0o077:
        raise RepositoryPathError("Repository object directory must be private.")


def _assert_real_directory_chain(boundary: Path, path: Path) -> None:
    """Reject symlinks and non-directories from a generation root to a child path."""
    boundary = boundary.absolute()
    path = path.absolute()
    try:
        relative = path.relative_to(boundary)
    except ValueError as exc:
        raise RepositoryPathError("Repository object path escapes the generation root.") from exc
    current = boundary
    for component in (Path(), *relative.parents[::-1], relative):
        candidate = current if component == Path() else boundary / component
        try:
            entry = candidate.lstat()
        except OSError as exc:
            raise RepositoryPathError("Repository object path is missing or unsafe.") from exc
        if stat.S_ISLNK(entry.st_mode) or not stat.S_ISDIR(entry.st_mode):
            raise RepositoryPathError("Repository object path must use real directories.")


def _assert_no_symlink_ancestors(path: Path, *, allow_missing: bool = False) -> None:
    """Reject a symlink at any existing component of an absolute path."""
    path = path.absolute()
    components = (*path.parents[::-1], path)
    for component in components:
        try:
            entry = component.lstat()
        except FileNotFoundError:
            if allow_missing:
                continue
            raise RepositoryPathError("Repository path is missing or unsafe.") from None
        except OSError as exc:
            raise RepositoryPathError("Repository path could not be inspected safely.") from exc
        if stat.S_ISLNK(entry.st_mode):
            raise RepositoryPathError("Repository path must not traverse symlinks.")
        if component != path and not stat.S_ISDIR(entry.st_mode):
            raise RepositoryPathError("Repository path ancestor must be a directory.")


def _write_all(fd: int, data: bytes) -> None:
    remaining = memoryview(data)
    while remaining:
        written = os.write(fd, remaining)
        if written <= 0:
            raise ObjectStoreError("Object write made no progress.")
        remaining = remaining[written:]


def _fingerprint_regular_file(path: Path) -> tuple[int, str]:
    try:
        before = path.lstat()
    except OSError as exc:
        raise ObjectCorruptionError("Source object is missing or unsafe.") from exc
    if not stat.S_ISREG(before.st_mode):
        raise ObjectCorruptionError("Source object must be a regular file.")
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise ObjectCorruptionError("Source object is missing or unsafe.") from exc
    digest = hashlib.sha256()
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(opened.st_mode):
            raise ObjectCorruptionError("Source object must be a regular file.")
        if opened.st_mode & 0o222:
            raise ObjectCorruptionError("Source object must not have write permission bits.")
        while True:
            chunk = os.read(fd, _CHUNK_SIZE)
            if not chunk:
                break
            digest.update(chunk)
        after = os.fstat(fd)
    finally:
        os.close(fd)
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_opened = (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_opened or identity_opened != identity_after:
        raise ObjectCorruptionError("Source object changed while it was verified.")
    return after.st_size, digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(path, flags)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError as exc:
        raise ObjectStoreError("Source object directory could not be made durable.") from exc
