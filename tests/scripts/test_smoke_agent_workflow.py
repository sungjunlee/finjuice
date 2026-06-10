"""Tests for the public agent workflow smoke helper."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import smoke_agent_workflow


def test_smoke_steps_cover_agent_first_public_path(tmp_path: Path) -> None:
    """The smoke matrix should cover setup, import, discovery, review, and report."""
    steps = smoke_agent_workflow.smoke_steps(
        data_dir=tmp_path / "data",
        sample_xlsx=Path("tests/fixtures/sample_banksalad.xlsx"),
    )

    assert [step.name for step in steps] == [
        "init-workspace",
        "import-sample",
        "status-json",
        "index-compact",
        "checkup-compact",
        "review-template",
        "report-markdown",
    ]
    assert steps[0].args[-2:] == ("--no-git", "--with-agents")
    assert "--privacy" in steps[3].args
    assert steps[5].args[-3:] == ("run", "monthly_spend", "--json")
    assert steps[6].args[-4:] == ("export", "--format", "md", "--json")


def test_isolated_env_redirects_home_xdg_and_disables_update_check(tmp_path: Path) -> None:
    """The public smoke must not read or write the user's real finjuice workspace."""
    env = smoke_agent_workflow.isolated_env(runtime_root=tmp_path / "runtime")

    assert env["HOME"] == str(tmp_path / "runtime" / "home")
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "runtime" / "xdg-config")
    assert env["XDG_CACHE_HOME"] == str(tmp_path / "runtime" / "xdg-cache")
    assert env["XDG_DATA_HOME"] == str(tmp_path / "runtime" / "xdg-data")
    assert env["FINJUICE_RUNTIME_UPDATE_CHECK"] == "0"


def test_validate_step_result_rejects_invalid_json() -> None:
    """JSON smoke steps should fail when the command output drifts."""
    step = smoke_agent_workflow.SmokeStep(
        name="status-json",
        args=("finjuice", "status", "--json"),
    )
    result = subprocess.CompletedProcess(
        args=step.args,
        returncode=0,
        stdout="not json",
        stderr="",
    )

    with pytest.raises(smoke_agent_workflow.AgentSmokeError, match="valid JSON"):
        smoke_agent_workflow.validate_step_result(step, result)
