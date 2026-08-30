"""Structure checks for the split CLI main helper implementation."""

from pathlib import Path

from finjuice.pipeline.cli.main_helpers import (
    _count_pending_imports,
    _count_transaction_partitions,
    _is_data_directory_initialized,
)
from finjuice.pipeline.config import Config

CLI_DIR = Path("src/finjuice/pipeline/cli")


def test_brief_status_helpers_live_in_helper_module() -> None:
    """No-args brief-status helpers should not live in the Typer app module."""
    main_text = (CLI_DIR / "main.py").read_text(encoding="utf-8")
    helpers_text = (CLI_DIR / "main_helpers.py").read_text(encoding="utf-8")

    assert "def main(" in main_text
    assert "def status(" in main_text
    assert "def cli_entry(" in main_text
    assert "class FinjuiceGroup" in main_text
    assert "def _is_data_directory_initialized" not in main_text
    assert "def _count_transaction_partitions" not in main_text
    assert "def _count_pending_imports" not in main_text
    assert "def _show_brief_status" not in main_text
    assert "def _is_data_directory_initialized" in helpers_text
    assert "def _count_transaction_partitions" in helpers_text
    assert "def _count_pending_imports" in helpers_text
    assert "def _show_brief_status" in helpers_text


def test_brief_status_public_names_stay_on_entrypoint() -> None:
    """The stable CLI main import path should keep brief-status helper names."""
    from finjuice.pipeline.cli import main, main_helpers

    assert main._is_data_directory_initialized is main_helpers._is_data_directory_initialized
    assert main._count_transaction_partitions is main_helpers._count_transaction_partitions
    assert main._count_pending_imports is main_helpers._count_pending_imports
    assert main._show_brief_status is main_helpers._show_brief_status
    assert callable(main.app)
    assert callable(main.cli_entry)
    assert callable(main.main)
    assert callable(main.status)


def test_is_data_directory_initialized_requires_standard_layout(tmp_path: Path) -> None:
    """Initialized layout needs the data dir, rules file, and standard subdirs."""
    data_dir = tmp_path / "data"
    config = Config.from_env(data_dir=data_dir)

    assert _is_data_directory_initialized(config) is False

    data_dir.mkdir()
    (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
    for path in (config.import_dir, config.csv_base_dir, config.export_dir, config.metadata_dir):
        path.mkdir(parents=True)

    assert _is_data_directory_initialized(config) is True


def test_count_transaction_partitions_and_pending_imports(tmp_path: Path) -> None:
    """Partition and pending-import counters walk only the expected file types."""
    data_dir = tmp_path / "data"
    config = Config.from_env(data_dir=data_dir)

    assert _count_transaction_partitions(config) == 0
    assert _count_pending_imports(config) == 0

    partition_dir = config.csv_base_dir / "2024" / "10"
    partition_dir.mkdir(parents=True)
    (partition_dir / "transactions.csv").write_text("row_hash\n", encoding="utf-8")
    (partition_dir / "notes.txt").write_text("ignore\n", encoding="utf-8")
    config.import_dir.mkdir(parents=True)
    (config.import_dir / "pending.xlsx").write_bytes(b"PK")
    (config.import_dir / "readme.md").write_text("ignore\n", encoding="utf-8")

    assert _count_transaction_partitions(config) == 1
    assert _count_pending_imports(config) == 1
