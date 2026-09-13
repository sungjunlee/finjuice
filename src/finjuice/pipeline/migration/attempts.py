"""Durable private attempt journals and portable retry evidence."""

from __future__ import annotations

import os
import stat
import sys
import uuid
from pathlib import Path
from typing import Any

from finjuice.pipeline.backup.io import fsync_parent_chain
from finjuice.pipeline.backup.paths import reject_overlap, reject_symlink_chain
from finjuice.pipeline.migration.common import (
    MANIFEST,
    MARKER,
    MigrationError,
    canonical,
    digest,
    load_sealed,
    seal,
)

JOURNAL = ".finjuice-migration-attempts"
VERSION = "finjuice.migration.attempt.v1"
PHASES = ("started", "building", "built", "publishing", "published", "verified")


def journal_root(destination: Path, protected: tuple[Path, ...]) -> Path:
    """Validate the sibling journal before creating any attempt artifacts."""
    root = reject_symlink_chain(destination.parent / JOURNAL)
    if JOURNAL in destination.parts:
        raise MigrationError("The attempt journal is reserved.")
    for path in (*protected, destination):
        reject_overlap(root, reject_symlink_chain(path))
    return root


def _publish(path: Path, record: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.pending")
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(canonical(record) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
    # link is an atomic, exclusive publication; it cannot replace existing evidence.
    os.link(temporary, path, follow_symlinks=False)
    temporary.unlink()
    fsync_parent_chain(path.parent)


def validate_chain(records: Any) -> list[dict[str, Any]]:
    """Validate a self-contained sealed sequence without consulting external files."""
    if not isinstance(records, list) or not records:
        raise MigrationError("Attempt phase evidence is missing.")
    previous = None
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise MigrationError("Attempt phase evidence is malformed.")
        unsigned = {key: value for key, value in record.items() if key != "canonical_digest"}
        phase = record.get("phase")
        if (
            record.get("schema_version") != VERSION
            or record.get("canonical_digest") != digest(unsigned)
            or record.get("sequence") != index
            or record.get("previous_digest") != previous
            or (phase != "failed" and (index >= len(PHASES) or phase != PHASES[index]))
            or (phase == "failed" and (index == 0 or index != len(records) - 1))
        ):
            raise MigrationError("Attempt phase chain is invalid.")
        previous = record["canonical_digest"]
    return records


def _validate_identity(start: dict[str, Any], attempt: str, plan: str, capture: str) -> None:
    identifier = start.get("attempt_id")
    target = start.get("target")
    if (
        not isinstance(identifier, str)
        or len(identifier) != 32
        or any(char not in "0123456789abcdef" for char in identifier)
        or not isinstance(target, str)
        or Path(target).name != target
        or target in {".", "..", "", JOURNAL}
    ):
        raise MigrationError("Attempt identity or target locator is invalid.")
    if (identifier, start.get("plan_digest"), start.get("capture_digest")) != (
        attempt,
        plan,
        capture,
    ):
        raise MigrationError("Attempt identity or input binding does not match.")


def _validate_outcome(evidence: dict[str, Any], records: list[dict[str, Any]]) -> None:
    outcome = evidence.get("outcome")
    if outcome not in ("failed", "interrupted"):
        raise MigrationError("Parent attempt outcome is invalid.")
    failed = records[-1]["phase"] == "failed"
    if (outcome == "failed") != failed:
        raise MigrationError("Parent terminal outcome does not match its phase chain.")
    if any(item["phase"] in {"published", "verified"} for item in records):
        raise MigrationError("Successful attempt cannot be a retry parent.")


def validate_evidence(evidence: Any, attempt: str, plan: str, capture: str) -> None:
    """Validate portable attempt bindings and every ancestor without external journals."""
    if not isinstance(evidence, dict):
        raise MigrationError("Attempt evidence is malformed.")
    seen_targets: set[str] = set()
    seen_attempts: set[str] = set()
    is_parent = isinstance(evidence, dict) and "outcome" in evidence
    while evidence is not None:
        if not isinstance(evidence, dict):
            raise MigrationError("Attempt evidence is malformed.")
        records = validate_chain(evidence.get("records"))
        start = records[0]
        _validate_identity(start, attempt, plan, capture)
        if start["target"] in seen_targets or attempt in seen_attempts:
            raise MigrationError("Retry reuses an ancestor target or identity.")
        seen_targets.add(start["target"])
        seen_attempts.add(attempt)
        if is_parent:
            _validate_outcome(evidence, records)
        evidence = start.get("parent")
        if evidence is not None:
            if not isinstance(evidence, dict):
                raise MigrationError("Parent attempt evidence is malformed.")
            prior = validate_chain(evidence.get("records"))
            attempt = prior[0].get("attempt_id", "")
            is_parent = True


def _read(directory: Path) -> list[dict[str, Any]]:
    files = sorted(directory.glob("*.json"))
    if [file.name for file in files] != [f"{index:04d}.json" for index in range(len(files))]:
        raise MigrationError("Attempt phase files are incomplete.")
    return validate_chain([load_sealed(file, VERSION) for file in files])


def _lock(path: Path, *, create: bool = False) -> int:
    import fcntl

    reject_symlink_chain(path)
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | (os.O_CREAT | os.O_EXCL if create else 0), 0o600)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode) or os.fstat(fd).st_nlink != 1:
            raise MigrationError("Attempt lock must be a regular private file.")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(fd)
        raise MigrationError("Attempt is live or its lock cannot be acquired.") from None
    return fd


def parent_evidence(root: Path, parent: str | None, target: Path, plan: dict[str, Any]) -> Any:
    """Read a retained failed attempt only after excluding a live OS lock owner."""
    if parent is None:
        return None
    directory = reject_symlink_chain(root / parent)
    try:
        fd = _lock(directory / "lock")
    except OSError as exc:
        raise MigrationError("Parent attempt is unknown or inaccessible.") from exc
    try:
        records = _read(directory)
        start = records[0]
        name = start.get("target")
        if not isinstance(name, str) or Path(name).name != name or name in {".", "..", ""}:
            raise MigrationError("Parent target locator is invalid.")
        prior_target = reject_symlink_chain(target.parent / name)
        if (prior_target / MARKER).exists() or (prior_target / "manifests" / MANIFEST).exists():
            raise MigrationError("Published target cannot be a retry parent.")
        outcome = "failed" if records[-1]["phase"] == "failed" else "interrupted"
        result = {"records": records, "outcome": outcome}
        validate_evidence(
            result, parent, plan["canonical_digest"], plan["capture"]["canonical_digest"]
        )
        if name == target.name:
            raise MigrationError("Retry requires a fresh candidate target.")
        return result
    finally:
        os.close(fd)


class AttemptJournal:
    """Keep an OS lock while recording immutable attempt phases."""

    def __init__(self, root: Path, attempt: str, target: Path, plan: dict[str, Any], parent: Any):
        root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.directory = root / attempt
        self.directory.mkdir(mode=0o700)
        self.fd = _lock(self.directory / "lock", create=True)
        self.records: list[dict[str, Any]] = []
        try:
            self.append(
                "started",
                attempt_id=attempt,
                target=target.name,
                plan_digest=plan["canonical_digest"],
                capture_digest=plan["capture"]["canonical_digest"],
                parent=parent,
            )
        except BaseException:
            self.close()
            raise

    def append(self, phase: str, **metadata: Any) -> None:
        record = seal(
            {
                "schema_version": VERSION,
                "sequence": len(self.records),
                "phase": phase,
                "previous_digest": self.records[-1]["canonical_digest"] if self.records else None,
                **metadata,
            }
        )
        path = self.directory / f"{len(self.records):04d}.json"
        try:
            _publish(path, record)
        except BaseException:
            # Publication may have completed before fsync failed. Keep the sealed chain
            # position so a recovered device can append failure at the next sequence.
            try:
                if load_sealed(path, VERSION) == record:
                    self.records.append(record)
            except Exception:
                pass
            raise
        self.records.append(record)

    def failure(self, error: BaseException) -> None:
        try:
            self.append("failed", error_class=type(error).__name__)
        except Exception:
            # Preserve the original failure and all successfully durable earlier records.
            pass

    def close(self) -> None:
        unwinding = sys.exc_info()[0] is not None
        try:
            os.close(self.fd)
        except OSError:
            if not unwinding:
                raise


def reject_used_target(root: Path, target: Path) -> None:
    """Require a different destination after any retained attempt has reserved its name."""
    if not root.exists():
        return
    for directory in root.iterdir():
        reject_symlink_chain(directory)
        if not directory.is_dir():
            raise MigrationError("Attempt journal contains an unsupported entry.")
        start = directory / "0000.json"
        if start.exists() and load_sealed(start, VERSION).get("target") == target.name:
            raise MigrationError("Candidate target was already used by an attempt.")
