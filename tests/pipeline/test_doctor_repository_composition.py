"""Doctor composes canonical diagnostics without legacy file or write probes."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from finjuice.pipeline.config import Config
from finjuice.pipeline.doctor import checks
from finjuice.pipeline.doctor.configuration import _check_configuration_environment
from finjuice.pipeline.doctor.data_directory import _observe_data_directory
from finjuice.pipeline.doctor.models import CheckResult


@pytest.mark.parametrize("failure", [False, True])
def test_canonical_branch_skips_legacy_checks_and_preserves_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: bool
) -> None:
    config = Config(data_dir=tmp_path)
    sentinel = tmp_path / ".doctor_test"
    sentinel.write_bytes(b"existing")
    for name in ("_check_data_directory", "_check_configuration", "_check_data_status"):
        monkeypatch.setattr(checks, name, Mock(side_effect=AssertionError("legacy collector")))
    for name in ("_check_python_version", "_check_finjuice_version", "_check_os_info"):
        monkeypatch.setattr(checks, name, lambda: CheckResult("ok", "environment"))
    monkeypatch.setattr(checks, "_check_skill_runtime", lambda: [])
    monkeypatch.setattr(checks, "_check_dependencies", lambda: [])
    monkeypatch.setattr(checks, "_check_analytics_duckdb", lambda: ([], [], None))
    monkeypatch.setenv("FINJUICE_DATA_DIR", "observed-runtime")
    repository = SimpleNamespace(
        config_checks=[CheckResult("warning", "absent")],
        data_checks=[CheckResult("error" if failure else "ok", "domain")],
        metadata={"dataset_revision": 7},
        next_step="finjuice status --json",
    )
    result = checks._build_doctor_result(config, repository=repository)
    assert result.metadata["dataset_revision"] == repository.metadata["dataset_revision"]
    assert "runtime_observation" not in repository.metadata
    assert result.next_step == repository.next_step
    assert result.payload["summary"]["errors"] == int(failure)
    assert result.payload["summary"]["total"] == len(result.payload["checks"])
    assert sum(len(items) for _, items in result.sections) == result.payload["summary"]["total"]
    assert any(title == "외부 관측: 환경 변수" for title, _ in result.sections)
    assert sentinel.read_bytes() == b"existing"
    assert {row["name"] for row in result.payload["checks"]} >= {
        "env_finjuice_data_dir",
        "data_directory_write_not_tested",
    }


def test_observation_does_not_require_legacy_layout(tmp_path: Path) -> None:
    results = _observe_data_directory(Config(data_dir=tmp_path))
    assert [item.name for item in results] == [
        "data_directory_observed",
        "data_directory_write_not_tested",
    ]
    assert not list(tmp_path.iterdir())
    assert results[0].status == "ok"


def test_environment_helper_is_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FINJUICE_DATA_DIR", raising=False)
    assert _check_configuration_environment() == []
    monkeypatch.setenv("FINJUICE_DATA_DIR", "observed-runtime")
    assert _check_configuration_environment()[0].message == "FINJUICE_DATA_DIR: observed-runtime"


def test_canonical_check_basis_and_staged_section(tmp_path: Path, monkeypatch) -> None:
    from datetime import datetime

    repository = SimpleNamespace(
        config_checks=[CheckResult("ok", "rules", name="canonical_rules")],
        data_checks=[CheckResult("warning", "pending", name="repository_staged_imports")],
        metadata={"nested": {"value": 1}},
        next_step="finjuice status",
    )
    result = checks._build_doctor_result(Config(data_dir=tmp_path), repository=repository)
    by_name = {row["name"]: row for row in result.payload["checks"]}
    assert by_name["canonical_rules"]["basis"] == "repository"
    assert by_name["repository_staged_imports"]["basis"] == "staged_observation"
    assert by_name["data_directory_observed"]["basis"] == "runtime_observation"
    assert dict(result.sections)["데이터"] == []
    assert dict(result.sections)["외부 관측: staged imports"] == repository.data_checks
    times = result.metadata["runtime_observation"]
    assert datetime.fromisoformat(times["observation_started_at"]) <= datetime.fromisoformat(
        times["observation_completed_at"]
    )
    result.metadata["nested"]["value"] = 2
    assert repository.metadata == {"nested": {"value": 1}}
