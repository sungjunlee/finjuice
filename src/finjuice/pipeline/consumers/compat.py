"""Isolated cutover compatibility path for inventoried consumers.

Installing this module does not change the operational default: CSV remains
the live authority and the legacy-writer fence stays disabled. Isolated
cutover mode is an explicit harness used to prove that every known consumer
can pin the same dataset/revision, that overlay corrections apply once, and
that direct CSV writes can be blocked even when an old install ignores the
lock file. Operational fence activation is deferred to the cutover issue.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from uuid import UUID

from finjuice.pipeline.consumers.inventory import (
    SCHEMA_VERSION,
    Authority,
    ConsumerSpec,
    get_consumer,
    known_consumers,
)
from finjuice.pipeline.storage.sqlite.paths import GenerationPaths

RuntimeMode = Literal["csv", "cutover"]
OverlayStatus = Literal["applied", "already_applied"]

LOCK_FILENAME = ".finjuice-legacy-csv-fence"
STATE_FILENAME = "cutover-state.json"
CSV_TREE_NAMES = ("transactions", "banksalad", "assets")
CUTOVER_ISSUE = 440
FENCE_PROCEDURE: tuple[str, ...] = (
    "enter_isolated_cutover_mode",
    "stop_inventoried_writers",
    "write_lock_and_settings",
    "chmod_csv_trees_unwritable",
    "verify_old_install_blocked_by_permissions",
    "defer_operational_activation",
)


class ConsumerCutoverError(Exception):
    """Privacy-safe failure for consumer cutover preparation."""


class LegacyCsvWriteBlockedError(ConsumerCutoverError):
    """Raised when a direct legacy CSV write is refused in cutover mode."""


class OverlayAlreadyAppliedError(ConsumerCutoverError):
    """Raised when overlay corrections would be applied a second time."""


@dataclass(frozen=True)
class DatasetPin:
    """One dataset generation and revision shared by consumers."""

    dataset_generation: str
    dataset_revision: int

    def __post_init__(self) -> None:
        try:
            generation = str(UUID(self.dataset_generation))
        except (AttributeError, TypeError, ValueError) as exc:
            raise ConsumerCutoverError("Dataset generation must be a canonical UUID.") from exc
        if generation != self.dataset_generation:
            raise ConsumerCutoverError("Dataset generation must be a canonical UUID.")
        if isinstance(self.dataset_revision, bool) or not isinstance(self.dataset_revision, int):
            raise ConsumerCutoverError("Dataset revision must be a non-negative integer.")
        if self.dataset_revision < 0:
            raise ConsumerCutoverError("Dataset revision must be a non-negative integer.")

    def to_public_dict(self) -> dict[str, str | int]:
        """Return the privacy-safe pin."""
        return {
            "dataset_generation": self.dataset_generation,
            "dataset_revision": self.dataset_revision,
        }


@dataclass(frozen=True)
class ManualState:
    """User-authored tags, notes, and category that restart must keep."""

    tags_manual: tuple[str, ...] = ()
    notes_manual: str = ""
    category_manual: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        """Return the preserved manual fields without financial amounts."""
        return {
            "tags_manual": list(self.tags_manual),
            "notes_manual": self.notes_manual,
            "category_manual": self.category_manual,
        }

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> ManualState:
        """Parse stored manual state."""
        raw_tags = payload.get("tags_manual") or []
        category = payload.get("category_manual")
        return cls(
            tags_manual=tuple(str(tag) for tag in raw_tags),
            notes_manual=str(payload.get("notes_manual") or ""),
            category_manual=None if category is None else str(category),
        )


@dataclass(frozen=True)
class RuntimeDefaults:
    """Operational defaults that survive installing cutover-prep code."""

    mode: RuntimeMode
    authority: Authority
    fence_enabled: bool
    cutover_issue: int

    def to_public_dict(self) -> dict[str, object]:
        """Return the privacy-safe default runtime contract."""
        return {
            "mode": self.mode,
            "authority": self.authority,
            "fence_enabled": self.fence_enabled,
            "cutover_issue": self.cutover_issue,
        }


@dataclass(frozen=True)
class ConsumerRead:
    """One consumer's resolved read against the active authority."""

    consumer: ConsumerSpec
    authority: Authority
    pin: DatasetPin | None
    derived_revision: str | None
    manual_state: ManualState

    def to_public_dict(self) -> dict[str, object]:
        """Return a privacy-safe read envelope."""
        payload: dict[str, object] = {
            "consumer_id": self.consumer.consumer_id,
            "kind": self.consumer.kind,
            "authority": self.authority,
            "derived_revision": self.derived_revision,
            "manual_state": self.manual_state.to_public_dict(),
        }
        if self.pin is not None:
            payload.update(self.pin.to_public_dict())
        else:
            payload["dataset_generation"] = None
            payload["dataset_revision"] = None
        return payload


@dataclass(frozen=True)
class OverlayBinding:
    """External overlay pinned to one canonical baseline revision."""

    digest: str
    baseline_revision: int
    applied_correction_id: str | None = None

    def to_public_dict(self) -> dict[str, object]:
        """Return overlay identity without overlay payload bytes."""
        return {
            "digest": self.digest,
            "baseline_revision": self.baseline_revision,
            "applied_correction_id": self.applied_correction_id,
        }


@dataclass(frozen=True)
class OverlayApplyResult:
    """Outcome of applying overlay corrections once at the baseline revision."""

    status: OverlayStatus
    correction_id: str
    pin: DatasetPin

    def to_public_dict(self) -> dict[str, object]:
        """Return a privacy-safe overlay apply envelope."""
        payload: dict[str, object] = {
            "status": self.status,
            "correction_id": self.correction_id,
        }
        payload.update(self.pin.to_public_dict())
        return payload


@dataclass(frozen=True)
class AnalysisReport:
    """Deterministic analysis report bound to one revision and manual state."""

    consumer_id: str
    pin: DatasetPin
    manual_state: ManualState
    digest: str

    def to_public_dict(self) -> dict[str, object]:
        """Return the report envelope without host paths or amounts."""
        payload: dict[str, object] = {
            "consumer_id": self.consumer_id,
            "digest": self.digest,
            "manual_state": self.manual_state.to_public_dict(),
        }
        payload.update(self.pin.to_public_dict())
        return payload


def operational_defaults() -> RuntimeDefaults:
    """Return the pre-cutover runtime contract.

    Merging or installing this package must not enable SQLite authority or
    the legacy CSV fence. Actual activation belongs to issue ``CUTOVER_ISSUE``.
    """
    return RuntimeDefaults(
        mode="csv",
        authority="csv",
        fence_enabled=False,
        cutover_issue=CUTOVER_ISSUE,
    )


def overlay_digest(payload: bytes) -> str:
    """Return the SHA-256 hex digest of overlay bytes."""
    return hashlib.sha256(payload).hexdigest()


def _reject_escape(root: Path, candidate: Path) -> Path:
    if ".." in Path(candidate).parts:
        raise ConsumerCutoverError("Consumer path must not contain parent segments.")
    absolute = candidate.expanduser()
    if not absolute.is_absolute():
        absolute = (root / candidate).expanduser()
    resolved_root = root.expanduser().absolute()
    resolved = absolute.absolute()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ConsumerCutoverError("Consumer path must stay inside the target root.")
    return resolved


def _lock_payload() -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "kind": "legacy_csv_write_fence",
        "enabled": True,
        "activation": "isolated_cutover_only",
        "cutover_issue": CUTOVER_ISSUE,
    }


def attempt_direct_csv_write(
    data_dir: Path,
    relative_path: str,
    payload: bytes,
    *,
    understands_lock_file: bool,
) -> None:
    """Try a direct CSV write, simulating new or old installations.

    New installs honor the lock/settings file. Old installs that ignore it still
    fail when the CSV tree has been made unwritable.
    """
    target = _reject_escape(data_dir, Path(relative_path))
    if understands_lock_file:
        lock_path = data_dir / LOCK_FILENAME
        if lock_path.is_file():
            raise LegacyCsvWriteBlockedError("Legacy CSV writes are fenced.")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    except OSError as exc:
        raise LegacyCsvWriteBlockedError("Direct CSV write blocked by permissions.") from exc


class IsolatedCutover:
    """Isolated-environment harness for consumer cutover validation.

    The default constructor argument ``mode="cutover"`` is for isolation
    tests. Production callers should keep :func:`operational_defaults`.
    """

    def __init__(
        self,
        target_root: Path,
        pin: DatasetPin,
        *,
        mode: RuntimeMode = "cutover",
        manual_state: ManualState | None = None,
        overlay_bytes: bytes = b"",
    ) -> None:
        if target_root.exists() and target_root.is_symlink():
            raise ConsumerCutoverError("Cutover target must not be a symlink.")
        if ".." in Path(target_root).parts:
            raise ConsumerCutoverError("Cutover target must not contain parent segments.")
        self.target_root = target_root.expanduser().absolute()
        self.data_dir = self.target_root / "data"
        self.pin = pin
        self.mode: RuntimeMode = mode
        self.manual_state = manual_state or ManualState()
        self.overlay_bytes = overlay_bytes
        self.overlay: OverlayBinding | None = None
        self.fence_enabled = False
        self._remembered_modes: dict[Path, int] = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if overlay_bytes:
            self.bind_overlay(overlay_bytes)

    def __enter__(self) -> IsolatedCutover:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    @property
    def authority(self) -> Authority:
        """Return CSV before cutover and the pinned revision in cutover mode."""
        if self.mode == "cutover":
            return "sqlite_revision"
        return "csv"

    @property
    def derived_revision(self) -> str | None:
        """Return the derived projection path in cutover mode only."""
        if self.mode != "cutover":
            return None
        path = GenerationPaths(self.target_root).derived_revision(
            self.pin.dataset_generation,
            self.pin.dataset_revision,
        )
        return path.relative_to(self.target_root).as_posix()

    @property
    def state_path(self) -> Path:
        """Return the isolated session file, outside CSV trees."""
        return self.target_root / STATE_FILENAME

    def persist(self) -> Path:
        """Write restartable session state without financial row payloads."""
        payload = {
            "schema_version": SCHEMA_VERSION,
            "mode": self.mode,
            "pin": self.pin.to_public_dict(),
            "manual_state": self.manual_state.to_public_dict(),
            "fence_enabled": self.fence_enabled,
            "overlay": None if self.overlay is None else self.overlay.to_public_dict(),
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
        self.state_path.write_text(f"{encoded}\n", encoding="utf-8")
        return self.state_path

    @classmethod
    def resume(cls, target_root: Path) -> IsolatedCutover:
        """Reload an isolated session after Hermes restart or re-run."""
        state_path = target_root.expanduser().absolute() / STATE_FILENAME
        if not state_path.is_file():
            raise ConsumerCutoverError("Cutover session state is missing.")
        payload = json.loads(state_path.read_text(encoding="utf-8"))
        pin_payload = payload["pin"]
        session = cls(
            target_root,
            DatasetPin(
                dataset_generation=str(pin_payload["dataset_generation"]),
                dataset_revision=int(pin_payload["dataset_revision"]),
            ),
            mode=payload["mode"],
            manual_state=ManualState.from_mapping(payload["manual_state"]),
        )
        session.fence_enabled = bool(payload.get("fence_enabled"))
        overlay_payload = payload.get("overlay")
        if overlay_payload:
            session.overlay = OverlayBinding(
                digest=str(overlay_payload["digest"]),
                baseline_revision=int(overlay_payload["baseline_revision"]),
                applied_correction_id=overlay_payload.get("applied_correction_id"),
            )
        return session

    def read_consumer(self, consumer_id: str) -> ConsumerRead:
        """Resolve one inventoried consumer to the active authority."""
        spec = get_consumer(consumer_id)
        pin = self.pin if self.mode == "cutover" else None
        return ConsumerRead(
            consumer=spec,
            authority=self.authority,
            pin=pin,
            derived_revision=self.derived_revision,
            manual_state=self.manual_state,
        )

    def read_all_consumers(self) -> tuple[ConsumerRead, ...]:
        """Resolve every known consumer against the same authority."""
        return tuple(self.read_consumer(spec.consumer_id) for spec in known_consumers())

    def verify_shared_revision(self) -> DatasetPin:
        """Fail unless every known consumer reads the same cutover pin."""
        if self.mode != "cutover":
            raise ConsumerCutoverError("Shared revision checks require cutover mode.")
        reads = self.read_all_consumers()
        pins = {
            (item.pin.dataset_generation, item.pin.dataset_revision)
            for item in reads
            if item.pin is not None
        }
        if len(pins) != 1:
            raise ConsumerCutoverError("Known consumers do not share one dataset revision.")
        authorities = {item.authority for item in reads}
        if authorities != {"sqlite_revision"}:
            raise ConsumerCutoverError("Cutover consumers must read the sqlite revision.")
        return self.pin

    def restart_hermes(self) -> IsolatedCutover:
        """Persist and reload so a Hermes restart keeps the same pin and manual state."""
        self.persist()
        return IsolatedCutover.resume(self.target_root)

    def rerun_hermes(self) -> IsolatedCutover:
        """Re-run the isolated Hermes session without changing user manual state."""
        return self.restart_hermes()

    def analysis_report(self, consumer_id: str = "analysis.export_report") -> AnalysisReport:
        """Build a deterministic report bound to the pinned revision and manual state."""
        spec = get_consumer(consumer_id)
        if spec.kind != "analysis_report":
            raise ConsumerCutoverError("Analysis reports must use an analysis consumer.")
        read = self.read_consumer(consumer_id)
        pin = read.pin or self.pin
        material = json.dumps(
            {
                "consumer_id": consumer_id,
                "pin": pin.to_public_dict(),
                "manual_state": self.manual_state.to_public_dict(),
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(material.encode("utf-8")).hexdigest()
        return AnalysisReport(
            consumer_id=consumer_id,
            pin=pin,
            manual_state=self.manual_state,
            digest=digest,
        )

    def bind_overlay(self, payload: bytes) -> OverlayBinding:
        """Pin overlay baseline meaning to the canonical dataset revision."""
        digest = overlay_digest(payload)
        binding = OverlayBinding(
            digest=digest,
            baseline_revision=self.pin.dataset_revision,
            applied_correction_id=self.overlay.applied_correction_id if self.overlay else None,
        )
        self.overlay_bytes = payload
        self.overlay = binding
        overlay_path = self.target_root / "overlay.yaml"
        overlay_path.write_bytes(payload)
        return binding

    def apply_overlay_corrections(self, correction_id: str) -> OverlayApplyResult:
        """Apply overlay corrections once; retries do not duplicate the baseline."""
        if self.overlay is None:
            raise ConsumerCutoverError("Overlay is not bound to a canonical revision.")
        if self.overlay.baseline_revision != self.pin.dataset_revision:
            raise ConsumerCutoverError("Overlay baseline must match the dataset revision.")
        if self.overlay.applied_correction_id == correction_id:
            return OverlayApplyResult(
                status="already_applied",
                correction_id=correction_id,
                pin=self.pin,
            )
        if self.overlay.applied_correction_id is not None:
            raise OverlayAlreadyAppliedError("Overlay corrections already applied.")
        self.overlay = OverlayBinding(
            digest=self.overlay.digest,
            baseline_revision=self.overlay.baseline_revision,
            applied_correction_id=correction_id,
        )
        self.persist()
        return OverlayApplyResult(
            status="applied",
            correction_id=correction_id,
            pin=self.pin,
        )

    def activate_legacy_csv_fence(self) -> Path:
        """Fence CSV writes in this isolated target only.

        Writes a lock/settings file new installs understand and makes CSV trees
        unwritable so old installs that ignore the lock still fail closed.
        """
        if self.mode != "cutover":
            raise ConsumerCutoverError("CSV fence activation is isolated cutover only.")
        for name in CSV_TREE_NAMES:
            tree = self.data_dir / name
            tree.mkdir(parents=True, exist_ok=True)
        lock_path = self.data_dir / LOCK_FILENAME
        encoded = json.dumps(_lock_payload(), ensure_ascii=False, sort_keys=True, indent=2)
        lock_path.write_text(f"{encoded}\n", encoding="utf-8")
        remembered: dict[Path, int] = {}
        for name in CSV_TREE_NAMES:
            remembered.update(_chmod_tree_readonly(self.data_dir / name))
        self._remembered_modes = remembered
        self.fence_enabled = True
        self.persist()
        return lock_path

    def attempt_direct_csv_write(
        self,
        relative_path: str = "transactions/2024/01/transactions.csv",
        payload: bytes = b"synthetic,blocked\n",
        *,
        understands_lock_file: bool,
    ) -> None:
        """Attempt a direct CSV write against this isolated data-dir."""
        attempt_direct_csv_write(
            self.data_dir,
            relative_path,
            payload,
            understands_lock_file=understands_lock_file,
        )

    def close(self) -> None:
        """Restore chmod'd trees so isolated fixtures can be deleted."""
        if self._remembered_modes:
            _restore_modes(self._remembered_modes)
            self._remembered_modes = {}
            return
        if not self.fence_enabled:
            return
        for name in CSV_TREE_NAMES:
            tree = self.data_dir / name
            if not tree.exists():
                continue
            paths = sorted((tree, *tree.rglob("*")), key=lambda item: len(item.parts), reverse=True)
            for path in paths:
                if path.is_dir():
                    os.chmod(path, 0o755)
                elif path.is_file():
                    os.chmod(path, 0o644)


def _chmod_tree_readonly(root: Path) -> dict[Path, int]:
    remembered: dict[Path, int] = {}
    if not root.exists():
        return remembered
    paths = [root, *sorted(root.rglob("*"))]
    for path in paths:
        if path.is_symlink():
            continue
        remembered[path] = stat.S_IMODE(path.stat().st_mode)
        if path.is_dir():
            path.chmod(0o555)
        elif path.is_file():
            path.chmod(0o444)
    return remembered


def _restore_modes(remembered: dict[Path, int]) -> None:
    for path in sorted(remembered, key=lambda item: len(item.parts), reverse=True):
        if path.exists():
            os.chmod(path, remembered[path])
