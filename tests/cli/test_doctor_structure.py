"""Structure and identity checks for the doctor next-step helper split."""

from pathlib import Path

from finjuice.pipeline.doctor import checks, next_step

DOCTOR_DIR = Path("src/finjuice/pipeline/doctor")

_NEXT_STEP_HELPERS = (
    "_next_step_from_schema",
    "_next_step_from_data_dir",
    "_next_step_from_data_status",
    "_suggest_next_step",
)


def test_next_step_helpers_live_in_helper_module() -> None:
    """Next-step suggestion helpers should not live in checks.py."""
    checks_text = (DOCTOR_DIR / "checks.py").read_text(encoding="utf-8")
    helpers_text = (DOCTOR_DIR / "next_step.py").read_text(encoding="utf-8")

    for name in _NEXT_STEP_HELPERS:
        assert f"def {name}" not in checks_text
        assert f"def {name}" in helpers_text

    assert "def _build_doctor_result" in checks_text
    assert "def _check_skill_runtime" in checks_text
    assert "def _check_python_version" in checks_text


def test_next_step_helpers_reexport_from_checks() -> None:
    """Existing checks imports should keep resolving to the helper definitions."""
    for name in _NEXT_STEP_HELPERS:
        assert getattr(checks, name) is getattr(next_step, name)
    assert callable(checks._build_doctor_result)
    assert callable(checks._check_python_version)
    assert callable(checks._check_skill_runtime)
