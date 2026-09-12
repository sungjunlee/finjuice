"""Synthetic boundary checks for private migration plan publication."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from finjuice.pipeline.backup import (
    BackupError,
    ConsistencyEvidence,
    CreateRequest,
    create_backup,
)
from finjuice.pipeline.migration import MigrationError, plan_migration
from finjuice.pipeline.migration.common import tree_inventory


@pytest.fixture
def capture(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "active"
    source.mkdir()
    (source / "synthetic.bin").write_bytes(b"synthetic-preservation-input")
    frozen = tmp_path / "capture"
    create_backup(
        CreateRequest(
            source=source,
            output=frozen,
            consistency=ConsistencyEvidence("stopped_writers", ("synthetic-test",)),
        )
    )
    return source, frozen


@pytest.mark.parametrize("boundary", ["active", "capture"])
@pytest.mark.parametrize("position", ["equal", "descendant", "ancestor"])
def test_plan_rejects_source_overlap_without_changing_either_tree(
    capture: tuple[Path, Path], boundary: str, position: str
) -> None:
    # Arrange.
    active, frozen = capture
    protected = active if boundary == "active" else frozen
    targets = {
        "equal": protected,
        "descendant": protected / "plan.json",
        "ancestor": protected.parent,
    }
    before = tree_inventory(active), tree_inventory(frozen)

    # Act.
    with pytest.raises(BackupError):
        plan_migration(
            frozen / "backup-manifest.json", output=targets[position], active_data_dir=active
        )

    # Assert.
    assert before == (tree_inventory(active), tree_inventory(frozen))
    assert not (protected / "plan.json").exists()


def test_plan_rejects_program_checkout_output(capture: tuple[Path, Path], tmp_path: Path) -> None:
    # Arrange: a synthetic checkout exercises installed-wheel repo detection too.
    active, frozen = capture
    checkout = tmp_path / "program"
    (checkout / ".git").mkdir(parents=True)
    (checkout / "src" / "finjuice").mkdir(parents=True)
    (checkout / "pyproject.toml").write_text("[project]\nname = 'finjuice'\n")
    before = tree_inventory(checkout), tree_inventory(active), tree_inventory(frozen)

    # Act.
    with pytest.raises(BackupError):
        plan_migration(
            frozen / "backup-manifest.json",
            output=checkout / "private-plan.json",
            active_data_dir=active,
        )

    # Assert.
    assert before == (tree_inventory(checkout), tree_inventory(active), tree_inventory(frozen))


@pytest.mark.parametrize("alias_target", ["active", "capture", "outside"])
def test_plan_rejects_symlink_output_ancestors(
    capture: tuple[Path, Path], tmp_path: Path, alias_target: str
) -> None:
    # Arrange.
    active, frozen = capture
    outside = tmp_path / "outside"
    outside.mkdir()
    target = {"active": active, "capture": frozen, "outside": outside}[alias_target]
    alias = tmp_path / "alias"
    alias.symlink_to(target, target_is_directory=True)
    before = tree_inventory(active), tree_inventory(frozen), tree_inventory(outside)

    # Act.
    with pytest.raises(BackupError):
        plan_migration(
            frozen / "backup-manifest.json", output=alias / "plan.json", active_data_dir=active
        )

    # Assert.
    assert before == (tree_inventory(active), tree_inventory(frozen), tree_inventory(outside))


def test_private_plan_requires_active_boundary_but_preview_does_not(
    capture: tuple[Path, Path], tmp_path: Path
) -> None:
    # Arrange.
    active, frozen = capture
    output = tmp_path / "private-plan.json"
    before = tree_inventory(active), tree_inventory(frozen)

    # Act.
    with pytest.raises(MigrationError, match="Active data directory is required"):
        plan_migration(frozen / "backup-manifest.json", output=output)
    preview = plan_migration(frozen / "backup-manifest.json")

    # Assert.
    assert preview.to_dict()["status"] == "ok"
    assert not output.exists()
    assert before == (tree_inventory(active), tree_inventory(frozen))


def test_plan_publishes_to_isolated_output_without_source_changes(
    capture: tuple[Path, Path], tmp_path: Path
) -> None:
    # Arrange.
    active, frozen = capture
    output = tmp_path / "private-plan.json"
    before = tree_inventory(active), tree_inventory(frozen)

    # Act.
    result = plan_migration(frozen / "backup-manifest.json", output=output, active_data_dir=active)

    # Assert.
    document = json.loads(output.read_text())
    assert document == result.to_dict()["plan"]
    assert before == (tree_inventory(active), tree_inventory(frozen))
    assert output.stat().st_mode & 0o777 == 0o600
