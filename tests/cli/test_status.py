"""
Tests for CLI status command.

Tests the finjuice status command that displays:
- Total transactions and partitions
- Date range
- Untagged transaction count
- Rules file status
- Import history
"""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from typer.testing import CliRunner

from finjuice.pipeline.cli.commands import status as status_command
from finjuice.pipeline.cli.main import app
from finjuice.pipeline.config import Config
from finjuice.pipeline.storage.csv_schema import CSV_COLUMNS, POLARS_SCHEMA
from finjuice.pipeline.tagging.models import ReportFilters
from tests.conftest import cli_text

runner = CliRunner()

V2_COLUMNS = [
    column
    for column in CSV_COLUMNS
    if column not in {"notes_manual", "category_rule", "category_final", "is_transfer_candidate"}
]


@dataclass(frozen=True)
class _StatusTransferState:
    """Transfer flags for status helper rows."""

    candidate: int | None = None
    confirmed: int = 0
    group_id: str | None = None


def _write_v2_status_partition(data_dir: Path) -> None:
    """Create one v2-shaped transaction partition for status compatibility checks."""
    partition_dir = data_dir / "transactions" / "2024" / "10"
    partition_dir.mkdir(parents=True)
    values = [
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
    partition_dir.joinpath("transactions.csv").write_text(
        ",".join(V2_COLUMNS) + "\n" + ",".join(values) + "\n",
        encoding="utf-8",
    )


@pytest.fixture
def data_dir_with_transactions(tmp_path: Path) -> Path:
    """Create a data directory with sample transactions."""
    data_dir = tmp_path / "data"
    transactions_dir = data_dir / "transactions" / "2024" / "10"
    transactions_dir.mkdir(parents=True)

    # Create sample CSV with transactions
    df = pl.DataFrame(
        {
            "row_hash": ["abc123", "def456", "ghi789"],
            "date": ["2024-10-01", "2024-10-15", "2024-10-31"],
            "time": ["10:00", "14:30", "18:00"],
            "type_raw": ["지출", "지출", "수입"],
            "type_norm": ["expense", "expense", "income"],
            "major_raw": ["식비", "교통", "급여"],
            "minor_raw": ["카페", "택시", None],
            "merchant_raw": ["스타벅스", "카카오택시", "회사"],
            "memo_raw": [None, None, None],
            "notes_manual": ["", "", ""],
            "amount": [-5000.0, -15000.0, 3000000.0],
            "account": ["신한카드", "신한카드", "급여계좌"],
            "currency": ["KRW", "KRW", "KRW"],
            "counterparty": [None, None, None],
            "datetime": [
                "2024-10-01T10:00:00",
                "2024-10-15T14:30:00",
                "2024-10-31T18:00:00",
            ],
            "category_rule": ["카페", "교통", None],
            "category_final": ["카페", "교통", "급여"],
            "tags_rule": ['["카페"]', '["교통"]', "[]"],
            "tags_ai": ["[]", "[]", "[]"],
            "tags_manual": ["[]", "[]", "[]"],
            "tags_final": ['["카페"]', '["교통"]', "[]"],  # One untagged
            "confidence": [0.95, 0.90, None],
            "needs_review": [0, 0, 1],
            "is_transfer_candidate": [0, 0, 0],
            "is_transfer": [0, 0, 0],
            "transfer_group_id": [None, None, None],
            "file_id": ["241001_1", "241001_1", "241001_1"],
            "source_row": [1, 2, 3],
        }
    )
    df.write_csv(transactions_dir / "transactions.csv")

    # Create rules.yaml
    rules_content = """version: 1
rules:
  - name: cafe_starbucks
    match: "스타벅스"
    fields: [merchant_raw]
    tags: ["카페"]
    priority: 80
"""
    (data_dir / "rules.yaml").write_text(rules_content, encoding="utf-8")

    return data_dir


@pytest.fixture
def data_dir_empty(tmp_path: Path) -> Path:
    """Create an empty data directory."""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    return data_dir


@pytest.fixture
def data_dir_no_partitions(tmp_path: Path) -> Path:
    """Create data directory with transactions folder but no CSV files."""
    data_dir = tmp_path / "data"
    transactions_dir = data_dir / "transactions"
    transactions_dir.mkdir(parents=True)
    return data_dir


class TestStatusCommand:
    """Tests for finjuice status command."""

    def test_status_no_transactions_dir(self, data_dir_empty: Path) -> None:
        """Test status when transactions/ directory doesn't exist."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_empty), "status"])

        # Assert
        assert result.exit_code in [2, 4]  # USAGE_ERROR or NO_DATA
        # CLI shows context-aware warning message
        assert "No transactions" in cli_text(result) or "ingest" in cli_text(result)

    def test_status_no_transactions_dir_human_precedes_invalid_report_filters(
        self,
        data_dir_empty: Path,
    ) -> None:
        """Missing transaction data should keep priority over report_filters validation."""
        # Arrange
        _write_invalid_report_filters_rules(data_dir_empty)

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_empty), "status"])

        # Assert
        assert result.exit_code == 4
        assert "No transactions directory" in cli_text(result)
        assert "report_filters" not in cli_text(result)

    def test_status_empty_partitions(self, data_dir_no_partitions: Path) -> None:
        """Test status when no CSV files exist in transactions/."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_no_partitions), "status"])

        # Assert
        assert result.exit_code == 4  # NO_DATA
        # CLI shows "No CSV partitions found" warning (exact message from status.py:48)
        assert "No CSV partitions found" in cli_text(result)

    def test_status_empty_partitions_json_precedes_invalid_report_filters(
        self,
        data_dir_no_partitions: Path,
    ) -> None:
        """JSON no-data envelope should keep priority over report_filters validation."""
        # Arrange
        _write_invalid_report_filters_rules(data_dir_no_partitions)

        # Act
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_no_partitions), "status", "--json"],
        )

        # Assert
        assert result.exit_code == 4
        payload = json.loads(result.output)
        assert payload["_meta"]["command"] == "status"
        assert payload["error"]["code"] == "NO_DATA"
        assert (
            payload["error"]["message"] == "No CSV partitions found. Run 'finjuice ingest' first."
        )
        assert "report_filters" not in payload["error"]["message"]

    def test_status_with_data(self, data_dir_with_transactions: Path) -> None:
        """Test status displays correct information with valid data."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_transactions), "status"])

        # Assert
        assert result.exit_code == 0
        assert "Finance Data Status" in cli_text(result)
        assert "3" in cli_text(result)  # 3 rows
        assert "2024-10-01" in cli_text(result)  # min date
        assert "2024-10-31" in cli_text(result)  # max date

    def test_status_json_includes_agent_health_cues(self, data_dir_with_transactions: Path) -> None:
        """status --json should expose additive health/action cues for agents."""
        result = runner.invoke(
            app,
            ["--data-dir", str(data_dir_with_transactions), "status", "--json"],
        )

        assert result.exit_code == 0
        data = json.loads(result.output)

        assert data["health"]["status"] == "warning"
        assert "untagged_transactions" in data["health"]["reasons"]
        assert data["actionable"] is True
        assert data["signals"] == {
            "rules_file_exists": True,
            "tagging_rate": 66.67,
            "untagged_count": 1,
            "filters_applied": 0,
            "detailed_requested": False,
        }
        assert data["next_steps"][0]["signal"] == "untagged_transactions"
        assert data["next_steps"][0]["command"] == "finjuice review --json"
        assert data["terminology"]["reference"] == "docs/reference/tagging-review-terminology.md"
        assert data["terminology"]["schema"] == "schemas/status.schema.json"
        assert "suggestable_untagged" in data["terminology"]["definitions"]

    def test_status_json_guides_compatible_legacy_v2_partitions(self, tmp_path: Path) -> None:
        """status --json should expose migration guidance for v2-compatible partitions."""
        # Arrange
        data_dir = tmp_path / "data"
        _write_v2_status_partition(data_dir)
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--json"])

        # Assert
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["schema"]["state"] == "compatible-legacy"
        assert payload["schema"]["compatible_legacy_versions"] == [2]
        assert payload["schema"]["migration"]["command"] == "finjuice refresh"
        assert "category_rule/category_final" in payload["schema"]["migration"]["message"]
        assert payload["next_steps"][0]["signal"] == "compatible_legacy_schema"
        assert payload["next_steps"][0]["command"] == "finjuice refresh"

    def test_status_text_guides_compatible_legacy_v2_partitions(self, tmp_path: Path) -> None:
        """Human status output should tell users how to migrate compatible v2 partitions."""
        # Arrange
        data_dir = tmp_path / "data"
        _write_v2_status_partition(data_dir)
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])

        # Assert
        assert result.exit_code == 0, result.output
        text = cli_text(result)
        assert "compatible legacy schema v2" in text
        assert "finjuice refresh" in text

    def test_status_applies_category_report_filters_to_v2_partitions(
        self,
        tmp_path: Path,
    ) -> None:
        """Compatible v2 partitions should be normalized before category filters run."""
        # Arrange
        data_dir = tmp_path / "data"
        _write_v2_status_partition(data_dir)
        (data_dir / "rules.yaml").write_text(
            "\n".join(
                [
                    "version: 1",
                    "report_filters:",
                    "  excluded_categories:",
                    "    - name: 카페",
                    "      reason: exclude legacy fallback category",
                    "rules: []",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--json"])

        # Assert
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["_meta"]["filters_applied"] == 1
        assert payload["transactions"]["count"] == 0
        assert payload["schema"]["state"] == "compatible-legacy"

    def test_status_compute_uses_typed_options_result_contract(
        self,
        data_dir_with_transactions: Path,
    ) -> None:
        """The status use case should receive options and return payload plus render context."""
        assert hasattr(status_command, "StatusOptions")
        assert hasattr(status_command, "StatusResult")

        options = status_command.StatusOptions(
            config=Config(data_dir=data_dir_with_transactions),
            data_dir_source="test fixture",
            detailed=False,
            top_n=2,
            report_filters=ReportFilters(),
            no_filter=False,
        )

        result = status_command._compute_status(options)

        assert isinstance(result, status_command.StatusResult)
        assert result.payload["transactions"]["count"] == 3
        assert result.payload["data_directory"]["source"] == "test fixture"
        assert result.payload["signals"]["detailed_requested"] is False
        assert "_top_n" not in result.payload
        assert "_filters_applied" not in result.payload
        assert result.render_context.top_n == 2
        assert result.render_context.filters_applied == 0

    def test_status_date_range_calculation(self, data_dir_with_transactions: Path) -> None:
        """Test that date range is correctly calculated from transactions."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_transactions), "status"])

        # Assert
        assert result.exit_code == 0
        # Should show date range
        assert "2024-10-01" in cli_text(result)
        assert "2024-10-31" in cli_text(result)

    def test_status_untagged_count(self, data_dir_with_transactions: Path) -> None:
        """Test that untagged transaction count is displayed."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_transactions), "status"])

        # Assert
        assert result.exit_code == 0
        # One transaction has tags_final = "[]" (untagged)
        assert "1" in cli_text(result) and "need" in cli_text(result).lower()

    def test_status_rules_file_display(self, data_dir_with_transactions: Path) -> None:
        """Test that rules file status is displayed."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_transactions), "status"])

        # Assert
        assert result.exit_code == 0
        # CLI shows "Rules file" row in status table (from status.py:151)
        assert "Rules file" in cli_text(result)

    def test_status_no_rules_file(self, tmp_path: Path) -> None:
        """Test status when rules.yaml doesn't exist."""
        # Arrange - create data without rules.yaml
        data_dir = tmp_path / "data"
        transactions_dir = data_dir / "transactions" / "2024" / "10"
        transactions_dir.mkdir(parents=True)

        df = pl.DataFrame(
            {
                "row_hash": ["abc123"],
                "date": ["2024-10-01"],
                "time": ["10:00"],
                "type_raw": ["지출"],
                "type_norm": ["expense"],
                "major_raw": ["식비"],
                "minor_raw": ["카페"],
                "merchant_raw": ["스타벅스"],
                "memo_raw": [None],
                "amount": [-5000.0],
                "account": ["신한카드"],
                "currency": ["KRW"],
                "counterparty": [None],
                "datetime": ["2024-10-01T10:00:00"],
                "tags_rule": ['["카페"]'],
                "tags_ai": ["[]"],
                "tags_manual": ["[]"],
                "tags_final": ['["카페"]'],
                "confidence": [0.95],
                "needs_review": [0],
                "is_transfer": [0],
                "transfer_group_id": [None],
                "file_id": ["241001_1"],
                "source_row": [1],
            }
        )
        df.write_csv(transactions_dir / "transactions.csv")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])

        # Assert
        assert result.exit_code == 0
        # Should show warning about missing rules (exact message from status.py:153)
        assert "Not found" in cli_text(result)

    def test_status_with_import_history(self, data_dir_with_transactions: Path) -> None:
        """Test status displays import history when available."""
        # Arrange - create import history
        metadata_dir = data_dir_with_transactions / "metadata"
        metadata_dir.mkdir(parents=True)

        import_df = pl.DataFrame(
            {
                "file_id": ["241001_1"],
                "original_filename": ["banksalad_export.xlsx"],
                "imported_from": ["/path/to/file.xlsx"],
                "archived": [False],
                "archived_path": [None],
                "imported_at": ["2024-10-01T12:00:00"],
                "source_rows": [100],
            }
        )
        import_df.write_csv(metadata_dir / "import_history.csv")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_transactions), "status"])

        # Assert
        assert result.exit_code == 0
        # CLI shows file_id in "Last import" row (from status.py:136)
        assert "241001_1" in cli_text(result)
        assert "Last import" in cli_text(result)

    def test_status_multiple_partitions(self, tmp_path: Path) -> None:
        """Test status with multiple month partitions."""
        # Arrange
        data_dir = tmp_path / "data"

        # Create October partition
        oct_dir = data_dir / "transactions" / "2024" / "10"
        oct_dir.mkdir(parents=True)
        df_oct = pl.DataFrame(
            {
                "row_hash": ["oct1"],
                "date": ["2024-10-15"],
                "time": ["10:00"],
                "type_raw": ["지출"],
                "type_norm": ["expense"],
                "major_raw": ["식비"],
                "minor_raw": [None],
                "merchant_raw": ["가맹점"],
                "memo_raw": [None],
                "amount": [-5000.0],
                "account": ["카드"],
                "currency": ["KRW"],
                "counterparty": [None],
                "datetime": ["2024-10-15T10:00:00"],
                "tags_rule": ["[]"],
                "tags_ai": ["[]"],
                "tags_manual": ["[]"],
                "tags_final": ["[]"],
                "confidence": [None],
                "needs_review": [1],
                "is_transfer": [0],
                "transfer_group_id": [None],
                "file_id": ["241015_1"],
                "source_row": [1],
            }
        )
        df_oct.write_csv(oct_dir / "transactions.csv")

        # Create November partition
        nov_dir = data_dir / "transactions" / "2024" / "11"
        nov_dir.mkdir(parents=True)
        df_nov = pl.DataFrame(
            {
                "row_hash": ["nov1"],
                "date": ["2024-11-20"],
                "time": ["14:00"],
                "type_raw": ["지출"],
                "type_norm": ["expense"],
                "major_raw": ["교통"],
                "minor_raw": [None],
                "merchant_raw": ["택시"],
                "memo_raw": [None],
                "amount": [-10000.0],
                "account": ["카드"],
                "currency": ["KRW"],
                "counterparty": [None],
                "datetime": ["2024-11-20T14:00:00"],
                "tags_rule": ['["교통"]'],
                "tags_ai": ["[]"],
                "tags_manual": ["[]"],
                "tags_final": ['["교통"]'],
                "confidence": [0.9],
                "needs_review": [0],
                "is_transfer": [0],
                "transfer_group_id": [None],
                "file_id": ["241120_1"],
                "source_row": [1],
            }
        )
        df_nov.write_csv(nov_dir / "transactions.csv")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])

        # Assert
        assert result.exit_code == 0
        assert "2" in cli_text(result)  # 2 rows total or 2 months
        assert "2024-10-15" in cli_text(result)  # min date
        assert "2024-11-20" in cli_text(result)  # max date

    def test_status_all_tagged(self, tmp_path: Path) -> None:
        """Test status shows success message when all transactions are tagged."""
        # Arrange
        data_dir = tmp_path / "data"
        transactions_dir = data_dir / "transactions" / "2024" / "10"
        transactions_dir.mkdir(parents=True)

        df = pl.DataFrame(
            {
                "row_hash": ["abc123"],
                "date": ["2024-10-01"],
                "time": ["10:00"],
                "type_raw": ["지출"],
                "type_norm": ["expense"],
                "major_raw": ["식비"],
                "minor_raw": ["카페"],
                "merchant_raw": ["스타벅스"],
                "memo_raw": [None],
                "amount": [-5000.0],
                "account": ["신한카드"],
                "currency": ["KRW"],
                "counterparty": [None],
                "datetime": ["2024-10-01T10:00:00"],
                "tags_rule": ['["카페"]'],
                "tags_ai": ["[]"],
                "tags_manual": ["[]"],
                "tags_final": ['["카페"]'],  # All tagged
                "confidence": [0.95],
                "needs_review": [0],
                "is_transfer": [0],
                "transfer_group_id": [None],
                "file_id": ["241001_1"],
                "source_row": [1],
            }
        )
        df.write_csv(transactions_dir / "transactions.csv")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])

        # Assert
        assert result.exit_code == 0
        # CLI shows "All transactions tagged ✓" when no untagged transactions (from status.py:147)
        assert "All transactions tagged" in cli_text(result)

    def test_status_tagging_rate(self, data_dir_with_transactions: Path) -> None:
        """Test that tagging rate is displayed correctly."""
        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir_with_transactions), "status"])

        # Assert
        assert result.exit_code == 0
        # 2 out of 3 transactions are tagged = 66.7%
        assert "Tagging rate" in cli_text(result)
        assert "66.7%" in cli_text(result)

    def test_status_top_untagged_merchants(self, tmp_path: Path) -> None:
        """Test that top untagged merchants are displayed."""
        # Arrange - create data with multiple untagged transactions
        data_dir = tmp_path / "data"
        transactions_dir = data_dir / "transactions" / "2024" / "10"
        transactions_dir.mkdir(parents=True)

        df = pl.DataFrame(
            {
                "row_hash": ["a1", "a2", "a3", "a4", "a5"],
                "date": ["2024-10-01"] * 5,
                "time": ["10:00"] * 5,
                "type_raw": ["지출"] * 5,
                "type_norm": ["expense"] * 5,
                "major_raw": ["식비"] * 5,
                "minor_raw": [None] * 5,
                "merchant_raw": ["가맹점A", "가맹점A", "가맹점B", "가맹점A", "가맹점C"],
                "memo_raw": [None] * 5,
                "amount": [-5000.0] * 5,
                "account": ["카드"] * 5,
                "currency": ["KRW"] * 5,
                "counterparty": [None] * 5,
                "datetime": ["2024-10-01T10:00:00"] * 5,
                "tags_rule": ["[]"] * 5,
                "tags_ai": ["[]"] * 5,
                "tags_manual": ["[]"] * 5,
                "tags_final": ["[]"] * 5,  # All untagged
                "confidence": [None] * 5,
                "needs_review": [1] * 5,
                "is_transfer": [0] * 5,
                "transfer_group_id": [None] * 5,
                "file_id": ["241001_1"] * 5,
                "source_row": [1, 2, 3, 4, 5],
            }
        )
        df.write_csv(transactions_dir / "transactions.csv")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])

        # Assert
        assert result.exit_code == 0
        assert "Top untagged" in cli_text(result)
        # 가맹점A appears 3 times, should be first
        assert "가맹점A(3)" in cli_text(result)
        assert "가맹점B(1)" in cli_text(result)

    def test_status_tagging_rate_100_percent(self, tmp_path: Path) -> None:
        """Test that 100% tagging rate shows green."""
        # Arrange
        data_dir = tmp_path / "data"
        transactions_dir = data_dir / "transactions" / "2024" / "10"
        transactions_dir.mkdir(parents=True)

        df = pl.DataFrame(
            {
                "row_hash": ["abc123"],
                "date": ["2024-10-01"],
                "time": ["10:00"],
                "type_raw": ["지출"],
                "type_norm": ["expense"],
                "major_raw": ["식비"],
                "minor_raw": ["카페"],
                "merchant_raw": ["스타벅스"],
                "memo_raw": [None],
                "amount": [-5000.0],
                "account": ["신한카드"],
                "currency": ["KRW"],
                "counterparty": [None],
                "datetime": ["2024-10-01T10:00:00"],
                "tags_rule": ['["카페"]'],
                "tags_ai": ["[]"],
                "tags_manual": ["[]"],
                "tags_final": ['["카페"]'],
                "confidence": [0.95],
                "needs_review": [0],
                "is_transfer": [0],
                "transfer_group_id": [None],
                "file_id": ["241001_1"],
                "source_row": [1],
            }
        )
        df.write_csv(transactions_dir / "transactions.csv")

        # Act
        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])

        # Assert
        assert result.exit_code == 0
        assert "100.0%" in cli_text(result)
        assert "Tagging rate" in cli_text(result)

    def test_status_detailed_json_splits_residual_and_structural_savings(
        self,
        tmp_path: Path,
    ) -> None:
        """Detailed status should expose residual, consumption, and structural savings."""
        data_dir = tmp_path / "data"
        rows: list[dict[str, Any]] = []
        for month in ("01", "02", "03"):
            rows.extend(
                [
                    _status_row(f"2026-{month}-05", 3_000_000, "급여", f"pay-{month}"),
                    _status_row(f"2026-{month}-10", -1_000_000, "생활", f"living-{month}"),
                    _status_row(
                        f"2026-{month}-20",
                        -300_000,
                        "금융",
                        f"irp-{month}",
                        tags='["IRP", "정기저축", "IRP"]',
                    ),
                    _status_row(
                        f"2026-{month}-21",
                        -900_000,
                        "이체",
                        f"transfer-{month}",
                        tags='["정기저축"]',
                        transfer=_StatusTransferState(confirmed=1),
                        type_norm="transfer",
                    ),
                ]
            )
        _write_status_partitions(data_dir, rows)
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")
        (data_dir / "goals.yaml").write_text(
            "\n".join(
                [
                    "version: 1",
                    "monthly_budget:",
                    "  total: 2000000",
                    "  categories: {}",
                    "recurring_savings:",
                    "  - label: 연금저축",
                    "    amount: 200000",
                    "    frequency: monthly",
                    "    tags: [연금]",
                    "    source: goals.yaml",
                    "",
                ]
            ),
            encoding="utf-8",
        )

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--detailed", "--json"])

        assert result.exit_code == 0, result.output
        stats = json.loads(result.output)["detailed_stats"]
        assert stats["savings_rate_3mo"] == 0.57
        assert stats["residual_savings_rate_3mo"] == 0.57
        assert stats["monthly_avg_expense"] == 1_300_000
        assert stats["structural_savings_transaction_monthly_avg"] == 300_000
        assert stats["recurring_savings_monthly_amount"] == 200_000
        assert stats["structural_savings_monthly_avg"] == 500_000
        assert stats["monthly_avg_consumption_expense"] == 1_000_000
        assert stats["consumption_savings_rate_3mo"] == 0.67

        sources = stats["structural_savings_sources"]
        assert [source["source"] for source in sources] == ["goals.yaml", "transactions"]
        assert sources[0] == {
            "source": "goals.yaml",
            "label": "연금저축",
            "monthly_amount": 200_000,
            "amount": 200_000,
            "frequency": "monthly",
            "tags": ["연금"],
        }
        assert sources[1]["amount"] == 900_000
        assert sources[1]["monthly_amount"] == 300_000
        assert sources[1]["transaction_count"] == 3
        assert sources[1]["tags"] == ["IRP", "정기저축"]

    def test_status_detailed_human_labels_residual_and_structural_savings(
        self,
        tmp_path: Path,
    ) -> None:
        """Human detailed output should name residual cashflow and structural savings."""
        data_dir = tmp_path / "data"
        _write_status_partitions(
            data_dir,
            [
                _status_row("2026-03-05", 3_000_000, "급여", "pay", type_norm="income"),
                _status_row("2026-03-10", -1_000_000, "생활", "living"),
                _status_row("2026-03-20", -300_000, "금융", "irp", tags='["IRP"]'),
            ],
        )
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--detailed"])
        output = cli_text(result)

        assert result.exit_code == 0, result.output
        assert "잔여 현금흐름 저축률" in output
        assert "소비 기준 저축률" in output
        assert "구조적 저축" in output
        assert "IRP" in output

    def test_status_detailed_json_handles_transfer_only_structural_tags(
        self,
        tmp_path: Path,
    ) -> None:
        """Transfer rows with savings tags should not count as structural savings."""
        data_dir = tmp_path / "data"
        _write_status_partitions(
            data_dir,
            [
                _status_row(
                    "2026-03-10",
                    -500_000,
                    "이체",
                    "internal",
                    tags='["정기저축"]',
                    transfer=_StatusTransferState(confirmed=1),
                    type_norm="transfer",
                )
            ],
        )
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--detailed", "--json"])

        assert result.exit_code == 0, result.output
        stats = json.loads(result.output)["detailed_stats"]
        assert stats["monthly_avg_income"] == 0
        assert stats["monthly_avg_expense"] == 0
        assert stats["savings_rate_3mo"] is None
        assert stats["residual_savings_rate_3mo"] is None
        assert stats["structural_savings_monthly_avg"] == 0
        assert stats["structural_savings_sources"] == []

    def test_status_json_counts_suggestable_untagged_separately_from_transfers(
        self,
        tmp_path: Path,
    ) -> None:
        """status --json should keep total untagged and transfer-excluded counts distinct."""
        data_dir = tmp_path / "data"
        _write_status_partitions(
            data_dir,
            [
                _status_row("2026-03-01", -10_000, "카페", "tagged", tags='["카페"]'),
                _status_row("2026-03-02", -20_000, "식비", "untagged-food"),
                _status_row(
                    "2026-03-03",
                    -30_000,
                    "이체",
                    "untagged-transfer",
                    transfer=_StatusTransferState(confirmed=1),
                    type_norm="transfer",
                ),
                _status_row(
                    "2026-03-04",
                    -40_000,
                    "이체",
                    "tagged-transfer",
                    tags='["내부이체"]',
                    transfer=_StatusTransferState(confirmed=1),
                    type_norm="transfer",
                ),
                _status_row(
                    "2026-03-05",
                    -50_000,
                    "송금",
                    "unconfirmed-candidate",
                    transfer=_StatusTransferState(candidate=1),
                ),
            ],
        )
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        tagging = payload["tagging"]
        assert tagging["untagged_count"] == 3
        assert tagging["suggestable_transaction_count"] == 3
        assert tagging["suggestable_untagged_count"] == 2
        assert tagging["transfer_candidate_count"] == 3
        assert tagging["transfer_excluded_count"] == 2
        assert tagging["transfer_excluded_untagged_count"] == 1
        assert tagging["unconfirmed_transfer_candidate_count"] == 1
        assert tagging["transfer_exclusions"]["candidate_count"] == 3
        assert tagging["transfer_exclusions"]["confirmed_count"] == 2
        assert tagging["transfer_exclusions"]["unconfirmed_candidate_count"] == 1
        assert tagging["transfer_exclusions"]["excluded_untagged_count"] == 1
        assert payload["health"] == {
            "status": "warning",
            "reasons": ["untagged_transactions"],
        }

    def test_status_human_output_explains_transfer_excluded_untagged(
        self,
        tmp_path: Path,
    ) -> None:
        """Human status output should not imply rules suggest can handle transfer rows."""
        data_dir = tmp_path / "data"
        _write_status_partitions(
            data_dir,
            [
                _status_row("2026-03-01", -10_000, "생활", "untagged"),
                _status_row(
                    "2026-03-02",
                    -20_000,
                    "이체",
                    "transfer",
                    transfer=_StatusTransferState(confirmed=1),
                    type_norm="transfer",
                ),
            ],
        )
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status"])

        assert result.exit_code == 0, result.output
        output = cli_text(result)
        assert "2 total" in output
        assert "1 rule-suggestable" in output
        assert "1 transfer-excluded" in output
        assert "Terminology: untagged = tags_final empty" in output
        assert "docs/reference/tagging-review-terminology.md" in output
        assert "Get suggestions for 1 suggestable untagged" in output

    def test_status_health_low_for_small_99_percent_remainder(
        self,
        tmp_path: Path,
    ) -> None:
        """A tiny remaining queue at 99%+ coverage should not be warning severity."""
        data_dir = tmp_path / "data"
        rows = [
            _status_row(
                "2026-03-01",
                -10_000,
                "생활",
                f"tagged-{index}",
                tags='["생활"]',
            )
            for index in range(199)
        ]
        rows.append(_status_row("2026-03-02", -10_000, "생활", "last-untagged"))
        _write_status_partitions(data_dir, rows)
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--json"])

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["tagging"]["suggestable_untagged_count"] == 1
        assert payload["tagging"]["suggestable_tagging_rate"] == 99.5
        assert payload["health"] == {
            "status": "ok",
            "reasons": ["low_untagged_remainder"],
        }
        assert payload["actionable"] is False
        assert payload["next_steps"][0]["command"] == "finjuice review --json"

    def test_status_detailed_json_handles_zero_income_structural_savings(
        self,
        tmp_path: Path,
    ) -> None:
        """Zero-income months should keep rates null while amounts remain deterministic."""
        data_dir = tmp_path / "data"
        _write_status_partitions(
            data_dir,
            [
                _status_row(
                    "2026-03-10",
                    -100_000,
                    "금융",
                    "pension",
                    tags='["연금"]',
                )
            ],
        )
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--detailed", "--json"])

        assert result.exit_code == 0, result.output
        stats = json.loads(result.output)["detailed_stats"]
        assert stats["monthly_avg_income"] == 0
        assert stats["monthly_avg_expense"] == 100_000
        assert stats["savings_rate_3mo"] is None
        assert stats["consumption_savings_rate_3mo"] is None
        assert stats["monthly_avg_consumption_expense"] == 0
        assert stats["structural_savings_transaction_monthly_avg"] == 100_000

    def test_status_detailed_json_handles_empty_partition_deterministically(
        self,
        tmp_path: Path,
    ) -> None:
        """An empty CSV partition should emit null rates and zero structural rows."""
        data_dir = tmp_path / "data"
        month_dir = data_dir / "transactions" / "2026" / "03"
        month_dir.mkdir(parents=True)
        pl.DataFrame(schema=POLARS_SCHEMA).write_csv(month_dir / "transactions.csv")
        (data_dir / "rules.yaml").write_text("version: 1\nrules: []\n", encoding="utf-8")

        result = runner.invoke(app, ["--data-dir", str(data_dir), "status", "--detailed", "--json"])

        assert result.exit_code == 0, result.output
        stats = json.loads(result.output)["detailed_stats"]
        assert stats["monthly_avg_income"] is None
        assert stats["monthly_avg_expense"] is None
        assert stats["savings_rate_3mo"] is None
        assert stats["residual_savings_rate_3mo"] is None
        assert stats["structural_savings_monthly_avg"] == 0
        assert stats["structural_savings_sources"] == []


def _write_status_partitions(data_dir: Path, rows: list[dict[str, Any]]) -> None:
    """Write test rows into monthly transaction partitions."""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        month_key = str(row["date"])[:7]
        grouped.setdefault(month_key, []).append(row)

    for month_key, month_rows in grouped.items():
        year, month = month_key.split("-")
        month_dir = data_dir / "transactions" / year / month
        month_dir.mkdir(parents=True)
        pl.DataFrame(month_rows).write_csv(month_dir / "transactions.csv")


def _write_invalid_report_filters_rules(data_dir: Path) -> None:
    """Write rules.yaml with invalid report_filters for status error-priority tests."""
    data_dir.joinpath("rules.yaml").write_text(
        "\n".join(
            [
                "version: 1",
                "report_filters:",
                "  excluded_merchants:",
                '    - pattern: "foo"',
                '      match_type: "wildcard"',
                '      reason: "bad"',
                "rules: []",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _status_row(
    date: str,
    amount: int,
    category: str,
    row_hash: str,
    *,
    tags: str = "[]",
    transfer: _StatusTransferState | None = None,
    type_norm: str | None = None,
) -> dict[str, Any]:
    """Build a minimal status transaction row."""
    transfer_state = transfer or _StatusTransferState()
    resolved_type_norm = type_norm or ("income" if amount > 0 else "expense")
    resolved_transfer_group_id = transfer_state.group_id
    if transfer_state.confirmed == 1 and resolved_transfer_group_id is None:
        resolved_transfer_group_id = f"T_{row_hash}"
    return {
        "row_hash": row_hash,
        "date": date,
        "time": "09:00",
        "type_raw": "입금" if amount > 0 else "지출",
        "type_norm": resolved_type_norm,
        "major_raw": category,
        "minor_raw": category,
        "merchant_raw": row_hash,
        "memo_raw": None,
        "notes_manual": "",
        "amount": float(amount),
        "account": "테스트계좌",
        "currency": "KRW",
        "counterparty": None,
        "datetime": f"{date}T09:00:00",
        "category_rule": category,
        "category_final": category,
        "tags_rule": tags,
        "tags_ai": "[]",
        "tags_manual": "[]",
        "tags_final": tags,
        "confidence": 0.9,
        "needs_review": 0,
        "is_transfer_candidate": (
            transfer_state.confirmed
            if transfer_state.candidate is None
            else transfer_state.candidate
        ),
        "is_transfer": transfer_state.confirmed,
        "transfer_group_id": resolved_transfer_group_id,
        "file_id": f"{date.replace('-', '')}_1",
        "source_row": 1,
    }
