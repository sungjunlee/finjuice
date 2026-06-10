"""Tests for finjuice rules gaps CLI command.

Tests cover:
- Basic invocation
- No data scenario
- Top N parameter
- File output
- Simulation toggle
"""

import json
import re
from pathlib import Path

import polars as pl
from typer.testing import CliRunner

from finjuice.pipeline.cli.main import app
from finjuice.pipeline.tagging.gap_analyzer import (
    CoverageSimulation,
    GapAnalysis,
    GapType,
)

runner = CliRunner()


def strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def create_sample_transactions_csv(csv_dir: Path) -> None:
    """Create sample transactions CSV for testing."""
    partition_dir = csv_dir / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)

    # Create sample data with mix of tagged and untagged
    data = {
        "row_hash": ["abc123", "def456", "ghi789", "jkl012"],
        "date": ["2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04"],
        "time": ["10:00", "11:00", "12:00", "13:00"],
        "datetime": [
            "2024-10-01T10:00:00",
            "2024-10-02T11:00:00",
            "2024-10-03T12:00:00",
            "2024-10-04T13:00:00",
        ],
        "type_raw": ["지출", "지출", "지출", "지출"],
        "type_norm": ["expense", "expense", "expense", "expense"],
        "major_raw": ["기타", "식비", "기타", "식비"],
        "minor_raw": ["기타", "카페", "기타", "카페"],
        "merchant_raw": ["스타벅스", "투썸플레이스", "GS25", "이디야커피"],
        "memo_raw": ["", "", "", ""],
        "amount": [-5000.0, -6000.0, -3000.0, -4500.0],
        "account": ["신한카드", "신한카드", "삼성카드", "신한카드"],
        "currency": ["KRW", "KRW", "KRW", "KRW"],
        "counterparty": ["", "", "", ""],
        "tags_rule": ["[]", '["카페", "커피"]', "[]", '["카페"]'],
        "tags_ai": ["[]", "[]", "[]", "[]"],
        "tags_manual": ["[]", "[]", "[]", "[]"],
        "tags_final": ["[]", '["카페", "커피"]', "[]", '["카페"]'],
        "confidence": [None, 0.95, None, 0.9],
        "needs_review": [1, 0, 1, 0],
        "is_transfer": [0, 0, 0, 0],
        "transfer_group_id": ["", "", "", ""],
        "file_id": ["241001_1", "241001_1", "241001_1", "241001_1"],
        "source_row": [1, 2, 3, 4],
    }

    df = pl.DataFrame(data)
    csv_path = partition_dir / "transactions.csv"
    df.write_csv(csv_path)


def create_mixed_mismatch_transactions_csv(csv_dir: Path) -> None:
    """Create transactions that exercise every mismatch severity."""
    partition_dir = csv_dir / "2024" / "10"
    partition_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "row_hash": ["conflict-1", "category-1", "noise-1", "complete-1"],
        "date": ["2024-10-01", "2024-10-02", "2024-10-03", "2024-10-04"],
        "time": ["10:00", "11:00", "12:00", "13:00"],
        "datetime": [
            "2024-10-01T10:00:00",
            "2024-10-02T11:00:00",
            "2024-10-03T12:00:00",
            "2024-10-04T13:00:00",
        ],
        "type_raw": ["지출", "지출", "지출", "지출"],
        "type_norm": ["expense", "expense", "expense", "expense"],
        "major_raw": ["생활", "식비", "식비", "식비"],
        "minor_raw": ["편의점", "기타", "카페", "카페"],
        "merchant_raw": ["카페충돌", "카페소분류불일치", "태그순서노이즈", "카페정상"],
        "memo_raw": ["", "", "", ""],
        "amount": [-5000.0, -6000.0, -7000.0, -4500.0],
        "account": ["Card", "Card", "Card", "Card"],
        "currency": ["KRW", "KRW", "KRW", "KRW"],
        "counterparty": ["", "", "", ""],
        "category_rule": ["", "", "", ""],
        "category_final": ["편의점", "기타", "카페", "카페"],
        "tags_rule": ['["카페"]', '["카페"]', '["구독", "카페"]', '["카페"]'],
        "tags_ai": ["[]", "[]", "[]", "[]"],
        "tags_manual": ["[]", "[]", "[]", "[]"],
        "tags_final": ['["카페"]', '["카페"]', '["구독", "카페"]', '["카페"]'],
        "confidence": [0.9, 0.9, 0.9, 0.9],
        "needs_review": [1, 1, 1, 0],
        "is_transfer": [0, 0, 0, 0],
        "transfer_group_id": ["", "", "", ""],
        "file_id": ["241001_1", "241001_1", "241001_1", "241001_1"],
        "source_row": [1, 2, 3, 4],
    }

    pl.DataFrame(data).write_csv(partition_dir / "transactions.csv")


class TestAnalyzeGapsCommand:
    """Tests for rules gaps CLI command."""

    def test_help_option(self):
        """Shows help text correctly."""
        result = runner.invoke(app, ["rules", "gaps", "--help"])

        assert result.exit_code == 0
        clean_output = strip_ansi(result.output)
        assert "Analyze gaps" in clean_output
        assert "--top" in clean_output
        assert "--simulate" in clean_output
        assert "--actionable-only" in clean_output
        assert "--output" in clean_output

    def test_no_transactions_dir(self, tmp_path: Path):
        """Shows error when transactions directory doesn't exist."""
        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "gaps"])

        assert result.exit_code == 1
        assert "No transaction data found" in result.output

    def test_empty_transactions(self, tmp_path: Path):
        """Shows message when no transactions to analyze."""
        # Create empty transactions directory
        csv_dir = tmp_path / "transactions"
        csv_dir.mkdir(parents=True)

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "gaps"])

        assert result.exit_code == 0
        assert "분석할 거래 내역이 없습니다" in result.output

    def test_basic_analysis(self, tmp_path: Path):
        """Performs basic gap analysis."""
        csv_dir = tmp_path / "transactions"
        create_sample_transactions_csv(csv_dir)

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "gaps"])

        assert result.exit_code == 0
        assert "Gap 분석" in result.output
        # Should show some analysis results
        assert "미태깅" in result.output or "매칭" in result.output

    def test_top_n_parameter(self, tmp_path: Path):
        """Respects --top parameter."""
        csv_dir = tmp_path / "transactions"
        create_sample_transactions_csv(csv_dir)

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "gaps", "--top", "3"])

        assert result.exit_code == 0
        assert "Gap 분석" in result.output

    def test_no_simulate_option(self, tmp_path: Path):
        """Skips simulation when --no-simulate is passed."""
        csv_dir = tmp_path / "transactions"
        create_sample_transactions_csv(csv_dir)

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "gaps", "--no-simulate"])

        assert result.exit_code == 0
        # Should not show simulation section
        # (but may still show other parts of the report)

    def test_save_to_file(self, tmp_path: Path):
        """Saves output to file when --output specified."""
        csv_dir = tmp_path / "transactions"
        create_sample_transactions_csv(csv_dir)
        output_file = tmp_path / "gaps.txt"

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "rules",
                "gaps",
                "-o",
                str(output_file),
            ],
        )

        assert result.exit_code == 0
        assert "저장되었습니다" in result.output
        assert output_file.exists()
        content = output_file.read_text(encoding="utf-8")
        assert "Gap 분석" in content

    def test_next_steps_suggestion(self, tmp_path: Path):
        """Shows appropriate next steps based on analysis."""
        csv_dir = tmp_path / "transactions"
        create_sample_transactions_csv(csv_dir)

        result = runner.invoke(app, ["--data-dir", str(tmp_path), "rules", "gaps"])

        assert result.exit_code == 0
        # Should show some next step recommendation
        assert "다음 단계" in result.output or "모든 거래가" in result.output

    def test_json_actionable_only_filters_low_signal_noise(self, tmp_path: Path) -> None:
        """--actionable-only filters multi-tag noise while reporting total counts."""
        csv_dir = tmp_path / "transactions"
        create_mixed_mismatch_transactions_csv(csv_dir)

        result = runner.invoke(
            app,
            [
                "--data-dir",
                str(tmp_path),
                "rules",
                "gaps",
                "--json",
                "--actionable-only",
                "--no-simulate",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["summary"]["actionable_only"] is True
        assert payload["summary"]["mismatch_count"] == 2
        assert payload["summary"]["filtered_mismatch_count"] == 2
        assert payload["summary"]["total_mismatch_count"] == 3
        assert payload["summary"]["filtered_out_mismatch_count"] == 1
        assert payload["summary"]["conflict_count"] == 1
        assert payload["summary"]["category_mismatch_count"] == 1
        assert payload["summary"]["multi_tag_noise_count"] == 1
        assert [item["mismatch_type"] for item in payload["mismatches"]] == [
            "conflict",
            "category_mismatch",
        ]

    def test_human_output_prioritizes_high_severity_mismatches(self, tmp_path: Path) -> None:
        """Conflict/category mismatches should appear before multi-tag noise."""
        csv_dir = tmp_path / "transactions"
        create_mixed_mismatch_transactions_csv(csv_dir)

        result = runner.invoke(
            app,
            ["--data-dir", str(tmp_path), "rules", "gaps", "--no-simulate"],
        )

        assert result.exit_code == 0, result.output
        clean_output = strip_ansi(result.output)
        assert clean_output.index("카페충돌") < clean_output.index("태그순서노이즈")


class TestGapAnalyzerModule:
    """Tests for gap_analyzer.py module functions."""

    def test_gap_type_enum(self):
        """GapType enum has expected values."""
        assert GapType.CRITICAL.value == "미태깅 + 미분류"
        assert GapType.MISMATCH.value == "태깅됨 + 불일치"
        assert GapType.PARTIAL.value == "부분 매칭"
        assert GapType.COMPLETE.value == "완전 매칭"

    def test_gap_analysis_dataclass(self):
        """GapAnalysis dataclass works correctly."""
        analysis = GapAnalysis(
            gap_type=GapType.CRITICAL,
            merchant="테스트가맹점",
            transaction_count=10,
            total_amount=50000.0,
            current_tags=[],
            current_category="기타:기타",
            suggested_action="규칙 추가 필요",
        )

        assert analysis.gap_type == GapType.CRITICAL
        assert analysis.merchant == "테스트가맹점"
        assert analysis.transaction_count == 10
        assert analysis.total_amount == 50000.0
        assert analysis.current_tags == []
        assert analysis.current_category == "기타:기타"

    def test_coverage_simulation_dataclass(self):
        """CoverageSimulation dataclass works correctly."""
        sim = CoverageSimulation(
            top_n=5,
            expected_tagged=100,
            expected_coverage_pct=50.0,
            improvement_pct=10.0,
        )

        assert sim.top_n == 5
        assert sim.expected_tagged == 100
        assert sim.expected_coverage_pct == 50.0
        assert sim.improvement_pct == 10.0

    def test_analyze_tag_category_gaps_empty(self, tmp_path: Path):
        """analyze_tag_category_gaps returns empty dict for no data."""
        from finjuice.pipeline.tagging.gap_analyzer import analyze_tag_category_gaps

        csv_dir = tmp_path / "transactions"
        csv_dir.mkdir(parents=True)

        result = analyze_tag_category_gaps(csv_dir)

        assert isinstance(result, dict)
        assert all(len(v) == 0 for v in result.values())

    def test_analyze_tag_category_gaps_with_data(self, tmp_path: Path):
        """analyze_tag_category_gaps returns proper analysis."""
        from finjuice.pipeline.tagging.gap_analyzer import analyze_tag_category_gaps

        csv_dir = tmp_path / "transactions"
        create_sample_transactions_csv(csv_dir)

        result = analyze_tag_category_gaps(csv_dir)

        assert isinstance(result, dict)
        assert GapType.CRITICAL in result
        # Should have some untagged transactions (스타벅스, GS25)
        assert len(result[GapType.CRITICAL]) > 0

    def test_analyze_tag_category_gaps_classifies_mismatch_severity(self, tmp_path: Path):
        """Gap analyzer should add mismatch type, severity, and actionable fields."""
        from finjuice.pipeline.tagging.gap_analyzer import analyze_tag_category_gaps

        csv_dir = tmp_path / "transactions"
        create_mixed_mismatch_transactions_csv(csv_dir)

        result = analyze_tag_category_gaps(csv_dir)
        mismatches = {
            gap.merchant: gap for gap in [*result[GapType.MISMATCH], *result[GapType.PARTIAL]]
        }

        assert mismatches["카페충돌"].mismatch_type == "conflict"
        assert mismatches["카페충돌"].mismatch_severity == "high"
        assert mismatches["카페충돌"].actionable is True
        assert mismatches["카페소분류불일치"].mismatch_type == "category_mismatch"
        assert mismatches["카페소분류불일치"].mismatch_severity == "medium"
        assert mismatches["카페소분류불일치"].actionable is True
        assert mismatches["태그순서노이즈"].mismatch_type == "multi_tag_noise"
        assert mismatches["태그순서노이즈"].mismatch_severity == "low"
        assert mismatches["태그순서노이즈"].actionable is False

    def test_simulate_coverage_improvement_empty(self, tmp_path: Path):
        """simulate_coverage_improvement returns empty for no data."""
        from finjuice.pipeline.tagging.gap_analyzer import simulate_coverage_improvement

        csv_dir = tmp_path / "transactions"
        csv_dir.mkdir(parents=True)

        result = simulate_coverage_improvement(csv_dir)

        assert result == []

    def test_simulate_coverage_improvement_with_data(self, tmp_path: Path):
        """simulate_coverage_improvement returns simulations."""
        from finjuice.pipeline.tagging.gap_analyzer import simulate_coverage_improvement

        csv_dir = tmp_path / "transactions"
        create_sample_transactions_csv(csv_dir)

        result = simulate_coverage_improvement(csv_dir, top_n_values=[5, 10])

        assert isinstance(result, list)
        assert len(result) == 2
        assert all(isinstance(s, CoverageSimulation) for s in result)
        assert result[0].top_n == 5
        assert result[1].top_n == 10

    def test_format_gap_analysis_report(self):
        """format_gap_analysis_report creates readable report."""
        from finjuice.pipeline.tagging.gap_analyzer import format_gap_analysis_report

        gaps = {
            GapType.CRITICAL: [
                GapAnalysis(
                    gap_type=GapType.CRITICAL,
                    merchant="스타벅스",
                    transaction_count=10,
                    total_amount=50000.0,
                    current_tags=[],
                    current_category="기타:기타",
                    suggested_action="규칙 추가 필요",
                )
            ],
            GapType.MISMATCH: [],
            GapType.PARTIAL: [],
            GapType.COMPLETE: [
                GapAnalysis(
                    gap_type=GapType.COMPLETE,
                    merchant="이디야",
                    transaction_count=5,
                    total_amount=25000.0,
                    current_tags=["카페"],
                    current_category="식비:카페",
                    suggested_action="매칭됨",
                )
            ],
        }

        simulations = [
            CoverageSimulation(
                top_n=5,
                expected_tagged=15,
                expected_coverage_pct=75.0,
                improvement_pct=25.0,
            )
        ]

        result = format_gap_analysis_report(gaps, simulations, top_n_per_category=5)

        assert "Gap 분석" in result
        assert "미태깅" in result
        assert "스타벅스" in result
        assert "완전 매칭" in result
        assert "커버리지" in result
        assert "75.0%" in result

    def test_format_gap_analysis_report_empty(self):
        """format_gap_analysis_report handles empty data."""
        from finjuice.pipeline.tagging.gap_analyzer import format_gap_analysis_report

        gaps = {
            GapType.CRITICAL: [],
            GapType.MISMATCH: [],
            GapType.PARTIAL: [],
            GapType.COMPLETE: [],
        }

        result = format_gap_analysis_report(gaps, [], top_n_per_category=5)

        assert "Gap 분석" in result
        # Should show 0 counts
        assert "0건" in result
