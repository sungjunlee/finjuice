"""Publish derived CLI files without overwriting active repository inputs."""

from __future__ import annotations

import os
import stat
import unicodedata
from pathlib import Path

from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.atomic_files import replace_with_owned_temp
from finjuice.pipeline.storage.authority import AuthorityPaths


def write_canonical_output(config: Config, output: Path, content: bytes) -> None:
    """Atomically publish bytes outside the configured input and control namespaces."""
    try:
        _require_output_destination(config, Path(os.path.abspath(output.expanduser())))
        target = output.expanduser().resolve()
        _require_output_destination(config, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        # Recheck after directory creation and publish through the resolved path.
        target = target.resolve()
        _require_output_destination(config, target)
        if target.exists() and not stat.S_ISREG(target.stat().st_mode):
            raise ValueError("Output must be a regular file.")
        replace_with_owned_temp(target, content)
    except (OSError, ValueError, RuntimeError):
        raise ValueError(
            "Canonical output could not be saved outside protected input and storage paths."
        ) from None


def _require_output_destination(config: Config, target: Path) -> None:
    target = _namespace_path(target)
    control = AuthorityPaths.for_data_dir(config.data_dir)
    directories = (
        control.control_root.parent,
        control.control_root,
        control.generations_root,
        config.import_dir,
        config.csv_base_dir,
        config.metadata_dir,
        config.data_dir / "assets",
        config.data_dir / "banksalad",
    )
    files = (config.rules_file, config.assets_file, config.goals_file, config.scenarios_file)
    if any(
        target.is_relative_to(candidate)
        for path in directories
        for candidate in (
            _namespace_path(Path(os.path.abspath(path))),
            _namespace_path(path.resolve()),
        )
    ) or any(
        target == candidate
        for path in files
        for candidate in (
            _namespace_path(Path(os.path.abspath(path))),
            _namespace_path(path.resolve()),
        )
    ):
        raise ValueError("Output overlaps protected repository inputs.")


def _namespace_path(path: Path) -> Path:
    """Reserve equivalent spellings even on case-sensitive output filesystems."""
    return Path(unicodedata.normalize("NFC", str(path)).casefold())
