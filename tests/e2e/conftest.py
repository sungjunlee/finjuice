"""Shared fixtures for E2E tests.

This module provides common fixtures used across E2E test files:
- sample_xlsx_path: Path to sample Banksalad XLSX file
- sample_rules_path: Path to sample rules.yaml
- e2e_data_dir: Clean temporary data directory
- initialized_data_dir: Data directory with finjuice init run
- data_dir_with_xlsx: Data directory ready for pipeline
"""

import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


# ============================================================================
# Path Fixtures (Session-scoped for performance)
# ============================================================================


@pytest.fixture(scope="session")
def sample_xlsx_path() -> Path:
    """Get path to sample XLSX fixture file.

    Session-scoped for performance - the file doesn't change.

    Returns:
        Path: Path to sample_banksalad.xlsx in tests/fixtures/
    """
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_banksalad.xlsx"
    if not fixture_path.exists():
        pytest.skip(f"Sample XLSX not found: {fixture_path}")
    return fixture_path


@pytest.fixture(scope="session")
def sample_rules_path() -> Path:
    """Get path to sample rules.yaml fixture file.

    Session-scoped for performance - the file doesn't change.

    Returns:
        Path: Path to sample_rules.yaml in tests/fixtures/
    """
    fixture_path = Path(__file__).parent.parent / "fixtures" / "sample_rules.yaml"
    if not fixture_path.exists():
        pytest.skip(f"Sample rules not found: {fixture_path}")
    return fixture_path


# ============================================================================
# Directory Fixtures
# ============================================================================


@pytest.fixture
def e2e_data_dir(tmp_path: Path) -> Path:
    """Create a clean temporary data directory for E2E testing.

    Does not create the directory - lets finjuice init do it.

    Returns:
        Path: Temporary directory path that will be used as --data-dir
    """
    return tmp_path / "e2e_data"


@pytest.fixture
def initialized_data_dir(e2e_data_dir: Path) -> Path:
    """Create and initialize a data directory using finjuice init.

    Returns:
        Path: Initialized data directory with proper structure
    """
    result = runner.invoke(app, ["--data-dir", str(e2e_data_dir), "init", "--no-git"])
    assert result.exit_code == 0, f"finjuice init failed: {result.output}"
    return e2e_data_dir


@pytest.fixture
def data_dir_with_xlsx(
    initialized_data_dir: Path, sample_xlsx_path: Path, sample_rules_path: Path
) -> Path:
    """Create data directory with sample XLSX and rules files.

    Returns:
        Path: Data directory ready for pipeline execution
    """
    # Copy sample XLSX to imports/
    imports_dir = initialized_data_dir / "imports"
    shutil.copy(sample_xlsx_path, imports_dir / sample_xlsx_path.name)

    # Copy sample rules to data directory
    shutil.copy(sample_rules_path, initialized_data_dir / "rules.yaml")

    return initialized_data_dir


@pytest.fixture
def data_dir_with_pipeline_run(data_dir_with_xlsx: Path) -> Path:
    """Create data directory with completed pipeline run.

    Returns:
        Path: Data directory after full pipeline execution
    """
    result = runner.invoke(app, ["--data-dir", str(data_dir_with_xlsx), "refresh"])
    assert result.exit_code == 0, f"pipeline failed: {result.output}"
    return data_dir_with_xlsx
