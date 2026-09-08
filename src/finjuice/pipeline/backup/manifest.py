"""Backup manifest encoding, digest, and structural verification."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from finjuice import get_version
from finjuice.pipeline.backup.errors import BackupError, invalid
from finjuice.pipeline.backup.paths import (
    ROOT_NAME_RE,
    portable_path_errors,
    require_portable_path,
)
from finjuice.pipeline.backup.types import (
    COMPLETION_MARKER,
    DATA_ROOT_NAME,
    MANIFEST_FILENAME,
    PAYLOAD_DIRNAME,
    ROOTS_DIRNAME,
    SCHEMA_VERSION,
    ConsistencyEvidence,
    Inventory,
    InventoryEntry,
    RootScan,
    SourceRoot,
)

_DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_MODE_RE = re.compile(r"^[0-7]{4}$")
_DATA_SCHEMA_RELATIVE = Path("metadata") / "schema_version"


def canonical_bytes(value: Any) -> bytes:
    """Return canonical JSON bytes for digesting."""
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(data: bytes) -> str:
    """Return a lowercase SHA-256 hex digest."""
    return hashlib.sha256(data).hexdigest()


def digest_text(digest: str) -> str:
    """Prefix a hex digest with ``sha256:``."""
    if digest.startswith("sha256:"):
        return digest
    return f"sha256:{digest}"


def inventory_definition_payload(roots: list[SourceRoot]) -> dict[str, Any]:
    """Return the inventory definition used for the definition digest."""
    return {
        "schema_version": SCHEMA_VERSION,
        "roots": [
            {"name": spec.name, "presence": spec.presence, "role": spec.role}
            for spec in sorted(roots, key=lambda item: item.name)
        ],
    }


def inventory_definition_digest(roots: list[SourceRoot]) -> str:
    """Digest the closed inventory definition."""
    return digest_text(sha256_bytes(canonical_bytes(inventory_definition_payload(roots))))


def _entry_payload(entry: InventoryEntry) -> dict[str, Any]:
    return {
        "root": entry.root,
        "path": entry.path,
        "type": entry.entry_type,
        "size": entry.size,
        "mode": entry.mode,
        "mtime_ns": entry.mtime_ns,
        "sha256": None if entry.sha256 is None else digest_text(entry.sha256),
    }


def _root_payload(scan: RootScan) -> dict[str, Any]:
    payload_path = None
    if scan.state == "present":
        if scan.spec.name == DATA_ROOT_NAME:
            payload_path = f"{PAYLOAD_DIRNAME}/{DATA_ROOT_NAME}"
        else:
            payload_path = f"{PAYLOAD_DIRNAME}/{ROOTS_DIRNAME}/{scan.spec.name}"
    return {
        "name": scan.spec.name,
        "role": scan.spec.role,
        "presence": scan.spec.presence,
        "state": scan.state,
        "entry_type": scan.entry_type,
        "payload_path": payload_path,
    }


def consistency_payload(evidence: ConsistencyEvidence) -> dict[str, Any]:
    return {
        "kind": evidence.kind,
        "operator_confirmed": True,
        "stopped_writers": list(evidence.stopped_writers),
        "snapshot_name": evidence.snapshot_name,
        "note": "operator-supplied evidence; CLI does not prove host-wide writer absence",
    }


def read_captured_data_schema(data_root: Path) -> tuple[int | None, str]:
    """Read schema evidence from captured bytes without exposing their value or path."""
    schema_file = data_root / _DATA_SCHEMA_RELATIVE
    if not schema_file.exists():
        return None, "missing"
    try:
        raw = schema_file.read_bytes().decode("utf-8").strip()
        if not raw or not raw.isascii() or not raw.isdecimal():
            return None, "invalid"
        version = int(raw)
    except (OSError, UnicodeDecodeError, ValueError):
        return None, "invalid"
    if version < 1:
        return None, "invalid"
    return version, "present"


def build_manifest(
    *,
    inventory: Inventory,
    evidence: ConsistencyEvidence,
    roots: list[SourceRoot],
    data_schema_version: int | None,
    data_schema_version_status: str,
    capture: dict[str, Any],
) -> dict[str, Any]:
    """Build a private portable manifest without absolute source maps."""
    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": "legacy_full_backup",
        "capture": capture,
        "finjuice_version": get_version(),
        "data_schema_version": data_schema_version,
        "data_schema_version_status": data_schema_version_status,
        "platform": {
            "system": platform.system(),
            "python": sys.version.split()[0],
        },
        "inventory_definition_digest": inventory_definition_digest(roots),
        "consistency": consistency_payload(evidence),
        "roots": [_root_payload(scan) for scan in inventory.roots],
        "entries": [_entry_payload(entry) for entry in inventory.entries],
        "entry_count": len(inventory.entries),
        "file_count": inventory.file_count,
        "directory_count": inventory.directory_count,
        "byte_count": inventory.byte_count,
        "completion_marker": COMPLETION_MARKER,
    }
    digest = digest_text(sha256_bytes(canonical_bytes(body)))
    return {**body, "canonical_digest": digest}


def manifest_without_digest(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the digestable subset of a manifest."""
    return {key: value for key, value in manifest.items() if key != "canonical_digest"}


def compute_manifest_digest(manifest: dict[str, Any]) -> str:
    """Recompute the canonical digest for a loaded manifest."""
    return digest_text(sha256_bytes(canonical_bytes(manifest_without_digest(manifest))))


def load_manifest(path: Path) -> dict[str, Any]:
    """Load a backup manifest JSON object."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BackupError("Backup manifest is missing.", code="FILE_NOT_FOUND") from exc
    except OSError as exc:
        raise BackupError("Backup manifest could not be read.", code="FILE_ACCESS_ERROR") from exc
    except json.JSONDecodeError as exc:
        raise BackupError("Backup manifest is not valid JSON.", code="VALIDATION_FAILED") from exc
    if not isinstance(payload, dict):
        raise BackupError("Backup manifest is not an object.", code="VALIDATION_FAILED")
    return payload


def backup_dir_from_manifest_path(manifest_path: Path) -> Path:
    """Return the backup directory that owns a manifest path."""
    if manifest_path.name == MANIFEST_FILENAME:
        return manifest_path.parent
    return manifest_path


def payload_relative(root_name: str, entry_path: str) -> Path:
    """Return the payload-relative path for one inventory entry."""
    require_portable_path(entry_path)
    if root_name == DATA_ROOT_NAME:
        base = Path(PAYLOAD_DIRNAME) / DATA_ROOT_NAME
    else:
        base = Path(PAYLOAD_DIRNAME) / ROOTS_DIRNAME / root_name
    if entry_path == ".":
        return base
    return base / entry_path


def validate_manifest_structure(manifest: dict[str, Any]) -> None:
    """Reject unsupported or internally inconsistent backup manifests."""
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise BackupError("Unsupported backup manifest schema.", code="VALIDATION_FAILED")
    if (
        manifest.get("kind") != "legacy_full_backup"
        or manifest.get("completion_marker") != COMPLETION_MARKER
    ):
        raise invalid("Backup manifest identity is invalid.")
    entries = manifest.get("entries")
    roots = manifest.get("roots")
    if not isinstance(entries, list) or not isinstance(roots, list):
        raise BackupError("Backup manifest is missing inventory lists.", code="VALIDATION_FAILED")
    roots_by_name = _validate_root_records(roots)
    entries_by_key = _validate_entry_records(entries, roots_by_name)
    _validate_root_entry_closure(roots_by_name, entries_by_key)
    _validate_manifest_counts(manifest, entries)
    _validate_inventory_definition(manifest, roots)
    _validate_data_schema_evidence(manifest)
    _validate_consistency(manifest.get("consistency"))
    _validate_capture(manifest.get("capture"))


def validate_attempt_id(value: str | None) -> None:
    """Reject malformed operator-supplied capture lineage identifiers."""
    if value is not None and (
        not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{32}", value) is None
    ):
        raise invalid("Capture attempt identifier must contain 32 lowercase hexadecimal digits.")


def _validate_capture(value: Any) -> None:
    if not isinstance(value, dict) or value.get("attempt_id") is None:
        raise invalid("Backup capture evidence is missing.")
    validate_attempt_id(value["attempt_id"])
    validate_attempt_id(value.get("parent_attempt_id"))
    if "parent_attempt_id" not in value or value["attempt_id"] == value["parent_attempt_id"]:
        raise invalid("Backup capture lineage is invalid.")
    try:
        start = datetime.fromisoformat(value["started_at"])
        end = datetime.fromisoformat(value["completed_at"])
        if start.utcoffset() is None or end.utcoffset() is None or end < start:
            raise ValueError
    except (KeyError, TypeError, ValueError) as exc:
        raise invalid("Backup capture interval is invalid.") from exc


def _valid_external_root_name(name: str) -> bool:
    return ROOT_NAME_RE.fullmatch(name) is not None


def _validate_root_records(roots: list[Any]) -> dict[str, dict[str, Any]]:
    seen: dict[str, dict[str, Any]] = {}
    for root in roots:
        if not isinstance(root, dict):
            raise BackupError("Backup manifest root is invalid.", code="VALIDATION_FAILED")
        name = root.get("name")
        if (
            not isinstance(name, str)
            or name in seen
            or (name != DATA_ROOT_NAME and not _valid_external_root_name(name))
        ):
            raise invalid("Backup manifest roots are duplicate or invalid.")
        presence = root.get("presence")
        state = root.get("state")
        entry_type = root.get("entry_type")
        role = root.get("role")
        if presence not in {"required", "optional"} or state not in {
            "present",
            "intentionally_absent",
        }:
            raise invalid("Backup manifest root state is invalid.")
        if not isinstance(role, str) or not role:
            raise invalid("Backup manifest root role is invalid.")
        if presence == "required" and state != "present":
            raise BackupError("A required backup root is missing.", code="VALIDATION_FAILED")
        expected_payload = None
        if state == "present":
            if entry_type not in {"file", "directory"}:
                raise invalid("Backup manifest root type is invalid.")
            expected_payload = (
                f"{PAYLOAD_DIRNAME}/{DATA_ROOT_NAME}"
                if name == DATA_ROOT_NAME
                else f"{PAYLOAD_DIRNAME}/{ROOTS_DIRNAME}/{name}"
            )
        elif entry_type is not None:
            raise invalid("Backup manifest absent root type is invalid.")
        if root.get("payload_path") != expected_payload:
            raise invalid("Backup manifest root payload is invalid.")
        seen[name] = root
    data = seen.get(DATA_ROOT_NAME)
    if (
        data is None
        or data.get("presence") != "required"
        or data.get("state") != "present"
        or data.get("entry_type") != "directory"
        or data.get("role") != "legacy_data_tree"
    ):
        raise invalid("Backup manifest data root is invalid.")
    return seen


def _validate_entry_records(
    entries: list[Any], roots: dict[str, dict[str, Any]]
) -> dict[tuple[str, str], dict[str, Any]]:
    seen: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise BackupError("Backup manifest entry is invalid.", code="VALIDATION_FAILED")
        root = entry.get("root")
        path = entry.get("path")
        if not isinstance(root, str) or root not in roots or not isinstance(path, str):
            raise BackupError("Backup manifest entry is invalid.", code="VALIDATION_FAILED")
        if portable_path_errors(path) is not None:
            raise BackupError("Backup manifest contains an unsafe path.", code="VALIDATION_FAILED")
        key = (root, path)
        if key in seen:
            raise BackupError("Backup manifest contains duplicate paths.", code="VALIDATION_FAILED")
        entry_type = entry.get("type")
        size = entry.get("size")
        mode = entry.get("mode")
        mtime_ns = entry.get("mtime_ns")
        digest = entry.get("sha256")
        if entry_type not in {"file", "directory"}:
            raise invalid("Backup manifest entry type is invalid.")
        if type(size) is not int or size < 0:
            raise invalid("Backup manifest entry size is invalid.")
        if not isinstance(mode, str) or _MODE_RE.fullmatch(mode) is None:
            raise invalid("Backup manifest entry mode is invalid.")
        if type(mtime_ns) is not int:
            raise invalid("Backup manifest entry timestamp is invalid.")
        if entry_type == "file":
            if not isinstance(digest, str) or _DIGEST_RE.fullmatch(digest) is None:
                raise invalid("Backup manifest file digest is invalid.")
        elif size != 0 or digest is not None:
            raise invalid("Backup manifest directory entry is invalid.")
        seen[key] = entry
    return seen


def _validate_root_entry_closure(
    roots: dict[str, dict[str, Any]], entries: dict[tuple[str, str], dict[str, Any]]
) -> None:
    for name, root in roots.items():
        root_entry = entries.get((name, "."))
        if root.get("state") == "intentionally_absent":
            if any(entry_root == name for entry_root, _path in entries):
                raise invalid("Backup manifest absent root contains entries.")
            continue
        if root_entry is None or root_entry.get("type") != root.get("entry_type"):
            raise invalid("Backup manifest present root entry is missing or invalid.")
        root_is_directory = root_entry.get("type") == "directory"
        for entry_root, path in entries:
            if entry_root != name or path == ".":
                continue
            if not root_is_directory:
                raise invalid("Backup manifest file root contains child entries.")
            parts = path.split("/")
            for length in range(1, len(parts)):
                parent = entries.get((name, "/".join(parts[:length])))
                if parent is None or parent.get("type") != "directory":
                    raise invalid("Backup manifest entry parent is missing or invalid.")


def _manifest_integer(manifest: dict[str, Any], key: str) -> int:
    value = manifest.get(key)
    if type(value) is not int or value < 0:
        raise invalid("Backup manifest count is invalid.")
    return value


def _validate_manifest_counts(manifest: dict[str, Any], entries: list[Any]) -> None:
    expected = {
        "entry_count": len(entries),
        "file_count": sum(entry["type"] == "file" for entry in entries),
        "directory_count": sum(entry["type"] == "directory" for entry in entries),
        "byte_count": sum(entry["size"] for entry in entries if entry["type"] == "file"),
    }
    if any(_manifest_integer(manifest, key) != value for key, value in expected.items()):
        raise invalid("Backup manifest counts do not match its entries.")


def _validate_inventory_definition(manifest: dict[str, Any], roots: list[Any]) -> None:
    definition = {
        "schema_version": SCHEMA_VERSION,
        "roots": [
            {"name": root["name"], "presence": root["presence"], "role": root["role"]}
            for root in sorted(roots, key=lambda item: item["name"])
        ],
    }
    expected = digest_text(sha256_bytes(canonical_bytes(definition)))
    if manifest.get("inventory_definition_digest") != expected:
        raise invalid("Backup manifest inventory definition does not match its roots.")


def _validate_data_schema_evidence(manifest: dict[str, Any]) -> None:
    status = manifest.get("data_schema_version_status")
    version = manifest.get("data_schema_version")
    if status == "present" and type(version) is int and version >= 1:
        return
    if status in {"missing", "invalid"} and version is None:
        return
    raise invalid("Backup manifest data schema evidence is invalid.")


def _validate_consistency(value: Any) -> None:
    if not isinstance(value, dict) or value.get("operator_confirmed") is not True:
        raise invalid("Backup manifest consistency evidence is invalid.")
    kind = value.get("kind")
    writers = value.get("stopped_writers")
    snapshot = value.get("snapshot_name")
    if not isinstance(writers, list) or not all(isinstance(item, str) and item for item in writers):
        raise invalid("Backup manifest consistency evidence is invalid.")
    if kind == "stopped_writers" and writers and snapshot is None:
        return
    if kind == "named_snapshot" and not writers and isinstance(snapshot, str) and snapshot:
        return
    raise invalid("Backup manifest consistency evidence is invalid.")
