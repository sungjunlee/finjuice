"""Structure and M1 acceptance tests for consumer cutover prep (issue #439)."""

from __future__ import annotations

import importlib
import json
import stat
from pathlib import Path
from uuid import uuid4

import pytest

from finjuice.pipeline.consumers.compat import (
    CUTOVER_ISSUE,
    FENCE_PROCEDURE,
    LOCK_FILENAME,
    ConsumerCutoverError,
    DatasetPin,
    IsolatedCutover,
    LegacyCsvWriteBlockedError,
    ManualState,
    OverlayAlreadyAppliedError,
    attempt_direct_csv_write,
    operational_defaults,
    overlay_digest,
)
from finjuice.pipeline.consumers.inventory import (
    SCHEMA_VERSION,
    consumer_ids,
    consumers_by_kind,
    known_consumers,
)
from finjuice.pipeline.tagging.manual import MANUAL_CATEGORY_PREFIX

CONSUMERS_DIR = Path("src/finjuice/pipeline/consumers")
PACKAGE = "finjuice.pipeline.consumers"
INVENTORY_MODULE = "finjuice.pipeline.consumers.inventory"
COMPAT_MODULE = "finjuice.pipeline.consumers.compat"

INVENTORY_NAMES = (
    "SCHEMA_VERSION",
    "ConsumerSpec",
    "consumer_ids",
    "consumers_by_kind",
    "get_consumer",
    "known_consumers",
)
COMPAT_NAMES = (
    "CUTOVER_ISSUE",
    "FENCE_PROCEDURE",
    "LOCK_FILENAME",
    "AnalysisReport",
    "ConsumerCutoverError",
    "ConsumerRead",
    "DatasetPin",
    "IsolatedCutover",
    "LegacyCsvWriteBlockedError",
    "ManualState",
    "OverlayAlreadyAppliedError",
    "OverlayApplyResult",
    "OverlayBinding",
    "RuntimeDefaults",
    "attempt_direct_csv_write",
    "operational_defaults",
    "overlay_digest",
)

REQUIRED_KINDS = {
    "cli",
    "data_dir",
    "hermes_skill",
    "analysis_report",
    "cron",
    "manual_script",
}

SYNTHETIC_MANUAL = ManualState(
    tags_manual=("카페", f"{MANUAL_CATEGORY_PREFIX}식비"),
    notes_manual="합성 수동 메모",
    category_manual="식비",
)
SYNTHETIC_OVERLAY = b"overlay: synthetic-baseline\n"


def _pin() -> DatasetPin:
    return DatasetPin(dataset_generation=str(uuid4()), dataset_revision=3)


def _profile_snapshot(root: Path) -> dict[str, tuple[int, bytes | None]]:
    state: dict[str, tuple[int, bytes | None]] = {}
    if not root.exists():
        return state
    for path in (root, *sorted(root.rglob("*"))):
        relative = "." if path == root else path.relative_to(root).as_posix()
        entry = path.lstat()
        contents = path.read_bytes() if path.is_file() else None
        state[relative] = (stat.S_IMODE(entry.st_mode), contents)
    return state


def test_consumers_package_reexports_definition_identity() -> None:
    """Public consumer names stay identity-equal to inventory and compat."""
    package = importlib.import_module(PACKAGE)
    inventory = importlib.import_module(INVENTORY_MODULE)
    compat = importlib.import_module(COMPAT_MODULE)

    for name in INVENTORY_NAMES:
        assert getattr(package, name) is getattr(inventory, name)
    for name in COMPAT_NAMES:
        assert getattr(package, name) is getattr(compat, name)


def test_consumer_names_are_defined_once_at_their_home() -> None:
    """Inventory and compat names are defined exactly once at the home module."""
    package = importlib.import_module(PACKAGE)
    inventory = importlib.import_module(INVENTORY_MODULE)
    compat = importlib.import_module(COMPAT_MODULE)

    for name in ("known_consumers", "get_consumer", "consumers_by_kind", "consumer_ids"):
        assert getattr(inventory, name).__module__ == INVENTORY_MODULE
        assert getattr(package, name).__module__ == INVENTORY_MODULE
    for name in (
        "operational_defaults",
        "attempt_direct_csv_write",
        "overlay_digest",
    ):
        assert getattr(compat, name).__module__ == COMPAT_MODULE
        assert getattr(package, name).__module__ == COMPAT_MODULE
    assert IsolatedCutover.__module__ == COMPAT_MODULE
    assert package.IsolatedCutover is IsolatedCutover


def test_consumer_bodies_do_not_leak_into_package_init() -> None:
    """Definitions stay in inventory/compat; the package only re-exports."""
    init_text = (CONSUMERS_DIR / "__init__.py").read_text(encoding="utf-8")
    inventory_text = (CONSUMERS_DIR / "inventory.py").read_text(encoding="utf-8")
    compat_text = (CONSUMERS_DIR / "compat.py").read_text(encoding="utf-8")

    assert "def known_consumers" in inventory_text
    assert "def known_consumers" not in init_text
    assert "def known_consumers" not in compat_text
    assert "class IsolatedCutover" in compat_text
    assert "class IsolatedCutover" not in init_text
    assert "class IsolatedCutover" not in inventory_text
    assert "class ConsumerSpec" in inventory_text
    assert "class ConsumerSpec" not in compat_text
    assert "from finjuice.pipeline.consumers import" not in inventory_text
    assert "from finjuice.pipeline.consumers import" not in compat_text


def test_inventory_lists_cli_data_dir_hermes_analysis_cron_and_scripts() -> None:
    """The catalog covers every consumer class named by the issue."""
    specs = known_consumers()
    kinds = {spec.kind for spec in specs}
    ids = consumer_ids()

    assert kinds == REQUIRED_KINDS
    assert "data_dir.runtime" in ids
    assert "cron.automation" in ids
    assert "script.manual" in ids
    assert "hermes.finjuice" in ids
    assert "hermes.finjuice-report" in ids
    assert consumers_by_kind("hermes_skill")
    assert consumers_by_kind("analysis_report")
    assert SCHEMA_VERSION == "finjuice.consumers.v1"
    assert CUTOVER_ISSUE == 440
    assert "chmod_csv_trees_unwritable" in FENCE_PROCEDURE


def test_cutover_mode_all_known_consumers_read_the_same_dataset_revision(
    tmp_path: Path,
) -> None:
    """Isolated cutover pins every inventoried consumer to one revision."""
    pin = _pin()
    with IsolatedCutover(
        tmp_path / "target",
        pin,
        manual_state=SYNTHETIC_MANUAL,
        overlay_bytes=SYNTHETIC_OVERLAY,
    ) as session:
        shared = session.verify_shared_revision()
        reads = session.read_all_consumers()

    assert shared == pin
    assert len(reads) == len(known_consumers())
    assert {item.authority for item in reads} == {"sqlite_revision"}
    assert {item.pin for item in reads} == {pin}
    derived = {item.derived_revision for item in reads}
    assert len(derived) == 1
    assert next(iter(derived)) == (f"derived/{pin.dataset_generation}/{pin.dataset_revision}")
    assert {item.manual_state for item in reads} == {SYNTHETIC_MANUAL}


def test_legacy_csv_write_fence_blocks_new_and_old_installs(tmp_path: Path) -> None:
    """Lock/settings stop new installs; chmod still stops lock-unaware installs."""
    csv_relative = "transactions/2024/01/transactions.csv"
    with IsolatedCutover(tmp_path / "target", _pin()) as session:
        seed = session.data_dir / csv_relative
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("row_hash,amount\nsynthetic,0\n", encoding="utf-8")
        lock_path = session.activate_legacy_csv_fence()
        payload = json.loads(lock_path.read_text(encoding="utf-8"))

        with pytest.raises(LegacyCsvWriteBlockedError, match="fenced"):
            session.attempt_direct_csv_write(understands_lock_file=True)
        with pytest.raises(LegacyCsvWriteBlockedError, match="permissions"):
            session.attempt_direct_csv_write(understands_lock_file=False)
        with pytest.raises(LegacyCsvWriteBlockedError, match="permissions"):
            attempt_direct_csv_write(
                session.data_dir,
                csv_relative,
                b"stale-writer\n",
                understands_lock_file=False,
            )

        assert payload["enabled"] is True
        assert payload["activation"] == "isolated_cutover_only"
        assert session.fence_enabled is True
        assert seed.read_text(encoding="utf-8") == "row_hash,amount\nsynthetic,0\n"


def test_installing_cutover_keeps_operational_csv_authority(tmp_path: Path) -> None:
    """Merging the feature leaves the live path on CSV with the fence off."""
    defaults = operational_defaults()
    other = tmp_path / "other-profile"
    marker = other / "transactions" / "2024" / "01" / "transactions.csv"
    marker.parent.mkdir(parents=True)
    marker.write_text("row_hash,amount\nlive,1\n", encoding="utf-8")
    before = _profile_snapshot(other)

    with IsolatedCutover(tmp_path / "target", _pin(), mode="csv") as session:
        csv_relative = "transactions/2024/01/transactions.csv"
        session.attempt_direct_csv_write(
            csv_relative,
            b"row_hash,amount\ncsv-authority,1\n",
            understands_lock_file=True,
        )
        written = (session.data_dir / csv_relative).read_bytes()
        with pytest.raises(ConsumerCutoverError, match="isolated cutover only"):
            session.activate_legacy_csv_fence()
        with pytest.raises(ConsumerCutoverError, match="cutover mode"):
            session.verify_shared_revision()
        reads = session.read_all_consumers()

    after = _profile_snapshot(other)
    assert defaults.mode == "csv"
    assert defaults.authority == "csv"
    assert defaults.fence_enabled is False
    assert defaults.cutover_issue == 440
    assert session.authority == "csv"
    assert session.fence_enabled is False
    assert not (session.data_dir / LOCK_FILENAME).exists()
    assert written == b"row_hash,amount\ncsv-authority,1\n"
    assert {item.authority for item in reads} == {"csv"}
    assert {item.pin for item in reads} == {None}
    assert after == before


def test_hermes_restart_and_analysis_report_keep_manual_state(tmp_path: Path) -> None:
    """Hermes restart/re-run and analysis reports keep user manual fields."""
    pin = _pin()
    with IsolatedCutover(
        tmp_path / "target",
        pin,
        manual_state=SYNTHETIC_MANUAL,
        overlay_bytes=SYNTHETIC_OVERLAY,
    ) as session:
        first_report = session.analysis_report()
        restarted = session.restart_hermes()
        rerun = session.rerun_hermes()
        second_report = restarted.analysis_report("analysis.template_report")
        third_report = rerun.analysis_report()
        overlay = session.apply_overlay_corrections("overlay-baseline-v1")
        retry = session.apply_overlay_corrections("overlay-baseline-v1")
        with pytest.raises(OverlayAlreadyAppliedError):
            session.apply_overlay_corrections("overlay-other-v1")
        hermes_reads = [
            restarted.read_consumer("hermes.finjuice"),
            restarted.read_consumer("hermes.finjuice-report"),
            restarted.read_consumer("analysis.html_report"),
        ]

    assert restarted.pin == pin
    assert restarted.manual_state == SYNTHETIC_MANUAL
    assert rerun.manual_state == SYNTHETIC_MANUAL
    assert first_report.manual_state == SYNTHETIC_MANUAL
    assert first_report.pin == pin
    assert third_report == first_report
    assert second_report.manual_state == SYNTHETIC_MANUAL
    assert second_report.digest != first_report.digest
    assert overlay.status == "applied"
    assert retry.status == "already_applied"
    assert overlay.pin == pin
    assert session.overlay is not None
    assert session.overlay.digest == overlay_digest(SYNTHETIC_OVERLAY)
    assert session.overlay.baseline_revision == pin.dataset_revision
    assert {item.manual_state for item in hermes_reads} == {SYNTHETIC_MANUAL}
    assert {item.pin for item in hermes_reads} == {pin}


def test_cutover_does_not_change_out_of_scope_profiles(tmp_path: Path) -> None:
    """Only the declared target profile is fenced or rewritten."""
    other = tmp_path / "other-profile"
    live = other / "data" / "transactions" / "2024" / "01" / "transactions.csv"
    live.parent.mkdir(parents=True)
    live.write_text("row_hash,amount\nlive-other,1\n", encoding="utf-8")
    before = _profile_snapshot(other)

    with IsolatedCutover(
        tmp_path / "target-profile",
        _pin(),
        manual_state=SYNTHETIC_MANUAL,
        overlay_bytes=SYNTHETIC_OVERLAY,
    ) as session:
        session.activate_legacy_csv_fence()
        session.apply_overlay_corrections("overlay-baseline-v1")
        session.restart_hermes()
        with pytest.raises(LegacyCsvWriteBlockedError):
            session.attempt_direct_csv_write(understands_lock_file=True)

    after = _profile_snapshot(other)
    assert after == before
    assert not (other / "data" / LOCK_FILENAME).exists()
    assert (tmp_path / "target-profile" / "overlay.yaml").read_bytes() == SYNTHETIC_OVERLAY
    assert not (other / "overlay.yaml").exists()


def test_resumed_close_restores_remembered_modes_without_widening(tmp_path: Path) -> None:
    """A resumed fenced session must not chmod trees to 0o755/0o644."""
    csv_relative = "transactions/2024/01/transactions.csv"
    target = tmp_path / "target"
    with IsolatedCutover(target, _pin()) as session:
        seed = session.data_dir / csv_relative
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("row_hash,amount\nsynthetic,0\n", encoding="utf-8")
        original_file_mode = stat.S_IMODE(seed.stat().st_mode)
        original_dir_mode = stat.S_IMODE(seed.parent.stat().st_mode)
        session.activate_legacy_csv_fence()
        resumed = IsolatedCutover.resume(target)
        resumed.close()
        assert stat.S_IMODE(seed.stat().st_mode) == original_file_mode
        assert stat.S_IMODE(seed.parent.stat().st_mode) == original_dir_mode


def test_stale_session_persist_does_not_drop_applied_overlay(tmp_path: Path) -> None:
    """A stale handle must not clobber apply-once overlay state on disk."""
    target = tmp_path / "target"
    pin = _pin()
    with IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY) as session:
        applied = session.apply_overlay_corrections("overlay-baseline-v1")
        stale = IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY)
        stale.persist()
        stale.close()
        resumed = IsolatedCutover.resume(target)
        retry = resumed.apply_overlay_corrections("overlay-baseline-v1")

    assert applied.status == "applied"
    assert retry.status == "already_applied"
    assert resumed.overlay is not None
    assert resumed.overlay.applied_correction_id == "overlay-baseline-v1"


def test_stale_session_cannot_apply_a_second_correction(tmp_path: Path) -> None:
    """A stale handle must not apply a different correction over disk state."""
    target = tmp_path / "target"
    pin = _pin()
    with IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY) as session:
        applied = session.apply_overlay_corrections("overlay-baseline-v1")
        stale = IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY)
        with pytest.raises(OverlayAlreadyAppliedError):
            stale.apply_overlay_corrections("overlay-other-v1")
        retry = IsolatedCutover.resume(target).apply_overlay_corrections("overlay-baseline-v1")

    assert applied.status == "applied"
    assert retry.status == "already_applied"


def test_stale_persist_does_not_drop_fence_modes(tmp_path: Path) -> None:
    """A stale handle must not poison remembered modes; restoring them clears the fence."""
    csv_relative = "transactions/2024/01/transactions.csv"
    target = tmp_path / "target"
    pin = _pin()
    with IsolatedCutover(target, pin) as session:
        seed = session.data_dir / csv_relative
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("row_hash,amount\nsynthetic,0\n", encoding="utf-8")
        original_file_mode = stat.S_IMODE(seed.stat().st_mode)
        session.activate_legacy_csv_fence()
        stale = IsolatedCutover(target, pin)
        stale.persist()
        stale.close()
        resumed = IsolatedCutover.resume(target)
        resumed.close()
        assert resumed.fence_enabled is False
        assert stat.S_IMODE(seed.stat().st_mode) == original_file_mode


def test_second_fence_activation_does_not_poison_remembered_modes(tmp_path: Path) -> None:
    """Re-activating the fence must restore the original, not 0o444."""
    csv_relative = "transactions/2024/01/transactions.csv"
    target = tmp_path / "target"
    with IsolatedCutover(target, _pin()) as session:
        seed = session.data_dir / csv_relative
        seed.parent.mkdir(parents=True, exist_ok=True)
        seed.write_text("row_hash,amount\nsynthetic,0\n", encoding="utf-8")
        original_file_mode = stat.S_IMODE(seed.stat().st_mode)
        session.activate_legacy_csv_fence()
        session.activate_legacy_csv_fence()
        session.close()
        assert stat.S_IMODE(seed.stat().st_mode) == original_file_mode


def test_mismatched_overlay_digest_does_not_adopt_disk_correction(tmp_path: Path) -> None:
    """A stale handle with a different overlay must not rewrite overlay.yaml."""
    target = tmp_path / "target"
    pin = _pin()
    other = b"overlay: other-binding\n"
    with IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY) as session:
        applied = session.apply_overlay_corrections("overlay-baseline-v1")
        with pytest.raises(OverlayAlreadyAppliedError):
            IsolatedCutover(target, pin, overlay_bytes=other)
        resumed = IsolatedCutover.resume(target)
        retry = resumed.apply_overlay_corrections("overlay-baseline-v1")

    assert applied.status == "applied"
    assert retry.status == "already_applied"
    assert (target / "overlay.yaml").read_bytes() == SYNTHETIC_OVERLAY
    assert resumed.overlay is not None
    assert resumed.overlay.digest == overlay_digest(SYNTHETIC_OVERLAY)
    assert resumed.overlay.applied_correction_id == "overlay-baseline-v1"


def test_close_resume_reactivate_refences_csv_trees(tmp_path: Path) -> None:
    """After close, resume must not claim a live fence until re-activated."""
    csv_relative = "transactions/2024/01/transactions.csv"
    target = tmp_path / "target"
    pin = _pin()
    session = IsolatedCutover(target, pin)
    seed = session.data_dir / csv_relative
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("row_hash,amount\nsynthetic,0\n", encoding="utf-8")
    session.activate_legacy_csv_fence()
    session.close()
    resumed = IsolatedCutover.resume(target)
    assert resumed.fence_enabled is False
    resumed.activate_legacy_csv_fence()
    with pytest.raises(LegacyCsvWriteBlockedError):
        resumed.attempt_direct_csv_write(understands_lock_file=False)
    resumed.close()


def test_applied_overlay_cannot_rebind_to_a_different_pin(tmp_path: Path) -> None:
    """An applied overlay keeps its baseline and cannot be rebound to another pin."""
    target = tmp_path / "target"
    pin = _pin()
    other = DatasetPin(dataset_generation=str(uuid4()), dataset_revision=pin.dataset_revision + 1)
    with IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY) as session:
        applied = session.apply_overlay_corrections("overlay-baseline-v1")
        with pytest.raises(ConsumerCutoverError, match="different dataset pin"):
            IsolatedCutover(target, other, overlay_bytes=SYNTHETIC_OVERLAY)
        resumed = IsolatedCutover.resume(target)
        retry = resumed.apply_overlay_corrections("overlay-baseline-v1")

    assert applied.status == "applied"
    assert retry.status == "already_applied"
    assert resumed.pin == pin
    assert resumed.overlay is not None
    assert resumed.overlay.baseline_revision == pin.dataset_revision
    assert (target / "overlay.yaml").read_bytes() == SYNTHETIC_OVERLAY


def test_resume_close_clears_fence_flag(tmp_path: Path) -> None:
    """A resumed handle that restores modes must persist fence_enabled=False."""
    csv_relative = "transactions/2024/01/transactions.csv"
    target = tmp_path / "target"
    pin = _pin()
    session = IsolatedCutover(target, pin)
    seed = session.data_dir / csv_relative
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("row_hash,amount\nsynthetic,0\n", encoding="utf-8")
    session.activate_legacy_csv_fence()
    resumed = IsolatedCutover.resume(target)
    resumed.close()
    payload = json.loads((target / "cutover-state.json").read_text(encoding="utf-8"))
    assert payload["fence_enabled"] is False
    session.close()


def test_direct_csv_write_rejects_symlink_escape(tmp_path: Path) -> None:
    """A symlink inside the data dir cannot write outside the target root."""
    target = tmp_path / "target"
    outside = tmp_path / "outside.csv"
    outside.write_text("keep\n", encoding="utf-8")
    session = IsolatedCutover(target, _pin())
    link = session.data_dir / "transactions" / "escape.csv"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)
    with pytest.raises(ConsumerCutoverError, match="inside the target root"):
        session.attempt_direct_csv_write(
            "transactions/escape.csv",
            b"escaped\n",
            understands_lock_file=False,
        )
    assert outside.read_text(encoding="utf-8") == "keep\n"
    session.close()


def test_owner_close_does_not_drop_applied_overlay(tmp_path: Path) -> None:
    """Owner close must merge disk overlay apply-once instead of nulling it."""
    target = tmp_path / "target"
    pin = _pin()
    owner = IsolatedCutover(target, pin)
    owner.activate_legacy_csv_fence()
    other = IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY)
    applied = other.apply_overlay_corrections("overlay-baseline-v1")
    other.close()
    owner.close()
    resumed = IsolatedCutover.resume(target)
    retry = resumed.apply_overlay_corrections("overlay-baseline-v1")
    assert applied.status == "applied"
    assert retry.status == "already_applied"
    assert resumed.overlay is not None
    assert resumed.overlay.applied_correction_id == "overlay-baseline-v1"


def test_applied_overlay_cannot_rebind_to_same_revision_other_generation(
    tmp_path: Path,
) -> None:
    """Same revision number with a different generation is still a different pin."""
    target = tmp_path / "target"
    pin = _pin()
    other = DatasetPin(dataset_generation=str(uuid4()), dataset_revision=pin.dataset_revision)
    with IsolatedCutover(target, pin, overlay_bytes=SYNTHETIC_OVERLAY) as session:
        session.apply_overlay_corrections("overlay-baseline-v1")
        with pytest.raises(ConsumerCutoverError, match="different dataset pin"):
            IsolatedCutover(target, other, overlay_bytes=SYNTHETIC_OVERLAY)
        resumed = IsolatedCutover.resume(target)
        assert resumed.overlay is not None
        assert resumed.overlay.dataset_generation == pin.dataset_generation


def test_data_dir_symlink_is_rejected(tmp_path: Path) -> None:
    """The isolated data dir itself must not point outside the target."""
    target = tmp_path / "target"
    target.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (target / "data").symlink_to(outside)
    with pytest.raises(ConsumerCutoverError, match="data dir must not be a symlink"):
        IsolatedCutover(target, _pin())


def test_owner_persist_does_not_revive_cleared_fence(tmp_path: Path) -> None:
    """A later owner persist must not rewrite fence_enabled=True after teardown."""
    csv_relative = "transactions/2024/01/transactions.csv"
    target = tmp_path / "target"
    pin = _pin()
    owner = IsolatedCutover(target, pin)
    seed = owner.data_dir / csv_relative
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("row_hash,amount\nsynthetic,0\n", encoding="utf-8")
    owner.activate_legacy_csv_fence()
    IsolatedCutover.resume(target).close()
    owner.persist()
    payload = json.loads((target / "cutover-state.json").read_text(encoding="utf-8"))
    assert payload["fence_enabled"] is False
    owner.close()
