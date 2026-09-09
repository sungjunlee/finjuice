"""Errors raised by the SQLite authoritative-storage foundation."""

from __future__ import annotations


class SQLiteStorageError(RuntimeError):
    """Base error for the isolated SQLite repository and object store."""


class RepositoryPathError(SQLiteStorageError):
    """A repository path is unsafe or conflicts with an existing entry."""


class RepositoryVersionError(SQLiteStorageError):
    """A database has an unsupported application identity or schema version."""


class RepositoryIntegrityError(SQLiteStorageError):
    """A database or related artifact failed an integrity invariant."""


class RepositorySnapshotError(SQLiteStorageError):
    """A stable, side-effect-free inspection snapshot could not be captured."""


class ExactValueError(ValueError):
    """An exact authoritative numeric value violates the decimal contract."""


class IdentifierError(ValueError):
    """A stable or deterministic identifier violates the ID contract."""


class ObjectStoreError(SQLiteStorageError):
    """An immutable source object could not be published or verified."""


class ObjectCorruptionError(ObjectStoreError):
    """An existing content-addressed object does not match its identity."""
