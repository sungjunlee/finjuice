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


class AuthorityError(SQLiteStorageError):
    """Base error for storage authority selection and coordination."""


class AuthorityIntegrityError(AuthorityError):
    """An activation record or its external identity binding is invalid."""


class AuthorityEvidenceUnavailableError(AuthorityIntegrityError):
    """An active dataset has no independently trusted runtime evidence."""


class AuthorityConflictError(AuthorityError):
    """The attempted writer does not own the active storage authority."""


class MutationError(SQLiteStorageError):
    """Base error for an authoritative repository mutation."""


class MutationValidationError(MutationError, ValueError):
    """A mutation request or domain operation is invalid."""


class MutationConflictError(MutationError):
    """A mutation conflicts with idempotency or optimistic concurrency state."""


class MutationBusyError(MutationError):
    """A repository writer could not acquire its bounded SQLite lock."""


class MutationAbortedError(MutationError):
    """A rolled-back mutation that left explicitly reported immutable objects."""

    def __init__(self, message: str, retained_artifacts: tuple[str, ...]) -> None:
        super().__init__(message)
        self.retained_artifacts = retained_artifacts
