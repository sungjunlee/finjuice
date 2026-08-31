"""Structure and identity checks for doctor helper splits from checks.py."""

from pathlib import Path

from finjuice.pipeline.doctor import checks, next_step, skill_runtime, system

DOCTOR_DIR = Path("src/finjuice/pipeline/doctor")

_NEXT_STEP_HELPERS = (
    "_next_step_from_schema",
    "_next_step_from_data_dir",
    "_next_step_from_data_status",
    "_suggest_next_step",
)

_SYSTEM_HELPERS = (
    "_check_python_version",
    "_check_finjuice_version",
    "_check_os_info",
)

_SKILL_RUNTIME_HELPERS = (
    "_parse_version_tuple",
    "_version_gte",
    "_discover_skill_runtime_helper",
    "_probe_cli_capabilities",
    "_known_skill_capability_checks",
    "_capability_check_name",
    "_check_skill_runtime",
)

_SKILL_RUNTIME_CONSTANTS = (
    "SKILL_RUNTIME_REQUIRED_VERSION",
    "SKILL_RUNTIME_UPDATE_COMMAND",
    "KNOWN_SKILL_CAPABILITIES",
)


def test_next_step_helpers_live_in_helper_module() -> None:
    """Next-step suggestion helpers should not live in checks.py."""
    checks_text = (DOCTOR_DIR / "checks.py").read_text(encoding="utf-8")
    helpers_text = (DOCTOR_DIR / "next_step.py").read_text(encoding="utf-8")

    for name in _NEXT_STEP_HELPERS:
        assert f"def {name}" not in checks_text
        assert f"def {name}" in helpers_text

    assert "def _build_doctor_result" in checks_text
    assert "def _check_dependencies" in checks_text


def test_next_step_helpers_reexport_from_checks() -> None:
    """Existing checks imports should keep resolving to the helper definitions."""
    for name in _NEXT_STEP_HELPERS:
        assert getattr(checks, name) is getattr(next_step, name)
    assert callable(checks._build_doctor_result)
    assert callable(checks._check_python_version)
    assert callable(checks._check_skill_runtime)


def test_system_helpers_live_in_helper_module() -> None:
    """Python/finjuice/OS checks should not live in checks.py."""
    checks_text = (DOCTOR_DIR / "checks.py").read_text(encoding="utf-8")
    helpers_text = (DOCTOR_DIR / "system.py").read_text(encoding="utf-8")

    for name in _SYSTEM_HELPERS:
        assert f"def {name}" not in checks_text
        assert f"def {name}" in helpers_text

    assert "def _build_doctor_result" in checks_text
    assert "def _check_dependencies" in checks_text
    assert "def _suggest_next_step" not in checks_text


def test_system_helpers_reexport_from_checks() -> None:
    """Existing checks imports should keep resolving to the system check definitions."""
    for name in _SYSTEM_HELPERS:
        assert getattr(checks, name) is getattr(system, name)
    assert callable(checks._build_doctor_result)
    assert callable(checks._check_skill_runtime)
    assert callable(checks._check_dependencies)


def test_skill_runtime_helpers_live_in_helper_module() -> None:
    """Skill runtime checks should not live in checks.py."""
    checks_text = (DOCTOR_DIR / "checks.py").read_text(encoding="utf-8")
    helpers_text = (DOCTOR_DIR / "skill_runtime.py").read_text(encoding="utf-8")

    for name in _SKILL_RUNTIME_HELPERS:
        assert f"def {name}" not in checks_text
        assert f"def {name}" in helpers_text

    for name in _SKILL_RUNTIME_CONSTANTS:
        assert f"{name} =" not in checks_text
        assert f"{name} =" in helpers_text

    assert "def _build_doctor_result" in checks_text
    assert "def _check_python_version" not in checks_text
    assert "def _check_dependencies" in checks_text


def test_skill_runtime_helpers_reexport_from_checks() -> None:
    """Existing checks imports should keep resolving to the skill runtime definitions."""
    for name in _SKILL_RUNTIME_HELPERS:
        assert getattr(checks, name) is getattr(skill_runtime, name)
    for name in _SKILL_RUNTIME_CONSTANTS:
        assert getattr(checks, name) is getattr(skill_runtime, name)
    assert callable(checks._build_doctor_result)
    assert callable(checks._check_python_version)
