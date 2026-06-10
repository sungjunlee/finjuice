"""Tests for installed package artifact smoke helpers."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from scripts import smoke_installed_artifact


def test_read_project_version_uses_project_table(tmp_path: Path) -> None:
    """The smoke expected version should come from pyproject's project table."""
    (tmp_path / "pyproject.toml").write_text(
        """
[tool.example]
version = "9.9.9"

[project]
name = "finjuice"
version = "1.2.3"
""".strip(),
        encoding="utf-8",
    )

    assert smoke_installed_artifact.read_project_version(tmp_path) == "1.2.3"


def test_prepare_smoke_data_dir_writes_minimal_status_fixture(tmp_path: Path) -> None:
    """The status smoke needs a tiny synthetic partition so the command exits 0."""
    smoke_installed_artifact.prepare_smoke_data_dir(tmp_path)

    partition_path = tmp_path / "transactions" / "2024" / "10" / "transactions.csv"
    assert partition_path.is_file()
    assert (tmp_path / "rules.yaml").read_text(encoding="utf-8") == "version: 1\nrules: []\n"

    csv_lines = partition_path.read_text(encoding="utf-8").splitlines()
    assert csv_lines[0].split(",") == smoke_installed_artifact.SMOKE_TRANSACTION_COLUMNS
    assert len(csv_lines) == 2


def test_validate_probe_result_rejects_empty_stdout() -> None:
    """Smoke probes must prove the installed CLI emitted something useful."""
    spec = smoke_installed_artifact.CommandProbe(
        name="help",
        args=("finjuice", "--help"),
    )
    result = subprocess.CompletedProcess(args=spec.args, returncode=0, stdout="", stderr="")

    with pytest.raises(smoke_installed_artifact.SmokeArtifactError, match="empty stdout"):
        smoke_installed_artifact.validate_probe_result(
            spec,
            result,
            expected_version="1.2.3",
        )


def test_validate_probe_result_checks_json_stdout() -> None:
    """JSON probes should fail before a broken CLI contract reaches CI green."""
    spec = smoke_installed_artifact.CommandProbe(
        name="doctor-json",
        args=("finjuice", "doctor", "--json"),
        json_output=True,
    )
    result = subprocess.CompletedProcess(
        args=spec.args,
        returncode=0,
        stdout="not json",
        stderr="",
    )

    with pytest.raises(smoke_installed_artifact.SmokeArtifactError, match="valid JSON"):
        smoke_installed_artifact.validate_probe_result(
            spec,
            result,
            expected_version="1.2.3",
        )


def test_validate_probe_result_checks_version_stdout() -> None:
    """The installed console script should report the built package version."""
    spec = smoke_installed_artifact.CommandProbe(
        name="version",
        args=("finjuice", "--version"),
        expected_stdout="finjuice 1.2.3",
    )
    result = subprocess.CompletedProcess(
        args=spec.args,
        returncode=0,
        stdout="finjuice 0.0.0\n",
        stderr="",
    )

    with pytest.raises(smoke_installed_artifact.SmokeArtifactError, match="expected stdout"):
        smoke_installed_artifact.validate_probe_result(
            spec,
            result,
            expected_version="1.2.3",
        )


def test_create_stdlib_venv_wraps_ensurepip_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """venv creation failures should produce smoke diagnostics instead of tracebacks."""

    class BrokenEnvBuilder:
        def __init__(self, *, with_pip: bool, clear: bool, symlinks: bool) -> None:
            assert with_pip is True
            assert clear is True
            assert symlinks is (os.name != "nt")

        def create(self, env_dir: Path) -> None:
            raise subprocess.CalledProcessError(
                returncode=6,
                cmd=["python", "-m", "ensurepip"],
                output="ensurepip stdout",
                stderr="ensurepip stderr",
            )

    monkeypatch.setattr(smoke_installed_artifact.venv, "EnvBuilder", BrokenEnvBuilder)

    with pytest.raises(
        smoke_installed_artifact.SmokeArtifactError,
        match="stdlib venv creation failed",
    ):
        smoke_installed_artifact.create_stdlib_venv(tmp_path / "venv")
