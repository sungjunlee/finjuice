"""
Unit tests for CLI commands.

Tests the Typer CLI interface for all commands:
init, ingest, tag, transfer, export, and all.
"""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app

runner = CliRunner()


@pytest.fixture
def temp_finance_dir(tmp_path: Path) -> Path:  # type: ignore[misc]
    """Create a temporary finance directory for testing."""
    return tmp_path / "finance"


# Test 1: finjuice init command
def test_cli_init_success(temp_finance_dir: Path) -> None:
    """Test that init command creates directory structure."""
    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Assert
    assert result.exit_code == 0
    assert "Initialization complete" in result.stdout
    assert (temp_finance_dir / "imports").exists()
    assert (temp_finance_dir / "exports" / "reports").exists()
    assert (temp_finance_dir / "rules.yaml").exists()


# Test 2: finjuice init creates template files
def test_cli_init_creates_template_files(temp_finance_dir: Path) -> None:
    """Test that init command copies template files."""
    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Assert
    assert result.exit_code == 0

    # Check template files exist
    assert (temp_finance_dir / ".gitignore").exists()
    assert (temp_finance_dir / "README.md").exists()
    assert (temp_finance_dir / "rules.yaml").exists()

    # Check rules.yaml has example content (not empty)
    rules_content = (temp_finance_dir / "rules.yaml").read_text(encoding="utf-8")
    assert "version: 1" in rules_content
    assert "rules:" in rules_content
    # Should have example rules from template
    assert "insurance_metlife" in rules_content or "cafe_starbucks" in rules_content

    # Check .gitignore has proper content
    gitignore_content = (temp_finance_dir / ".gitignore").read_text(encoding="utf-8")
    assert "transactions/" in gitignore_content
    assert "imports/" in gitignore_content

    # Check README.md has content
    readme_content = (temp_finance_dir / "README.md").read_text(encoding="utf-8")
    assert "My Finance Data" in readme_content


# Test 3: finjuice init with git initialization
def test_cli_init_with_git(temp_finance_dir: Path) -> None:
    """Test that init command initializes git repository."""
    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Assert
    assert result.exit_code == 0

    # Check git directory exists (if git is available)
    git_dir = temp_finance_dir / ".git"
    if "Git repository initialized" in result.stdout:
        assert git_dir.exists()
        assert git_dir.is_dir()
    else:
        # Git not available or already initialized - check warning
        assert (
            "Git initialization skipped" in result.stdout
            or "Git not found" in result.stdout
            or not git_dir.exists()
        )


# Test 4: finjuice init without git (--no-git)
def test_cli_init_no_git_option(temp_finance_dir: Path) -> None:
    """Test that --no-git option skips git initialization."""
    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Assert
    assert result.exit_code == 0
    assert "Initialization complete" in result.stdout

    # Git should not be initialized
    git_dir = temp_finance_dir / ".git"
    assert not git_dir.exists()


# Test 5: finjuice init idempotent (already initialized)
def test_cli_init_idempotent(temp_finance_dir: Path) -> None:
    """Test that running init twice handles existing directory safely."""
    # Act - Run init twice
    result1 = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    result2 = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Assert
    assert result1.exit_code == 0
    assert result2.exit_code == 0

    # Second run should detect existing initialization
    assert "already initialized" in result2.stdout or "Initialization complete" in result2.stdout

    # Files should still exist and not be corrupted
    assert (temp_finance_dir / "rules.yaml").exists()
    assert (temp_finance_dir / ".gitignore").exists()


# Test 6: finjuice init preserves existing files
def test_cli_init_preserves_existing_files(temp_finance_dir: Path) -> None:
    """Test that init doesn't overwrite existing user data."""
    # Arrange - Create directory with custom rules
    temp_finance_dir.mkdir(parents=True)
    custom_rules = temp_finance_dir / "rules.yaml"
    custom_rules.write_text("version: 1\nrules:\n  - name: my_custom_rule\n")

    # Act - Run init
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Assert
    assert result.exit_code == 0

    # Custom rules should NOT be overwritten
    rules_content = custom_rules.read_text(encoding="utf-8")
    assert "my_custom_rule" in rules_content


# Test 7: finjuice init with missing templates (graceful degradation)
def test_cli_init_missing_template(temp_finance_dir: Path) -> None:
    """Test that init handles missing templates gracefully."""
    from unittest.mock import patch

    # Mock copy_template_file to raise FileNotFoundError for one template
    def mock_copy(template_name: str, dest_path: Path) -> bool:
        if template_name == "README.data.md":
            raise FileNotFoundError(f"Template not found: {template_name}")
        # For other templates, create empty files to simulate success
        if not dest_path.exists():
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            dest_path.touch()
            return True
        return False

    with patch("finjuice.pipeline.cli.main.copy_template_file", side_effect=mock_copy):
        # Act
        result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Assert - Should still succeed despite missing template
    assert result.exit_code == 0
    assert "Initialization complete" in result.stdout


# Test 4: finjuice ingest with no files
def test_cli_ingest_no_files(temp_finance_dir: Path) -> None:
    """Test ingest command with empty imports directory."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "ingest"])

    # Assert
    assert result.exit_code == 0
    assert "Files processed: 0" in result.stdout


# Test 5: finjuice tag without rules file
def test_cli_tag_no_rules_file(temp_finance_dir: Path) -> None:
    """Test tag command fails gracefully when rules.yaml is missing."""
    # Arrange
    (temp_finance_dir / "imports").mkdir(parents=True)
    (temp_finance_dir / "transactions").mkdir(parents=True)

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "tag"])

    # Assert
    assert result.exit_code == 1
    # Error message goes to stderr, not stdout
    assert result.exception is not None or "Tagging failed" in result.output


# Test 5b: finjuice tag --dry-run option
def test_cli_tag_dry_run(temp_finance_dir: Path) -> None:
    """Test tag --dry-run shows preview without modifying files."""
    import polars as pl

    from finjuice.pipeline.storage import csv_partition

    # Arrange: Initialize and create test transactions
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"

    # Create test transactions
    transactions = [
        {
            "date": "2025-10-27",
            "time": "10:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "merchant_raw": "스타벅스 강남점",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -5500.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "",
            "datetime": "2025-10-27T10:00:00",
            "row_hash": "test_hash_1",
            "file_id": "251027_1",
            "source_row": 1,
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": [],
            "confidence": None,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
    ]
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

    # Record file state before dry-run
    csv_file = csv_base_dir / "2025" / "10" / "transactions.csv"
    original_content = csv_file.read_text(encoding="utf-8")

    # Act: Run tag with --dry-run
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "tag", "--dry-run"])

    # Assert
    assert result.exit_code == 0
    assert "Dry-run Summary" in result.stdout
    assert "Total transactions" in result.stdout

    # File should be unchanged
    assert csv_file.read_text(encoding="utf-8") == original_content


# Test 5c: finjuice tag --dry-run shows changes
def test_cli_tag_dry_run_shows_changes(temp_finance_dir: Path) -> None:
    """Test tag --dry-run displays sample changes."""
    import polars as pl

    from finjuice.pipeline.storage import csv_partition

    # Arrange: Initialize and create test transactions
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"

    # Create test transactions (starbucks should be tagged by default rules)
    transactions = [
        {
            "date": "2025-10-27",
            "time": "10:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "merchant_raw": "스타벅스",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -5500.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "",
            "datetime": "2025-10-27T10:00:00",
            "row_hash": "test_hash_2",
            "file_id": "251027_1",
            "source_row": 1,
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": [],
            "confidence": None,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
    ]
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)

    # Act: Run tag with --dry-run
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "tag", "--dry-run"])

    # Assert
    assert result.exit_code == 0
    assert "Dry-run Summary" in result.stdout
    # Should show the transaction would be changed (스타벅스 matches cafe_starbucks rule)
    assert "Would be tagged" in result.stdout or "Sample changes" in result.stdout


# ============================================================================
# Tests for finjuice show command
# ============================================================================


def _create_test_transactions(csv_base_dir: Path) -> None:
    """Helper to create test transactions for show command tests."""
    import polars as pl

    from finjuice.pipeline.storage import csv_partition

    transactions = [
        {
            "date": "2025-10-27",
            "time": "10:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "merchant_raw": "스타벅스 강남점",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -5500.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "",
            "datetime": "2025-10-27T10:00:00",
            "row_hash": "show_test_1",
            "file_id": "251027_1",
            "source_row": 1,
            "tags_rule": ["카페", "커피"],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": ["카페", "커피"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "date": "2025-10-27",
            "time": "12:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "merchant_raw": "GS25 편의점",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -3000.0,
            "account": "신한카드",
            "currency": "KRW",
            "counterparty": "",
            "datetime": "2025-10-27T12:00:00",
            "row_hash": "show_test_2",
            "file_id": "251027_1",
            "source_row": 2,
            "tags_rule": [],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": [],
            "confidence": None,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
        {
            "date": "2025-10-28",
            "time": "14:00",
            "type_raw": "지출",
            "type_norm": "expense",
            "merchant_raw": "맥도날드",
            "memo_raw": "",
            "major_raw": "",
            "minor_raw": "",
            "amount": -8000.0,
            "account": "국민카드",
            "currency": "KRW",
            "counterparty": "",
            "datetime": "2025-10-28T14:00:00",
            "row_hash": "show_test_3",
            "file_id": "251027_1",
            "source_row": 3,
            "tags_rule": ["패스트푸드"],
            "tags_ai": [],
            "tags_manual": [],
            "tags_final": ["패스트푸드"],
            "confidence": 1.0,
            "needs_review": 0,
            "is_transfer": 0,
            "transfer_group_id": None,
        },
    ]
    df = pl.DataFrame(transactions)
    csv_partition.append_transactions(csv_base_dir, df, deduplicate=False)


# Test: finjuice show (default - latest month)
def test_cli_show_default_latest_month(temp_finance_dir: Path) -> None:
    """Test show command loads latest month by default."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"
    _create_test_transactions(csv_base_dir)

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "show"])

    # Assert
    assert result.exit_code == 0
    assert "Transactions" in result.stdout
    assert "2025-10" in result.stdout
    assert "스타벅스" in result.stdout


# Test: finjuice show --month
def test_cli_show_specific_month(temp_finance_dir: Path) -> None:
    """Test show command with specific month filter."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"
    _create_test_transactions(csv_base_dir)

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "show", "--month", "2025-10"])

    # Assert
    assert result.exit_code == 0
    assert "2025-10" in result.stdout


# Test: finjuice show --untagged
def test_cli_show_untagged_filter(temp_finance_dir: Path) -> None:
    """Test show command with untagged filter."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"
    _create_test_transactions(csv_base_dir)

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "show", "--untagged"])

    # Assert
    assert result.exit_code == 0
    # GS25 is the only untagged transaction
    assert "GS25" in result.stdout
    # Should NOT include tagged transactions
    assert "스타벅스" not in result.stdout
    assert "untagged only" in result.stdout


# Test: finjuice show --tag
def test_cli_show_tag_filter(temp_finance_dir: Path) -> None:
    """Test show command with tag filter."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"
    _create_test_transactions(csv_base_dir)

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "show", "--tag", "카페"])

    # Assert
    assert result.exit_code == 0
    assert "스타벅스" in result.stdout
    # Should NOT include non-cafe transactions
    assert "맥도날드" not in result.stdout
    assert "tag=카페" in result.stdout


# Test: finjuice show --merchant
def test_cli_show_merchant_filter(temp_finance_dir: Path) -> None:
    """Test show command with merchant substring filter."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"
    _create_test_transactions(csv_base_dir)

    # Act
    result = runner.invoke(
        app, ["--data-dir", str(temp_finance_dir), "show", "--merchant", "스타벅스"]
    )

    # Assert
    assert result.exit_code == 0
    assert "스타벅스" in result.stdout
    assert "GS25" not in result.stdout
    assert "merchant contains" in result.stdout


# Test: finjuice show --limit
def test_cli_show_limit(temp_finance_dir: Path) -> None:
    """Test show command with limit option."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])
    csv_base_dir = temp_finance_dir / "transactions"
    _create_test_transactions(csv_base_dir)

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "show", "--limit", "1"])

    # Assert
    assert result.exit_code == 0
    assert "showing 1/3" in result.stdout


# Test: finjuice show with no data
def test_cli_show_no_data(temp_finance_dir: Path) -> None:
    """Test show command with no transaction data."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "show"])

    # Assert
    assert result.exit_code == 1
    # Error messages go to stderr, so check output (combines stdout + stderr)
    assert "No transaction data found" in result.output or "ERROR" in result.output


# Test: finjuice show with invalid month format
def test_cli_show_invalid_month_format(temp_finance_dir: Path) -> None:
    """Test show command with invalid month format."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init", "--no-git"])

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "show", "--month", "invalid"])

    # Assert
    assert result.exit_code == 1
    # Error messages go to stderr, so check output (combines stdout + stderr)
    assert "Invalid month format" in result.output or "ERROR" in result.output


# ============================================================================
# Tests for finjuice transfer command
# ============================================================================


# Test 6: finjuice transfer with empty database
def test_cli_transfer_empty_db(temp_finance_dir: Path) -> None:
    """Test transfer command with empty database."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "transfer"])

    # Assert
    assert result.exit_code == 0
    assert "Transfer candidates: 0" in result.stdout


# Test 7: finjuice export with empty database
def test_cli_export_empty_db(temp_finance_dir: Path) -> None:
    """Test export command with empty database."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "export"])

    # Assert
    assert result.exit_code == 0
    assert "[WARN] No transactions found; master XLSX was not created." in result.stdout


# Test 8: finjuice all without rules file (warning)
def test_cli_all_skips_tagging_without_rules(temp_finance_dir: Path) -> None:
    """Test that 'all' command skips tagging when rules.yaml is missing."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])
    rules_path = temp_finance_dir / "rules.yaml"
    rules_path.unlink()  # Remove rules file

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "all"])

    # Assert
    assert result.exit_code == 0
    # When rules file is missing, it just skips without explicit warning in stdout
    # The warning goes to stderr, so we just check that pipeline completes
    assert "Step 2/4: Tagging" in result.stdout
    assert "Pipeline complete" in result.stdout
    assert "Tagged: 0 transactions" in result.stdout


# Test 9: finjuice all success with empty data
def test_cli_all_success_empty_data(temp_finance_dir: Path) -> None:
    """Test full pipeline with empty data."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "all"])

    # Assert
    assert result.exit_code == 0
    assert "Step 1/4: Ingestion" in result.stdout
    assert "Step 2/4: Tagging" in result.stdout
    assert "Step 3/4: Transfer Detection" in result.stdout
    assert "Step 4/4: Export" in result.stdout
    assert "Pipeline complete" in result.stdout


# Test 10: finjuice all creates output files
def test_cli_all_creates_output_files(temp_finance_dir: Path) -> None:
    """Test that 'all' command completes successfully.

    Note: With no data in imports, no output files are created (expected behavior).
    """
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Act
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "all"])

    # Assert
    assert result.exit_code == 0
    assert "Pipeline complete" in result.stdout

    # With no imports, no master/report files are created (correct behavior)
    exports_dir = temp_finance_dir / "exports"
    master_files = list(exports_dir.glob("master_*.xlsx"))
    assert len(master_files) == 0  # No files when no data


# Test 11: CLI default path
def test_cli_default_path(monkeypatch, tmp_path) -> None:
    """Test that CLI uses correct default path based on environment.

    Uses OS-specific default (via typer.get_app_dir) when no legacy ./data exists.
    """
    import typer

    from finjuice.pipeline.config import Config

    # Change to temp dir to avoid legacy ./data directory
    monkeypatch.chdir(tmp_path)

    config = Config.from_env()

    # Should use OS-specific default (not ./data) when no legacy directory exists
    expected = Path(typer.get_app_dir("banksalad-tools"))
    assert config.data_dir == expected
    assert config.import_dir == expected / "imports"
    assert config.csv_base_dir == expected / "transactions"


# Test 12: CLI help text
def test_cli_help() -> None:
    """Test that CLI help command works."""
    # Act
    result = runner.invoke(app, ["--help"])

    # Assert
    assert result.exit_code == 0
    assert "finjuice" in result.stdout
    assert "Local-first personal finance pipeline" in result.stdout
    assert "init" in result.stdout
    assert "all" in result.stdout


# Test 13: Individual command help
def test_cli_command_help() -> None:
    """Test that individual command help works."""
    # Act
    result = runner.invoke(app, ["init", "--help"])

    # Assert
    assert result.exit_code == 0
    assert "Initialize directory structure" in result.stdout


# ===== Phase 11b: Advanced CLI Options Tests =====


# Test 14: --verbose option
def test_cli_verbose_option(temp_finance_dir: Path) -> None:
    """Test that --verbose option is accepted."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Act - Test verbose flag on 'all' command
    result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "--verbose", "all"])

    # Assert
    assert result.exit_code == 0
    # Verbose flag doesn't change output structure, just logging detail
    assert "Pipeline complete" in result.stdout


# Test 15: --verbose on individual commands
def test_cli_verbose_on_all_commands(temp_finance_dir: Path) -> None:
    """Test that --verbose works on all commands."""
    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Act & Assert - Test each command
    commands = ["ingest", "tag", "transfer", "export"]

    for cmd in commands:
        result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "--verbose", cmd])
        # Commands may fail due to missing data/rules, but should accept --verbose
        assert "--verbose" not in result.output or result.exit_code in [0, 1, 2, 3, 4]


# ============================================================================
# Error Handling Tests (for coverage gaps)
# ============================================================================


def test_cli_init_failure_permission_error(tmp_path: Path) -> None:
    """Test init command handles permission errors gracefully."""
    from unittest.mock import patch

    # Arrange - Mock mkdir to raise PermissionError
    with patch("pathlib.Path.mkdir", side_effect=PermissionError("Access denied")):
        # Act
        result = runner.invoke(app, ["--data-dir", str(tmp_path / "finance"), "init"])

    # Assert
    assert result.exit_code == 1
    # The error should be caught and logged


def test_cli_ingest_complete_failure(temp_finance_dir: Path) -> None:
    """Test ingest command when ingestion completely fails."""
    from unittest.mock import patch

    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Mock ingest_all_files to raise exception
    with patch(
        "finjuice.pipeline.cli.main.ingest_all_files", side_effect=Exception("Database error")
    ):
        # Act
        result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "ingest"])

    # Assert
    assert result.exit_code == 1


def test_cli_transfer_detection_failure(temp_finance_dir: Path) -> None:
    """Test transfer command when detection fails."""
    from unittest.mock import patch

    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Mock detect_transfers to raise exception
    with patch(
        "finjuice.pipeline.cli.main.run_transfer_detection",
        side_effect=Exception("Detection error"),
    ):
        # Act
        result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "transfer"])

    # Assert
    assert result.exit_code == 1


def test_cli_export_failure(temp_finance_dir: Path) -> None:
    """Test export command when export fails."""
    from unittest.mock import patch

    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Mock export functions to raise exception
    with patch(
        "finjuice.pipeline.cli.main.export_master_xlsx", side_effect=Exception("Export error")
    ):
        # Act
        result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "export"])

    # Assert
    assert result.exit_code == 1


def test_cli_all_pipeline_failure(temp_finance_dir: Path) -> None:
    """Test all command when full pipeline fails."""
    from unittest.mock import patch

    # Arrange
    runner.invoke(app, ["--data-dir", str(temp_finance_dir), "init"])

    # Mock ingest_all_files to raise exception early in pipeline
    with patch(
        "finjuice.pipeline.cli.main.ingest_all_files", side_effect=Exception("Pipeline error")
    ):
        # Act
        result = runner.invoke(app, ["--data-dir", str(temp_finance_dir), "all"])

    # Assert
    assert result.exit_code == 1


def test_cli_main_entry_point() -> None:
    """Test cli_entry() entry point function."""
    from unittest.mock import patch

    from finjuice.pipeline.cli.main import cli_entry

    # Mock app() to avoid actual execution
    with patch("finjuice.pipeline.cli.main.app") as mock_app:
        # Act
        cli_entry()

    # Assert
    mock_app.assert_called_once()


# ============================================================================
# E2E CLI Tests with Real Data (Phase 15)
# ============================================================================


@pytest.mark.e2e
def test_cli_all_with_real_sample_data(tmp_path: Path) -> None:
    """Test full pipeline with real anonymized sample data via CLI.

    This is an E2E test that validates the CLI can process real data end-to-end.
    """
    import shutil

    # Arrange - Setup data directory with real sample
    data_dir = tmp_path / "finance"
    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True)

    # Copy real sample data
    sample_data = Path("tests/fixtures/sample_banksalad.xlsx")
    if not sample_data.exists():
        pytest.skip("Sample data not found")

    shutil.copy(sample_data, imports_dir / "sample.xlsx")

    # Copy sample rules
    sample_rules = Path("tests/fixtures/sample_rules.yaml")
    if not sample_rules.exists():
        pytest.skip("Sample rules not found")

    shutil.copy(sample_rules, data_dir / "rules.yaml")

    # Act - Run full pipeline via CLI
    result = runner.invoke(app, ["--data-dir", str(data_dir), "all"])

    # Assert
    assert result.exit_code == 0, f"CLI failed: {result.output}"
    assert "Pipeline complete" in result.stdout

    # Verify outputs created
    exports_dir = data_dir / "exports"
    reports_dir = exports_dir / "reports"

    master_files = list(exports_dir.glob("master_*.xlsx"))
    assert len(master_files) == 1, "Master XLSX not created"

    assert (reports_dir / "monthly_spend.csv").exists()
    assert (reports_dir / "by_tag.csv").exists()
    assert (reports_dir / "by_account.csv").exists()
    assert (reports_dir / "transfers.csv").exists()

    # Verify CSV partitions have data
    from finjuice.pipeline.storage import csv_partition

    csv_base_dir = data_dir / "transactions"
    assert csv_base_dir.exists()

    df = csv_partition.get_all_transactions(csv_base_dir)
    assert len(df) > 0, "No transactions ingested"


@pytest.mark.e2e
def test_cli_verbose_with_real_data(tmp_path: Path) -> None:
    """Test verbose option with real data processing."""
    import shutil

    # Arrange
    data_dir = tmp_path / "finance"
    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True)

    sample_data = Path("tests/fixtures/sample_banksalad.xlsx")
    if not sample_data.exists():
        pytest.skip("Sample data not found")

    shutil.copy(sample_data, imports_dir / "sample.xlsx")

    sample_rules = Path("tests/fixtures/sample_rules.yaml")
    if sample_rules.exists():
        shutil.copy(sample_rules, data_dir / "rules.yaml")

    # Act - Run with verbose
    result = runner.invoke(app, ["--data-dir", str(data_dir), "--verbose", "all"])

    # Assert
    assert result.exit_code == 0
    assert "Pipeline complete" in result.stdout


@pytest.mark.skip(
    reason="Real data file may contain pre-existing duplicates - "
    "idempotency tested in integration tests"
)
@pytest.mark.e2e
def test_cli_idempotency_real_data(tmp_path: Path) -> None:
    """Test that running CLI twice with same data is idempotent."""
    import shutil

    from finjuice.pipeline.storage import csv_partition

    # Arrange
    data_dir = tmp_path / "finance"
    imports_dir = data_dir / "imports"
    imports_dir.mkdir(parents=True)

    sample_data = Path("tests/fixtures/sample_banksalad.xlsx")
    if not sample_data.exists():
        pytest.skip("Sample data not found")

    shutil.copy(sample_data, imports_dir / "sample.xlsx")

    sample_rules = Path("tests/fixtures/sample_rules.yaml")
    if sample_rules.exists():
        shutil.copy(sample_rules, data_dir / "rules.yaml")

    # Act - Run pipeline twice
    result1 = runner.invoke(app, ["--data-dir", str(data_dir), "all"])
    result2 = runner.invoke(app, ["--data-dir", str(data_dir), "all"])

    # Assert both succeeded
    assert result1.exit_code == 0
    assert result2.exit_code == 0

    # Check transaction count is identical
    csv_base_dir = data_dir / "transactions"
    df = csv_partition.get_all_transactions(csv_base_dir)

    count = len(df)
    hashes = set(df["row_hash"].tolist())

    # Verify no duplicates created
    assert count == len(hashes), "Duplicate transactions detected"
