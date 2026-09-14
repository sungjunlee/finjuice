"""Frozen-source inventory, digest revalidation, and space preflight."""

from __future__ import annotations

import errno
import os
import shutil
from pathlib import Path
from typing import Any, Iterable

from finjuice.pipeline.backup.scan import fingerprint_file
from finjuice.pipeline.config import is_inside_program_repo, validate_not_program_repo_path
from finjuice.pipeline.migrate.csvio import read_csv_rows
from finjuice.pipeline.migrate.encoding import (
    canonical_bytes,
    digest_text,
    hex_digest,
    load_json_object,
    sha256_bytes,
)
from finjuice.pipeline.migrate.errors import MigrationError, invalid
from finjuice.pipeline.migrate.types import (
    CAPTURE_KIND,
    CSV_ROLES,
    INVENTORY_ROLES,
    SCHEMA_VERSION,
    CaptureEntry,
    CaptureManifest,
    Disposition,
    PlannedInput,
)

_ROLE_PREFIXES: tuple[tuple[str, str], ...] = (
    ("transactions/", "transaction_partition"),
    ("banksalad/overview_facts/", "overview_facts"),
    ("banksalad/balance/", "overview_balance"),
    ("banksalad/cashflow/", "overview_cashflow"),
    ("banksalad/insurance/", "overview_insurance"),
    ("banksalad/investments/", "overview_investment"),
    ("banksalad/loans/", "overview_loan"),
    ("assets/", "asset_snapshot"),
    ("imports/", "source_workbook"),
    ("metadata/import_history.csv", "import_history"),
    ("metadata/", "audit_history"),
    ("audit/", "audit_history"),
)

_ROLE_FILES: dict[str, str] = {
    "rules": "rules.yaml",
    "goals": "goals.yaml",
    "assets": "assets.yaml",
    "scenarios": "scenarios.yaml",
}

_WORKBOOK_SUFFIXES = {".xlsx", ".zip"}
_AUDIT_SUFFIXES = {".jsonl", ".json"}


def require_outside_repo(path: Path, *, context: str) -> Path:
    """Reject program-repo and symlink roots."""
    absolute = path.expanduser()
    if not absolute.is_absolute():
        absolute = Path.cwd() / absolute
    current = absolute
    while True:
        if os.path.lexists(current) and os.path.islink(current):
            raise invalid("A migration path is a symlink.")
        parent = current.parent
        if parent == current:
            break
        current = parent
    try:
        validate_not_program_repo_path(absolute, context=context)
    except ValueError as exc:
        raise MigrationError(
            "Refusing a migration path inside the program repository.",
            code="INVALID_ARGS",
        ) from exc
    if is_inside_program_repo(absolute):
        raise MigrationError(
            "Refusing a migration path inside the program repository.",
            code="INVALID_ARGS",
        )
    return absolute


def reject_overlap(left: Path, right: Path) -> None:
    """Refuse source/staging containment."""
    if left == right or left in right.parents or right in left.parents:
        raise invalid("Staging must be a new directory outside the frozen source.")


def preflight_space(parent: Path, needed_bytes: int) -> None:
    """Fail when free space is below the captured byte count plus a margin."""
    try:
        usage = shutil.disk_usage(parent)
    except OSError as exc:
        raise MigrationError(
            "Could not inspect free disk space.",
            code="FILE_ACCESS_ERROR",
        ) from exc
    margin = max(1024 * 1024, needed_bytes // 10)
    if usage.free < needed_bytes + margin:
        raise MigrationError(
            "Insufficient disk space for migration.",
            code="FILE_ACCESS_ERROR",
        )


def raise_io(exc: OSError) -> None:
    """Map OS I/O errors to privacy-safe migration errors."""
    if exc.errno == errno.ENOSPC:
        raise MigrationError("Disk is full.", code="FILE_ACCESS_ERROR") from exc
    raise MigrationError("Migration I/O failed.", code="FILE_ACCESS_ERROR") from exc


def classify_relative_path(relative: str) -> str | None:
    """Return the inventory role for one portable relative path."""
    for role, filename in _ROLE_FILES.items():
        if relative == filename:
            return role
    matched: str | None = None
    for prefix, role in _ROLE_PREFIXES:
        if relative.startswith(prefix):
            matched = role
            break
    if matched == "source_workbook":
        suffix = Path(relative).suffix.lower()
        return matched if suffix in _WORKBOOK_SUFFIXES else None
    if matched == "audit_history":
        suffix = Path(relative).suffix.lower()
        return matched if suffix in _AUDIT_SUFFIXES else None
    return matched


def _relative_of(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _scan_tree(root: Path) -> list[CaptureEntry]:
    entries: list[CaptureEntry] = []
    if not root.exists():
        return entries
    for current, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        dirnames[:] = sorted(name for name in dirnames if name != ".git")
        base = Path(current)
        for name in sorted(filenames):
            path = base / name
            if path.is_symlink():
                continue
            relative = _relative_of(root, path)
            role = classify_relative_path(relative)
            if role is None:
                continue
            identity, digest = fingerprint_file(path)
            entries.append(
                CaptureEntry(
                    logical_role=role,
                    relative_path=relative,
                    state="present",
                    size=identity.size,
                    sha256=digest_text(digest),
                    required=role in {"transaction_partition", "rules"},
                )
            )
    return entries


def _absent(role: str) -> CaptureEntry:
    return CaptureEntry(
        logical_role=role,
        relative_path=None,
        state="intentionally_absent",
        required=False,
    )


def capture_frozen_inputs(
    source: Path,
    *,
    extra_roots: dict[str, Path | None] | None = None,
) -> CaptureManifest:
    """Inventory a frozen copy without mutating it.

    Args:
        source: Frozen data directory. Must not be the live operational tree
            that callers continue to write.
        extra_roots: Optional external overlays keyed by inventory role.

    Returns:
        Capture manifest with per-file digests and inventoried absences.
    """
    frozen_root = require_outside_repo(source, context="migration source")
    if not frozen_root.is_dir():
        raise MigrationError("Frozen source must be a directory.", code="INVALID_ARGS")
    entries = _scan_tree(frozen_root)
    present_roles = {entry.logical_role for entry in entries}
    extras = extra_roots or {}
    for name, path in extras.items():
        if path is None:
            if name not in present_roles:
                entries.append(_absent(name))
            continue
        extra_path = require_outside_repo(path, context="migration overlay")
        reject_overlap(frozen_root, extra_path)
        if not extra_path.is_file():
            raise MigrationError("Overlay source is missing.", code="FILE_NOT_FOUND")
        identity, digest = fingerprint_file(extra_path)
        entries.append(
            CaptureEntry(
                logical_role=name,
                relative_path=extra_path.name,
                state="present",
                size=identity.size,
                sha256=digest_text(digest),
                required=True,
            )
        )
        present_roles.add(name)
    for role in INVENTORY_ROLES:
        if role not in present_roles:
            entries.append(_absent(role))
    manifest = CaptureManifest(
        frozen_root=frozen_root,
        entries=entries,
        extra_roots={
            name: str(require_outside_repo(path, context="migration overlay"))
            for name, path in extras.items()
            if path is not None
        },
    )
    manifest.canonical_digest = digest_text(sha256_bytes(canonical_bytes(_digestable(manifest))))
    return manifest


def _digestable(manifest: CaptureManifest) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": CAPTURE_KIND,
        "entries": [
            {
                "logical_role": entry.logical_role,
                "relative_path": entry.relative_path,
                "state": entry.state,
                "size": entry.size,
                "sha256": entry.sha256,
                "required": entry.required,
            }
            for entry in manifest.entries
        ],
    }


def capture_to_dict(manifest: CaptureManifest) -> dict[str, Any]:
    """Serialize a capture, including the operational frozen root."""
    payload = _digestable(manifest)
    payload["frozen_root"] = str(manifest.frozen_root)
    payload["extra_roots"] = dict(manifest.extra_roots)
    payload["canonical_digest"] = manifest.canonical_digest
    return payload


def write_capture_manifest(manifest: CaptureManifest, path: Path) -> Path:
    """Write a capture manifest next to, not inside, the frozen source."""
    destination = require_outside_repo(path, context="capture manifest")
    reject_overlap(manifest.frozen_root, destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = capture_to_dict(manifest)
    destination.write_text(
        canonical_bytes(payload).decode("utf-8") + "\n",
        encoding="utf-8",
    )
    return destination


def load_capture_manifest(path: Path) -> CaptureManifest:
    """Load and re-hash a capture manifest."""
    payload = load_json_object(path)
    frozen_root = Path(str(payload.get("frozen_root", "")))
    if not frozen_root:
        raise invalid("Capture manifest is missing its frozen root.")
    entries = [
        CaptureEntry(
            logical_role=str(item["logical_role"]),
            relative_path=item.get("relative_path"),
            state=item["state"],
            size=item.get("size"),
            sha256=item.get("sha256"),
            required=bool(item.get("required", False)),
        )
        for item in payload.get("entries", [])
    ]
    extra_roots = {str(key): str(value) for key, value in payload.get("extra_roots", {}).items()}
    manifest = CaptureManifest(
        frozen_root=require_outside_repo(frozen_root, context="migration source"),
        entries=entries,
        extra_roots=extra_roots,
        canonical_digest=str(payload.get("canonical_digest", "")),
    )
    expected = digest_text(sha256_bytes(canonical_bytes(_digestable(manifest))))
    if manifest.canonical_digest != expected:
        raise invalid("Capture manifest digest does not match its contents.")
    return manifest


def resolve_entry_path(manifest: CaptureManifest, entry: CaptureEntry) -> Path:
    """Resolve one present entry to a frozen filesystem path."""
    if entry.relative_path is None:
        raise invalid("Present capture entry is missing its relative path.")
    if entry.logical_role in manifest.extra_roots:
        return Path(manifest.extra_roots[entry.logical_role])
    return manifest.frozen_root / entry.relative_path


def revalidate_entry(manifest: CaptureManifest, entry: CaptureEntry) -> None:
    """Reject missing or mutated frozen inputs."""
    if entry.state != "present":
        return
    path = resolve_entry_path(manifest, entry)
    if not path.exists():
        raise MigrationError("A captured source file is missing.", code="FILE_NOT_FOUND")
    _identity, digest = fingerprint_file(path)
    if digest_text(digest) != entry.sha256:
        raise MigrationError(
            "Frozen source changed after capture.",
            code="VALIDATION_FAILED",
            suggestion="Create a fresh freeze and capture before migrating.",
        )


def revalidate_capture(manifest: CaptureManifest) -> None:
    """Re-hash every present captured file."""
    for entry in manifest.present_files():
        revalidate_entry(manifest, entry)


def captured_byte_count(manifest: CaptureManifest) -> int:
    """Return inventoried present-file bytes."""
    return sum(entry.size or 0 for entry in manifest.present_files())


def record_kind_for_role(role: str) -> str:
    """Return the default migrated record kind for an inventory role."""
    mapping = {
        "transaction_partition": "transaction",
        "overview_facts": "overview_fact",
        "overview_balance": "overview_balance",
        "overview_cashflow": "overview_cashflow",
        "overview_insurance": "overview_insurance",
        "overview_investment": "overview_investment",
        "overview_loan": "overview_loan",
        "asset_snapshot": "asset_snapshot",
        "source_workbook": "source_occurrence",
        "rules": "config_revision",
        "goals": "config_revision",
        "assets": "config_revision",
        "scenarios": "config_revision",
        "import_history": "source_occurrence",
        "audit_history": "source_occurrence",
        "overlay": "config_revision",
    }
    return mapping.get(role, "source_occurrence")


def expand_planned_inputs(manifest: CaptureManifest) -> list[PlannedInput]:
    """Expand captured files into planned record inputs."""
    inputs: list[PlannedInput] = []
    for entry in manifest.entries:
        if entry.state == "intentionally_absent":
            inputs.append(
                PlannedInput(
                    logical_role=entry.logical_role,
                    relative_path=None,
                    record_kind="absent",
                    ordinal=None,
                    expected_disposition="intentionally_absent",
                )
            )
            continue
        if entry.logical_role in CSV_ROLES:
            headers, rows = read_csv_rows(resolve_entry_path(manifest, entry))
            del headers
            if not rows:
                inputs.append(_file_input(entry, expected="intentionally_absent"))
                continue
            for ordinal, _row in enumerate(rows):
                inputs.append(
                    PlannedInput(
                        logical_role=entry.logical_role,
                        relative_path=entry.relative_path,
                        record_kind=record_kind_for_role(entry.logical_role),
                        ordinal=ordinal,
                        expected_disposition="migrated",
                        sha256=entry.sha256,
                    )
                )
            continue
        expected: Disposition = "preserved_opaque"
        if entry.logical_role in {"rules", "goals", "assets", "scenarios", "overlay"}:
            expected = "migrated"
        inputs.append(_file_input(entry, expected=expected))
    return inputs


def _file_input(entry: CaptureEntry, *, expected: Disposition) -> PlannedInput:
    return PlannedInput(
        logical_role=entry.logical_role,
        relative_path=entry.relative_path,
        record_kind=record_kind_for_role(entry.logical_role),
        ordinal=None,
        expected_disposition=expected,
        sha256=entry.sha256,
    )


def capture_hex(manifest: CaptureManifest) -> str:
    """Return the 64-character capture digest used as an ID seed."""
    return hex_digest(manifest.canonical_digest)


def iter_role_entries(
    manifest: CaptureManifest,
    roles: Iterable[str],
) -> list[CaptureEntry]:
    """Return present entries for the given roles, in role then path order."""
    wanted = tuple(roles)
    selected = [entry for entry in manifest.present_files() if entry.logical_role in wanted]
    selected.sort(key=lambda entry: (wanted.index(entry.logical_role), entry.relative_path or ""))
    return selected
