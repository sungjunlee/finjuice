"""Tests for finjuice version reporting."""

import importlib.metadata
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice import __version__, get_version
from finjuice.pipeline.cli.commands import doctor
from finjuice.pipeline.cli.commands.doctor import _check_finjuice_version
from finjuice.pipeline.cli.main import app

runner = CliRunner()


def test_root_version_option_prints_version_without_data_dir(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """`finjuice --version` should not require config or a data directory."""
    monkeypatch.setenv("FINJUICE_DATA_DIR", str(tmp_path / "missing-data-dir"))

    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"finjuice {__version__}"


def test_doctor_finjuice_version_uses_current_package_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Doctor should report the installed finjuice package, not the legacy package name."""
    requested_packages: list[str] = []

    def fake_version(package_name: str) -> str:
        requested_packages.append(package_name)
        return "9.8.7"

    monkeypatch.setattr(doctor.importlib.metadata, "version", fake_version)

    result = _check_finjuice_version()

    assert requested_packages == ["finjuice"]
    assert result.status == "ok"
    assert result.message == "finjuice v9.8.7"


def test_doctor_version_falls_back_to_source_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source checkouts should still report the package source version."""

    def missing_version(package_name: str) -> str:
        raise importlib.metadata.PackageNotFoundError(package_name)

    monkeypatch.setattr(doctor.importlib.metadata, "version", missing_version)

    assert get_version() == __version__
