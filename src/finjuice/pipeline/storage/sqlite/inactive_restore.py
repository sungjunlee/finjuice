"""Explicit caller-bound inactive restores; no host activation or implicit admission."""

from __future__ import annotations

import copy
import os
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from finjuice.pipeline.storage.authority import AuthorityPaths, CoordinationLease
from finjuice.pipeline.storage.sqlite.backup import BackupResult, create_backup, restore_backup
from finjuice.pipeline.storage.sqlite.backup_io import checked_directories
from finjuice.pipeline.storage.sqlite.backup_verify import resolve_backup_input, verify_payload
from finjuice.pipeline.storage.sqlite.generation_binding import GenerationBinding
from finjuice.pipeline.storage.sqlite.inactive_restore_descriptor import (
    InactiveRestoreError,
    RestoredWorkspaceReceipt,
    descriptor_body,
    descriptor_digest,
    fsync_directory,
    path_identity,
    validate_receipt,
    verify_descriptor,
    workspace_identity,
    write_durable,
)
from finjuice.pipeline.storage.sqlite.mutations import (
    JSONValue,
    MutationContext,
    MutationHandler,
    MutationOutcome,
    MutationReceipt,
    MutationRequest,
    _connect_reader,
    _connect_writer,
    execute_generation_mutation,
    find_generation_replay,
    preview_generation_mutation,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths
from finjuice.pipeline.storage.sqlite.repository import RepositoryReader

_Result = TypeVar("_Result")


def restore_workspace(backup_root: Path, destination: Path) -> RestoredWorkspaceReceipt:
    """Restore into a fresh private workspace and return independently retained evidence.

    Failed workspaces remain for inspection and cannot issue a successful receipt.
    This API neither detects arbitrary external activation nor promotes the copy.
    """
    from finjuice.pipeline.storage.sqlite.recovery_store_lock import managed_read_lease

    with managed_read_lease(backup_root):
        return _restore_workspace_unlocked(backup_root, destination)


def _restore_workspace_unlocked(backup_root: Path, destination: Path) -> RestoredWorkspaceReceipt:
    try:
        source, manifest, _ = resolve_backup_input(backup_root)
        verify_payload(source, manifest)
        workspace = _fresh_workspace_path(destination, backup_root)
        workspace.mkdir(mode=0o700)
        control = workspace / "restore-control"
        control.mkdir(mode=0o700)
        restored = restore_backup(backup_root, workspace / "generation")
        restored_root, restored_manifest, _ = resolve_backup_input(workspace / "generation")
        if (
            not restored.verified
            or restored.source_generation != restored_manifest.source_generation
            or restored.dataset_revision != restored_manifest.dataset_revision
            or restored.manifest_digest != restored_manifest.manifest_digest
        ):
            raise InactiveRestoreError()
        manifest = restored_manifest
        verify_payload(restored_root, manifest)
        receipt = RestoredWorkspaceReceipt(
            workspace,
            "",
            str(uuid4()),
            restored.source_generation,
            manifest.dataset_revision,
            1,
            next(entry.sha256 for entry in manifest.files if entry.role == "database"),
            manifest.manifest_digest,
        )
        with RepositoryReader(workspace / "generation" / "finjuice.sqlite3") as reader:
            receipt = replace(receipt, sqlite_schema_version=reader.info.schema_version)
        receipt = replace(receipt, descriptor_digest=descriptor_digest(descriptor_body(receipt)))
        validate_receipt(receipt)
        write_durable(
            control / "descriptor.json",
            {
                **descriptor_body(receipt),
                "descriptor_digest": receipt.descriptor_digest,
            },
        )
        fsync_directory(workspace)
        fsync_directory(workspace.parent)
        return receipt
    except Exception:
        raise InactiveRestoreError() from None


def _fresh_workspace_path(destination: Path, backup_root: Path) -> Path:
    absolute = destination.expanduser().absolute()
    checked_directories(absolute.parent)
    if os.path.lexists(absolute):
        raise InactiveRestoreError()
    workspace = absolute.resolve()
    source = backup_root.expanduser().resolve()
    if workspace == source or workspace.is_relative_to(source) or source.is_relative_to(workspace):
        raise InactiveRestoreError()
    if os.path.lexists(workspace) or ".finjuice" in workspace.parts:
        raise InactiveRestoreError()
    return workspace


class InactiveRestoreSession:
    """Operate under the restored copy's lease using caller-supplied receipt evidence.

    Original manifest/digests describe the initial restore, not later edits. Every
    operation rechecks immutable admission evidence and physical path identity.
    Future activation must retire this workspace under this same lease first.
    """

    def __init__(self, receipt: RestoredWorkspaceReceipt, *, timeout_ms: int = 5000) -> None:
        self.receipt = receipt
        self._closed = False
        self._busy = False
        self._timeout_ms = timeout_ms
        try:
            validate_receipt(receipt)
            self._paths = AuthorityPaths(
                receipt.workspace / "restore-control", receipt.workspace / "generation"
            )
            self.binding = GenerationBinding(
                GenerationPaths(receipt.workspace / "generation"),
                receipt.dataset_generation,
                receipt.sqlite_schema_version,
                receipt.initial_dataset_revision,
            )
            self._identity = workspace_identity(receipt.workspace)
            with self._operation():
                self._lock_identity = path_identity(self._paths.coordination_lock)
        except Exception:
            self._closed = True
            raise InactiveRestoreError() from None

    def __enter__(self) -> InactiveRestoreSession:
        if self._closed:
            raise InactiveRestoreError()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    def _revalidate(self) -> None:
        try:
            if self._closed or workspace_identity(self.receipt.workspace) != self._identity:
                raise InactiveRestoreError()
            if (
                hasattr(self, "_lock_identity")
                and path_identity(self._paths.coordination_lock) != self._lock_identity
            ):
                raise InactiveRestoreError()
            verify_descriptor(self.receipt)
        except Exception:
            raise InactiveRestoreError() from None

    def _admit_current(self) -> None:
        self._revalidate()
        root, manifest, _ = resolve_backup_input(self.binding.paths.root)
        if (
            manifest.manifest_digest != self.receipt.source_manifest_digest
            or next(entry.sha256 for entry in manifest.files if entry.role == "database")
            != self.receipt.initial_database_digest
            or manifest.source_generation != self.receipt.dataset_generation
            or manifest.dataset_revision != self.receipt.initial_dataset_revision
        ):
            raise InactiveRestoreError()
        with RepositoryReader(self.binding.paths.database) as reader:
            info = reader.info
            if (
                info.dataset_generation != self.receipt.dataset_generation
                or info.schema_version != self.receipt.sqlite_schema_version
                or info.dataset_revision is None
                or info.dataset_revision < self.receipt.initial_dataset_revision
            ):
                raise InactiveRestoreError()
            if info.dataset_revision == self.receipt.initial_dataset_revision:
                verify_payload(root, manifest)
        self._revalidate()

    @contextmanager
    def _operation(self) -> Iterator[None]:
        if self._closed or self._busy:
            raise InactiveRestoreError()
        self._revalidate()
        self._busy = True
        try:
            with CoordinationLease(self._paths, exclusive=True, timeout_ms=self._timeout_ms):
                try:
                    self._admit_current()
                except Exception:
                    raise InactiveRestoreError() from None
                yield
        finally:
            self._busy = False

    def execute(self, request: MutationRequest, handler: MutationHandler) -> MutationReceipt:
        """Apply one existing typed mutation with replay and revision semantics intact."""
        with (
            self._operation(),
            closing(_connect_writer(self.binding.paths.database, self._timeout_ms)) as connection,
        ):

            def guarded(context: MutationContext) -> MutationOutcome:
                outcome = handler(context)
                self._revalidate()
                return outcome

            return execute_generation_mutation(
                connection, self.binding, request, guarded, revalidate=self._revalidate
            )

    def preview(
        self, request: MutationRequest, handler: MutationHandler
    ) -> Mapping[str, JSONValue]:
        """Preview through the shared read-only typed engine."""
        with (
            self._operation(),
            closing(_connect_reader(self.binding.paths.database, self._timeout_ms)) as connection,
        ):
            return preview_generation_mutation(
                connection, self.binding, request, handler, revalidate=self._revalidate
            )

    def find_replay(self, request: MutationRequest) -> MutationReceipt | None:
        """Look up historical idempotency without fabricating active authority."""
        with (
            self._operation(),
            closing(_connect_reader(self.binding.paths.database, self._timeout_ms)) as connection,
        ):
            connection.execute("BEGIN")
            try:
                return find_generation_replay(
                    connection, self.binding, request, revalidate=self._revalidate
                )
            finally:
                if connection.in_transaction:
                    connection.execute("ROLLBACK")

    def read_snapshot(self, callback: Callable[[RepositoryReader], _Result]) -> _Result:
        """Materialize a detached result under the workspace lease."""
        with self._operation(), RepositoryReader(self.binding.paths.database) as reader:
            self._revalidate()
            result = callback(reader)
            if result is reader:
                raise InactiveRestoreError()
            self._revalidate()
            return copy.deepcopy(result)

    def backup(self, destination: Path) -> BackupResult:
        """Capture this bound copy at its current revision into a separate backup."""
        with self._operation():
            result = create_backup(self.binding.paths.database, destination)
            self._revalidate()
            return result

    def retire(self) -> None:
        """Durably revoke this restore epoch; all existing handles then fail closed."""
        with self._operation():
            try:
                write_durable(
                    self._paths.control_root / "retired.json",
                    {
                        "restore_id": self.receipt.restore_id,
                        "descriptor_digest": self.receipt.descriptor_digest,
                    },
                )
            except Exception:
                raise InactiveRestoreError() from None

    def close(self) -> None:
        """Close the handle permanently without modifying its historical evidence."""
        if self._busy:
            raise InactiveRestoreError()
        self._closed = True
