"""Tests for the validate CLI command."""

import json
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS

runner = CliRunner()


def test_validate_no_data(tmp_path: Path) -> None:
    """Validate returns empty result when no data exists."""
    (tmp_path / "transactions").mkdir(parents=True)
    result = runner.invoke(app, ["validate", "--json"], env={"FINJUICE_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is True
    assert data["partitions_checked"] == 0


def test_validate_valid_partition(tmp_path: Path) -> None:
    """Validate passes on a well-formed partition."""
    part_dir = tmp_path / "transactions" / "2025" / "01"
    part_dir.mkdir(parents=True)
    csv_path = part_dir / "transactions.csv"

    header = CSV_COLUMNS
    df = pl.DataFrame({col: ["placeholder"] for col in header})
    df.write_csv(csv_path)

    result = runner.invoke(app, ["validate", "--json"], env={"FINJUICE_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["partitions_checked"] == 1
    assert data["valid"] is True


def test_validate_invalid_partition(tmp_path: Path) -> None:
    """Validate flags a partition with wrong columns."""
    part_dir = tmp_path / "transactions" / "2025" / "01"
    part_dir.mkdir(parents=True)
    csv_path = part_dir / "transactions.csv"

    df = pl.DataFrame({"bad_column": ["1"], "another_bad": ["2"]})
    df.write_csv(csv_path)

    result = runner.invoke(app, ["validate", "--json"], env={"FINJUICE_DATA_DIR": str(tmp_path)})
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["valid"] is False
    assert data["invalid_count"] == 1


def test_validate_fix_malformed(tmp_path: Path) -> None:
    """Validate --fix removes malformed rows (wrong column count after header)."""
    part_dir = tmp_path / "transactions" / "2025" / "01"
    part_dir.mkdir(parents=True)
    csv_path = part_dir / "transactions.csv"

    header = ["row_hash", "date", "amount", "merchant_raw"]
    good = ["hash1,2025-01-01,-1000,StoreA", "hash2,2025-01-02,-2000,StoreB"]
    bad = "too,few"
    csv_path.write_text("\n".join([",".join(header)] + good + [bad]) + "\n", encoding="utf-8")

    result = runner.invoke(
        app, ["validate", "--fix", "--json"], env={"FINJUICE_DATA_DIR": str(tmp_path)}
    )
    assert result.exit_code == 0
    fixed_lines = csv_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(fixed_lines) == 3
    assert "too,few" not in csv_path.read_text(encoding="utf-8")
