"""Tests for finjuice doctor command."""

import importlib.metadata
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS

runner = CliRunner()

V2_COLUMNS = [
    column
    for column in CSV_COLUMNS
    if column not in {"notes_manual", "category_rule", "category_final", "is_transfer_candidate"}
]


def _write_v2_partition(data_dir: Path) -> None:
    """Create one v2-shaped transaction partition for schema diagnostics."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True)
    rows = [
        [
            "abc1234567890123",
            "2024-10-01",
            "10:00",
            "지출",
            "expense",
            "식비",
            "카페",
            "스타벅스",
            "",
            "-5000",
            "신한카드",
            "KRW",
            "",
            "2024-10-01T10:00:00",
            "[]",
            "[]",
            "[]",
            "[]",
            "0",
            "1",
            "0",
            "",
            "241001_1",
            "1",
        ]
    ]
    partition_dir.joinpath("transactions.csv").write_text(
        ",".join(V2_COLUMNS) + "\n" + ",".join(rows[0]) + "\n",
        encoding="utf-8",
    )


def _write_stale_v2_registry(data_dir: Path) -> None:
    """Create a stale local v2 registry like an old initialized data directory."""
    metadata_dir = data_dir / "metadata"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "current_version": 2,
        "schemas": {
            "v2": {
                "active": True,
                "partition_schema": {
                    "columns": [
                        {
                            "name": column_name,
                            "type": "string",
                            "description": f"{column_name} column",
                        }
                        for column_name in V2_COLUMNS
                    ]
                },
            }
        },
    }
    (metadata_dir / "schema.yaml").write_text(
        yaml.safe_dump(schema, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


@pytest.fixture
def doctor_data_dir(tmp_path: Path) -> Path:
    """Create a temporary data directory for doctor command testing."""
    data_dir = tmp_path / "doctor_test"
    data_dir.mkdir()
    return data_dir


@pytest.fixture
def initialized_doctor_dir(doctor_data_dir: Path, sample_rules_path: Path) -> Path:
    """Create an initialized data directory with proper structure."""
    # Create directory structure
    (doctor_data_dir / "imports").mkdir()
    (doctor_data_dir / "transactions").mkdir()
    (doctor_data_dir / "exports").mkdir()
    (doctor_data_dir / "metadata").mkdir()

    # Copy rules file
    shutil.copy(sample_rules_path, doctor_data_dir / "rules.yaml")

    return doctor_data_dir


@pytest.fixture
def sample_rules_path() -> Path:
    """Get path to sample rules.yaml fixture file."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_rules.yaml"
    if not fixture_path.exists():
        pytest.skip(f"Sample rules not found: {fixture_path}")
    return fixture_path


class TestDoctorCommand:
    """Tests for finjuice doctor command."""

    def test_doctor_shows_help(self) -> None:
        """finjuice doctor --help should show help text."""
        result = runner.invoke(app, ["doctor", "--help"])

        assert result.exit_code == 0
        assert "Diagnose environment" in result.output

    def test_doctor_runs_without_error(self, doctor_data_dir: Path) -> None:
        """finjuice doctor should run without crashing."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        # Should run successfully (exit code 0)
        assert result.exit_code == 0
        # Should contain diagnostic sections
        assert "환경 진단" in result.output
        assert "시스템" in result.output
        assert "의존성" in result.output

    def test_doctor_checks_python_version(self, doctor_data_dir: Path) -> None:
        """Doctor should check Python version."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "Python" in result.output

    def test_doctor_checks_finjuice_version(self, doctor_data_dir: Path) -> None:
        """Doctor should check finjuice version."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "finjuice" in result.output

    def test_doctor_checks_os_info(self, doctor_data_dir: Path) -> None:
        """Doctor should check OS information."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "OS:" in result.output

    def test_doctor_checks_data_directory(self, doctor_data_dir: Path) -> None:
        """Doctor should check data directory."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])
        normalized_output = "".join(result.output.split())

        assert result.exit_code == 0
        assert "데이터 디렉토리" in result.output
        # Rich may wrap long temp paths mid-token; remove whitespace before asserting.
        assert str(doctor_data_dir) in normalized_output

    def test_doctor_warns_missing_subdirectories(self, doctor_data_dir: Path) -> None:
        """Doctor should warn about missing subdirectories."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        # Should warn about missing directories
        assert "누락된 디렉토리" in result.output or "finjuice init" in result.output

    def test_doctor_checks_rules_file(self, initialized_doctor_dir: Path) -> None:
        """Doctor should check rules.yaml file."""
        result = runner.invoke(app, ["--data-dir", str(initialized_doctor_dir), "doctor"])

        assert result.exit_code == 0
        assert "rules.yaml" in result.output
        # Should show rule count
        assert "규칙" in result.output

    def test_doctor_warns_missing_rules(self, doctor_data_dir: Path) -> None:
        """Doctor should warn about missing rules.yaml."""
        # Create directory structure but no rules file
        (doctor_data_dir / "imports").mkdir()
        (doctor_data_dir / "transactions").mkdir()

        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "rules.yaml 없음" in result.output

    def test_doctor_checks_dependencies(self, doctor_data_dir: Path) -> None:
        """Doctor should check dependencies."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "의존성" in result.output
        assert "polars" in result.output
        assert "typer" in result.output

    def test_doctor_suggests_next_step(self, doctor_data_dir: Path) -> None:
        """Doctor should suggest next step."""
        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "다음 단계" in result.output
        # Should suggest finjuice init for new directory
        assert "finjuice" in result.output

    def test_doctor_with_existing_data(
        self, initialized_doctor_dir: Path, sample_xlsx_path: Path
    ) -> None:
        """Doctor should work with existing data directory."""
        # Copy sample XLSX to imports
        shutil.copy(sample_xlsx_path, initialized_doctor_dir / "imports" / "sample.xlsx")

        result = runner.invoke(app, ["--data-dir", str(initialized_doctor_dir), "doctor"])

        assert result.exit_code == 0
        # Should show positive status for existing directory
        assert "✅" in result.output

    def test_doctor_json_guides_compatible_legacy_v2_partitions(
        self,
        initialized_doctor_dir: Path,
    ) -> None:
        """doctor --json should surface actionable guidance for compatible v2 partitions."""
        # Arrange
        _write_v2_partition(initialized_doctor_dir)

        # Act
        result = runner.invoke(app, ["--data-dir", str(initialized_doctor_dir), "doctor", "--json"])

        # Assert
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        checks = {check["name"]: check for check in payload["checks"]}
        schema_check = checks["transaction_schema_compatibility"]
        assert schema_check["status"] == "warn"
        assert "compatible legacy schema v2" in schema_check["message"]
        assert "finjuice refresh" in schema_check["suggestion"]
        assert "category_rule/category_final" in schema_check["detail"]

    def test_doctor_json_guides_v2_partitions_even_with_stale_local_registry(
        self,
        initialized_doctor_dir: Path,
    ) -> None:
        """doctor --json should not trust stale metadata/schema.yaml compatibility."""
        # Arrange
        _write_v2_partition(initialized_doctor_dir)
        _write_stale_v2_registry(initialized_doctor_dir)

        # Act
        result = runner.invoke(app, ["--data-dir", str(initialized_doctor_dir), "doctor", "--json"])

        # Assert
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        checks = {check["name"]: check for check in payload["checks"]}
        schema_check = checks["transaction_schema_compatibility"]
        assert schema_check["status"] == "warn"
        assert "compatible legacy schema v2" in schema_check["message"]
        assert "finjuice refresh" in schema_check["suggestion"]


@pytest.fixture
def sample_xlsx_path() -> Path:
    """Get path to sample XLSX fixture file."""
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_banksalad.xlsx"
    if not fixture_path.exists():
        pytest.skip(f"Sample XLSX not found: {fixture_path}")
    return fixture_path


class TestDoctorCheckResults:
    """Tests for individual doctor check functions."""

    def test_check_result_icons(self) -> None:
        """CheckResult should return correct icons for each status."""
        from finjuice.pipeline.cli.commands.doctor import CheckResult

        ok_result = CheckResult(status="ok", message="Test")
        assert ok_result.icon == "✅"

        warning_result = CheckResult(status="warning", message="Test")
        assert warning_result.icon == "⚠️"

        error_result = CheckResult(status="error", message="Test")
        assert error_result.icon == "❌"

    def test_check_result_with_detail(self) -> None:
        """CheckResult should store detail and suggestion."""
        from finjuice.pipeline.cli.commands.doctor import CheckResult

        result = CheckResult(
            status="warning",
            message="Test warning",
            detail="This is a detail",
            suggestion="Do something",
        )

        assert result.status == "warning"
        assert result.message == "Test warning"
        assert result.detail == "This is a detail"
        assert result.suggestion == "Do something"


class TestDoctorSystemChecks:
    """Tests for system check functions."""

    def test_python_version_check(self) -> None:
        """Python version check should return ok for Python 3.10+."""
        from finjuice.pipeline.cli.commands.doctor import _check_python_version

        result = _check_python_version()

        assert result.status == "ok"
        assert "Python" in result.message

    def test_finjuice_version_check(self) -> None:
        """finjuice version check should return version info."""
        from finjuice.pipeline.cli.commands.doctor import _check_finjuice_version

        result = _check_finjuice_version()

        assert result.status == "ok"
        assert "finjuice" in result.message

    def test_os_info_check(self) -> None:
        """OS info check should return system information."""
        from finjuice.pipeline.cli.commands.doctor import _check_os_info

        result = _check_os_info()

        assert result.status == "ok"
        assert "OS:" in result.message


class TestDoctorSkillRuntimeChecks:
    """Tests for skill runtime sanity checks."""

    def test_skill_runtime_checks_report_helper_version_and_capabilities(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Runtime checks should be read-only and expose known skill capabilities."""
        import finjuice.pipeline.cli.commands.doctor as doctor

        helper = tmp_path / "skills/finjuice/scripts/ensure_finjuice_cli.sh"
        helper.parent.mkdir(parents=True)
        helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        helper.chmod(0o755)

        monkeypatch.setattr(doctor, "get_version", lambda: doctor.SKILL_RUNTIME_REQUIRED_VERSION)
        monkeypatch.setattr(
            doctor,
            "_discover_skill_runtime_helper",
            lambda: helper,
        )
        monkeypatch.setattr(
            doctor,
            "_known_skill_capability_checks",
            lambda: {"tag.edit": True},
        )

        results = doctor._check_skill_runtime()

        assert [result.name for result in results] == [
            "skill_runtime_finjuice_version",
            "skill_runtime_helper",
            "skill_runtime_capability_tag_edit",
        ]
        assert all(result.status == "ok" for result in results)
        assert doctor.SKILL_RUNTIME_REQUIRED_VERSION in results[0].message
        assert str(helper) in results[1].message

    def test_skill_runtime_checks_warn_on_stale_version_and_missing_helper(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale or missing runtime support should suggest explicit update only."""
        import finjuice.pipeline.cli.commands.doctor as doctor

        monkeypatch.setattr(doctor, "get_version", lambda: "0.6.1")
        monkeypatch.setattr(doctor, "_discover_skill_runtime_helper", lambda: None)
        monkeypatch.setattr(
            doctor,
            "_known_skill_capability_checks",
            lambda: {"tag.edit": False},
        )

        results = doctor._check_skill_runtime()

        version_result = next(
            result for result in results if result.name == "skill_runtime_finjuice_version"
        )
        helper_result = next(result for result in results if result.name == "skill_runtime_helper")
        tag_result = next(
            result for result in results if result.name == "skill_runtime_capability_tag_edit"
        )

        assert version_result.status == "warning"
        assert version_result.suggestion == (
            "Run skills/finjuice/scripts/ensure_finjuice_cli.sh --update --json explicitly."
        )
        assert helper_result.status == "warning"
        assert "not found" in helper_result.message
        assert tag_result.status == "warning"
        assert "stale or unsupported" in tag_result.detail

    def test_doctor_json_includes_skill_runtime_checks(
        self, doctor_data_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """doctor --json should include deterministic skill runtime sanity checks."""
        import finjuice.pipeline.cli.commands.doctor as doctor

        helper = tmp_path / "ensure_finjuice_cli.sh"
        helper.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        helper.chmod(0o755)

        monkeypatch.setattr(doctor, "get_version", lambda: doctor.SKILL_RUNTIME_REQUIRED_VERSION)
        monkeypatch.setattr(doctor, "_discover_skill_runtime_helper", lambda: helper)
        monkeypatch.setattr(
            doctor,
            "_known_skill_capability_checks",
            lambda: {"tag.edit": True},
        )

        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        checks = {check["name"]: check for check in payload["checks"]}
        assert checks["skill_runtime_finjuice_version"]["status"] == "pass"
        assert checks["skill_runtime_helper"]["status"] == "pass"
        assert checks["skill_runtime_capability_tag_edit"]["status"] == "pass"
        assert "skill_runtime" in payload
        assert payload["skill_runtime"]["required_version"] == doctor.SKILL_RUNTIME_REQUIRED_VERSION
        assert payload["skill_runtime"]["capabilities"] == ["tag.edit"]

    def test_doctor_text_shows_skill_runtime_section(
        self, doctor_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Human doctor output should show runtime sanity without network checks."""
        import finjuice.pipeline.cli.commands.doctor as doctor

        monkeypatch.setattr(doctor, "get_version", lambda: "0.6.1")
        monkeypatch.setattr(doctor, "_discover_skill_runtime_helper", lambda: None)
        monkeypatch.setattr(
            doctor,
            "_known_skill_capability_checks",
            lambda: {"tag.edit": True},
        )

        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "스킬 런타임" in result.output
        assert "finjuice 0.6.1" in result.output
        assert "ensure_finjuice_cli.sh not found" in result.output
        assert "ensure_finjuice_cli.sh --update --json" in result.output


class TestDoctorDependencyChecks:
    """Tests for dependency check functions."""

    def test_dependency_check_finds_polars(self) -> None:
        """Dependency check should find polars package."""
        from finjuice.pipeline.cli.commands.doctor import _check_dependencies

        results = _check_dependencies()

        polars_result = next((r for r in results if "polars" in r.message.lower()), None)
        assert polars_result is not None
        assert polars_result.status == "ok"

    def test_dependency_check_finds_typer(self) -> None:
        """Dependency check should find typer package."""
        from finjuice.pipeline.cli.commands.doctor import _check_dependencies

        results = _check_dependencies()

        typer_result = next((r for r in results if "typer" in r.message.lower()), None)
        assert typer_result is not None
        assert typer_result.status == "ok"


class TestDoctorAnalyticsChecks:
    """Tests for analytics-specific doctor output."""

    def test_detect_analytics_install_command_modes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Install hint detection should cover uv tool, uv sync, and fallback paths."""
        from finjuice.pipeline.analytics.install_hints import (
            PIP_ANALYTICS_INSTALL,
            UV_SYNC_ANALYTICS_INSTALL,
            UV_TOOL_ANALYTICS_INSTALL,
            detect_analytics_install_command,
        )

        monkeypatch.setattr(
            importlib.metadata,
            "distribution",
            lambda _name: (_ for _ in ()).throw(importlib.metadata.PackageNotFoundError),
        )

        checkout = tmp_path / "checkout"
        checkout.mkdir()
        (checkout / "pyproject.toml").write_text("[project]\nname='finjuice'\n", encoding="utf-8")
        (checkout / "uv.lock").write_text("version = 1\n", encoding="utf-8")

        assert (
            detect_analytics_install_command(Path.home() / ".local/share/uv/tools/finjuice")
            == UV_TOOL_ANALYTICS_INSTALL
        )
        assert detect_analytics_install_command(checkout / ".venv") == UV_SYNC_ANALYTICS_INSTALL
        assert detect_analytics_install_command(tmp_path / "pip-env") == PIP_ANALYTICS_INSTALL
        assert (
            detect_analytics_install_command(tmp_path / "unknown" / "prefix")
            == PIP_ANALYTICS_INSTALL
        )

    def test_detect_analytics_install_command_uses_uv_tool_direct_url(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """GitHub-installed uv tools should be reinstalled from the same source URL."""
        import finjuice.pipeline.analytics.install_hints as install_hints

        class FakeDistribution:
            def read_text(self, filename: str) -> str | None:
                assert filename == "direct_url.json"
                return json.dumps(
                    {
                        "url": "https://github.com/sungjunlee/finjuice",
                        "vcs_info": {"vcs": "git"},
                    }
                )

        monkeypatch.setattr(
            importlib.metadata,
            "distribution",
            lambda _name: FakeDistribution(),
        )

        assert (
            install_hints.detect_analytics_install_command(
                Path.home() / ".local/share/uv/tools/finjuice"
            )
            == "uv tool install --force --with duckdb git+https://github.com/sungjunlee/finjuice"
        )

    def test_detect_analytics_install_command_resolves_custom_uv_tool_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Custom UV_TOOL_DIR paths should match even when symlinks resolve differently."""
        import finjuice.pipeline.analytics.install_hints as install_hints

        real_tool_dir = tmp_path / "real-tools"
        real_tool_dir.mkdir()
        linked_tool_dir = tmp_path / "linked-tools"
        try:
            linked_tool_dir.symlink_to(real_tool_dir, target_is_directory=True)
        except OSError:
            pytest.skip("symlinks are unavailable on this filesystem")

        monkeypatch.setenv("UV_TOOL_DIR", str(linked_tool_dir))
        monkeypatch.setattr(
            importlib.metadata,
            "distribution",
            lambda _name: (_ for _ in ()).throw(importlib.metadata.PackageNotFoundError),
        )

        assert (
            install_hints.detect_analytics_install_command(real_tool_dir / "finjuice")
            == install_hints.UV_TOOL_ANALYTICS_INSTALL
        )

    def test_analytics_check_reports_no_missing_extras_when_duckdb_imports(self) -> None:
        """Analytics check should report no missing extra when duckdb imports cleanly."""
        import finjuice.pipeline.cli.commands.doctor as doctor

        original_import_module = doctor.importlib.import_module
        doctor.importlib.import_module = lambda name: SimpleNamespace(__version__="1.4.2")
        try:
            results, missing_extras, install_hint = doctor._check_analytics_duckdb()
        finally:
            doctor.importlib.import_module = original_import_module

        assert missing_extras == []
        assert install_hint
        assert results[0].status == "ok"
        assert "duckdb 1.4.2" in results[0].message

    def test_doctor_text_shows_analytics_section_and_install_hint(
        self, doctor_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Doctor text output should name the missing analytics extra and install command."""
        import finjuice.pipeline.cli.commands.doctor as doctor

        original_import_module = doctor.importlib.import_module

        def fake_import_module(name: str):
            if name == "duckdb":
                raise ImportError("simulated")
            return original_import_module(name)

        monkeypatch.setattr(doctor.importlib, "import_module", fake_import_module)

        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor"])

        assert result.exit_code == 0
        assert "Analytics / DuckDB" in result.output
        assert "analytics extra 누락" in result.output
        assert "uv sync --extra analytics" in result.output

    def test_doctor_json_adds_missing_extras_and_install_hint(
        self, doctor_data_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """doctor --json should expose additive analytics recovery keys."""
        import finjuice.pipeline.cli.commands.doctor as doctor

        original_import_module = doctor.importlib.import_module

        def fake_import_module(name: str):
            if name == "duckdb":
                raise ImportError("simulated")
            return original_import_module(name)

        monkeypatch.setattr(doctor.importlib, "import_module", fake_import_module)

        result = runner.invoke(app, ["--data-dir", str(doctor_data_dir), "doctor", "--json"])

        assert result.exit_code == 0
        payload = json.loads(result.output)
        assert isinstance(payload["checks"], list)
        assert payload["summary"]["total"] == len(payload["checks"])
        assert payload["missing_extras"] == ["analytics"]
        assert payload["install_hint"] == "uv sync --extra analytics"
        assert {"name", "status", "message", "detail", "suggestion"} <= set(
            payload["checks"][0].keys()
        )
